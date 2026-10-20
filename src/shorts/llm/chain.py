"""Try free providers in order; never fall through to anything paid."""

import logging

import httpx

from shorts.config import Settings
from shorts.llm.base import AllProvidersExhausted, InvalidOutput, LLMProvider, ProviderUnavailable, T
from shorts.llm.gemini import GeminiProvider
from shorts.llm.openai_compat import OpenAICompatProvider

log = logging.getLogger(__name__)


class FallbackLLM:
    name = "fallback"

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = tuple(providers)

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        failures = []
        for provider in self.providers:
            try:
                return provider.generate_json(prompt, schema)
            except (ProviderUnavailable, InvalidOutput) as exc:
                log.warning("LLM provider %s failed: %s", provider.name, exc)
                failures.append(f"{provider.name}: {exc}")
        raise AllProvidersExhausted("All free AI providers failed — " + "; ".join(failures))


def build_llm(settings: Settings, http: httpx.Client) -> FallbackLLM:
    providers: list[LLMProvider] = [
        GeminiProvider(settings.gemini_api_key, settings.llm.gemini_model)
    ]
    if settings.llm.gemini_backup_model:
        providers.append(GeminiProvider(settings.gemini_api_key, settings.llm.gemini_backup_model, name="gemini-lite"))
    if settings.fallback_api_key:
        providers.append(
            OpenAICompatProvider(
                settings.llm.fallback_base_url, settings.fallback_api_key, settings.llm.fallback_model, http
            )
        )
    return FallbackLLM(providers)
