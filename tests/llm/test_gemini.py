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
    p = GeminiProvider("k", "m", client=FakeGenaiClient(raises=api_error(code, "nope")))
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
