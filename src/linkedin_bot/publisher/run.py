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
from collections.abc import Callable, Mapping
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
from linkedin_bot.notify import messages
from linkedin_bot.notify.telegram import Notifier, NullNotifier, build_notifier
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
    notifier: Notifier | None = None,
    run_url: str | None = None,
) -> int:
    """Return a process exit code: 0 = published or nothing to do, 1 = needs attention."""
    notifier = notifier or NullNotifier()
    run_link = ("🔍 Ver la ejecución", run_url) if run_url else None

    def alert(title: str, detail: str) -> None:
        notifier.send(*messages.problem(title, detail, run_link))

    selection = select_next(store.list_queue(), store.list_published(), clock())
    log(selection.reason)
    if selection.blocked:
        alert("Publicación bloqueada", selection.reason)
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
        alert(
            "Post rechazado: no llegó por un PR fusionado",
            f"{queue_path} no se publicará. Bórralo o vuelve a añadirlo mediante un PR.",
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
            alert(
                "Resultado desconocido al publicar",
                f"{post.id} quedó en 'publishing'. Revisa en LinkedIn si se publicó antes de "
                f"tocar nada. Detalle: {exc}",
            )
            return 1
        store.save_to_queue(replace(claimed, status=QUEUED, claimed_at=None))
        git.commit_and_push([queue_path], f"Release claim on post {post.id} (rejected)")
        log(f"LinkedIn rejected the post; it is queued again: {exc}")
        if exc.status_code == 401:
            log(
                "The LinkedIn access token is expired or revoked. Renew it with "
                "`uv run linkedin-bot-auth` and update the LINKEDIN_ACCESS_TOKEN secret "
                "(see the [linkedin-token] reminder issue)."
            )
            alert(
                "El token de LinkedIn caducó o fue revocado",
                f"{post.id} volvió a la cola. Renueva el token con `uv run linkedin-bot-auth` "
                "y actualiza el secret LINKEDIN_ACCESS_TOKEN.",
            )
        else:
            alert("LinkedIn rechazó el post", f"{post.id} volvió a la cola. Detalle: {exc}")
        return 1
    except httpx.TransportError as exc:
        log(f"UNKNOWN OUTCOME (network error), left in 'publishing': {exc!r}")
        alert(
            "Error de red al publicar",
            f"{post.id} quedó en 'publishing'. Revisa en LinkedIn si se publicó.",
        )
        return 1

    log(f"Published post URN: {post_urn}")
    done = replace(claimed, status=PUBLISHED, linkedin_urn=post_urn, published_at=clock())
    published_path = store.move_to_published(done)
    git.commit_and_push([queue_path, published_path], f"Publish post {post.id} ({post_urn})")
    log(f"Recorded in {published_path}")
    notifier.send(*messages.published(post.id, post_urn, post.body))
    return 0


def actions_run_url(env: Mapping[str, str]) -> str | None:
    """Link to the current GitHub Actions run (default env vars set by the runner)."""
    server, repo, run_id = (env.get(k, "") for k in
                            ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else None


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
            notifier=build_notifier(http, os.environ),
            run_url=actions_run_url(os.environ),
        )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
