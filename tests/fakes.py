"""Test doubles shared across test modules."""

import numpy as np

from shorts.llm.base import InvalidOutput, ProviderUnavailable  # noqa: F401  (re-export for tests)


class Failing:
    def __init__(self, error: Exception, name: str = "failing") -> None:
        self.error, self.name, self.calls = error, name, 0

    def generate_json(self, prompt, schema):
        self.calls += 1
        raise self.error


class Returning:
    def __init__(self, value, name: str = "returning") -> None:
        self.value, self.name, self.calls = value, name, 0

    def generate_json(self, prompt, schema):
        self.calls += 1
        return self.value


class ScriptedLLM:
    """Returns the given responses in order and records every prompt."""

    name = "scripted"

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    def generate_json(self, prompt, schema):
        self.prompts.append(prompt)
        response = self._responses.pop(0)
        assert isinstance(response, schema), f"expected {schema.__name__}, got {type(response).__name__}"
        return response


class FakeTTS:
    """Silent audio whose length is proportional to the text (seconds per character)."""

    def __init__(self, rate: float = 0.05, sample_rate: int = 24000) -> None:
        self.rate, self.sample_rate = rate, sample_rate

    def synthesize(self, text):
        return np.zeros(int(len(text) * self.rate * self.sample_rate), np.float32), self.sample_rate

