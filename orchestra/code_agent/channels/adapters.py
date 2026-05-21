"""Platform-specific adapters for Slack, Telegram, WhatsApp, Discord, iMessage, Email.

Each adapter normalizes inbound messages into a standard format,
handles platform-specific auth, and provides a send() method.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from orchestra.code_agent.channels.manager import ChannelType


@dataclass
class InboundMessage:
    """Normalized message from any platform."""
    content: str
    channel: ChannelType
    sender_id: str = ""
    sender_name: str = ""
    channel_id: str = ""
    thread_id: str = ""
    attachments: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    timestamp: str = ""

    @property
    def has_image(self) -> bool:
        return any(a.get("type") == "image" for a in self.attachments)


class BaseChannelAdapter:
    """Base class for channel adapters."""

    channel: ChannelType = ChannelType.CLI

    def __init__(self):
        self.logger = logging.getLogger(f"channel.{self.channel.value}")

    async def send(self, target: str, text: str) -> bool:
        raise NotImplementedError

    async def send_file(self, target: str, file_path: str, caption: str = "") -> bool:
        raise NotImplementedError

    def normalize(self, raw: dict) -> InboundMessage | None:
        raise NotImplementedError


class SlackAdapter(BaseChannelAdapter):
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

    def normalize(self, raw: dict) -> InboundMessage | None:
        event = raw.get("event", raw)
        if event.get("type") != "message" or "subtype" in event:
            return None
        files = event.get("files", [])
        attachments = []
        for f in files:
            if f.get("mimetype", "").startswith("image/"):
                attachments.append({"type": "image", "url": f.get("url_private", ""), "name": f.get("name", "image")})
        return InboundMessage(
            content=event.get("text", ""),
            channel=self.channel,
            sender_id=event.get("user", "unknown"),
            sender_name=event.get("user", "unknown"),
            channel_id=event.get("channel", ""),
            thread_id=event.get("thread_ts", event.get("ts", "")),
            attachments=attachments,
            raw=raw,
        )


class TelegramAdapter(BaseChannelAdapter):
    channel = ChannelType.TELEGRAM

    async def send(self, bot_token: str, chat_id: str, text: str) -> bool:
        try:
            import httpx
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(url, json={"chat_id": chat_id, "text": text})
                return r.status_code == 200
        except Exception as e:
            self.logger.error("Telegram send error: %s", e)
            return False

    def normalize(self, raw: dict) -> InboundMessage | None:
        msg = raw.get("message", raw)
        if "text" not in msg and "caption" not in msg:
            return None
        attachments = []
        if "photo" in msg:
            photo = msg["photo"][-1]
            attachments.append({"type": "image", "file_id": photo.get("file_id", ""), "name": "photo.jpg"})
        if "document" in msg:
            attachments.append({"type": "file", "file_id": msg["document"].get("file_id", ""), "name": msg["document"].get("file_name", "file")})
        return InboundMessage(
            content=msg.get("text", msg.get("caption", "")),
            channel=self.channel,
            sender_id=str(msg.get("from", {}).get("id", "unknown")),
            sender_name=msg.get("from", {}).get("first_name", "unknown"),
            channel_id=str(msg.get("chat", {}).get("id", "")),
            attachments=attachments,
            raw=raw,
        )


class DiscordAdapter(BaseChannelAdapter):
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

    def normalize(self, raw: dict) -> InboundMessage | None:
        if "content" not in raw and "attachments" not in raw:
            return None
        attachments = []
        for att in raw.get("attachments", []):
            if att.get("content_type", "").startswith("image/"):
                attachments.append({"type": "image", "url": att.get("url", ""), "name": att.get("filename", "image")})
        return InboundMessage(
            content=raw.get("content", ""),
            channel=self.channel,
            sender_id=raw.get("author", {}).get("id", "unknown"),
            sender_name=raw.get("author", {}).get("username", "unknown"),
            channel_id=raw.get("channel_id", ""),
            attachments=attachments,
            raw=raw,
        )


class WhatsAppAdapter(BaseChannelAdapter):
    channel = ChannelType.WHATSAPP

    async def send(self, phone_number_id: str, token: str, to: str, text: str) -> bool:
        try:
            import httpx
            url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(url, json={
                    "messaging_product": "whatsapp", "to": to, "type": "text",
                    "text": {"body": text},
                }, headers={"Authorization": f"Bearer {token}"})
                return r.status_code == 200
        except Exception as e:
            self.logger.error("WhatsApp send error: %s", e)
            return False

    def normalize(self, raw: dict) -> InboundMessage | None:
        entries = raw.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    if msg.get("type") == "text":
                        return InboundMessage(
                            content=msg.get("text", {}).get("body", ""),
                            channel=self.channel,
                            sender_id=msg.get("from", "unknown"),
                            sender_name=msg.get("from", "unknown"),
                            channel_id=value.get("metadata", {}).get("phone_number_id", ""),
                            raw=raw,
                        )
        return None


class EmailAdapter(BaseChannelAdapter):
    channel = ChannelType.CLI  # mapped via IMAP/SMTP

    async def send(self, smtp_config: dict, to: str, subject: str, body: str) -> bool:
        try:
            import smtplib
            from email.message import EmailMessage
            msg = EmailMessage()
            msg.set_content(body)
            msg["Subject"] = subject
            msg["From"] = smtp_config.get("from", "orchestra@localhost")
            msg["To"] = to
            with smtplib.SMTP(smtp_config.get("host", "localhost"), smtp_config.get("port", 25)) as s:
                s.send_message(msg)
            return True
        except Exception as e:
            self.logger.error("Email send error: %s", e)
            return False

    def normalize(self, raw: dict) -> InboundMessage | None:
        return InboundMessage(
            content=raw.get("body", raw.get("text", "")),
            channel=ChannelType.CLI,
            sender_id=raw.get("from", "unknown"),
            sender_name=raw.get("from", "unknown"),
            channel_id=raw.get("to", ""),
            thread_id=raw.get("message_id", ""),
            attachments=[{"type": "file", "name": a} for a in raw.get("attachments", [])],
            raw=raw,
        )


class IMessagesAdapter(BaseChannelAdapter):
    channel = ChannelType.CLI  # macOS/iCloud only

    async def send(self, target: str, text: str) -> bool:
        try:
            import subprocess
            import shlex
            cmd = f'osascript -e \'tell application "Messages" to send "{text}" to buddy "{target}"\''
            subprocess.run(shlex.split(cmd), capture_output=True, timeout=10)
            return True
        except Exception:
            self.logger.warning("iMessage send requires macOS")
            return False

    def normalize(self, raw: dict) -> InboundMessage | None:
        return InboundMessage(
            content=raw.get("text", ""),
            channel=ChannelType.CLI,
            sender_id=raw.get("sender", "unknown"),
            sender_name=raw.get("sender", "unknown"),
            raw=raw,
        )


ADAPTER_REGISTRY: dict[ChannelType, type[BaseChannelAdapter]] = {
    ChannelType.SLACK: SlackAdapter,
    ChannelType.TELEGRAM: TelegramAdapter,
    ChannelType.DISCORD: DiscordAdapter,
    ChannelType.WHATSAPP: WhatsAppAdapter,
}


def get_adapter(channel: ChannelType) -> BaseChannelAdapter:
    cls = ADAPTER_REGISTRY.get(channel)
    if not cls:
        raise ValueError(f"No adapter for channel: {channel}")
    return cls()
