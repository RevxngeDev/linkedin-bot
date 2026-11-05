"""Listening Telegram bot that runs on the owner's PC (Telegram T3, D-033).

Long-polls getUpdates, accepts updates only from TELEGRAM_CHAT_ID and passes them to
`BotCommands`. Meant to run hidden in the background (pythonw + a scheduled task at logon,
like reel-translator): it logs to `data/telegram_bot.log` (rotating) and retries forever
when Telegram or GitHub are unreachable (e.g. while the VPN reconnects).

Publishing still happens only in GitHub Actions; if this bot is off, nothing breaks —
drafts can still be approved from GitHub, and button presses wait up to 24 h in Telegram.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable, Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from dotenv import load_dotenv

from linkedin_bot.repo.github import GitHubClient
from linkedin_bot.telegram_bot.api import LONG_POLL_SECONDS, BotApi, ChatAdapter, TelegramError
from linkedin_bot.telegram_bot.commands import COMMANDS, BotCommands

LOG_PATH = Path("data/telegram_bot.log")
DEFAULT_REPOSITORY = "RevxngeDev/linkedin-bot"
MAX_BACKOFF_SECONDS = 60

log = logging.getLogger("linkedin_bot.telegram")


class ConfigError(ValueError):
    """Raised when a required setting is missing."""


def setup_logging(path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    ]
    if sys.stderr is not None:  # pythonw has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
    # httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing {name} in .env (see .env.example)")
    return value


def authorized(update: dict, chat_id: str) -> bool:
    """Only the owner's private chat may give orders."""
    if "callback_query" in update:
        sender = update["callback_query"].get("from", {}).get("id")
    else:
        sender = (update.get("message") or {}).get("chat", {}).get("id")
    return str(sender) == chat_id


def dispatch(update: dict, commands: BotCommands, chat_id: str) -> None:
    if not authorized(update, chat_id):
        log.warning("Ignored update %s from an unauthorized chat", update.get("update_id"))
        return
    if "callback_query" in update:
        query = update["callback_query"]
        message_id = (query.get("message") or {}).get("message_id")
        if query.get("data") and message_id is not None:
            log.info("Button %s", query["data"])
            commands.handle_callback(query["id"], query["data"], message_id)
        return
    text = (update.get("message") or {}).get("text")
    if text:
        log.info("Command %s", text.split(" ", 1)[0])
        commands.handle_text(text)


def run_forever(
    api: BotApi,
    commands: BotCommands,
    chat_id: str,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    offset: int | None = None
    backoff = 5
    commands_set = False
    while not should_stop():
        try:
            if not commands_set:
                api.set_commands(COMMANDS)
                commands_set = True
                log.info("Connected to Telegram; command menu set.")
            updates = api.get_updates(offset, LONG_POLL_SECONDS)
            backoff = 5
        except (TelegramError, httpx.HTTPError) as exc:
            log.warning("Telegram unreachable (%s); retrying in %ss", api.scrub(str(exc)), backoff)
            sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue
        for update in updates:
            offset = update["update_id"] + 1  # confirms it on the next getUpdates call
            try:
                dispatch(update, commands, chat_id)
            except Exception:  # noqa: BLE001 — one bad update must not stop the bot
                log.exception("Error handling update %s", update.get("update_id"))


def main() -> None:
    load_dotenv()
    setup_logging()
    env = dict(os.environ)
    try:
        token = require(env, "TELEGRAM_BOT_TOKEN")
        chat_id = require(env, "TELEGRAM_CHAT_ID")
        github_pat = require(env, "GITHUB_PAT")
        timezone = ZoneInfo(env.get("BOT_TIMEZONE", "").strip() or "UTC")
    except (ConfigError, ZoneInfoNotFoundError) as exc:
        log.error("Cannot start: %s", exc)
        sys.exit(1)
    repository = env.get("GITHUB_REPOSITORY", "").strip() or DEFAULT_REPOSITORY
    proxy = env.get("TELEGRAM_BOT_PROXY", "").strip() or None

    telegram_http = httpx.Client(timeout=LONG_POLL_SECONDS + 20, trust_env=False, proxy=proxy)
    github_http = httpx.Client(timeout=30, trust_env=False)
    api = BotApi(telegram_http, token)
    commands = BotCommands(
        repo=GitHubClient(github_http, repository, github_pat),
        chat=ChatAdapter(api, chat_id),
        timezone=timezone,
        log=log.warning,
    )
    log.info("linkedin-bot Telegram listener starting (repo %s, tz %s)", repository, timezone.key)
    try:
        run_forever(api, commands, chat_id)
    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        telegram_http.close()
        github_http.close()


if __name__ == "__main__":
    main()
