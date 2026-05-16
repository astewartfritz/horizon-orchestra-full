from __future__ import annotations

import json
from typing import Any

import httpx

from code_agent.notify.notifier import Notification, Notifier


class SlackNotifier(Notifier):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, notification: Notification) -> bool:
        color_map = {"info": "#3498db", "success": "#2ecc71", "warning": "#f39c12", "error": "#e74c3c"}
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": notification.title},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": notification.body[:3000]},
            },
        ]
        if notification.metadata:
            meta_str = "\n".join(f"*{k}:* {v}" for k, v in notification.metadata.items())
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": meta_str[:2000]}]})

        payload = {"blocks": blocks}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.webhook_url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False


class WebhookNotifier(Notifier):
    def __init__(self, url: str, secret: str = ""):
        self.url = url
        self.secret = secret

    async def send(self, notification: Notification) -> bool:
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["X-Webhook-Secret"] = self.secret

        payload = {
            "title": notification.title,
            "body": notification.body,
            "level": notification.level,
            "metadata": notification.metadata or {},
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.url, json=payload, headers=headers)
                return resp.status_code < 400
        except Exception:
            return False
