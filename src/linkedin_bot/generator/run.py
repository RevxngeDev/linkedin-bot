"""Turn new notes in content/ideas/ into draft PRs (Phase 2).

For each note `content/ideas/<slug>.md`:
  - its branch is always `post/idea-<slug>` (D-023), so the note's history is findable;
  - if any PR exists for that branch (open, merged or closed = rejected) → skip;
  - if a queued/published post already cites the note → skip;
  - if the branch exists without a PR (an earlier run stopped half-way) → only open the PR;
  - otherwise draft with the LLM, push the branch with content/queue/<id>.md, open the PR.
The owner reviews and merges (approve) or closes (reject); publishing is Phase 1's job.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from linkedin_bot.generator.draft import write_note_draft
from linkedin_bot.generator.prompt import GeneratorError, VoiceProfile, load_voice_profile
from linkedin_bot.llm.base import LLMClient, LLMError
from linkedin_bot.llm.config import build_llm_client, load_llm_config
from linkedin_bot.repo.git import Git
from linkedin_bot.repo.github import GitHubClient
from linkedin_bot.store.posts import ID_PATTERN, QUEUED, Post, PostStore, render_post

BASE_BRANCH = "main"
CONTENT_DIR = Path("content")
IDEAS_DIR = CONTENT_DIR / "ideas"
MAX_DRAFTS_PER_RUN = 3
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


@dataclass(frozen=True)
class Idea:
    slug: str
    path: Path
    text: str

    @property
    def branch(self) -> str:
        return f"post/idea-{self.slug}"


class GitPort(Protocol):
    def remote_branch_exists(self, branch: str) -> bool: ...
    def push_new_branch(self, branch: str, files: dict[Path, str], message: str) -> None: ...


class GitHubPort(Protocol):
    def pull_requests_for_branch(self, branch: str) -> list[dict]: ...
    def create_pull_request(self, head: str, base: str, title: str, body: str) -> dict: ...


def find_ideas(ideas_dir: Path, log: Callable[[str], None] = print) -> list[Idea]:
    if not ideas_dir.is_dir():
        return []
    ideas = []
    for path in sorted(ideas_dir.glob("*.md")):
        if not ID_PATTERN.match(path.stem):
            log(f"Skipping {path}: file name must be lowercase letters, digits and '-'.")
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            log(f"Skipping {path}: empty note.")
            continue
        ideas.append(Idea(slug=path.stem, path=path, text=text))
    return ideas


def pull_request_body(idea: Idea, post_id: str) -> str:
    return f"""Draft generated from the note `{idea.path.as_posix()}`.

**Review checklist**
- [ ] Every fact in the draft is in the note below (nothing invented).
- [ ] It sounds like me; edit the file in this PR as much as needed.
- [ ] Hashtags make sense.

**Merge** = approve: `publish.yml` publishes it (max 1 post per UTC day).
**Close** = reject: this note will not be drafted again.

<details><summary>Source note</summary>

{idea.text}

</details>

Post file: `content/queue/{post_id}.md`
"""


def run_generator(
    ideas_dir: Path,
    store: PostStore,
    git: GitPort,
    github: GitHubPort,
    llm: LLMClient,
    profile: VoiceProfile,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    log: Callable[[str], None] = print,
    max_drafts: int = MAX_DRAFTS_PER_RUN,
) -> int:
    """Return a process exit code: 0 = all good, 1 = at least one note failed."""
    cited = {p.source_ref for p in store.list_queue() + store.list_published()}
    opened = 0
    failures = 0

    for idea in find_ideas(ideas_dir, log):
        source_ref = idea.path.as_posix()
        if source_ref in cited:
            log(f"{source_ref}: already has a post; skipping.")
            continue
        existing = github.pull_requests_for_branch(idea.branch)
        if existing:
            log(f"{source_ref}: PR #{existing[0]['number']} ({existing[0]['state']}); skipping.")
            continue
        if opened >= max_drafts:
            log(f"Reached {max_drafts} drafts this run; remaining notes wait for the next run.")
            break

        post_id = f"{clock():%Y-%m-%d}-{idea.slug}"
        if git.remote_branch_exists(idea.branch):
            log(f"{source_ref}: branch {idea.branch} exists without a PR; opening the PR only.")
        else:
            try:
                body = write_note_draft(llm, profile, idea.text)
            except (LLMError, GeneratorError) as exc:
                log(f"{source_ref}: draft FAILED: {exc}")
                failures += 1
                continue
            post = Post(
                id=post_id,
                source="note",
                source_ref=source_ref,
                status=QUEUED,
                created_at=clock().replace(microsecond=0),
                body=body,
            )
            git.push_new_branch(
                idea.branch,
                {store.queue_path(post.id): render_post(post)},
                f"Draft post {post.id} from {source_ref}",
            )

        pull = github.create_pull_request(
            head=idea.branch,
            base=BASE_BRANCH,
            title=f"Post draft: {idea.slug}",
            body=pull_request_body(idea, post_id),
        )
        log(f"{source_ref}: opened PR #{pull['number']} {pull.get('html_url', '')}")
        opened += 1

    log(f"Done: {opened} PR(s) opened, {failures} failure(s).")
    return 1 if failures else 0


def main() -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repository:
        sys.exit("Missing required environment variable: GITHUB_REPOSITORY")
    try:
        profile = load_voice_profile()
        config = load_llm_config()
        with httpx.Client(timeout=120) as http:
            exit_code = run_generator(
                ideas_dir=IDEAS_DIR,
                store=PostStore(CONTENT_DIR),
                git=Git(Path("."), BASE_BRANCH, BOT_NAME, BOT_EMAIL),
                github=GitHubClient(http, repository, os.environ.get("GITHUB_TOKEN")),
                llm=build_llm_client(config, http, dict(os.environ)),
                profile=profile,
            )
    except (GeneratorError, LLMError) as exc:
        sys.exit(f"Generator FAILED: {exc}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
