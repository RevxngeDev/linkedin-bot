"""Preview a draft (plus its automatic fact check) without opening a PR or publishing.

Used by `preview-draft.yml` to tune `config/voice_profile.md` against real model output.
Input comes from environment variables:
  PREVIEW_REPO  owner/name of a public repo → previews a project introduction post;
  PREVIEW_NOTE  otherwise, the note text to turn into a post.
"""

from __future__ import annotations

import os
import sys

import httpx

from linkedin_bot.generator.draft import check_draft, write_draft
from linkedin_bot.generator.prompt import (
    GeneratorError,
    build_note_prompt,
    build_project_intro_prompt,
    load_voice_profile,
)
from linkedin_bot.llm.base import LLMError
from linkedin_bot.llm.config import build_llm_client, load_llm_config
from linkedin_bot.repo.github import GitHubClient, GitHubError
from linkedin_bot.sources.projects import REPO_PATTERN, take_snapshot


def main() -> None:
    repo = os.environ.get("PREVIEW_REPO", "").strip()
    note = os.environ.get("PREVIEW_NOTE", "")
    try:
        profile = load_voice_profile()
        config = load_llm_config()
        with httpx.Client(timeout=120) as http:
            env = dict(os.environ)
            careful = build_llm_client(config, http, env, careful=True)
            if repo:
                if not REPO_PATTERN.match(repo):
                    sys.exit(f"Preview FAILED: invalid repo {repo!r} (expected owner/name)")
                github = GitHubClient(
                    http, env.get("GITHUB_REPOSITORY", repo), env.get("GITHUB_TOKEN")
                )
                prompt = build_project_intro_prompt(take_snapshot(github, repo))
                draft = write_draft(careful, profile, prompt)
            else:
                prompt = build_note_prompt(note)
                draft = write_draft(build_llm_client(config, http, env), profile, prompt)
            report = check_draft(careful, prompt, draft)
    except (GeneratorError, LLMError, GitHubError) as exc:
        sys.exit(f"Preview FAILED: {exc}")
    source = f"project intro of {repo}" if repo else "note"
    print(f"Model: {config.model} | {source} | {len(draft.split())} words\n")
    print("----- DRAFT -----")
    print(draft)
    print("-----------------")
    print("\n----- AUTOMATIC FACT CHECK -----")
    print(report)


if __name__ == "__main__":
    main()
