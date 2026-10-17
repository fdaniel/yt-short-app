"""Structured LLM outputs for scripts and fact checks."""

from pydantic import BaseModel, ConfigDict, Field


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


class ClaimVerdict(_Frozen):
    claim: str
    supported: bool
    reason: str


class FactCheckResult(_Frozen):
    verdicts: list[ClaimVerdict]
