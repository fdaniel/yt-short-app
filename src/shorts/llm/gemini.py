"""Google Gemini (free tier) provider."""

import logging
import time
from collections.abc import Callable

import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import ValidationError

from shorts.llm.base import InvalidOutput, ProviderUnavailable, T

log = logging.getLogger(__name__)

TIMEOUT_MS = 120_000
# "high demand" (503), server errors and slow answers usually pass within a minute; quota and key errors do not
BUSY_WAITS_S = (20, 60)
_BUSY_CODES = (500, 502, 503, 504)


class _Busy(ProviderUnavailable):
    """Gemini is overloaded or slow right now: worth asking again after a wait."""


class GeminiProvider:

    def __init__(self, api_key: str, model: str, client: genai.Client | None = None, *, name: str = "gemini",
                 busy_waits_s: tuple[float, ...] = BUSY_WAITS_S, sleep: Callable[[float], None] = time.sleep) -> None:
        self._client = client or genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
        self._model = model
        self.name = name
        self._busy_waits_s = busy_waits_s
        self._sleep = sleep

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        for wait in self._busy_waits_s:
            try:
                return self._generate(prompt, schema)
            except _Busy as exc:
                log.warning("%s is busy (%s), trying again in %ss", self._model, exc, wait)
                self._sleep(wait)
        try:
            return self._generate(prompt, schema)
        except _Busy as exc:
            raise ProviderUnavailable(str(exc)) from exc

    def _generate(self, prompt: str, schema: type[T]) -> T:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "temperature": 0.4,
                },
            )
        except APIError as exc:
            error = _Busy if exc.code in _BUSY_CODES else ProviderUnavailable
            raise error(f"gemini: {exc.code} {exc.message}") from exc
        except httpx.TimeoutException as exc:
            raise _Busy(f"gemini: network error {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"gemini: network error {exc}") from exc
        if not response.text:
            raise InvalidOutput("gemini returned an empty response")
        try:
            return schema.model_validate_json(response.text)
        except ValidationError as exc:
            raise InvalidOutput(f"gemini output did not match {schema.__name__}") from exc
