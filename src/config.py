"""Configuration: environment variables and the default RSS feed catalogue.

Settings are loaded through ``load_settings()`` instead of at import time, so
modules and tests can be imported without any secrets present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import find_dotenv, load_dotenv


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Feed:
    name: str
    url: str


# Category key -> feeds. Keys are stable identifiers; human-readable labels
# live in ``src/i18n.py`` so they can be localised.
#
# Every URL below was verified live when this catalogue was written. Notes:
# - Reuters discontinued its public RSS feeds in 2020, so it is not included.
# - Nikkei Asia's feed has neither dates nor summaries (titles only); the
#   fetcher keeps undated entries but caps them per feed.
# - The Economist publishes weekly, so on most days it contributes little
#   within a 24h window. It is kept for the days it does publish.
DEFAULT_FEEDS: dict[str, list[Feed]] = {
    "us": [
        Feed("Financial Times", "https://www.ft.com/world/us?format=rss"),
        Feed("NPR", "https://feeds.npr.org/1014/rss.xml"),
        Feed("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/US.xml"),
        Feed("The Economist", "https://www.economist.com/united-states/rss.xml"),
    ],
    "europe": [
        Feed("Financial Times", "https://www.ft.com/world/europe?format=rss"),
        Feed("BBC News", "https://feeds.bbci.co.uk/news/world/europe/rss.xml"),
        Feed("Politico Europe", "https://www.politico.eu/feed/"),
        Feed("The Guardian", "https://www.theguardian.com/world/europe-news/rss"),
        Feed("The Economist", "https://www.economist.com/europe/rss.xml"),
    ],
    "asia": [
        Feed("Nikkei Asia", "https://asia.nikkei.com/rss/feed/nar"),
        Feed("The Japan Times", "https://www.japantimes.co.jp/feed/"),
        Feed("Financial Times", "https://www.ft.com/world/asia-pacific?format=rss"),
        Feed("South China Morning Post", "https://www.scmp.com/rss/91/feed"),
        Feed("The Economist", "https://www.economist.com/asia/rss.xml"),
    ],
    "markets": [
        Feed("Financial Times", "https://www.ft.com/markets?format=rss"),
        Feed("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        Feed("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
        Feed("The Guardian", "https://www.theguardian.com/business/economics/rss"),
        Feed("The Economist", "https://www.economist.com/finance-and-economics/rss.xml"),
    ],
    "geopolitics": [
        Feed("Financial Times", "https://www.ft.com/world?format=rss"),
        Feed("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        Feed("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        Feed("Foreign Policy", "https://foreignpolicy.com/feed/"),
        Feed("The Economist", "https://www.economist.com/international/rss.xml"),
    ],
    "technology": [
        Feed("Financial Times", "https://www.ft.com/technology?format=rss"),
        Feed("The Verge", "https://www.theverge.com/rss/index.xml"),
        Feed("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        Feed("MIT Technology Review", "https://www.technologyreview.com/feed/"),
        Feed("The Economist", "https://www.economist.com/science-and-technology/rss.xml"),
    ],
}

DEFAULT_MODEL = "gemini-3.8-flash"
# Used when the primary model is overloaded or out of quota. Each model has its own
# free-tier quota (gemini-3.8-flash only allows ~20 requests/day on the free tier).
DEFAULT_FALLBACK_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_MODEL
    gemini_fallback_model: str = DEFAULT_FALLBACK_MODEL
    email_sender: str = ""
    email_password: str = ""
    email_receivers: tuple[str, ...] = ()
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    language: str = "en"
    lookback_hours: int = 24
    articles_per_category: int = 4
    candidates_per_category: int = 12
    max_per_feed: int = 8
    request_timeout: float = 15.0
    feeds: dict[str, list[Feed]] = field(default_factory=lambda: DEFAULT_FEEDS)

    @property
    def gemini_models(self) -> tuple[str, ...]:
        """Primary model first, then the fallback (if any)."""
        return tuple(m for m in (self.gemini_model, self.gemini_fallback_model) if m)


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    return value


def _fallback_model(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return DEFAULT_FALLBACK_MODEL
    return "" if value.lower() == "none" else value


def load_settings(*, require_gemini: bool = True, require_email: bool = True) -> Settings:
    """Build ``Settings`` from the environment (and ``.env`` if present).

    Only the variables needed for the requested mode are validated, so e.g. a
    ``--dry-run`` does not need SMTP credentials.
    """
    # Look for .env from the working directory (not from this file's location).
    load_dotenv(find_dotenv(usecwd=True))

    receivers = tuple(
        addr.strip() for addr in os.getenv("EMAIL_RECEIVER", "").split(",") if addr.strip()
    )
    articles = _int_env("ARTICLES_PER_CATEGORY", 4)

    settings = Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL,
        # Set GEMINI_FALLBACK_MODEL=none to disable the fallback.
        gemini_fallback_model=_fallback_model(os.getenv("GEMINI_FALLBACK_MODEL")),
        email_sender=os.getenv("EMAIL_SENDER", "").strip(),
        # Gmail shows App Passwords as "abcd efgh ijkl mnop"; spaces are optional.
        email_password=os.getenv("EMAIL_PASSWORD", "").replace(" ", ""),
        email_receivers=receivers,
        smtp_host=os.getenv("SMTP_HOST", "").strip() or "smtp.gmail.com",
        smtp_port=_int_env("SMTP_PORT", 587),
        language=(os.getenv("DIGEST_LANGUAGE", "").strip() or "en").lower(),
        lookback_hours=_int_env("LOOKBACK_HOURS", 24),
        articles_per_category=articles,
        # Send the model ~3x candidates so it can actually choose the most relevant.
        candidates_per_category=_int_env("CANDIDATES_PER_CATEGORY", articles * 3),
        max_per_feed=_int_env("MAX_PER_FEED", 8),
    )

    missing = []
    if require_gemini and not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if require_email:
        if not settings.email_sender:
            missing.append("EMAIL_SENDER")
        if not settings.email_password:
            missing.append("EMAIL_PASSWORD")
        if not settings.email_receivers:
            missing.append("EMAIL_RECEIVER")
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

    return settings
