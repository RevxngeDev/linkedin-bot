"""Weekly Telegram summary: published last 7 days, queue, drafts awaiting review, token.

Runs from `weekly-summary.yml` (T1, D-032). Read-only: it changes nothing in the repo.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from linkedin_bot.notify import messages
from linkedin_bot.notify.telegram import Notifier, build_notifier
from linkedin_bot.ops.token_reminder import TokenConfig, TokenConfigError, load_token_config
from linkedin_bot.store.posts import PostStore

CONTENT_DIR = Path("content")
WINDOW = timedelta(days=7)


class PullsPort(Protocol):
    def list_pull_requests(self) -> list[dict]: ...


def build_summary(
    store: PostStore,
    github: PullsPort,
    token: TokenConfig | None,
    now: datetime,
    repo_url: str,
) -> tuple[str, list[tuple[str, str]]]:
    published = sorted(
        (p for p in store.list_published() if p.published_at and now - p.published_at <= WINDOW),
        key=lambda p: p.published_at,
    )
    queue = sorted(store.list_queue(), key=lambda p: (p.publish_at or p.created_at, p.id))
    open_pulls = [
        (p["number"], p.get("title", ""), p.get("html_url", ""))
        for p in github.list_pull_requests()
        if p.get("state") == "open"
    ]
    token_days = (token.expires_at - now).days if token else None
    return messages.weekly_summary(
        [(p.id, p.linkedin_urn or "") for p in published],
        [p.id for p in queue],
        open_pulls,
        token_days,
        repo_url,
    )


def run_summary(
    store: PostStore,
    github: PullsPort,
    token: TokenConfig | None,
    notifier: Notifier,
    now: datetime,
    repo_url: str,
    log: Callable[[str], None] = print,
) -> int:
    text, buttons = build_summary(store, github, token, now, repo_url)
    log(text)
    notifier.send(text, buttons)
    return 0


def main() -> None:
    from linkedin_bot.repo.github import GitHubClient, GitHubError

    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repository:
        sys.exit("Missing required environment variable: GITHUB_REPOSITORY")
    try:
        token = load_token_config()
    except TokenConfigError:
        token = None
    repo_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repository}"
    try:
        with httpx.Client(timeout=30) as http:
            exit_code = run_summary(
                PostStore(CONTENT_DIR),
                GitHubClient(http, repository, os.environ.get("GITHUB_TOKEN")),
                token,
                build_notifier(http, os.environ),
                datetime.now(UTC),
                repo_url,
            )
    except GitHubError as exc:
        sys.exit(f"Weekly summary FAILED: {exc}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
