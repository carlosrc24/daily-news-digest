"""Entry point: fetch RSS -> analyse with Gemini -> render -> email.

Usage:
    python main.py              # full run, sends the email
    python main.py --dry-run    # calls Gemini, writes output/digest.html, sends nothing
    python main.py --fetch-only # only fetches feeds and lists the candidates (no API calls)
    python main.py --demo       # renders examples/sample_digest.json (no credentials needed)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.config import ConfigError, Settings, load_settings
from src.fetcher import fetch_all
from src.i18n import category_label, labels
from src.mailer import build_message, build_subject, render_html, render_text, send_email
from src.models import Article, Digest, DigestSection
from src.summarizer import Summarizer

logger = logging.getLogger("digest")

SAMPLE_DIGEST = Path(__file__).parent / "examples" / "sample_digest.json"


def build_digest(
    settings: Settings, candidates: dict[str, list[Article]], summarizer: Summarizer
) -> Digest:
    """Summarise each category independently; a failing category is reported, not fatal."""
    lang = settings.language
    sections: list[DigestSection] = []
    failed: list[str] = []

    for category, articles in candidates.items():
        if not articles:
            logger.warning("No recent articles for %s", category)
            continue
        try:
            items = summarizer.summarize_category(
                category_label(category, "en"),
                articles,
                limit=settings.articles_per_category,
                lookback_hours=settings.lookback_hours,
            )
        except Exception as exc:
            logger.error("Summarisation failed for %s: %s", category, exc)
            failed.append(category)
            continue
        logger.info("%-12s %d/%d articles selected", category, len(items), len(articles))
        if items:
            sections.append(DigestSection(category=category, items=items))

    key_points: list[str] = []
    if sections:
        try:
            names = {s.category: category_label(s.category, lang) for s in sections}
            key_points = summarizer.daily_brief(sections, names)
        except Exception as exc:
            logger.error("Daily brief failed; sending digest without it: %s", exc)

    return Digest(
        generated_at=datetime.now(UTC),
        language=lang,
        model=", ".join(getattr(summarizer, "models_used", None) or [settings.gemini_model]),
        key_points=key_points,
        sections=sections,
        failed_categories=failed,
    )


def write_output(html: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    logger.info("HTML written to %s", path)


def cmd_fetch_only() -> int:
    settings = load_settings(require_gemini=False, require_email=False)
    candidates = fetch_all(settings)
    for category, articles in candidates.items():
        print(f"\n## {category_label(category, 'en')} ({len(articles)})")
        for a in articles:
            when = a.published.strftime("%d %b %H:%M") if a.published else "   undated  "
            print(f"  {a.id:<14} {when}  [{a.source}] {a.title[:80]}")
    return 0 if any(candidates.values()) else 1


def cmd_demo(output: Path) -> int:
    digest = Digest.model_validate_json(SAMPLE_DIGEST.read_text(encoding="utf-8"))
    write_output(render_html(digest), output)
    return 0


def cmd_run(*, dry_run: bool, output: Path) -> int:
    settings = load_settings(require_email=not dry_run)
    logger.info("Models=%s language=%s lookback=%dh", " -> ".join(settings.gemini_models),
                settings.language, settings.lookback_hours)  # fmt: skip

    candidates = fetch_all(settings)
    total = sum(len(v) for v in candidates.values())
    if total == 0:
        logger.error("No articles fetched from any feed; aborting")
        return 1
    logger.info("%d candidate articles across %d categories", total, len(candidates))

    summarizer = Summarizer(settings.gemini_api_key, settings.gemini_models, settings.language)
    digest = build_digest(settings, candidates, summarizer)
    if not digest.sections:
        logger.error("Every category failed or was empty; not sending an empty digest")
        return 1

    html = render_html(digest)
    write_output(html, output)
    if dry_run:
        logger.info("Dry run: email not sent (%d articles)", digest.article_count)
        return 0

    message = build_message(
        sender=settings.email_sender,
        receivers=settings.email_receivers,
        subject=build_subject(digest),
        html=html,
        text=render_text(digest),
    )
    send_email(settings, message)
    # Partial failures still deliver an email, but surface as a non-zero exit so CI shows it.
    return 2 if digest.failed_categories else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=labels("en")["title"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="generate but do not send")
    mode.add_argument("--fetch-only", action="store_true", help="only list RSS candidates")
    mode.add_argument("--demo", action="store_true", help="render the bundled sample digest")
    parser.add_argument("--output", type=Path, default=Path("output/digest.html"))
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Third-party HTTP clients are very chatty at INFO.
    for noisy in ("httpx", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        if args.demo:
            return cmd_demo(args.output)
        if args.fetch_only:
            return cmd_fetch_only()
        return cmd_run(dry_run=args.dry_run, output=args.output)
    except ConfigError as exc:
        logger.error("%s (see .env.example)", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
