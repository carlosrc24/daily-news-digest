from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from src.config import Feed, Settings
from src.models import Article


def rss(*items: tuple[str, str, datetime | None, str]) -> bytes:
    """Build a minimal RSS 2.0 document from (title, link, published, summary) tuples."""
    body = []
    for title, link, published, summary in items:
        date = f"<pubDate>{format_datetime(published)}</pubDate>" if published else ""
        body.append(
            f"<item><title>{title}</title><link>{link}</link>{date}"
            f"<description><![CDATA[{summary}]]></description></item>"
        )
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
        + "".join(body)
        + "</channel></rss>"
    ).encode()


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Never read a developer's real .env: tests must not use live credentials."""
    monkeypatch.setattr("src.config.load_dotenv", lambda *args, **kwargs: False)


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gemini_api_key="test-key",
        gemini_model="test-model",
        email_sender="sender@gmail.com",
        email_password="app-password",
        email_receivers=("a@example.com", "b@example.com"),
        articles_per_category=2,
        candidates_per_category=5,
        feeds={
            "markets": [
                Feed("Alpha", "https://alpha.test/rss"),
                Feed("Beta", "https://beta.test/rss"),
            ],
            "technology": [Feed("Gamma", "https://gamma.test/rss")],
        },
    )


@pytest.fixture
def articles(now: datetime) -> list[Article]:
    return [
        Article(
            id=f"markets-{i}",
            category="markets",
            source="Alpha",
            title=f"Title {i}",
            link=f"https://alpha.test/{i}",
            summary=f"Summary {i}",
            published=now - timedelta(hours=i),
        )
        for i in range(1, 4)
    ]
