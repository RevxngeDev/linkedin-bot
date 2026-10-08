import json

import httpx
import pytest

from linkedin_bot.llm.base import LLMError
from linkedin_bot.llm.config import LLMConfig, build_llm_client, load_llm_config
from linkedin_bot.llm.groq import CHAT_COMPLETIONS_URL, GroqClient


def ok_response(content="Hola mundo.", finish_reason="stop"):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ]
        },
    )


def groq(handler, effort="low"):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GroqClient(http, "gsk_test", "openai/gpt-oss-120b", 4096, effort)


def test_generate_sends_expected_request_and_returns_text():
    seen = {}

    def handler(request):
        seen["request"] = request
        return ok_response("  Un post en español.  ")

    text = groq(handler).generate("Sistema", "Nota del autor")
    request = seen["request"]
    body = json.loads(request.content)
    assert text == "Un post en español."
    assert str(request.url) == CHAT_COMPLETIONS_URL
    assert request.headers["Authorization"] == "Bearer gsk_test"
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["messages"] == [
        {"role": "system", "content": "Sistema"},
        {"role": "user", "content": "Nota del autor"},
    ]
    assert body["max_completion_tokens"] == 4096
    assert body["include_reasoning"] is False
    assert body["reasoning_effort"] == "low"


def test_reasoning_effort_and_temperature_omitted_when_not_configured():
    def handler(request):
        body = json.loads(request.content)
        assert "reasoning_effort" not in body and "temperature" not in body
        return ok_response()

    groq(handler, effort=None).generate("s", "p")


def test_temperature_is_sent_when_configured():
    def handler(request):
        assert json.loads(request.content)["temperature"] == 0.5
        return ok_response()

    http = httpx.Client(transport=httpx.MockTransport(handler))
    GroqClient(http, "k", "m", 100, None, 0.5).generate("s", "p")


def test_rate_limit_error_mentions_retry_after():
    client = groq(lambda r: httpx.Response(429, headers={"retry-after": "7"}, text="slow"))
    with pytest.raises(LLMError, match="retry-after=7"):
        client.generate("s", "p")


def test_http_error_raises():
    with pytest.raises(LLMError, match="401"):
        groq(lambda r: httpx.Response(401, text="invalid key")).generate("s", "p")


def test_empty_content_raises_with_finish_reason():
    with pytest.raises(LLMError, match="finish_reason=length"):
        groq(lambda r: ok_response("", "length")).generate("s", "p")


def test_unexpected_shape_raises():
    with pytest.raises(LLMError, match="Unexpected"):
        groq(lambda r: httpx.Response(200, json={"oops": True})).generate("s", "p")


def test_load_config(tmp_path):
    path = tmp_path / "llm.yml"
    path.write_text(
        "provider: groq\nmodel: openai/gpt-oss-120b\nmax_completion_tokens: 4096\n"
        "reasoning_effort: low\n",
        encoding="utf-8",
    )
    assert load_llm_config(path) == LLMConfig("groq", "openai/gpt-oss-120b", 4096, "low")


def test_repo_config_file_is_valid():
    config = load_llm_config()
    assert config.provider == "groq" and config.model
    assert config.temperature is not None and 0 <= config.temperature <= 2


def test_load_config_with_temperature(tmp_path):
    path = tmp_path / "llm.yml"
    path.write_text(
        "provider: groq\nmodel: m\nmax_completion_tokens: 10\ntemperature: 0.5\n",
        encoding="utf-8",
    )
    assert load_llm_config(path).temperature == 0.5


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("provider: other\nmodel: m\nmax_completion_tokens: 1\n", "provider"),
        ("provider: groq\nmax_completion_tokens: 1\n", "model"),
        ("provider: groq\nmodel: m\nmax_completion_tokens: 0\n", "max_completion_tokens"),
        ("- not a mapping\n", "mapping"),
        ("provider: groq\nmodel: m\nmax_completion_tokens: 1\ntemperature: 3\n", "temperature"),
        ("provider: groq\nmodel: m\nmax_completion_tokens: 1\ntemperature: hot\n", "temperature"),
    ],
)
def test_invalid_config_raises(tmp_path, content, message):
    path = tmp_path / "llm.yml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LLMError, match=message):
        load_llm_config(path)


def test_build_client_requires_api_key():
    config = LLMConfig("groq", "m", 10)
    with httpx.Client() as http:
        with pytest.raises(LLMError, match="GROQ_API_KEY"):
            build_llm_client(config, http, {})
        assert isinstance(build_llm_client(config, http, {"GROQ_API_KEY": "k"}), GroqClient)
