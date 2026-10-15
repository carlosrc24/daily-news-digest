"""Email rendering (HTML + plain text) and delivery through Gmail SMTP."""

from __future__ import annotations

import logging
import smtplib
import ssl
import textwrap
from collections.abc import Callable
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from jinja2 import Environment, PackageLoader, select_autoescape

from src.config import Settings
from src.i18n import format_date, labels, topic_label
from src.models import Digest

logger = logging.getLogger(__name__)

# Autoescape is essential: every text field comes from an LLM or a third-party feed.
_env = Environment(
    loader=PackageLoader("src", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def build_subject(digest: Digest) -> str:
    t = labels(digest.language)
    return f"{t['title']} · {format_date(digest.generated_at, digest.language)}"


def render_html(digest: Digest) -> str:
    lang = digest.language
    t = labels(lang)
    stats = t["stats"].format(articles=len(digest.items))
    first = digest.key_points[0] if digest.key_points else stats
    return _env.get_template("digest.html.j2").render(
        digest=digest,
        language=lang,
        t=t,
        date_str=format_date(digest.generated_at, lang),
        stats=stats,
        preheader=first,
        footer=t["footer"].format(model=digest.model),
        topic_label=lambda topic: topic_label(topic, lang),
    )


def render_text(digest: Digest) -> str:
    """Plain-text alternative: shown by text-only clients and helps deliverability."""
    lang = digest.language
    t = labels(lang)
    wrap = textwrap.TextWrapper(width=78, subsequent_indent="  ")
    lines = [t["title"].upper(), format_date(digest.generated_at, lang), ""]
    if digest.key_points:
        lines += [t["key_points"].upper(), *(wrap.fill(f"- {p}") for p in digest.key_points), ""]
    for n, item in enumerate(digest.items, 1):
        lines += [
            f"{n}. [{topic_label(item.topic, lang).upper()}] {item.headline}",
            textwrap.fill(item.summary, width=78),
            f"{t['read_more']} {item.source}: {item.link}",
            "",
        ]
    lines.append(t["footer"].format(model=digest.model))
    return "\n".join(lines)


def build_message(
    *, sender: str, receivers: tuple[str, ...], subject: str, html: str, text: str
) -> MIMEMultipart:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = formataddr(("Daily Briefing", sender))
    message["To"] = ", ".join(receivers)
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender.split("@")[-1] or None)
    # Order matters: clients render the last part they support, so HTML goes last.
    message.attach(MIMEText(text, "plain", "utf-8"))
    message.attach(MIMEText(html, "html", "utf-8"))
    return message


def send_email(
    settings: Settings,
    message: MIMEMultipart,
    *,
    smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
) -> None:
    """Send through SMTP with STARTTLS (smtp.gmail.com:587 by default)."""
    context = ssl.create_default_context()
    with smtp_factory(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(settings.email_sender, settings.email_password)
        server.sendmail(settings.email_sender, list(settings.email_receivers), message.as_string())
    logger.info("Email sent to %d recipient(s)", len(settings.email_receivers))
