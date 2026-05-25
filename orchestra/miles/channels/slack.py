"""MILES Slack channel adapter.

Requires: SLACK_BOT_TOKEN env var.
Polls for DMs and @-mentions via the Slack Web API (no SDK dependency).

For real-time ingestion in production use Socket Mode:
    pip install slack_bolt
and set SLACK_APP_TOKEN as well.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from orchestra.miles.channels.base import ChannelAdapter, ChannelMessage, ChannelResponse

__all__ = ["SlackChannelAdapter"]

log = logging.getLogger("orchestra.miles.channels.slack")

_API = "https://slack.com/api"


class SlackChannelAdapter(ChannelAdapter):
    """Poll Slack DMs and mentions, reply in-thread."""

    channel_name = "slack"
    supports_polling = True
    supports_webhook = True

    def __init__(
        self,
        bot_token: str = "",
        poll_channels: list[str] | None = None,
        since_ts: float | None = None,
    ) -> None:
        self._token = bot_token or os.environ.get("SLACK_BOT_TOKEN", "")
        self._poll_channels = poll_channels or []
        self._since_ts: float = since_ts or time.time()
        self._bot_id: str = ""

    async def connect(self) -> bool:
        if not self._token:
            log.error("SLACK_BOT_TOKEN not set.")
            return False
        resp = await self._api("auth.test")
        if resp.get("ok"):
            self._bot_id = resp.get("bot_id", "")
            log.info("Slack connected: %s (%s)", resp.get("user"), resp.get("team"))
            return True
        log.error("Slack auth failed: %s", resp.get("error"))
        return False

    async def poll(self) -> list[ChannelMessage]:
        messages: list[ChannelMessage] = []
        oldest = str(self._since_ts)
        new_ts = self._since_ts

        for channel_id in self._poll_channels:
            resp = await self._api("conversations.history", {
                "channel": channel_id,
                "oldest": oldest,
                "limit": 50,
            })
            for raw in resp.get("messages", []):
                # Skip bot messages and self
                if raw.get("bot_id") or raw.get("user") == self._bot_id:
                    continue
                ts = float(raw.get("ts", 0))
                if ts > new_ts:
                    new_ts = ts
                user_id = raw.get("user", "unknown")
                messages.append(ChannelMessage(
                    id=raw.get("ts", str(ts)),
                    channel="slack",
                    sender_id=user_id,
                    sender_name=await self._get_display_name(user_id),
                    text=raw.get("text", ""),
                    timestamp=ts,
                    thread_id=raw.get("thread_ts") or raw.get("ts"),
                    raw=raw,
                ))

        if new_ts > self._since_ts:
            self._since_ts = new_ts + 0.001

        return messages

    async def send(self, response: ChannelResponse) -> bool:
        payload: dict[str, Any] = {
            "channel": response.recipient_id,
            "text": response.text,
        }
        if response.thread_id:
            payload["thread_ts"] = response.thread_id
        resp = await self._api("chat.postMessage", payload)
        if not resp.get("ok"):
            log.error("Slack send failed: %s", resp.get("error"))
        return bool(resp.get("ok"))

    async def _get_display_name(self, user_id: str) -> str:
        try:
            resp = await self._api("users.info", {"user": user_id})
            profile = resp.get("user", {}).get("profile", {})
            return profile.get("display_name") or profile.get("real_name", user_id)
        except Exception:
            return user_id

    async def _api(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=20) as client:
            if params:
                resp = await client.post(f"{_API}/{method}", headers=headers, json=params)
            else:
                resp = await client.get(f"{_API}/{method}", headers=headers)
            return resp.json()
