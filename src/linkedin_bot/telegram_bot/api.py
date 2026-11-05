"""Telegram Bot API client for the listening bot (Telegram T3, D-033).

Methods per https://core.telegram.org/bots/api (Bot API 10.3, read 2026-11-05):
getUpdates (long polling with offset/timeout/allowed_updates), sendMessage,
answerCallbackQuery, editMessageReplyMarkup, setMyCommands.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from linkedin_bot.notify.telegram import API_URL, Button, fit, inline_keyboard

LONG_POLL_SECONDS = 50


class TelegramError(RuntimeError):
    """Raised when the Bot API answers ok=false; the bot token is never included."""


class BotApi:
    def __init__(self, http: httpx.Client, token: str) -> None:
        self._http = http
        self._token = token

    def call(self, method: str, payload: dict | None = None) -> object:
        try:
            response = self._http.post(f"{API_URL}/bot{self._token}/{method}", json=payload or {})
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(f"{method}: {self.scrub(repr(exc))}") from None
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description')}")
        return data.get("result")

    def get_updates(self, offset: int | None, timeout: int = LONG_POLL_SECONDS) -> list[dict]:
        payload: dict[str, object] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload) or []

    def send_message(self, chat_id: str, text: str, buttons: Sequence[Button] = ()) -> None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": fit(text),
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard(buttons)}
        self.call("sendMessage", payload)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})

    def edit_buttons(self, chat_id: str, message_id: int, buttons: Sequence[Button]) -> None:
        """Replace a message's inline keyboard ([] removes it)."""
        self.call(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": inline_keyboard(buttons)},
            },
        )

    def set_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        self.call(
            "setMyCommands",
            {"commands": [{"command": c, "description": d} for c, d in commands]},
        )

    def scrub(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text


class ChatAdapter:
    """The owner's chat as seen by the command handlers."""

    def __init__(self, api: BotApi, chat_id: str) -> None:
        self._api = api
        self._chat_id = chat_id

    def send(self, text: str, buttons: Sequence[Button] = ()) -> None:
        self._api.send_message(self._chat_id, text, buttons)

    def answer(self, callback_id: str, text: str = "") -> None:
        self._api.answer_callback(callback_id, text)

    def set_buttons(self, message_id: int, buttons: Sequence[Button]) -> None:
        self._api.edit_buttons(self._chat_id, message_id, buttons)
