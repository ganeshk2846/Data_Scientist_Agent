"""OpenAI-compatible model gateway with bounded retries and safe telemetry."""
from __future__ import annotations

import logging
import math
import os
import random
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from src.onboarding.privacy import redact_payload

load_dotenv()
logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    model: str
    cost_usd: float | None = None


class LLMError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _positive_int(name: str, default: str, *, maximum: int = 1000) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError as error:
        raise LLMError("LLM_CONFIG_INVALID") from error
    if value < 1 or value > maximum:
        raise LLMError("LLM_CONFIG_INVALID")
    return value


def _positive_float(name: str, default: str, *, maximum: float = 3600.0) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError as error:
        raise LLMError("LLM_CONFIG_INVALID") from error
    if not math.isfinite(value) or value <= 0 or value > maximum:
        raise LLMError("LLM_CONFIG_INVALID")
    return value


class LLMGateway:
    def __init__(self, model: str | None = None, *, client=None):
        self.model = model or os.getenv("LLM_MODEL", "qwen-plus")
        self.max_attempts = _positive_int("LLM_MAX_ATTEMPTS", "3", maximum=10)
        self.failure_threshold = _positive_int("LLM_CIRCUIT_FAILURE_THRESHOLD", "3", maximum=100)
        self.circuit_reset_seconds = _positive_float("LLM_CIRCUIT_RESET_SECONDS", "30")
        try:
            jitter_seed = int(os.getenv("LLM_RETRY_JITTER_SEED", "0"))
        except ValueError as error:
            raise LLMError("LLM_CONFIG_INVALID") from error
        connect_timeout = _positive_float("LLM_CONNECT_TIMEOUT_SECONDS", "5")
        read_timeout = _positive_float("LLM_READ_TIMEOUT_SECONDS", "30")
        self._random = random.Random(jitter_seed)
        self._lock = threading.Lock()
        self._failures = 0
        self._circuit_opened_at: float | None = None
        self.calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost_usd = 0.0
        if client is not None:
            self.client = client
        else:
            base_url = os.getenv("LLM_BASE_URL")
            if not base_url:
                raise LLMError("LLM_UNAVAILABLE")
            api_key = os.getenv("LLM_API_KEY")
            if not api_key:
                raise LLMError("LLM_UNAVAILABLE")
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise LLMError("LLM_CONFIG_INVALID")
            if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise LLMError("LLM_CONFIG_INVALID")
            if api_key.startswith("sk-your-") or api_key.startswith("sk-or-..."):
                raise LLMError("LLM_CONFIG_INVALID")
            timeout = httpx.Timeout(read_timeout, connect=connect_timeout, read=read_timeout)
            self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)

    def chat(self, system: str, user: str, temperature: float = 0.0, max_retries: int | None = None) -> LLMResult:
        attempts = min(self.max_attempts, max(1, max_retries or self.max_attempts))
        with self._lock:
            if self._circuit_opened_at is not None:
                if time.monotonic() - self._circuit_opened_at < self.circuit_reset_seconds:
                    raise LLMError("LLM_UNAVAILABLE")
                self._circuit_opened_at = None
                self._failures = 0

        prompt_system = redact_payload(system)
        prompt_user = redact_payload(user)
        started = time.perf_counter()
        failure_code = "LLM_UNAVAILABLE"
        for attempt in range(attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": prompt_system}, {"role": "user", "content": prompt_user}],
                    temperature=temperature,
                )
                elapsed = int((time.perf_counter() - started) * 1000)
                text = response.choices[0].message.content or ""
                text = redact_payload(text)
                usage = getattr(response, "usage", None)
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                cost = _estimate_cost(prompt_tokens, completion_tokens)
                with self._lock:
                    self._failures = 0
                    self._circuit_opened_at = None
                    self.calls += 1
                    self.total_prompt_tokens += prompt_tokens
                    self.total_completion_tokens += completion_tokens
                    if cost is not None:
                        self.total_cost_usd += cost
                logger.info("llm_call", extra={"model": self.model, "latency_ms": elapsed, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "cost_usd": cost})
                return LLMResult(text, prompt_tokens, completion_tokens, elapsed, self.model, cost)
            except (APITimeoutError, httpx.TimeoutException):
                failure_code = "LLM_TIMEOUT"
            except RateLimitError:
                failure_code = "LLM_QUOTA"
            except APIConnectionError:
                failure_code = "LLM_UNAVAILABLE"
            except APIStatusError as error:
                failure_code = "LLM_QUOTA" if error.status_code == 429 else "LLM_UNAVAILABLE"
            except Exception:
                failure_code = "LLM_UNAVAILABLE"
            logger.warning("llm_call_failed", extra={"model": self.model, "failure_code": failure_code, "attempt": attempt + 1})
            with self._lock:
                self._failures += 1
                if self._failures >= self.failure_threshold:
                    self._circuit_opened_at = time.monotonic()
            if attempt + 1 < attempts:
                base = min(8.0, 0.5 * (2 ** attempt))
                time.sleep(base * (0.75 + self._random.random() * 0.5))
        raise LLMError(failure_code)


def _estimate_cost(prompt_tokens: int, completion_tokens: int) -> float | None:
    try:
        input_rate = float(os.environ["LLM_INPUT_USD_PER_1M"])
        output_rate = float(os.environ["LLM_OUTPUT_USD_PER_1M"])
    except (KeyError, ValueError):
        return None
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
