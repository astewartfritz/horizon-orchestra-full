"""MILES Telegram channel adapter.

Uses the Telegram Bot API via httpx (no SDK dependency).
Requires: TELEGRAM_BOT_TOKEN env var (obtain from @BotFather).

Supports both polling (getUpdates long-poll) and webhook mode.
For production use webhook mode to avoid getUpdates conflicts.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from orchestra.miles.channels.base import ChannelAdapter, ChannelMessage, ChannelResponse

__all__ = ["TelegramChannelAdapter"]

log = logging.getLogger("orchestra.miles.channels.telegram")

_API = "https://api.telegram.org/bot{token}"


class TelegramChannelAdapter(ChannelAdapter):
    """Poll or receive Telegram messages and reply via the Bot API."""

    channel_name = "telegram"
    supports_polling = True
    supports_webhook = True

    def __init__(
        self,
        bot_token: str = "",
        allowed_chat_ids: list[int] | None = None,
        poll_timeout: int = 30,
    ) -> None:
        self._token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._allowed_chat_ids: set[int] = set(allowed_chat_ids or [])
        self._poll_timeout = poll_timeout
        self._offset: int = 0
        self._bot_id: int = 0
        self._bot_username: str = ""

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._token}/{method}"

    async def connect(self) -> bool:
        if not self._token:
            log.error("TELEGRAM_BOT_TOKEN not set.")
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self._url("getMe"))
            data = resp.json()
            if not data.get("ok"):
                log.error("Telegram auth failed: %s", data.get("description"))
                return False
            bot = data["result"]
            self._bot_id = bot["id"]
            self._bot_username = bot.get("username", "")
            log.info("Telegram connected: @%s (id=%s)", self._bot_username, self._bot_id)
            return True
        except Exception as exc:
            log.error("Telegram connection error: %s", exc)
            return False

    async def poll(self) -> list[ChannelMessage]:
        if not self._token:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._poll_timeout + 5) as client:
                resp = await client.get(
                    self._url("getUpdates"),
                    params={
                        "offset": self._offset,
                        "timeout": self._poll_timeout,
                        "allowed_updates": ["message"],
                    },
                )
            data = resp.json()
            if not data.get("ok"):
                log.warning("Telegram getUpdates error: %s", data.get("description"))
                return []

            updates = data.get("result", [])
            messages: list[ChannelMessage] = []

            for update in updates:
                self._offset = update["update_id"] + 1
                msg = self._parse_update(update)
                if msg:
                    messages.append(msg)

            return messages
        except Exception as exc:
            log.error("Telegram poll error: %s", exc)
            return []

    def _parse_update(self, update: dict[str, Any]) -> ChannelMessage | None:
        raw_msg = update.get("message")
        if not raw_msg:
            return None

        text = raw_msg.get("text", "")
        if not text:
            return None

        # Filter by allowed chat IDs if configured
        chat_id = raw_msg.get("chat", {}).get("id", 0)
        if self._allowed_chat_ids and chat_id not in self._allowed_chat_ids:
            log.debug("Telegram message from non-whitelisted chat %s — ignored", chat_id)
            return None

        # Skip messages from the bot itself
        from_user = raw_msg.get("from", {})
        if from_user.get("id") == self._bot_id:
            return None

        ts = float(raw_msg.get("date", time.time()))
        user_id = str(from_user.get("id", "unknown"))

        first = from_user.get("first_name", "")
        last = from_user.get("last_name", "")
        username = from_user.get("username", "")
        sender_name = f"{first} {last}".strip() or username or user_id

        thread_id = str(raw_msg.get("message_thread_id") or raw_msg.get("message_id", ts))

        return ChannelMessage(
            id=str(raw_msg.get("message_id", ts)),
            channel="telegram",
            sender_id=user_id,
            sender_name=sender_name,
            text=text,
            timestamp=ts,
            thread_id=thread_id,
            is_dm=raw_msg.get("chat", {}).get("type") == "private",
            raw=raw_msg,
        )

    async def send(self, response: ChannelResponse) -> bool:
        payload: dict[str, Any] = {
            "chat_id": response.recipient_id,
            "text": response.text,
            "parse_mode": "Markdown",
        }
        if response.thread_id:
            try:
                payload["reply_to_message_id"] = int(response.thread_id)
            except (ValueError, TypeError):
                pass

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(self._url("sendMessage"), json=payload)
            data = resp.json()
            if not data.get("ok"):
                # Retry without Markdown if parse error
                if "parse" in data.get("description", "").lower():
                    payload.pop("parse_mode", None)
                    async with httpx.AsyncClient(timeout=20) as client:
                        resp = await client.post(self._url("sendMessage"), json=payload)
                    data = resp.json()
            if not data.get("ok"):
                log.error("Telegram send failed: %s", data.get("description"))
                return False
            return True
        except Exception as exc:
            log.error("Telegram send exception: %s", exc)
            return False

    def parse_webhook(self, payload: dict[str, Any]) -> list[ChannelMessage]:
        """Parse a Telegram webhook update payload into ChannelMessages."""
        msg = self._parse_update(payload)
        return [msg] if msg else []

    async def set_webhook(self, url: str) -> bool:
        """Register a webhook URL with Telegram (call once on deploy)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    self._url("setWebhook"),
                    json={"url": url, "allowed_updates": ["message"]},
                )
            data = resp.json()
            if data.get("ok"):
                log.info("Telegram webhook set: %s", url)
                return True
            log.error("Telegram setWebhook failed: %s", data.get("description"))
            return False
        except Exception as exc:
            log.error("Telegram setWebhook exception: %s", exc)
            return False

    async def delete_webhook(self) -> bool:
        """Remove the webhook (switch back to polling mode)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(self._url("deleteWebhook"))
            return resp.json().get("ok", False)
        except Exception as exc:
            log.error("Telegram deleteWebhook exception: %s", exc)
            return False
