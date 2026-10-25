"""Structured LLM outputs for scripts and fact checks."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_FOOTAGE_QUERIES = 4
MAX_QUERY_CHARS = 40
MAX_GAMES_NAMED = 3
MAX_GAME_NAME_CHARS = 80


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


class ClaimVerdict(_Frozen):
    claim: str
    supported: bool
    reason: str


class FactCheckResult(_Frozen):
    verdicts: list[ClaimVerdict]
