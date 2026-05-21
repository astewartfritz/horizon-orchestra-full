"""Enhanced channel adapters for Slack, Discord, Telegram, and WhatsApp.

Each adapter handles platform-specific auth, message schema mapping,
and presents a unified interface to the Gateway.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from orchestra.code_agent.channels.manager import ChannelType, Message


class BaseAdapter:
    """Base class for channel adapters."""

    channel: ChannelType = ChannelType.CLI

    def __init__(self):
        self.logger = logging.getLogger(f"adapter.{self.channel.value}")

    async def send(self, target: str, text: str) -> bool:
        raise NotImplementedError

    async def receive(self, raw: Any) -> Message | None:
        raise NotImplementedError

    def format_message(self, text: str) -> str:
        """Normalize message format for the Gateway."""
        return text.strip()


class SlackAdapter(BaseAdapter):
    channel = ChannelType.SLACK

    async def send(self, webhook_url: str, text: str) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(webhook_url, json={"text": text})
                return r.status_code == 200
        except Exception as e:
            self.logger.error("Slack send error: %s", e)
            return False

    async def receive(self, raw: dict) -> Message | None:
        if "event" not in raw:
            return None
        event = raw["event"]
        if event.get("type") != "message" or "subtype" in event:
            return None
        return Message(
            content=event.get("text", ""),
            channel=self.channel,
            sender=event.get("user", "unknown"),
            metadata={"channel": event.get("channel"), "ts": event.get("ts")},
        )


class DiscordAdapter(BaseAdapter):
    channel = ChannelType.DISCORD

    async def send(self, webhook_url: str, text: str) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(webhook_url, json={"content": text})
                return r.status_code == 204
        except Exception as e:
            self.logger.error("Discord send error: %s", e)
            return False

    async def receive(self, raw: dict) -> Message | None:
        if "content" not in raw:
            return None
        return Message(
            content=raw.get("content", ""),
            channel=self.channel,
            sender=raw.get("author", {}).get("username", "unknown"),
            metadata={"channel_id": raw.get("channel_id"), "guild_id": raw.get("guild_id")},
        )


class TelegramAdapter(BaseAdapter):
    channel = ChannelType.TELEGRAM

    async def send(self, token: str, chat_id: str, text: str) -> bool:
        try:
            import httpx
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(url, json={"chat_id": chat_id, "text": text})
                return r.status_code == 200
        except Exception as e:
            self.logger.error("Telegram send error: %s", e)
            return False

    async def receive(self, raw: dict) -> Message | None:
        if "message" not in raw:
            return None
        msg = raw["message"]
        return Message(
            content=msg.get("text", ""),
            channel=self.channel,
            sender=str(msg.get("from", {}).get("id", "unknown")),
            metadata={"chat_id": msg.get("chat", {}).get("id"), "message_id": msg.get("message_id")},
        )


ADAPTER_REGISTRY: dict[ChannelType, type[BaseAdapter]] = {
    ChannelType.SLACK: SlackAdapter,
    ChannelType.DISCORD: DiscordAdapter,
    ChannelType.TELEGRAM: TelegramAdapter,
}


def get_adapter(channel: ChannelType) -> BaseAdapter:
    cls = ADAPTER_REGISTRY.get(channel)
    if not cls:
        raise ValueError(f"Unsupported channel: {channel}")
    return cls()
