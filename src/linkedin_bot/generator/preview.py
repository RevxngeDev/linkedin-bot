"""Preview a draft for a note without opening a PR or publishing anything.

Used by `preview-draft.yml` to tune `config/voice_profile.md` against real model output.
The note arrives in the PREVIEW_NOTE environment variable.
"""

from __future__ import annotations

import os
import sys

import httpx

from linkedin_bot.generator.draft import write_note_draft
from linkedin_bot.generator.prompt import GeneratorError, load_voice_profile
from linkedin_bot.llm.base import LLMError
from linkedin_bot.llm.config import build_llm_client, load_llm_config


def main() -> None:
    note = os.environ.get("PREVIEW_NOTE", "")
    try:
        profile = load_voice_profile()
        config = load_llm_config()
        with httpx.Client(timeout=120) as http:
            llm = build_llm_client(config, http, dict(os.environ))
            draft = write_note_draft(llm, profile, note)
    except (GeneratorError, LLMError) as exc:
        sys.exit(f"Preview FAILED: {exc}")
    words = len(draft.split())
    print(f"Model: {config.model} | {words} words\n")
    print("----- DRAFT -----")
    print(draft)
    print("-----------------")


if __name__ == "__main__":
    main()
