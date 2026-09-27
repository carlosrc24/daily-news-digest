"""Domain models shared across the pipeline.

Two families:
- LLM schemas (``ArticleAnalysis``, ``CategoryAnalysis``, ``DailyBrief``) are
  passed to Gemini as ``response_schema``. They deliberately contain no URLs,
  sources or dates: those always come from the RSS data, never from the model.
- Pipeline models (``Article``, ``Digest``...) carry the joined result.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# --- Fetched data ------------------------------------------------------------


class Article(BaseModel):
    id: str
    category: str
    source: str
    title: str
    link: str
    summary: str = ""
    published: datetime | None = None


# --- Gemini structured output --------------------------------------------------


class ArticleAnalysis(BaseModel):
    article_id: str = Field(description="The exact id of the input article being analysed.")
    headline: str = Field(description="Concise, neutral headline in the output language.")
    context: str = Field(description="Background needed to understand the news (1-2 sentences).")
    impact: str = Field(
        description="Economic and/or geopolitical impact, with the mechanisms involved "
        "(1-2 sentences)."
    )
    conclusion: str = Field(description="Analytical takeaway or what to watch next (1 sentence).")


class CategoryAnalysis(BaseModel):
    articles: list[ArticleAnalysis]


class DailyBrief(BaseModel):
    key_points: list[str] = Field(description="3 to 5 cross-cutting takeaways of the day.")


# --- Final digest --------------------------------------------------------------


class DigestItem(BaseModel):
    headline: str
    context: str
    impact: str
    conclusion: str
    source: str
    link: str
    original_title: str
    published: datetime | None = None


class DigestSection(BaseModel):
    category: str
    items: list[DigestItem]


class Digest(BaseModel):
    generated_at: datetime
    language: str
    model: str
    key_points: list[str] = []
    sections: list[DigestSection] = []
    failed_categories: list[str] = []

    @property
    def article_count(self) -> int:
        return sum(len(section.items) for section in self.sections)
