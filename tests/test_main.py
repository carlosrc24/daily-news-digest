import main
from src.models import DigestItem


def item(link):
    return DigestItem(topic="economy", headline="h", summary="s",
                      source="s", link=link, original_title="o")  # fmt: skip


class FakeSummarizer:
    def __init__(self, brief_fails=False):
        self.brief_fails = brief_fails
        self.received = []

    def select_stories(self, articles, *, limit, lookback_hours):
        self.received = articles
        return [item(a.link) for a in articles[:limit]]

    def daily_brief(self, items):
        if self.brief_fails:
            raise RuntimeError("brief down")
        return ["point"]


def test_all_categories_are_ranked_together(settings, articles, now):
    tech = [
        a.model_copy(update={"id": "technology-1", "category": "technology"}) for a in articles[:1]
    ]
    candidates = {"markets": articles, "technology": tech, "geopolitics": []}
    summarizer = FakeSummarizer()

    digest = main.build_digest(settings, candidates, summarizer)

    assert [a.id for a in summarizer.received] == [
        "markets-1",
        "markets-2",
        "markets-3",
        "technology-1",
    ]
    assert len(digest.items) == settings.max_stories
    assert digest.key_points == ["point"]


def test_brief_failure_is_not_fatal(settings, articles):
    digest = main.build_digest(settings, {"markets": articles}, FakeSummarizer(brief_fails=True))
    assert digest.items
    assert digest.key_points == []


def test_demo_renders_sample_without_credentials(tmp_path):
    out = tmp_path / "demo.html"
    assert main.main(["--demo", "--output", str(out)]) == 0
    assert "The day in brief" in out.read_text(encoding="utf-8")


def test_missing_config_exits_with_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for var in ("GEMINI_API_KEY", "EMAIL_SENDER", "EMAIL_PASSWORD", "EMAIL_RECEIVER"):
        monkeypatch.delenv(var, raising=False)
    assert main.main([]) == 1
