"""Static labels for the email template.

``DIGEST_LANGUAGE`` controls both Gemini's output language and these labels.
Any language code works for the model output; labels fall back to English when
the code has no translation here.
"""

from __future__ import annotations

from datetime import datetime

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
}

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Daily Briefing",
        "subtitle": "Economy · Geopolitics · Technology",
        "key_points": "The day in brief",
        "context": "Context",
        "impact": "Impact",
        "conclusion": "Takeaway",
        "read_more": "Read at",
        "failed": "Unavailable today",
        "footer": "Summaries generated automatically with {model}. "
        "They may contain errors: check the original source before relying on them.",
        "stats": "{articles} stories · {sections} sections",
        "cat.us": "United States",
        "cat.europe": "Europe",
        "cat.asia": "Asia & Japan",
        "cat.markets": "Markets & Economy",
        "cat.geopolitics": "Geopolitics",
        "cat.technology": "Technology",
    },
    "es": {
        "title": "Resumen diario",
        "subtitle": "Economía · Geopolítica · Tecnología",
        "key_points": "Lo esencial del día",
        "context": "Contexto",
        "impact": "Impacto",
        "conclusion": "Conclusión",
        "read_more": "Leer en",
        "failed": "No disponible hoy",
        "footer": "Resúmenes generados automáticamente con {model}. "
        "Pueden contener errores: contrasta con la fuente original.",
        "stats": "{articles} noticias · {sections} secciones",
        "cat.us": "Estados Unidos",
        "cat.europe": "Europa",
        "cat.asia": "Asia y Japón",
        "cat.markets": "Mercados y Economía",
        "cat.geopolitics": "Geopolítica",
        "cat.technology": "Tecnología",
    },
}

_WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
}
_MONTHS = {
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
    "es": [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ],
}  # fmt: skip


def language_name(code: str) -> str:
    """Name passed to the model, e.g. ``es`` -> ``Spanish``. Unknown codes pass through."""
    return LANGUAGE_NAMES.get(code, code)


def labels(code: str) -> dict[str, str]:
    return {**LABELS["en"], **LABELS.get(code, {})}


def category_label(category: str, code: str) -> str:
    return labels(code).get(f"cat.{category}", category.replace("_", " ").title())


def format_date(value: datetime, code: str) -> str:
    """Locale-independent date formatting (``locale`` is unreliable on CI runners)."""
    lang = code if code in _WEEKDAYS else "en"
    weekday = _WEEKDAYS[lang][value.weekday()]
    month = _MONTHS[lang][value.month - 1]
    if lang == "es":
        return f"{weekday.capitalize()}, {value.day} de {month} de {value.year}"
    return f"{weekday}, {value.day} {month} {value.year}"
