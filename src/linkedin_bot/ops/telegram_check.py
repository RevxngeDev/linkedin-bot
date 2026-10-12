"""Telegram setup helper (D-032), run from `telegram-check.yml` on GitHub Actions.

- Only TELEGRAM_BOT_TOKEN set: lists the chats that recently wrote to the bot
  (getUpdates), so the owner can copy their chat id into TELEGRAM_CHAT_ID.
- Both secrets set: sends a test message with a URL button.
The bot token is never printed.
"""

from __future__ import annotations

import os
import sys

import httpx

from linkedin_bot.notify.telegram import (
    API_URL,
    CHAT_ID_ENV,
    TOKEN_ENV,
    TelegramNotifier,
)


def list_recent_chats(http: httpx.Client, token: str) -> list[tuple[int, str]]:
    response = http.get(f"{API_URL}/bot{token}/getUpdates")
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"getUpdates failed: {data.get('description')}")
    chats: dict[int, str] = {}
    for update in data.get("result", []):
        chat = (update.get("message") or {}).get("chat") or {}
        if "id" in chat:
            name = chat.get("username") or chat.get("first_name") or chat.get("title") or ""
            chats[chat["id"]] = name
    return sorted(chats.items())


def main() -> None:
    token = os.environ.get(TOKEN_ENV, "").strip()
    chat_id = os.environ.get(CHAT_ID_ENV, "").strip()
    if not token:
        sys.exit(f"Missing secret {TOKEN_ENV}: create the bot with @BotFather first.")
    with httpx.Client(timeout=30) as http:
        if not chat_id:
            try:
                chats = list_recent_chats(http, token)
            except Exception as exc:  # noqa: BLE001
                sys.exit(f"Telegram check FAILED: {str(exc).replace(token, '***')}")
            if not chats:
                sys.exit("No chats found. Send any message to your bot in Telegram, then rerun.")
            print(f"Chats that wrote to the bot (copy yours into the {CHAT_ID_ENV} secret):")
            for found_id, name in chats:
                print(f"  chat_id={found_id}  ({name})")
            return
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
