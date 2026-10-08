"""Turn a note into a post draft with any `LLMClient`."""

from __future__ import annotations

import re

from linkedin_bot.generator.prompt import (
    GeneratorError,
    VoiceProfile,
    build_note_prompt,
    build_system_prompt,
)
from linkedin_bot.llm.base import LLMClient

WRAPPING_FENCE = re.compile(r"\A```[a-zA-Z]*\n(.*)\n```\Z", re.DOTALL)
WRAPPING_QUOTES = (('"', '"'), ("“", "”"), ("«", "»"))


def clean_draft(text: str) -> str:
    """Remove wrappers a model sometimes adds around the post despite the rules."""
    text = text.strip()
    fence = WRAPPING_FENCE.match(text)
    if fence:
        text = fence.group(1).strip()
    for opening, closing in WRAPPING_QUOTES:
        inner = text[len(opening) : -len(closing)]
        if text.startswith(opening) and text.endswith(closing) and opening not in inner:
            text = inner.strip()
    return text


def write_note_draft(llm: LLMClient, profile: VoiceProfile, note: str) -> str:
    draft = clean_draft(llm.generate(build_system_prompt(profile), build_note_prompt(note)))
    if not draft:
        raise GeneratorError("the model returned an empty draft")
    return draft
