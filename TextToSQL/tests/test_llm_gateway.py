import logging
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from src.llm.gateway import LLMError, LLMGateway


class FakeCompletions:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def fake_client(completions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_prompts_responses_and_logs_are_redacted(caplog):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Echo person@example.invalid"))], usage=SimpleNamespace(prompt_tokens=4, completion_tokens=3))
    completions = FakeCompletions(response=response)
    gateway = LLMGateway(client=fake_client(completions))
    with caplog.at_level(logging.INFO):
        result = gateway.chat("Answer safely", "Contact person@example.invalid")
    message = completions.calls[0]["messages"][1]["content"]
    assert "person@example.invalid" not in message
    assert "person@example.invalid" not in result.text
    assert "person@example.invalid" not in caplog.text
    assert result.prompt_tokens == 4 and result.completion_tokens == 3


def test_timeout_is_bounded_by_attempt_limit_and_opens_circuit(monkeypatch, caplog):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("LLM_CIRCUIT_FAILURE_THRESHOLD", "1")
    completions = FakeCompletions(error=httpx.ReadTimeout("contact person@example.invalid"))
    gateway = LLMGateway(client=fake_client(completions))
    with pytest.raises(LLMError) as error:
        gateway.chat("system", "user")
    assert error.value.code == "LLM_TIMEOUT"
    assert "person@example.invalid" not in str(error.value)
    assert "person@example.invalid" not in caplog.text
    with pytest.raises(LLMError) as open_error:
        gateway.chat("system", "user")
    assert open_error.value.code == "LLM_UNAVAILABLE"
    assert len(completions.calls) == 1


def test_openai_compatible_fake_http_server_receives_redacted_prompt():
    seen = []

    def handle(request):
        import json

        body = json.loads(request.content)
        seen.extend(message["content"] for message in body["messages"])
        return httpx.Response(200, json={"id": "fake", "object": "chat.completion", "created": 0, "model": "fake", "choices": [{"index": 0, "message": {"role": "assistant", "content": "Safe response."}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}})

    transport = httpx.MockTransport(handle)
    http_client = httpx.Client(transport=transport)
    fake_server_client = OpenAI(api_key="test", base_url="http://fake.test/v1", http_client=http_client, max_retries=0)
    result = LLMGateway(client=fake_server_client).chat("System prompt", "Email person@example.invalid")
    assert result.text == "Safe response."
    assert "person@example.invalid" not in " ".join(seen)
    fake_server_client.close()


@pytest.mark.parametrize("name,value", [
    ("LLM_MAX_ATTEMPTS", "0"),
    ("LLM_CONNECT_TIMEOUT_SECONDS", "nan"),
    ("LLM_READ_TIMEOUT_SECONDS", "-1"),
    ("LLM_RETRY_JITTER_SEED", "not-an-integer"),
])
def test_invalid_runtime_configuration_fails_with_non_sensitive_error(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(LLMError) as error:
        LLMGateway(client=fake_client(FakeCompletions()))
    assert error.value.code == "LLM_CONFIG_INVALID"


def test_remote_http_endpoint_and_example_secret_are_rejected(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://api.example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    with pytest.raises(LLMError) as error:
        LLMGateway()
    assert error.value.code == "LLM_CONFIG_INVALID"
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-your-placeholder")
    with pytest.raises(LLMError) as error:
        LLMGateway()
    assert error.value.code == "LLM_CONFIG_INVALID"
