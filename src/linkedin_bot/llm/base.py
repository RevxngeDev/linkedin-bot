"""Provider-agnostic interface for text generation (D-008).

The generator depends only on `LLMClient`; each provider is one implementation.
This module knows nothing about prompt content (see ARCHITECTURE boundaries).
"""

from __future__ import annotations

from typing import Protocol


class LLMError(RuntimeError):
    """Raised when a provider cannot return generated text."""


class LLMClient(Protocol):
    def generate(self, system: str, prompt: str) -> str:
        """Return the model's text for `prompt`, following the `system` instructions."""
        ...
