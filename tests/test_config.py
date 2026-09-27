import pytest

from src.config import DEFAULT_FALLBACK_MODEL, DEFAULT_MODEL, ConfigError, load_settings

ENV_VARS = [
    "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FALLBACK_MODEL",
    "EMAIL_SENDER", "EMAIL_PASSWORD", "EMAIL_RECEIVER",
    "DIGEST_LANGUAGE", "ARTICLES_PER_CATEGORY", "CANDIDATES_PER_CATEGORY",
]  # fmt: skip


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_missing_variables_are_all_reported():
    with pytest.raises(ConfigError) as exc:
        load_settings()
    for var in ("GEMINI_API_KEY", "EMAIL_SENDER", "EMAIL_PASSWORD", "EMAIL_RECEIVER"):
        assert var in str(exc.value)


def test_dry_run_only_needs_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    settings = load_settings(require_email=False)
    assert settings.gemini_models == (DEFAULT_MODEL, DEFAULT_FALLBACK_MODEL)
    assert settings.language == "en"


def test_parses_receivers_password_and_derived_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("EMAIL_SENDER", "me@gmail.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("EMAIL_RECEIVER", "a@x.com, b@x.com ,")
    monkeypatch.setenv("DIGEST_LANGUAGE", "ES")
    monkeypatch.setenv("ARTICLES_PER_CATEGORY", "5")

    settings = load_settings()

    assert settings.email_receivers == ("a@x.com", "b@x.com")
    assert settings.email_password == "abcdefghijklmnop"  # noqa: S105
    assert settings.language == "es"
    assert settings.candidates_per_category == 15


@pytest.mark.parametrize("value", ["abc", "0"])
def test_invalid_integers_are_rejected(monkeypatch, value):
    monkeypatch.setenv("ARTICLES_PER_CATEGORY", value)
    with pytest.raises(ConfigError, match="ARTICLES_PER_CATEGORY"):
        load_settings(require_gemini=False, require_email=False)


def test_fallback_model_can_be_disabled(monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "none")
    settings = load_settings(require_gemini=False, require_email=False)
    assert settings.gemini_models == (DEFAULT_MODEL,)
