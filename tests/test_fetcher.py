from datetime import timedelta

from src.config import Feed
from src.fetcher import clean_text, fetch_all, normalize_link, parse_feed
from tests.conftest import rss


def test_clean_text_strips_html_and_truncates():
    assert clean_text("<p>Rates &amp; <b>bonds</b></p>\n\n rally") == "Rates & bonds rally"
    long = clean_text("word " * 200, max_chars=50)
    assert len(long) <= 51
    assert long.endswith("…")


def test_normalize_link_ignores_tracking_and_trailing_slash():
    assert normalize_link("https://FT.com/a/?utm_source=rss#x") == normalize_link(
        "https://ft.com/a"
    )


def test_parse_feed_filters_by_date_and_keeps_undated(now):
    raw = rss(
        ("Fresh", "https://a.test/1", now - timedelta(hours=2), "<p>fresh</p>"),
        ("Stale", "https://a.test/2", now - timedelta(hours=30), ""),
        ("Undated", "https://a.test/3", None, ""),
    )
    items = parse_feed(
        raw, Feed("A", "u"), "markets", since=now - timedelta(hours=24), max_items=10
    )
    assert [a.title for a in items] == ["Fresh", "Undated"]
    assert items[0].summary == "fresh"
    assert items[0].published.tzinfo is not None
    assert items[1].published is None


def test_parse_feed_respects_max_items(now):
    raw = rss(*[(f"T{i}", f"https://a.test/{i}", now, "") for i in range(10)])
    items = parse_feed(raw, Feed("A", "u"), "markets", since=now - timedelta(hours=24), max_items=3)
    assert len(items) == 3


def test_fetch_all_dedupes_interleaves_and_isolates_failures(settings, now):
    recent = now - timedelta(hours=1)
    feeds = {
        "https://alpha.test/rss": rss(
            ("Shared story", "https://news.test/shared?utm=1", recent, ""),
            ("Alpha two", "https://alpha.test/2", recent - timedelta(minutes=5), ""),
            ("Alpha three", "https://alpha.test/3", recent - timedelta(minutes=10), ""),
        ),
        "https://beta.test/rss": rss(
            ("Beta one", "https://beta.test/1", recent, ""),
            ("Shared story", "https://news.test/shared", recent, ""),
        ),
    }

    def fake_get(url, timeout):
        if url not in feeds:
            raise TimeoutError("boom")  # the technology feed fails
        return feeds[url]

    result = fetch_all(settings, get=fake_get)

    # Round-robin across sources, with the duplicate story removed.
    titles = [a.title for a in result["markets"]]
    assert titles == ["Shared story", "Beta one", "Alpha two", "Alpha three"]
    assert [a.id for a in result["markets"]] == [f"markets-{i}" for i in range(1, 5)]
    assert result["technology"] == []


def test_fetch_all_caps_candidates_and_dedupes_across_categories(settings, now):
    raw = rss(*[(f"T{i}", f"https://a.test/{i}", now, "") for i in range(20)])
    settings = settings.__class__(
        **{**settings.__dict__, "max_per_feed": 20, "candidates_per_category": 5}
    )
    result = fetch_all(settings, get=lambda url, timeout: raw)
    assert len(result["markets"]) == 5
    # Technology gets the same feed, but only stories markets did not already use.
    assert {a.title for a in result["technology"]}.isdisjoint({a.title for a in result["markets"]})
