"""Provider-neutral interface for structured (JSON) LLM calls."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderUnavailable(Exception):
    """Quota, auth, region, network or server problem: try another provider."""


class InvalidOutput(Exception):
    """The provider answered, but not with JSON matching the schema."""


class AllProvidersExhausted(Exception):
    """Every configured free provider failed for this request."""


class LLMProvider(Protocol):
    name: str

    def generate_json(self, prompt: str, schema: type[T]) -> T: ...
