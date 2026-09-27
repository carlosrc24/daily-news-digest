from datetime import UTC, datetime
from typing import ClassVar

import pytest

from src.mailer import build_message, build_subject, render_html, render_text, send_email
from src.models import Digest, DigestItem, DigestSection


@pytest.fixture
def digest():
    item = DigestItem(
        headline="Rates <script>alert(1)</script> rise",
        context="Context text",
        impact="Impact text",
        conclusion="Conclusion text",
        source="Alpha",
        link="https://alpha.test/1",
        original_title="Original",
        published=datetime(2026, 9, 28, 5, 30, tzinfo=UTC),
    )
    return Digest(
        generated_at=datetime(2026, 9, 28, 6, 0, tzinfo=UTC),
        language="es",
        model="test-model",
        key_points=["First point"],
        sections=[DigestSection(category="markets", items=[item])],
        failed_categories=["technology"],
    )


def test_html_is_escaped_localised_and_complete(digest):
    html = render_html(digest)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "Lo esencial del día" in html
    assert "Mercados y Economía" in html
    assert "No disponible hoy: Tecnología" in html
    assert 'href="https://alpha.test/1"' in html
    assert "05:30 UTC" in html
    assert "Lunes, 28 de septiembre de 2026" in html


def test_unknown_language_falls_back_to_english_labels(digest):
    html = render_html(digest.model_copy(update={"language": "ja"}))
    assert "The day in brief" in html


def test_text_version_contains_every_item(digest):
    text = render_text(digest)
    assert "MERCADOS Y ECONOMÍA" in text
    assert "https://alpha.test/1" in text
    assert "Contexto: Context text" in text


def test_message_is_multipart_alternative_with_html_last(digest):
    msg = build_message(
        sender="me@gmail.com",
        receivers=("a@x.com", "b@x.com"),
        subject=build_subject(digest),
        html="<p>h</p>",
        text="t",
    )
    assert msg.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in msg.get_payload()] == ["text/plain", "text/html"]
    assert msg["To"] == "a@x.com, b@x.com"
    assert msg["Subject"].startswith("Resumen diario")


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.calls.append((name, args))


def test_send_email_uses_starttls_before_login(settings):
    msg = build_message(
        sender="s@gmail.com", receivers=("a@x.com",), subject="s", html="h", text="t"
    )
    send_email(settings, msg, smtp_factory=FakeSMTP)

    server = FakeSMTP.instances[-1]
    names = [name for name, _ in server.calls]
    calls = dict(server.calls)
    assert (server.host, server.port) == ("smtp.gmail.com", 587)
    assert names.index("starttls") < names.index("login") < names.index("sendmail")
    assert calls["login"] == ("sender@gmail.com", "app-password")
    assert calls["sendmail"][1] == ["a@example.com", "b@example.com"]
