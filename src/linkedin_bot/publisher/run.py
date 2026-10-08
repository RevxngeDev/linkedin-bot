"""Publish at most one approved, due post from content/queue/ (Phase 1).

Flow (D-019, D-020):
  select → verify merged PR → claim ("publishing" + push) → create post on LinkedIn
  → record URN, move to content/published/ (+ push).
Claiming before publishing guarantees at-most-once: if a run dies after LinkedIn created
the post, the file stays in "publishing" and no later run publishes it again.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from linkedin_bot.repo.github import GitHubClient
from linkedin_bot.repo.git import Git
from linkedin_bot.publisher.linkedin_client import (
    DEFAULT_API_VERSION,
    LinkedInClient,
    PublishError,
)
from linkedin_bot.publisher.little_text import to_little_text
from linkedin_bot.publisher.selection import select_next
from linkedin_bot.store.posts import PUBLISHED, PUBLISHING, QUEUED, PostStore

BASE_BRANCH = "main"
CONTENT_DIR = Path("content")
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


class GitPort(Protocol):
    def commit_that_added(self, path: Path) -> str | None: ...
    def commit_and_push(self, paths: list[Path], message: str) -> None: ...


class GitHubPort(Protocol):
    def merged_pull_request(self, commit_sha: str, base_branch: str) -> dict | None: ...


class LinkedInPort(Protocol):
    def create_text_post(self, author_urn: str, text: str) -> str: ...


def run_once(
    store: PostStore,
    git: GitPort,
    github: GitHubPort,
    linkedin: LinkedInPort,
    author_urn: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    log: Callable[[str], None] = print,
) -> int:
    """Return a process exit code: 0 = published or nothing to do, 1 = needs attention."""
    selection = select_next(store.list_queue(), store.list_published(), clock())
    log(selection.reason)
    if selection.blocked:
        return 1
    post = selection.post
    if post is None:
        return 0

    queue_path = store.queue_path(post.id)
    added_in = git.commit_that_added(queue_path)
    pull = github.merged_pull_request(added_in, BASE_BRANCH) if added_in else None
    if pull is None:
        log(
            f"REFUSED: {queue_path} did not reach {BASE_BRANCH} through a merged pull "
            f"request (added in commit {added_in}). Remove it or re-add it via a PR."
        )
        return 1
    log(f"Approved by merged PR #{pull['number']}: {pull.get('html_url', '')}")

    claimed = replace(post, status=PUBLISHING, claimed_at=clock())
    store.save_to_queue(claimed)
    git.commit_and_push([queue_path], f"Claim post {post.id} for publishing")

    try:
        post_urn = linkedin.create_text_post(author_urn, to_little_text(post.body))
    except PublishError as exc:
        if not exc.rejected:
            log(f"UNKNOWN OUTCOME, left in 'publishing': {exc}")
            return 1
        store.save_to_queue(replace(claimed, status=QUEUED, claimed_at=None))
        git.commit_and_push([queue_path], f"Release claim on post {post.id} (rejected)")
        log(f"LinkedIn rejected the post; it is queued again: {exc}")
        return 1
    except httpx.TransportError as exc:
        log(f"UNKNOWN OUTCOME (network error), left in 'publishing': {exc!r}")
        return 1

    log(f"Published post URN: {post_urn}")
    done = replace(claimed, status=PUBLISHED, linkedin_urn=post_urn, published_at=clock())
    published_path = store.move_to_published(done)
    git.commit_and_push([queue_path, published_path], f"Publish post {post.id} ({post_urn})")
    log(f"Recorded in {published_path}")
    return 0


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    access_token = _require_env("LINKEDIN_ACCESS_TOKEN")
    author_urn = _require_env("LINKEDIN_MEMBER_URN")
    repository = _require_env("GITHUB_REPOSITORY")
    github_token = os.environ.get("GITHUB_TOKEN", "").strip() or None
    api_version = os.environ.get("LINKEDIN_API_VERSION", "").strip() or DEFAULT_API_VERSION

    with httpx.Client(timeout=30) as http:
        exit_code = run_once(
            store=PostStore(CONTENT_DIR),
            git=Git(Path("."), BASE_BRANCH, BOT_NAME, BOT_EMAIL),
            github=GitHubClient(http, repository, github_token),
            linkedin=LinkedInClient(http, access_token, api_version),
            author_urn=author_urn,
        )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
