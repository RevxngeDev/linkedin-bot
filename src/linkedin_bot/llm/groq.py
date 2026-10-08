"""Groq implementation of `LLMClient` (D-024), via its OpenAI-compatible Chat API.

Request/response shape per Groq's API reference, read 2026-10-08:
https://console.groq.com/docs/api-reference#chat-create
"""

from __future__ import annotations

import httpx

from linkedin_bot.llm.base import LLMError

CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqClient:
    def __init__(
        self,
        http: httpx.Client,
        api_key: str,
        model: str,
        max_completion_tokens: int,
        reasoning_effort: str | None = None,
    ) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._max_completion_tokens = max_completion_tokens
        self._reasoning_effort = reasoning_effort

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

        response = self._http.post(CHAT_COMPLETIONS_URL, json=body, headers=self._headers)
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
