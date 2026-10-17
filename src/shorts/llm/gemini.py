"""Google Gemini (free tier) provider."""

from google import genai
from google.genai.errors import APIError
from pydantic import ValidationError

from shorts.llm.base import InvalidOutput, ProviderUnavailable, T


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, client: genai.Client | None = None) -> None:
        self._client = client or genai.Client(api_key=api_key)
        self._model = model

    def generate_json(self, prompt: str, schema: type[T]) -> T:
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
            raise ProviderUnavailable(f"gemini: {exc.code} {exc.message}") from exc
        if not response.text:
            raise InvalidOutput("gemini returned an empty response")
        try:
            return schema.model_validate_json(response.text)
        except ValidationError as exc:
            raise InvalidOutput(f"gemini output did not match {schema.__name__}") from exc
