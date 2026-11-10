"""The words on a gameplay Short: written by a vision model from frames of the clip, never guessed."""

import logging
import re
from collections.abc import Sequence
from typing import Protocol, TypeVar

from pydantic import BaseModel, Field, field_validator

from shorts.llm.base import InvalidOutput, ProviderUnavailable
from shorts.text import clean_text

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
COVER_LINE_MAX = 12


class VisionLLM(Protocol):
    name: str

    def generate_json_with_images(self, prompt: str, images: list[bytes], schema: type[T]) -> T: ...


class ClipText(BaseModel):
    hook: str = Field(min_length=1, max_length=60)  # on screen all the way through, above the gameplay
    lines: list[str] = Field(default_factory=list, max_length=3)  # one after another, under the gameplay
    title_options: list[str] = Field(min_length=3, max_length=3)
    description: str = Field(max_length=600)
    hashtags: list[str] = Field(min_length=1, max_length=5)
    cover_lines: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("hook", "description")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_text(value).strip()

    @field_validator("lines")
    @classmethod
    def _short_lines(cls, value: list[str]) -> list[str]:
        cleaned = [clean_text(line).strip() for line in value]
        if any(len(line) > 40 for line in cleaned):
            raise ValueError("each line must fit the screen (40 characters)")
        return [line for line in cleaned if line]

    @field_validator("title_options")
    @classmethod
    def _titles(cls, value: list[str]) -> list[str]:
        titles = [clean_text(title).strip()[:100] for title in value]
        if not all(titles):
            raise ValueError("a title is empty once cleaned")
        return titles

    @field_validator("hashtags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        tags = ["#" + re.sub(r"[^\w]", "", tag) for tag in value]
        return [tag for tag in dict.fromkeys(tags) if len(tag) > 1]

    @field_validator("cover_lines")
    @classmethod
    def _cover(cls, value: list[str]) -> list[str]:
        lines = [clean_text(line).strip().upper() for line in value]
        return lines if all(0 < len(line) <= COVER_LINE_MAX for line in lines) else []


def build_clip_prompt(game: str) -> str:
    named = f"the game {game}" if game else "a video game"
    return f"""These pictures are frames, in order, from a short gameplay clip the channel owner recorded while playing {named}.
Write the text for a YouTube Short made from this clip. English only. Return JSON.

- hook: up to 6 words shown above the gameplay the whole time: the payoff or the question that makes people watch.
- lines: 0 to 3 captions of up to 5 words, shown one after another under the gameplay, following what happens.
- title_options: 3 titles of up to 70 characters, each naming {game or "the game"}.
- description: 1 or 2 plain sentences about what happens. No hashtags in it.
- hashtags: 3 to 5, including #shorts and one for the game.
- cover_lines: 2 or 3 words of up to 12 letters for the cover picture.

Rules, because viewers notice mistakes:
- Describe only what the frames show. Do not guess what happens before or after.
- Name a boss, character, item, place or skill only when that name is readable on screen in the frames;
  otherwise say "this boss", "this sword", "this spot".
- No numbers that are not on screen. No "best ever", "secret" or "insane" unless the frames show why.
"""


def fallback_text(game: str) -> ClipText:
    """Plain words when no vision model answers; the owner can discard the Short or upload it by hand with a better title."""
    name = game or "Gameplay"
    tag = "#" + re.sub(r"[^\w]", "", game) if game else "#gaming"
    return ClipText(hook=f"{name} moment", lines=[],
                    title_options=[f"{name}: a moment worth watching", f"{name} gameplay", f"Watch this in {name}"],
                    description=f"A moment from my {name} gameplay.",
                    hashtags=list(dict.fromkeys([tag, "#gaming", "#shorts"])), cover_lines=[])


def write_clip_text(frames: list[bytes], game: str, vision: Sequence[VisionLLM]) -> ClipText:
    prompt = build_clip_prompt(game)
    for model in vision:
        try:
            return model.generate_json_with_images(prompt, frames, ClipText)
        except (ProviderUnavailable, InvalidOutput) as exc:
            log.warning("%s could not write the clip's text: %s", model.name, exc)
    return fallback_text(game)
