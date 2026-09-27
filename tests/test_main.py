import main
from src.models import DigestItem


def item(link):
    return DigestItem(headline="h", context="c", impact="i", conclusion="k",
                      source="s", link=link, original_title="o")  # fmt: skip


class FakeSummarizer:
    def __init__(self, fail=(), brief_fails=False):
        self.fail, self.brief_fails = set(fail), brief_fails

    def summarize_category(self, label, articles, *, limit, lookback_hours):
        if label in self.fail:
            raise RuntimeError("quota")
        return [item(a.link) for a in articles[:limit]]

    def daily_brief(self, sections, labels):
        if self.brief_fails:
            raise RuntimeError("brief down")
        return ["point"]


def test_partial_failure_keeps_other_sections(settings, articles):
    candidates = {"markets": articles, "technology": articles, "geopolitics": []}
    digest = main.build_digest(settings, candidates, FakeSummarizer(fail={"Technology"}))

    assert [s.category for s in digest.sections] == ["markets"]
    assert len(digest.sections[0].items) == settings.articles_per_category
    assert digest.failed_categories == ["technology"]
    assert digest.key_points == ["point"]


def test_brief_failure_is_not_fatal(settings, articles):
    digest = main.build_digest(settings, {"markets": articles}, FakeSummarizer(brief_fails=True))
    assert digest.sections
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
