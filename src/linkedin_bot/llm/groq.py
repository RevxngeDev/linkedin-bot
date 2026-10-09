"""Groq implementation of `LLMClient` (D-024), via its OpenAI-compatible Chat API.

Request/response shape per Groq's API reference, read 2026-10-08:
https://console.groq.com/docs/api-reference#chat-create
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from linkedin_bot.llm.base import LLMError

CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
# Free plan allows ~8K tokens/minute and one draft prompt is ~5K, so consecutive drafts
# in one run can hit 429. Wait as Groq asks (retry-after), within these bounds.
MAX_RATE_LIMIT_RETRIES = 3
DEFAULT_RETRY_AFTER_SECONDS = 30.0
MAX_RETRY_AFTER_SECONDS = 90.0


class GroqClient:
    def __init__(
        self,
        http: httpx.Client,
        api_key: str,
        model: str,
        max_completion_tokens: int,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._max_completion_tokens = max_completion_tokens
        self._reasoning_effort = reasoning_effort
        self._temperature = temperature
        self._sleep = sleep

    def generate(self, system: str, prompt: str) -> str:
        body: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": self._max_completion_tokens,
            # Only the final answer is wanted, never the model's reasoning trace.
            "include_reasoning": False,
        }
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort
        if self._temperature is not None:
            body["temperature"] = self._temperature

        response = self._post_with_rate_limit_retries(body)
        if response.status_code != 200:
            hint = ""
            if response.status_code == 429:
                hint = f" (rate limited; retry-after={response.headers.get('retry-after')})"
            raise LLMError(
                f"Groq request failed ({response.status_code}){hint}: {response.text}"
            )
        try:
            choice = response.json()["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"Unexpected Groq response shape: {response.text[:500]}") from exc
        if not content or not content.strip():
            raise LLMError(
                f"Groq returned empty content (finish_reason={choice.get('finish_reason')})."
            )
        return content.strip()

    def _post_with_rate_limit_retries(self, body: dict[str, object]) -> httpx.Response:
        for _ in range(MAX_RATE_LIMIT_RETRIES):
            response = self._http.post(CHAT_COMPLETIONS_URL, json=body, headers=self._headers)
            if response.status_code != 429:
                return response
            self._sleep(_retry_after_seconds(response))
        return self._http.post(CHAT_COMPLETIONS_URL, json=body, headers=self._headers)


def _retry_after_seconds(response: httpx.Response) -> float:
    try:
        seconds = float(response.headers.get("retry-after", DEFAULT_RETRY_AFTER_SECONDS))
    except ValueError:
        seconds = DEFAULT_RETRY_AFTER_SECONDS
    return min(max(seconds, 1.0), MAX_RETRY_AFTER_SECONDS)
