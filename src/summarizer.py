"""Gemini integration: select and analyse articles per category, then brief the day.

Design choices:
- One request per category (plus one for the daily brief) keeps usage well inside
  the free tier and lets the model rank and de-duplicate stories across sources.
- Structured output (JSON + Pydantic schema) instead of free-form HTML: the
  response is validated, and rendering stays in our own escaped template.
- The model only returns article ids plus analysis. Titles, links and sources are
  joined back from the RSS data, so the model cannot invent or alter them.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.i18n import language_name
from src.models import Article, CategoryAnalysis, DailyBrief, DigestItem, DigestSection

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

SYSTEM_PROMPT = """\
You are a senior analyst writing an executive news briefing for a reader with a \
technical background who follows economics, geopolitics and technology.

Style:
- Analytical, objective and precise. No sensationalism, opinions or filler.
- Explain mechanisms (rates, trade flows, supply chains, alliances, regulation) \
rather than restating the headline.
- Write every field in {language}.

Factual discipline:
- Use ONLY the information in the provided articles plus widely established \
background knowledge. Never invent figures, quotes, names or dates.
- Some articles only include a title. For those, keep the analysis general and \
explicitly avoid specifics that the title does not support.
- Reference articles only by the exact `id` you were given.
"""

CATEGORY_PROMPT = """\
Category: {category}

Below are {count} candidate articles published in the last {hours} hours (JSON).
Select the {limit} most significant for their economic, geopolitical or \
technological consequences. If several articles cover the same story, choose the \
most informative one and ignore the rest. Skip lifestyle, sport and minor local news \
unless they carry real macro relevance. Order the selection from most to least \
important. Return fewer than {limit} if fewer are genuinely relevant.

For each selected article provide: headline, context, impact and conclusion.

Articles:
{articles}
"""

BRIEF_PROMPT = """\
Below are today's analysed stories, grouped by section (JSON). Write 3 to 5 key \
points that synthesise the day: connect stories across sections where there is a \
real link, and prioritise what matters most for markets and international affairs. \
Each point is one or two sentences. Do not repeat headlines verbatim.

{sections}
"""


_RETRY_IN_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)
_backoff = wait_exponential(multiplier=2, min=5, max=60)


def _is_daily_quota(exc: BaseException) -> bool:
    """429 caused by the per-day quota: retrying today is pointless and burns requests."""
    return (
        isinstance(exc, errors.ClientError)
        and exc.code == 429
        and "PerDay" in json.dumps(exc.details, default=str)
    )


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, errors.ServerError):
        return True
    return isinstance(exc, errors.ClientError) and exc.code == 429 and not _is_daily_quota(exc)


def _wait(retry_state: RetryCallState) -> float:
    """Honour the server's "retry in Ns" hint (per-minute quota); otherwise back off."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    match = _RETRY_IN_RE.search(getattr(exc, "message", None) or "")
    if match:
        return min(float(match.group(1)) + 1, 60)
    return _backoff(retry_state)


class Summarizer:
    """Calls Gemini with a primary model and optional fallbacks.

    Each model has its own free-tier quota, so when the primary is overloaded (503)
    or out of daily quota (429), the next model in ``models`` takes over.
    """

    def __init__(
        self,
        api_key: str = "",
        models: Sequence[str] = (),
        language: str = "en",
        *,
        client: genai.Client | None = None,
        temperature: float = 0.3,
    ) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self.client = client or genai.Client(api_key=api_key)
        self.models = list(dict.fromkeys(models))  # dedupe, keep order
        self.language = language
        self.temperature = temperature
        self.models_used: list[str] = []
        self._exhausted: set[str] = set()

    def _generate(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        candidates = [m for m in self.models if m not in self._exhausted]
        if not candidates:
            raise RuntimeError("every Gemini model is out of daily quota")
        for i, model in enumerate(candidates):
            try:
                result = self._generate_with(model, prompt, schema)
            except Exception as exc:
                if _is_daily_quota(exc):
                    self._exhausted.add(model)  # skip it for the rest of this run
                if i == len(candidates) - 1:
                    raise
                reason = getattr(exc, "status", None) or type(exc).__name__
                logger.warning("%s failed (%s); trying %s", model, reason, candidates[i + 1])
                continue
            if model not in self.models_used:
                self.models_used.append(model)
            return result
        raise AssertionError("unreachable")

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=_wait,
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _generate_with(self, model: str, prompt: str, schema: type[SchemaT]) -> SchemaT:
        response = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT.format(language=language_name(self.language)),
                temperature=self.temperature,
                response_mime_type="application/json",
                response_schema=schema,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        if not response.text:
            # Typically a response blocked by safety filters.
            raise ValueError("Gemini returned an empty response")
        return schema.model_validate_json(response.text)

    def summarize_category(
        self, category_label: str, articles: list[Article], *, limit: int, lookback_hours: int
    ) -> list[DigestItem]:
        if not articles:
            return []
        payload = [
            {
                "id": a.id,
                "source": a.source,
                "title": a.title,
                "summary": a.summary or None,
                "published": a.published.isoformat() if a.published else None,
            }
            for a in articles
        ]
        prompt = CATEGORY_PROMPT.format(
            category=category_label,
            count=len(articles),
            hours=lookback_hours,
            limit=limit,
            articles=json.dumps(payload, ensure_ascii=False, indent=1),
        )
        analysis = self._generate(prompt, CategoryAnalysis)
        return join_analysis(analysis, articles, limit=limit)

    def daily_brief(self, sections: list[DigestSection], labels: dict[str, str]) -> list[str]:
        if not sections:
            return []
        payload = {
            labels.get(s.category, s.category): [
                {"headline": i.headline, "impact": i.impact, "conclusion": i.conclusion}
                for i in s.items
            ]
            for s in sections
        }
        prompt = BRIEF_PROMPT.format(sections=json.dumps(payload, ensure_ascii=False, indent=1))
        brief = self._generate(prompt, DailyBrief)
        return [point.strip() for point in brief.key_points if point.strip()][:5]


def join_analysis(
    analysis: CategoryAnalysis, articles: list[Article], *, limit: int
) -> list[DigestItem]:
    """Attach trusted RSS metadata to the model's analysis, keeping the model's order.

    Unknown or repeated ids are dropped (and logged) rather than trusted.
    """
    by_id = {a.id: a for a in articles}
    items: list[DigestItem] = []
    used: set[str] = set()
    for result in analysis.articles:
        article = by_id.get(result.article_id.strip())
        if article is None or article.id in used:
            logger.warning("Discarding analysis with unknown/duplicate id %r", result.article_id)
            continue
        used.add(article.id)
        items.append(
            DigestItem(
                headline=result.headline.strip() or article.title,
                context=result.context.strip(),
                impact=result.impact.strip(),
                conclusion=result.conclusion.strip(),
                source=article.source,
                link=article.link,
                original_title=article.title,
                published=article.published,
            )
        )
        if len(items) >= limit:
            break
    return items
