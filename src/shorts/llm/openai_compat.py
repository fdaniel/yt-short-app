"""Any OpenAI-compatible chat endpoint (e.g. a free Groq key) as a fallback provider."""

import json

import httpx
from pydantic import ValidationError

from shorts.llm.base import InvalidOutput, ProviderUnavailable, T

_UNAVAILABLE = {401, 403, 429}


class OpenAICompatProvider:
    name = "fallback-openai-compat"

    def __init__(self, base_url: str, api_key: str, model: str, http: httpx.Client) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key, self._model, self._http = api_key, model, http

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        full_prompt = (
            f"{prompt}\n\nReply with only a JSON object matching this JSON schema:\n"
            f"{json.dumps(schema.model_json_schema())}"
        )
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": full_prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
        }
        try:
            response = self._http.post(
                self._url, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.name}: network error {exc}") from exc
        if response.status_code in _UNAVAILABLE or response.status_code >= 500:
            raise ProviderUnavailable(f"{self.name}: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise InvalidOutput(f"{self.name}: HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            return schema.model_validate_json(content)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise InvalidOutput(f"{self.name} output did not match {schema.__name__}") from exc
