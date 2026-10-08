"""Connectivity check: one short generation with the configured provider and model.

Run from GitHub Actions (`llm-check.yml`) to confirm the API key, model id and network
path work before the generator depends on them. Publishes nothing.
"""

from __future__ import annotations

import os
import sys

import httpx

from linkedin_bot.llm.base import LLMError
from linkedin_bot.llm.config import build_llm_client, load_llm_config

SYSTEM = "Responde siempre en español, en una sola frase."
PROMPT = "¿Para qué sirve GitHub Actions?"


def main() -> None:
    try:
        config = load_llm_config()
        with httpx.Client(timeout=60) as http:
            client = build_llm_client(config, http, dict(os.environ))
            text = client.generate(SYSTEM, PROMPT)
    except LLMError as exc:
        sys.exit(f"LLM check FAILED: {exc}")
    print(f"Provider: {config.provider} | model: {config.model}")
    print(f"Reply: {text}")


if __name__ == "__main__":
    main()
