"""Horizon Orchestra — Notification System.

Push notifications, webhooks, email alerts for async results.
Agents and cron jobs use this to notify users when background work
completes or when monitored conditions are met.

Channels:
1. **In-app** — stored in memory, polled by frontend
2. **Webhook** — HTTP POST to a user-defined URL
3. **Email** — via Gmail connector
4. **Slack** — via Slack connector

Usage::

    from orchestra.notifications import NotificationManager
    notif = NotificationManager()
    await notif.send("ashton", "Your report is ready", channel="email", data={"url": "..."})
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

__all__ = ["NotificationManager", "Notification", "NotificationConfig"]

log = logging.getLogger("orchestra.notifications")


@dataclass
class Notification:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: str = ""
    title: str = ""
    body: str = ""
    channel: str = "in_app"       # in_app, webhook, email, slack
    data: dict[str, Any] = field(default_factory=dict)
    read: bool = False
    created_at: float = field(default_factory=time.time)
    delivered: bool = False
    error: str = ""


@dataclass
class NotificationConfig:
    webhook_url: str = ""
    webhook_secret: str = ""
    email_connector: Any = None   # GmailConnector instance
    slack_connector: Any = None   # SlackConnector instance
    slack_channel: str = ""
    max_stored: int = 500


class NotificationManager:
    """Multi-channel notification delivery."""

    def __init__(self, config: NotificationConfig | None = None) -> None:
        self.config = config or NotificationConfig()
        self._store: dict[str, list[Notification]] = {}  # user_id → notifications

    async def send(
        self,
        user_id: str,
        title: str,
        body: str = "",
        channel: str = "in_app",
        data: dict[str, Any] | None = None,
    ) -> Notification:
        """Send a notification through the specified channel."""
        notif = Notification(
            user_id=user_id, title=title, body=body,
            channel=channel, data=data or {},
        )

        dispatch = {
            "in_app": self._send_in_app,
            "webhook": self._send_webhook,
            "email": self._send_email,
            "slack": self._send_slack,
        }
        handler = dispatch.get(channel, self._send_in_app)

        try:
            await handler(notif)
            notif.delivered = True
        except Exception as exc:
            notif.error = str(exc)
            log.error("Notification delivery failed (%s): %s", channel, exc)
            # Fallback: always store in-app
            await self._send_in_app(notif)

        return notif

    async def send_all_channels(self, user_id: str, title: str, body: str = "", data: dict | None = None) -> list[Notification]:
        """Broadcast to all configured channels."""
        results = []
        channels = ["in_app"]
        if self.config.webhook_url:
            channels.append("webhook")
        if self.config.email_connector and self.config.email_connector.connected:
            channels.append("email")
        if self.config.slack_connector and self.config.slack_connector.connected:
            channels.append("slack")
        for ch in channels:
            results.append(await self.send(user_id, title, body, channel=ch, data=data))
        return results

    async def _send_in_app(self, notif: Notification) -> None:
        if notif.user_id not in self._store:
            self._store[notif.user_id] = []
        self._store[notif.user_id].append(notif)
        # Trim
        if len(self._store[notif.user_id]) > self.config.max_stored:
            self._store[notif.user_id] = self._store[notif.user_id][-self.config.max_stored:]

    async def _send_webhook(self, notif: Notification) -> None:
        if not self.config.webhook_url:
            raise ValueError("No webhook_url configured")
        payload = {
            "id": notif.id, "user_id": notif.user_id,
            "title": notif.title, "body": notif.body,
            "data": notif.data, "ts": notif.created_at,
        }
        headers = {"Content-Type": "application/json"}
        if self.config.webhook_secret:
            headers["X-Horizon-Secret"] = self.config.webhook_secret
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self.config.webhook_url, json=payload, headers=headers)
            resp.raise_for_status()

    async def _send_email(self, notif: Notification) -> None:
        if not self.config.email_connector or not self.config.email_connector.connected:
            raise ValueError("Email connector not configured or not connected")
        await self.config.email_connector.execute("gmail_send", {
            "to": notif.data.get("email", notif.user_id),
            "subject": f"[Horizon Orchestra] {notif.title}",
            "body": notif.body or notif.title,
        })

    async def _send_slack(self, notif: Notification) -> None:
        if not self.config.slack_connector or not self.config.slack_connector.connected:
            raise ValueError("Slack connector not configured or not connected")
        channel = notif.data.get("slack_channel", self.config.slack_channel)
        if not channel:
            raise ValueError("No Slack channel specified")
        await self.config.slack_connector.execute("slack_post_message", {
            "channel": channel,
            "message": f"*{notif.title}*\n{notif.body}",
        })

    # -- reading notifications ----------------------------------------------

    def get_unread(self, user_id: str) -> list[dict[str, Any]]:
        notifs = self._store.get(user_id, [])
        return [
            {"id": n.id, "title": n.title, "body": n.body, "data": n.data, "ts": n.created_at}
            for n in notifs if not n.read
        ]

    def mark_read(self, user_id: str, notif_id: str) -> bool:
        for n in self._store.get(user_id, []):
            if n.id == notif_id:
                n.read = True
                return True
        return False

    def mark_all_read(self, user_id: str) -> int:
        count = 0
        for n in self._store.get(user_id, []):
            if not n.read:
                n.read = True
                count += 1
        return count

    def get_history(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        notifs = self._store.get(user_id, [])
        return [
            {"id": n.id, "title": n.title, "channel": n.channel, "read": n.read,
             "delivered": n.delivered, "ts": n.created_at}
            for n in sorted(notifs, key=lambda x: x.created_at, reverse=True)[:limit]
        ]
