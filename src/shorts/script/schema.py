"""Structured LLM outputs for scripts and fact checks."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shorts.script.take import TakeError, clean_take

MAX_FOOTAGE_QUERIES = 4
MAX_QUERY_CHARS = 40
MAX_GAMES_NAMED = 3
MAX_GAME_NAME_CHARS = 80
MAX_TAKE_OPTIONS = 3


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Claim(_Frozen):
    text: str
    source_quote: str


class CardFact(_Frozen):
    label: str
    value: str


class ScriptDraft(_Frozen):
    hook: str
    body: list[str] = Field(min_length=3, max_length=6)
    closing: str
    title_options: list[str] = Field(min_length=3, max_length=3)
    description: str
    hashtags: list[str] = Field(min_length=3, max_length=5)
    claims: list[Claim] = Field(min_length=1)
    card_facts: list[CardFact] = Field(default_factory=list, max_length=6)
    footage_queries: list[str] = Field(default_factory=list)
    games_named: list[str] = Field(default_factory=list)
    subject: str = ""  # the one game, platform or product the Short is about
    # opinions the owner may pick from for their own closing line; never voiced unless they choose one
    take_options: list[str] = Field(default_factory=list)

    @field_validator("footage_queries", mode="before")
    @classmethod
    def _tidy_queries(cls, queries: object) -> list[str]:
        """Search terms only steer stock footage, so sloppy ones are dropped rather than failing the script."""
        if not isinstance(queries, list):
            return []
        tidy = [" ".join(q.split())[:MAX_QUERY_CHARS].strip() for q in queries if isinstance(q, str)]
        return [q for q in tidy if q][:MAX_FOOTAGE_QUERIES]

    @field_validator("games_named", mode="before")
    @classmethod
    def _tidy_games(cls, names: object) -> list[str]:
        """Game names only add footage, and each is checked against the story, so bad ones are dropped."""
        if not isinstance(names, list):
            return []
        tidy = [" ".join(n.split()) for n in names if isinstance(n, str)]
        return [n for n in tidy if 0 < len(n) <= MAX_GAME_NAME_CHARS][:MAX_GAMES_NAMED]


    @field_validator("take_options", mode="before")
    @classmethod
    def _tidy_takes(cls, options: object) -> list[str]:
        """Only suggestions, so unusable ones are dropped; one with a number could state an unchecked fact."""
        if not isinstance(options, list):
            return []
        tidy = []
        for option in options:
            try:
                take = clean_take(option) if isinstance(option, str) and not re.search(r"\d", option) else None
            except TakeError:
                take = None
            if take and take not in tidy:
                tidy.append(take)
        return tidy[:MAX_TAKE_OPTIONS]


class ClaimVerdict(_Frozen):
    claim: str
    supported: bool
    reason: str


class FactCheckResult(_Frozen):
    verdicts: list[ClaimVerdict]
