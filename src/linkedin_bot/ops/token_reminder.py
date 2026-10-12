"""Open a GitHub issue before the LinkedIn access token expires (Phase 4, D-031).

LinkedIn tokens last 60 days and cannot be refreshed programmatically for this app, so
renewal is a manual step on the owner's machine. The expiry date (not a secret) lives in
`config/linkedin_token.yml`; a daily workflow runs this check and opens one issue with
the renewal steps once the expiry is inside the reminder window.
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
import yaml

from linkedin_bot.notify import messages
from linkedin_bot.notify.telegram import Notifier, NullNotifier, build_notifier

DEFAULT_CONFIG_PATH = Path("config/linkedin_token.yml")
DEFAULT_REMIND_DAYS_BEFORE = 14
ISSUE_MARKER = "[linkedin-token]"

CONFIG_TEMPLATE = """\
# Expiry of the LinkedIn access token stored in the LINKEDIN_ACCESS_TOKEN secret (D-031).
# Not a secret. `uv run linkedin-bot-auth` rewrites expires_at after each renewal:
# commit this file together with updating the secret.
expires_at: "{expires_at}"
# token-reminder.yml opens a GitHub issue once the expiry is this close.
remind_days_before: {remind_days_before}
"""

RENEWAL_STEPS = """\
**How to renew** (about 5 minutes, on your own machine)

1. Turn the VPN on and run `uv run linkedin-bot-auth` in the project folder.
2. Sign in to LinkedIn in the browser tab that opens and click **Allow**.
3. Copy `access_token` from `.linkedin_token.json` into the repository secret
   `LINKEDIN_ACCESS_TOKEN` (Settings → Secrets and variables → Actions).
4. Commit and push the updated `config/linkedin_token.yml` (the helper rewrites the date).
5. Close this issue.

Until then, `publish.yml` will fail with HTTP 401 once the token has expired."""


class TokenConfigError(ValueError):
    """Raised when config/linkedin_token.yml is missing or invalid."""


@dataclass(frozen=True)
class TokenConfig:
    expires_at: datetime
    remind_days_before: int


@dataclass(frozen=True)
class Reminder:
    title: str
    body: str
    expired: bool


class IssuesPort(Protocol):
    def list_open_issues(self) -> list[dict]: ...
    def create_issue(self, title: str, body: str) -> dict: ...


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise TokenConfigError(f"expires_at: invalid ISO datetime {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def load_token_config(path: Path = DEFAULT_CONFIG_PATH) -> TokenConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise TokenConfigError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict) or not raw.get("expires_at"):
        raise TokenConfigError(f"{path}: 'expires_at' is required")
    days = raw.get("remind_days_before", DEFAULT_REMIND_DAYS_BEFORE)
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise TokenConfigError(f"{path}: 'remind_days_before' must be a positive integer")
    return TokenConfig(_parse_datetime(raw["expires_at"]), days)


def write_token_expiry(expires_at: datetime, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Record a new expiry, keeping the configured reminder window."""
    try:
        days = load_token_config(path).remind_days_before
    except TokenConfigError:
        days = DEFAULT_REMIND_DAYS_BEFORE
    expires_at = expires_at.astimezone(UTC).replace(second=0, microsecond=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        CONFIG_TEMPLATE.format(expires_at=expires_at.isoformat(), remind_days_before=days),
        encoding="utf-8",
        newline="\n",
    )


def evaluate(config: TokenConfig, now: datetime) -> Reminder | None:
    """A reminder if the expiry is within the window (or already passed), else None."""
    remaining = config.expires_at - now
    days_left = remaining.days  # floor: 13 days 23 h → 13
    if days_left >= config.remind_days_before:
        return None
    date = f"{config.expires_at:%Y-%m-%d %H:%M} UTC"
    if remaining.total_seconds() <= 0:
        title = f"{ISSUE_MARKER} LinkedIn token EXPIRED on {date}"
        intro = f"The LinkedIn access token expired on **{date}**. Publishing is failing."
        return Reminder(title, f"{intro}\n\n{RENEWAL_STEPS}\n", expired=True)
    title = f"{ISSUE_MARKER} LinkedIn token expires on {date} ({days_left} days left)"
    intro = (
        f"The LinkedIn access token expires on **{date}** — {days_left} days left. "
        "Renew it before then so publishing keeps working."
    )
    return Reminder(title, f"{intro}\n\n{RENEWAL_STEPS}\n", expired=False)


def run_reminder(
    config: TokenConfig,
    issues: IssuesPort,
    now: datetime,
    log: Callable[[str], None] = print,
    notifier: Notifier | None = None,
) -> int:
    """Return 0 when nothing is wrong, 1 when the token has already expired.

    Telegram is notified when the reminder issue is opened and on every run once expired.
    """
    notifier = notifier or NullNotifier()
    reminder = evaluate(config, now)
    if reminder is None:
        days_left = (config.expires_at - now).days
        log(f"Token expires {config.expires_at:%Y-%m-%d}; {days_left} days left. No reminder.")
        return 0
    open_issue = next(
        (i for i in issues.list_open_issues() if i.get("title", "").startswith(ISSUE_MARKER)),
        None,
    )
    if open_issue is not None:
        log(f"Reminder issue #{open_issue['number']} is already open; not creating another.")
        issue = open_issue
    else:
        issue = issues.create_issue(reminder.title, reminder.body)
        log(f"Opened reminder issue #{issue['number']}: {issue.get('html_url', '')}")
    if open_issue is None or reminder.expired:
        title = "El token de LinkedIn CADUCÓ" if reminder.expired else "Renueva el token de LinkedIn"
        days_left = (config.expires_at - now).days
        detail = (
            f"Caduca el {config.expires_at:%Y-%m-%d %H:%M} UTC"
            + ("" if reminder.expired else f" (quedan {days_left} días)")
            + ". Con la VPN activa ejecuta `uv run linkedin-bot-auth`, actualiza el secret "
            "LINKEDIN_ACCESS_TOKEN y haz commit de config/linkedin_token.yml."
        )
        link = ("📋 Abrir el Issue", issue["html_url"]) if issue.get("html_url") else None
        notifier.send(*messages.problem(title, detail, link))
    return 1 if reminder.expired else 0


def main() -> None:
    from linkedin_bot.repo.github import GitHubClient, GitHubError

    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repository:
        sys.exit("Missing required environment variable: GITHUB_REPOSITORY")
    as_of = os.environ.get("TOKEN_CHECK_AS_OF", "").strip()
    try:
        now = _parse_datetime(as_of) if as_of else datetime.now(UTC)
        config = load_token_config()
        with httpx.Client(timeout=30) as http:
            github = GitHubClient(http, repository, os.environ.get("GITHUB_TOKEN"))
            if as_of:
                print(f"Simulating the check as of {now:%Y-%m-%d %H:%M} UTC.")
            notifier = build_notifier(http, os.environ)
            exit_code = run_reminder(config, github, now, notifier=notifier)
    except (TokenConfigError, GitHubError) as exc:
        sys.exit(f"Token check FAILED: {exc}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
