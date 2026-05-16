from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from code_agent.gateway.runtime import GatewayEvent


class WebhookManager:
    """Accepts external events from CI/CD, CRM, monitoring systems.

    Supports HMAC signature verification for authenticity.
    """

    def __init__(self):
        self.logger = logging.getLogger("orchestra.webhooks")
        self._secrets: dict[str, str] = {}  # source → secret
        self._handlers: dict[str, callable] = {}  # source → handler

    def register(self, source: str, secret: str = "", handler: callable | None = None) -> None:
        self._secrets[source] = secret
        if handler:
            self._handlers[source] = handler

    def verify(self, source: str, payload: bytes, signature: str, header: str = "") -> bool:
        secret = self._secrets.get(source, "")
        if not secret:
            return True
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def handle(self, source: str, payload: dict[str, Any],
                     metadata: dict[str, Any] | None = None) -> str:
        """Process an incoming webhook and convert to a GatewayEvent."""
        from code_agent.channels.manager import ChannelType

        content = payload.get("text", payload.get("message", json.dumps(payload)[:500]))
        sender = payload.get("sender", metadata.get("sender", "webhook") if metadata else "webhook")

        event = GatewayEvent(
            id=payload.get("id", source),
            channel=ChannelType.WEB,
            sender=sender,
            content=content,
            metadata=metadata or payload,
        )

        if source in self._handlers:
            handler = self._handlers[source]
            result = handler(event)
            if hasattr(result, "__await__"):
                return await result

        return f"Webhook received from {source}: {content[:100]}"
