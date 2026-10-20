import httpx
import pytest
from pydantic import BaseModel

from shorts.llm.base import AllProvidersExhausted, InvalidOutput, ProviderUnavailable
from shorts.llm.chain import FallbackLLM, build_llm
from tests.fakes import Failing, Returning


class Out(BaseModel):
    answer: str


def test_first_provider_used_when_it_works():
    second = Returning(Out(answer="second"))
    llm = FallbackLLM([Returning(Out(answer="first")), second])
    assert llm.generate_json("p", Out).answer == "first" and second.calls == 0


def test_fallback_used_when_first_unavailable():
    llm = FallbackLLM([Failing(ProviderUnavailable("429")), Returning(Out(answer="ok"))])
    assert llm.generate_json("p", Out).answer == "ok"


def test_fallback_on_invalid_output():
    llm = FallbackLLM([Failing(InvalidOutput("not json")), Returning(Out(answer="ok"))])
    assert llm.generate_json("p", Out).answer == "ok"


def test_all_exhausted_message_names_providers():
    llm = FallbackLLM(
        [Failing(ProviderUnavailable("quota"), name="gemini"), Failing(ProviderUnavailable("quota"), name="groq")]
    )
    with pytest.raises(AllProvidersExhausted, match="gemini.*groq"):
        llm.generate_json("p", Out)


def test_unexpected_errors_are_not_swallowed():
    llm = FallbackLLM([Failing(RuntimeError("bug")), Returning(Out(answer="ok"))])
    with pytest.raises(RuntimeError):
        llm.generate_json("p", Out)


def test_build_llm_without_fallback_key(settings):
    # the lighter Gemini model runs on the same free key and is often free when the main one is busy
    assert [p.name for p in build_llm(settings, httpx.Client()).providers] == ["gemini", "gemini-lite"]


def test_build_llm_with_fallback_key(settings):
    s = settings.model_copy(update={"fallback_api_key": "f"})
    names = [p.name for p in build_llm(s, httpx.Client()).providers]
    assert names == ["gemini", "gemini-lite", "fallback-openai-compat"]


def test_backup_gemini_model_can_be_turned_off(settings):
    s = settings.model_copy(update={"llm": settings.llm.model_copy(update={"gemini_backup_model": None})})
    assert [p.name for p in build_llm(s, httpx.Client()).providers] == ["gemini"]
