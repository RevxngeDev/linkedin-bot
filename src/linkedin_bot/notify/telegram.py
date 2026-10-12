"""Outgoing Telegram notifications (Telegram front-end T1/T2, D-032).

GitHub Actions sends messages to the owner's chat through the Telegram Bot API; the bot
never listens, so no server is needed. Buttons are URL buttons only (they open the PR or
the LinkedIn post). Notifications are best effort: a Telegram failure is logged and never
breaks publishing or drafting. Without the two secrets, a no-op notifier is used.

API per https://core.telegram.org/bots/api (Bot API 10.3, read 2026-10-12): sendMessage
with chat_id, text (1-4096 chars), parse_mode "HTML", link_preview_options, reply_markup.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

import httpx

API_URL = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4096
TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

Button = tuple[str, str]  # (label, url)


class Notifier(Protocol):
    def send(self, text: str, buttons: Sequence[Button] = ()) -> None:
        """Send an HTML message; must never raise."""
        ...


class NullNotifier:
    """Used when Telegram is not configured: notifications are silently skipped."""

    def send(self, text: str, buttons: Sequence[Button] = ()) -> None:
        return None


class TelegramNotifier:
    def __init__(
        self,
        http: httpx.Client,
        bot_token: str,
        chat_id: str,
        log: Callable[[str], None] = print,
    ) -> None:
        self._http = http
        self._token = bot_token
        self._chat_id = chat_id
        self._log = log

    def send(self, text: str, buttons: Sequence[Button] = ()) -> None:
        payload: dict[str, object] = {
            "chat_id": self._chat_id,
            "text": fit(text),
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": label, "url": url}] for label, url in buttons]
            }
        try:
            response = self._http.post(f"{API_URL}/bot{self._token}/sendMessage", json=payload)
            data = response.json()
            if not data.get("ok"):
                self._log(f"Telegram notification failed: {data.get('description')}")
        except Exception as exc:  # noqa: BLE001 — a notification must never break the pipeline
            self._log(f"Telegram notification failed: {self._scrub(repr(exc))}")

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text


def build_notifier(
    http: httpx.Client, env: Mapping[str, str], log: Callable[[str], None] = print
) -> Notifier:
    token = env.get(TOKEN_ENV, "").strip()
    chat_id = env.get(CHAT_ID_ENV, "").strip()
    if not token or not chat_id:
        return NullNotifier()
    return TelegramNotifier(http, token, chat_id, log)


def esc(text: object) -> str:
    """Escape text for Telegram HTML (&, <, > and quotes)."""
    return html.escape(str(text), quote=True)


def fit(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
