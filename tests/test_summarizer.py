import json
from types import SimpleNamespace

import pytest
from google.genai import errors

from src.models import ArticleAnalysis, CategoryAnalysis, DigestItem, DigestSection
from src.summarizer import Summarizer, _is_retryable, join_analysis


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(text=response)


def make_summarizer(*responses, language="en", models=("test-model",)):
    fake = FakeModels(responses)
    client = SimpleNamespace(models=fake)
    return Summarizer(models=models, language=language, client=client), fake


def quota_error(quota_id, message="Quota exceeded. Please retry in 2.5s."):
    details = {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
               "violations": [{"quotaId": quota_id}]}  # fmt: skip
    return errors.ClientError(
        429, {"error": {"code": 429, "message": message, "details": [details]}}
    )


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(Summarizer._generate_with.retry, "sleep", sleeps.append)
    return sleeps


def analysis(article_id, headline="H"):
    return {
        "article_id": article_id,
        "headline": headline,
        "context": "ctx",
        "impact": "imp",
        "conclusion": "conc",
    }


def test_summarize_category_joins_trusted_metadata(articles):
    response = json.dumps({"articles": [analysis("markets-3", "Third"), analysis("markets-1")]})
    summarizer, models = make_summarizer(response, language="es")

    items = summarizer.summarize_category("Markets", articles, limit=2, lookback_hours=24)

    assert [i.headline for i in items] == ["Third", "H"]  # model's relevance order is kept
    assert items[0].link == "https://alpha.test/3"
    assert items[0].original_title == "Title 3"
    call = models.calls[0]
    assert call.model == "test-model"
    assert "Spanish" in call.config.system_instruction
    assert call.config.response_schema is CategoryAnalysis
    assert '"id": "markets-2"' in call.contents


def test_join_analysis_drops_hallucinated_and_duplicate_ids(articles):
    result = CategoryAnalysis(
        articles=[
            ArticleAnalysis(**analysis("markets-9")),
            ArticleAnalysis(**analysis("markets-1")),
            ArticleAnalysis(**analysis("markets-1")),
            ArticleAnalysis(**analysis(" markets-2 ")),
            ArticleAnalysis(**analysis("markets-3")),
        ]
    )
    items = join_analysis(result, articles, limit=2)
    assert [i.link for i in items] == ["https://alpha.test/1", "https://alpha.test/2"]


def test_empty_category_makes_no_api_call():
    summarizer, models = make_summarizer()
    assert summarizer.summarize_category("X", [], limit=3, lookback_hours=24) == []
    assert models.calls == []


def test_invalid_json_raises(articles):
    summarizer, _ = make_summarizer('{"not": "the schema"}')
    with pytest.raises(ValueError):
        summarizer.summarize_category("Markets", articles, limit=2, lookback_hours=24)


def test_daily_brief_trims_and_caps():
    points = {"key_points": [" one ", "", "two", "3", "4", "5", "6"]}
    summarizer, _ = make_summarizer(json.dumps(points))
    item = DigestItem(headline="h", context="c", impact="i", conclusion="k",
                      source="s", link="l", original_title="o")  # fmt: skip
    brief = summarizer.daily_brief([DigestSection(category="markets", items=[item])], {})
    assert brief == ["one", "two", "3", "4", "5"]


def test_daily_quota_falls_back_without_retrying(articles, no_sleep):
    ok = json.dumps({"articles": [analysis("markets-1")]})
    summarizer, fake = make_summarizer(
        quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier"), ok, ok,
        models=("primary", "fallback"),
    )  # fmt: skip

    summarizer.summarize_category("Markets", articles, limit=2, lookback_hours=24)
    summarizer.summarize_category("Markets", articles, limit=2, lookback_hours=24)

    # No retry on the exhausted model, and it is skipped for the rest of the run.
    assert [c.model for c in fake.calls] == ["primary", "fallback", "fallback"]
    assert no_sleep == []
    assert summarizer.models_used == ["fallback"]


def test_per_minute_quota_waits_for_server_hint(articles, no_sleep):
    ok = json.dumps({"articles": [analysis("markets-1")]})
    summarizer, fake = make_summarizer(quota_error("GenerateRequestsPerMinute"), ok)

    summarizer.summarize_category("Markets", articles, limit=2, lookback_hours=24)

    assert [c.model for c in fake.calls] == ["test-model", "test-model"]
    assert no_sleep == [3.5]  # "retry in 2.5s" + 1s margin


def test_overloaded_primary_falls_back_after_retries(articles, no_sleep):
    ok = json.dumps({"articles": [analysis("markets-1")]})
    busy = errors.ServerError(503, {"error": {"message": "high demand"}})
    summarizer, fake = make_summarizer(busy, busy, busy, ok, models=("primary", "fallback"))

    items = summarizer.summarize_category("Markets", articles, limit=2, lookback_hours=24)

    assert len(items) == 1
    assert [c.model for c in fake.calls] == ["primary"] * 3 + ["fallback"]
    assert summarizer.models_used == ["fallback"]


def test_last_model_error_is_raised(articles, no_sleep):
    summarizer, _ = make_summarizer(errors.ClientError(400, {"error": {"message": "bad"}}))
    with pytest.raises(errors.ClientError):
        summarizer.summarize_category("Markets", articles, limit=2, lookback_hours=24)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (errors.ClientError(429, {}), True),
        (quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier"), False),
        (errors.ServerError(503, {}), True),
        (errors.ClientError(400, {}), False),
        (errors.ClientError(403, {}), False),
        (ValueError("x"), False),
    ],
)
def test_only_rate_limits_and_server_errors_are_retried(error, expected):
    assert _is_retryable(error) is expected
