"""One cheap LLM call that rates a batch of candidate stories for the channel's audience."""

import html
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shorts.discovery.feeds import FeedItem
from shorts.llm.base import LLMProvider
from shorts.models import VideoFormat

EXCERPT_CHARS = 600
MAX_REASON = 200


class Triage(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    interest: int = Field(ge=0, le=10)
    rumour_or_leak: bool
    on_topic: bool
    game_title: str | None
    format: VideoFormat
    reason: str

    @field_validator("reason")
    @classmethod
    def _short_reason(cls, value: str) -> str:
        return value[:MAX_REASON]


class TriageBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdicts: list[Triage]


def _excerpt(content_html: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", content_html))
    return " ".join(text.split())[:EXCERPT_CHARS]


def build_triage_prompt(items: list[FeedItem]) -> str:
    stories = "\n\n".join(
        f"[{i}] source: {it.source} ({it.topic})\ntitle: {it.title}\ntext: {_excerpt(it.content_html) or '(title only)'}"
        for i, it in enumerate(items)
    )
    formats = ", ".join(f.value for f in VideoFormat)
    return f"""You pick stories for a YouTube Shorts channel about PC hardware and video games
(NVIDIA, AMD, new games, trailers, release dates). Viewers are gamers and PC enthusiasts.

For EVERY story below return one verdict with:
- index: the number in brackets
- interest: 0-10, how much these viewers would want a 45-second video about it
  (launches, release dates, prices, specs, big game announcements score high;
  business deals, finance, executives, events, podcasts and regional promos score low)
- rumour_or_leak: true if the story is about rumours, leaks or unconfirmed information
- on_topic: true only for PC hardware, gaming hardware or video games
- game_title: if the story is about ONE specific video game, its full official title exactly as written
  in the story (e.g. "Call of Duty: Modern Warfare 4"); otherwise null
- format: one of {formats}
- reason: one short sentence

Stories:

{stories}
"""


def triage(items: list[FeedItem], llm: LLMProvider) -> dict[int, Triage]:
    """Verdicts keyed by the item's index in `items`; items the model skipped have no entry."""
    if not items:
        return {}
    batch = llm.generate_json(build_triage_prompt(items), TriageBatch)
    return {v.index: v for v in batch.verdicts if 0 <= v.index < len(items)}
