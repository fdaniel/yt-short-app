import pytest
from google.genai.errors import APIError
from pydantic import BaseModel

from shorts.llm.base import InvalidOutput, ProviderUnavailable
from shorts.llm.gemini import GeminiProvider


class Out(BaseModel):
    answer: str


class _Resp:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, result=None, raises=None):
        self.result, self.raises, self.kwargs = result, raises, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self.raises:
            raise self.raises
        return self.result


class FakeGenaiClient:
    def __init__(self, result=None, raises=None):
        self.models = _Models(result, raises)


def api_error(code, message, status="ERROR"):
    return APIError(code, {"error": {"code": code, "message": message, "status": status}})


def test_valid_json_parsed_with_schema():
    client = FakeGenaiClient(result=_Resp('{"answer": "ok"}'))
    assert GeminiProvider("k", "gemini-2.5-flash", client=client).generate_json("p", Out).answer == "ok"
    assert client.models.kwargs["model"] == "gemini-2.5-flash"
    assert client.models.kwargs["config"]["response_schema"] is Out


@pytest.mark.parametrize("code", [401, 403, 429, 500, 503])
def test_api_errors_are_unavailable(code):
    p = GeminiProvider("k", "m", client=FakeGenaiClient(raises=api_error(code, "nope")), sleep=lambda s: None)
    with pytest.raises(ProviderUnavailable):
        p.generate_json("p", Out)


def test_region_error_is_unavailable():
    err = api_error(400, "User location is not supported for the API use.", "FAILED_PRECONDITION")
    with pytest.raises(ProviderUnavailable, match="location"):
        GeminiProvider("k", "m", client=FakeGenaiClient(raises=err)).generate_json("p", Out)


@pytest.mark.parametrize("text", [None, "{bad", '{"other": 1}'])
def test_bad_output_is_invalid(text):
    with pytest.raises(InvalidOutput):
        GeminiProvider("k", "m", client=FakeGenaiClient(result=_Resp(text))).generate_json("p", Out)


def test_network_error_is_unavailable():
    import httpx

    p = GeminiProvider("k", "m", client=FakeGenaiClient(raises=httpx.ConnectError("refused")))
    with pytest.raises(ProviderUnavailable, match="network"):
        p.generate_json("p", Out)


def test_client_built_with_timeout(monkeypatch):
    from shorts.llm import gemini

    captured = {}

    class Spy:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(gemini.genai, "Client", Spy)
    GeminiProvider("k", "m")
    assert captured["api_key"] == "k"
    assert captured["http_options"].timeout == gemini.TIMEOUT_MS


class _Sequence:
    """Answers each call with the next item: an exception is raised, anything else returned."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def generate_content(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _provider(*outcomes):
    client = FakeGenaiClient()
    client.models = _Sequence(*outcomes)
    waits = []
    return GeminiProvider("k", "m", client=client, sleep=waits.append), client.models, waits


def test_busy_gemini_is_tried_again_after_a_wait():
    from shorts.llm.gemini import BUSY_WAITS_S

    p, models, waits = _provider(api_error(503, "high demand"), _Resp('{"answer": "ok"}'))
    assert p.generate_json("p", Out).answer == "ok"
    assert models.calls == 2 and waits == [BUSY_WAITS_S[0]]


def test_busy_gemini_gives_up_after_the_last_wait():
    from shorts.llm.gemini import BUSY_WAITS_S

    busy = [api_error(503, "high demand") for _ in range(len(BUSY_WAITS_S) + 1)]
    p, models, waits = _provider(*busy)
    with pytest.raises(ProviderUnavailable, match="503"):
        p.generate_json("p", Out)
    assert waits == list(BUSY_WAITS_S) and models.calls == len(BUSY_WAITS_S) + 1


def test_slow_answer_is_tried_again():
    import httpx

    p, models, _ = _provider(httpx.ReadTimeout("The read operation timed out"), _Resp('{"answer": "ok"}'))
    assert p.generate_json("p", Out).answer == "ok" and models.calls == 2


@pytest.mark.parametrize("code", [400, 401, 403, 429])
def test_errors_that_waiting_cannot_fix_are_not_retried(code):
    p, models, waits = _provider(api_error(code, "nope"), _Resp('{"answer": "ok"}'))
    with pytest.raises(ProviderUnavailable):
        p.generate_json("p", Out)
    assert models.calls == 1 and waits == []
