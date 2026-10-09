"""Preview a draft for a note without opening a PR or publishing anything.

Used by `preview-draft.yml` to tune `config/voice_profile.md` against real model output.
The note arrives in the PREVIEW_NOTE environment variable.
"""

from __future__ import annotations

import os
import sys

import httpx

from linkedin_bot.generator.draft import check_draft, write_draft
from linkedin_bot.generator.prompt import GeneratorError, build_note_prompt, load_voice_profile
from linkedin_bot.llm.base import LLMError
from linkedin_bot.llm.config import build_llm_client, load_llm_config


def main() -> None:
    note = os.environ.get("PREVIEW_NOTE", "")
    try:
        profile = load_voice_profile()
        config = load_llm_config()
        with httpx.Client(timeout=120) as http:
            env = dict(os.environ)
            prompt = build_note_prompt(note)
            draft = write_draft(build_llm_client(config, http, env), profile, prompt)
            report = check_draft(build_llm_client(config, http, env, careful=True), prompt, draft)
    except (GeneratorError, LLMError) as exc:
        sys.exit(f"Preview FAILED: {exc}")
    words = len(draft.split())
    print(f"Model: {config.model} | {words} words\n")
    print("----- DRAFT -----")
    print(draft)
    print("-----------------")
    print("\n----- AUTOMATIC FACT CHECK -----")
    print(report)


if __name__ == "__main__":
    main()
