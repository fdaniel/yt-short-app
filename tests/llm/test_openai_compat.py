import httpx
import pytest
import respx
from pydantic import BaseModel

from shorts.llm.base import InvalidOutput, ProviderUnavailable
from shorts.llm.openai_compat import OpenAICompatProvider

URL = "https://api.groq.com/openai/v1/chat/completions"


class Out(BaseModel):
    answer: str


def provider():
    return OpenAICompatProvider("https://api.groq.com/openai/v1", "k", "m", httpx.Client())


def reply(content: str):
    return {"choices": [{"message": {"content": content}}]}


@respx.mock
@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_unavailable_statuses(status):
    respx.post(URL).respond(status)
    with pytest.raises(ProviderUnavailable):
        provider().generate_json("p", Out)


@respx.mock
def test_network_error_is_unavailable():
    respx.post(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(ProviderUnavailable):
        provider().generate_json("p", Out)


@respx.mock
def test_bad_json_is_invalid_output():
    respx.post(URL).respond(200, json=reply("{nope"))
    with pytest.raises(InvalidOutput):
        provider().generate_json("p", Out)


@respx.mock
def test_wrong_shape_is_invalid_output():
    respx.post(URL).respond(200, json=reply('{"other": 1}'))
    with pytest.raises(InvalidOutput):
        provider().generate_json("p", Out)


@respx.mock
def test_parses_valid_and_sends_schema_and_key():
    route = respx.post(URL).respond(200, json=reply('{"answer": "hi"}'))
    assert provider().generate_json("p", Out).answer == "hi"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer k"
    body = request.content.decode()
    assert '"json_object"' in body and "answer" in body
