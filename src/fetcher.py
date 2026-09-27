"""RSS fetching: download, parse, filter by date, clean, dedupe and cap.

feedparser is only used as a parser. Downloading is done with urllib so we can
enforce a timeout and a browser-like User-Agent (some publishers reject
feedparser's default one).
"""

from __future__ import annotations

import calendar
import html
import logging
import re
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from itertools import zip_longest
from urllib.parse import urlsplit, urlunsplit

import feedparser

from src.config import Feed, Settings
from src.models import Article

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
SUMMARY_MAX_CHARS = 600

HttpGet = Callable[[str, float], bytes]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def http_get(url: str, timeout: float) -> bytes:
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"refusing non-HTTP feed URL: {url}")
    request = urllib.request.Request(  # noqa: S310 - scheme validated above
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def clean_text(raw: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """Strip HTML tags/entities, collapse whitespace and truncate on a word boundary."""
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw or ""))).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def normalize_link(url: str) -> str:
    """Canonical form for deduplication: no query string, fragment or trailing slash."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def normalize_title(title: str) -> str:
    return re.sub(r"[^\w]+", " ", title.lower()).strip()


def _entry_datetime(entry: feedparser.FeedParserDict) -> datetime | None:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not struct:
        return None
    # feedparser normalises to a UTC struct_time; timegm (not mktime) keeps it UTC.
    return datetime.fromtimestamp(calendar.timegm(struct), tz=UTC)


def parse_feed(
    raw: bytes, feed: Feed, category: str, *, since: datetime, max_items: int
) -> list[Article]:
    """Parse one feed and keep entries published after ``since``.

    Undated entries (e.g. Nikkei Asia) are kept, since feeds list newest first and
    ``max_items`` bounds how far back they can reach.
    """
    parsed = feedparser.parse(raw)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.get('bozo_exception')}")

    articles: list[Article] = []
    for entry in parsed.entries:
        if len(articles) >= max_items:
            break
        title = clean_text(entry.get("title", ""), max_chars=300)
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        published = _entry_datetime(entry)
        if published is not None and published < since:
            continue
        articles.append(
            Article(
                id="",  # assigned after dedupe/capping
                category=category,
                source=feed.name,
                title=title,
                link=link,
                summary=clean_text(entry.get("summary") or entry.get("description") or ""),
                published=published,
            )
        )
    return articles


def _interleave(groups: Iterable[list[Article]]) -> list[Article]:
    """Round-robin across sources so one prolific feed cannot crowd out the rest."""
    return [a for batch in zip_longest(*groups) for a in batch if a is not None]


def fetch_all(settings: Settings, *, get: HttpGet = http_get) -> dict[str, list[Article]]:
    """Fetch every configured feed and return candidates per category.

    Articles are deduplicated globally (by link and by title), so a story that
    appears in several feeds is kept only in the first category it shows up in.
    """
    since = datetime.now(UTC) - timedelta(hours=settings.lookback_hours)
    jobs = [(cat, feed) for cat, feeds in settings.feeds.items() for feed in feeds]

    def run(job: tuple[str, Feed]) -> list[Article]:
        category, feed = job
        try:
            raw = get(feed.url, settings.request_timeout)
            items = parse_feed(raw, feed, category, since=since, max_items=settings.max_per_feed)
            logger.info("%-12s %-26s %2d recent entries", category, feed.name, len(items))
            return items
        except Exception as exc:  # one broken feed must never abort the digest
            logger.warning("%-12s %-26s FAILED: %s", category, feed.name, exc)
            return []

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(run, jobs))  # map() preserves job order -> deterministic

    grouped: dict[str, list[list[Article]]] = {cat: [] for cat in settings.feeds}
    for (category, _), items in zip(jobs, results, strict=True):
        # Dated entries first (newest first) within each feed; undated ones after.
        items.sort(key=lambda a: a.published or datetime.min.replace(tzinfo=UTC), reverse=True)
        grouped[category].append(items)

    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    candidates: dict[str, list[Article]] = {}
    for category, groups in grouped.items():
        selected: list[Article] = []
        for article in _interleave(groups):
            link_key, title_key = normalize_link(article.link), normalize_title(article.title)
            if link_key in seen_links or title_key in seen_titles:
                continue
            seen_links.add(link_key)
            seen_titles.add(title_key)
            selected.append(article)
            if len(selected) >= settings.candidates_per_category:
                break
        candidates[category] = [
            a.model_copy(update={"id": f"{category}-{i}"}) for i, a in enumerate(selected, 1)
        ]
    return candidates
