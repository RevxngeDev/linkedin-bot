"""Telegram setup helper (D-032), run from `telegram-check.yml` on GitHub Actions.

- Only TELEGRAM_BOT_TOKEN set: shows which bot the token belongs to, whether a webhook
  is blocking getUpdates, and the chats that recently wrote to the bot, so the owner can
  copy their chat id into TELEGRAM_CHAT_ID.
- Both secrets set: sends a test message with a URL button.
The bot token is never printed.
"""

from __future__ import annotations

import os
import sys
from collections import Counter

import httpx

from linkedin_bot.notify.telegram import (
    API_URL,
    CHAT_ID_ENV,
    TOKEN_ENV,
    TelegramNotifier,
)

# Update fields that carry a chat (a private /start or text arrives as "message").
CHAT_FIELDS = ("message", "edited_message", "my_chat_member", "channel_post")


class TelegramCheckError(RuntimeError):
    """Raised when a Bot API call fails."""


def _call(http: httpx.Client, token: str, method: str) -> object:
    data = http.get(f"{API_URL}/bot{token}/{method}").json()
    if not data.get("ok"):
        raise TelegramCheckError(f"{method} failed: {data.get('description')}")
    return data.get("result")


def bot_identity(http: httpx.Client, token: str) -> str:
    me = _call(http, token, "getMe") or {}
    return f"@{me.get('username', '?')} (id {me.get('id', '?')})"


def webhook_url(http: httpx.Client, token: str) -> str:
    info = _call(http, token, "getWebhookInfo") or {}
    return info.get("url", "")


def read_updates(http: httpx.Client, token: str) -> tuple[list[tuple[int, str]], Counter]:
    """Chats found in pending updates, and how many updates of each type there are."""
    updates = _call(http, token, "getUpdates") or []
    kinds: Counter = Counter()
    chats: dict[int, str] = {}
    for update in updates:
        kind = next((k for k in update if k != "update_id"), "unknown")
        kinds[kind] += 1
        for field in CHAT_FIELDS:
            chat = (update.get(field) or {}).get("chat") or {}
            if "id" in chat:
                name = chat.get("username") or chat.get("first_name") or chat.get("title") or ""
                chats[chat["id"]] = name
    return sorted(chats.items()), kinds


def list_recent_chats(http: httpx.Client, token: str) -> list[tuple[int, str]]:
    return read_updates(http, token)[0]


def diagnose(http: httpx.Client, token: str) -> int:
    print(f"Token belongs to bot {bot_identity(http, token)}.")
    hook = webhook_url(http, token)
    if hook:
        print(
            "A webhook is set for this bot, so getUpdates cannot read messages. Another "
            "service is receiving them. Remove the webhook (deleteWebhook) or use another bot."
        )
        return 1
    print("No webhook set (good).")
    chats, kinds = read_updates(http, token)
    print(f"Pending updates: {sum(kinds.values())} {dict(kinds)}")
    if not chats:
        print(
            "No chats found. Open THIS bot (the username above) in Telegram, press Start or "
            "send 'hola', make sure the message shows a check mark, then rerun. Telegram keeps "
            "updates for 24 h, and another program polling with the same token would consume them."
        )
        return 1
    print(f"Chats that wrote to the bot (copy yours into the {CHAT_ID_ENV} secret):")
    for found_id, name in chats:
        print(f"  chat_id={found_id}  ({name})")
    return 0


def main() -> None:
    token = os.environ.get(TOKEN_ENV, "").strip()
    chat_id = os.environ.get(CHAT_ID_ENV, "").strip()
    if not token:
        sys.exit(f"Missing secret {TOKEN_ENV}: create the bot with @BotFather first.")
    with httpx.Client(timeout=30) as http:
        if not chat_id:
            try:
                sys.exit(diagnose(http, token))
            except (TelegramCheckError, httpx.HTTPError) as exc:
                sys.exit(f"Telegram check FAILED: {str(exc).replace(token, '***')}")
        errors: list[str] = []
        TelegramNotifier(http, token, chat_id, errors.append).send(
            "✅ <b>linkedin-bot conectado</b>\nLos avisos de borradores, publicaciones y "
            "problemas llegarán a este chat.",
            [("📂 Abrir el repositorio", f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}")],
        )
        if errors:
            sys.exit(f"Telegram check FAILED: {errors[0]}")
        print("Test message sent. Check Telegram.")


if __name__ == "__main__":
    main()
