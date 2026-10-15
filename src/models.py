"""Domain models shared across the pipeline.

Two families:
- LLM schemas (``StoryAnalysis``, ``DailySelection``, ``DailyBrief``) are
  passed to Gemini as ``response_schema``. They deliberately contain no URLs,
  sources or dates: those always come from the RSS data, never from the model.
- Pipeline models (``Article``, ``Digest``...) carry the joined result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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


Topic = Literal["economy", "geopolitics", "technology"]

TOPICS: tuple[Topic, ...] = ("economy", "geopolitics", "technology")
# Topic used when the model's label is not one of TOPICS; derived from the feed category.
CATEGORY_TOPICS: dict[str, Topic] = {
    "markets": "economy",
    "technology": "technology",
}
DEFAULT_TOPIC: Topic = "geopolitics"


class StoryAnalysis(BaseModel):
    article_id: str = Field(description="The exact id of the input article being analysed.")
    # Plain str (not Topic) so an unexpected label falls back instead of failing validation.
    topic: str = Field(description="Main area of the story: economy, geopolitics or technology.")
    headline: str = Field(description="Concise, neutral headline in the output language.")
    summary: str = Field(
        description="What happened, why it matters and what to watch next, in 3-4 sentences "
        "(60-80 words). Explain the mechanisms, do not restate the headline."
    )


class DailySelection(BaseModel):
    stories: list[StoryAnalysis]


class DailyBrief(BaseModel):
    key_points: list[str] = Field(description="3 to 5 cross-cutting takeaways of the day.")


# --- Final digest --------------------------------------------------------------


class DigestItem(BaseModel):
    topic: Topic
    headline: str
    summary: str
    source: str
    link: str
    original_title: str
    published: datetime | None = None


class Digest(BaseModel):
    generated_at: datetime
    language: str
    model: str
    key_points: list[str] = []
    items: list[DigestItem] = []
