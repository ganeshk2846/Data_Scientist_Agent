from __future__ import annotations
import os
"""Minimal OpenAI-compatible client for a local Ollama model (SQL-15).

The client talks to Ollama's OpenAI-compatible endpoint using only the standard
library. It is deliberately model-agnostic; the default configuration targets
``deepseek-r1:7b`` at ``http://localhost:11434/v1``.
"""


import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from contracts.models import ModelUsage

DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "deepseek-r1:7b")
DEFAULT_TIMEOUT_S = 60.0

Transport = Callable[[str, Mapping[str, str], bytes, float], bytes]


class ModelUnavailableError(RuntimeError):
    """The local model endpoint could not be reached or returned an error."""


class ModelResponseError(RuntimeError):
    """The endpoint answered with a response the client cannot use."""


@dataclass(frozen=True, slots=True)
class ChatResponse:
    content: str
    model: str
    usage: ModelUsage
    reasoning: str | None = None


def _default_transport(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout: float,
) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = [
            line
            for line in stripped.splitlines()
            if not line.strip().startswith("```")
        ]
        stripped = "\n".join(lines).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ModelResponseError("model response did not contain a JSON object")

    try:
        value = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ModelResponseError(f"model returned invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ModelResponseError("model JSON response must be an object")
    return value


class OllamaClient:
    """Small chat client for Ollama's OpenAI-compatible API."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        api_key: str | None = None,
        temperature: float = 0.0,
        transport: Transport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url must not be empty")
        if not model.strip():
            raise ValueError("model must not be empty")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")

        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._api_key = api_key or os.environ.get("LLM_API_KEY")
        self._temperature = temperature
        self._transport = transport or _default_transport

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str:
        return self._model

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        if not messages:
            raise ValueError("messages must not be empty")
        if max_tokens is not None and max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")

        selected_model = model or self._model
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": [dict(message) for message in messages],
            "stream": False,
            "temperature": (
                self._temperature if temperature is None else temperature
            ),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ds-agent/0.1",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = f"{self._base_url}/chat/completions"

        try:
            raw = self._transport(url, headers, body, self._timeout_s)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise ModelUnavailableError(
                f"Ollama is unavailable at {self._base_url}: {exc}"
            ) from exc

        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelResponseError("Ollama returned a non-JSON response") from exc
        if not isinstance(response, dict):
            raise ModelResponseError("Ollama response must be a JSON object")

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelResponseError("Ollama response did not include choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        if not isinstance(message, dict):
            raise ModelResponseError("Ollama response did not include a message")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError("Ollama response content was empty")
        reasoning = message.get("reasoning_content")
        if not isinstance(reasoning, str) or not reasoning.strip():
            reasoning = None

        usage_payload = response.get("usage")
        usage_payload = usage_payload if isinstance(usage_payload, dict) else {}
        selected = response.get("model")
        selected = selected if isinstance(selected, str) and selected else selected_model

        return ChatResponse(
            content=content,
            model=selected,
            reasoning=reasoning,
            usage=ModelUsage(
                name=selected,
                version=selected,
                tokens_in=_token_count(usage_payload.get("prompt_tokens")),
                tokens_out=_token_count(usage_payload.get("completion_tokens")),
            ),
        )

    def chat_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], ModelUsage]:
        response = self.chat(
            messages,
            model=model,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _extract_json_object(response.content), response.usage


def _token_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


__all__ = [
    "ChatResponse",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_S",
    "ModelResponseError",
    "ModelUnavailableError",
    "OllamaClient",
    "Transport",
]
