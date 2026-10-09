"""Turn a user prompt (a note or repo material) into a clean post draft."""

from __future__ import annotations

import re

from linkedin_bot.generator.prompt import (
    CHECK_SYSTEM,
    NO_PROBLEMS,
    GeneratorError,
    VoiceProfile,
    build_check_prompt,
    build_note_prompt,
    build_system_prompt,
)
from linkedin_bot.llm.base import LLMClient, LLMError

WRAPPING_FENCE = re.compile(r"\A```[a-zA-Z]*\n(.*)\n```\Z", re.DOTALL)
WRAPPING_QUOTES = (('"', '"'), ("\u201c", "\u201d"), ("\u00ab", "\u00bb"))
# Markdown emphasis is not rendered by LinkedIn (D-022): keep the words, drop the markers.
MARKDOWN_EMPHASIS = re.compile(r"(\*\*|__)(.+?)\1")
# Single-asterisk italics (*texto*), but not "2 * 3" or "* item" bullets: the opening
# asterisk must touch the word after it and the closing one the word before it.
MARKDOWN_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])")
# Non-standard hyphens and spaces that models emit (e.g. U+2011 in "gpt-oss").
CHARACTER_FIXES = str.maketrans(
    {"\u2010": "-", "\u2011": "-", "\u00a0": " ", "\u202f": " "}
)


def clean_draft(text: str) -> str:
    """Remove wrappers and formatting a model sometimes adds despite the rules."""
    text = text.strip()
    fence = WRAPPING_FENCE.match(text)
    if fence:
        text = fence.group(1).strip()
    for opening, closing in WRAPPING_QUOTES:
        inner = text[len(opening) : -len(closing)]
        if text.startswith(opening) and text.endswith(closing) and opening not in inner:
            text = inner.strip()
    text = MARKDOWN_EMPHASIS.sub(r"\2", text)
    text = MARKDOWN_ITALIC.sub(r"\1", text).translate(CHARACTER_FIXES)
    return "\n".join(line.rstrip() for line in text.splitlines())


def write_draft(llm: LLMClient, profile: VoiceProfile, user_prompt: str) -> str:
    draft = clean_draft(llm.generate(build_system_prompt(profile), user_prompt))
    if not draft:
        raise GeneratorError("the model returned an empty draft")
    return draft


def write_note_draft(llm: LLMClient, profile: VoiceProfile, note: str) -> str:
    return write_draft(llm, profile, build_note_prompt(note))


def check_draft(llm: LLMClient, draft_prompt: str, draft: str) -> str:
    """Second LLM pass listing unsupported or distorted claims, for the PR description.

    Never raises: a failed check must not block the draft, it is reported instead.
    """
    try:
        report = llm.generate(CHECK_SYSTEM, build_check_prompt(draft_prompt, draft)).strip()
    except LLMError as exc:
        return f"Automatic fact check could not run: {exc}"
    if not report or report.upper().startswith(NO_PROBLEMS):
        return "No problems detected by the automatic check (still review it yourself)."
    return report
