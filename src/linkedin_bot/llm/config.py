"""LLM settings live in `config/llm.yml`, never in code (D-008): models change often."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from linkedin_bot.llm.base import LLMClient, LLMError
from linkedin_bot.llm.groq import GroqClient

DEFAULT_CONFIG_PATH = Path("config/llm.yml")
SUPPORTED_PROVIDERS = ("groq",)
API_KEY_ENV = {"groq": "GROQ_API_KEY"}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    max_completion_tokens: int
    reasoning_effort: str | None = None


def load_llm_config(path: Path = DEFAULT_CONFIG_PATH) -> LLMConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise LLMError(f"Cannot read LLM config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LLMError(f"{path}: expected a mapping")

    provider = str(raw.get("provider", "")).strip()
    model = str(raw.get("model", "")).strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise LLMError(f"{path}: provider must be one of {', '.join(SUPPORTED_PROVIDERS)}")
    if not model:
        raise LLMError(f"{path}: 'model' is required")
    max_tokens = raw.get("max_completion_tokens")
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        raise LLMError(f"{path}: 'max_completion_tokens' must be a positive integer")
    effort = raw.get("reasoning_effort")
    return LLMConfig(provider, model, max_tokens, str(effort) if effort else None)


def build_llm_client(config: LLMConfig, http: httpx.Client, env: dict[str, str]) -> LLMClient:
    key_name = API_KEY_ENV[config.provider]
    api_key = env.get(key_name, "").strip()
    if not api_key:
        raise LLMError(f"Missing environment variable {key_name}")
    return GroqClient(
        http,
        api_key,
        config.model,
        config.max_completion_tokens,
        config.reasoning_effort,
    )
