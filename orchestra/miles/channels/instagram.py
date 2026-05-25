"""MILES Instagram channel adapter.

Uses the Meta Graph API (Instagram Messaging / Messenger API for Instagram).
Requires a Facebook App with instagram_manage_messages permission and a
Page Access Token with an Instagram Professional Account linked.

Requires env vars:
    INSTAGRAM_PAGE_TOKEN  — long-lived Page Access Token
    INSTAGRAM_PAGE_ID     — numeric Facebook Page ID linked to the IG account
    INSTAGRAM_VERIFY_TOKEN — webhook verification token (any string you choose)

Inbound messages arrive via webhook — this adapter is push-only.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from orchestra.miles.channels.base import ChannelAdapter, ChannelMessage, ChannelResponse

__all__ = ["InstagramChannelAdapter"]

log = logging.getLogger("orchestra.miles.channels.instagram")

_GRAPH_API = "https://graph.facebook.com/v19.0"


class InstagramChannelAdapter(ChannelAdapter):
    """Receive Instagram DMs via webhook; reply via the Graph API."""

    channel_name = "instagram"
    supports_polling = False
    supports_webhook = True

    def __init__(
        self,
        page_token: str = "",
        page_id: str = "",
        verify_token: str = "",
    ) -> None:
        self._token = page_token or os.environ.get("INSTAGRAM_PAGE_TOKEN", "")
        self._page_id = page_id or os.environ.get("INSTAGRAM_PAGE_ID", "")
        self._verify_token = verify_token or os.environ.get("INSTAGRAM_VERIFY_TOKEN", "")

    async def connect(self) -> bool:
        if not self._token or not self._page_id:
            log.error("INSTAGRAM_PAGE_TOKEN and INSTAGRAM_PAGE_ID must be set.")
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{_GRAPH_API}/{self._page_id}",
                    params={"fields": "id,name", "access_token": self._token},
                )
            data = resp.json()
            if "error" in data:
                log.error("Instagram auth failed: %s", data["error"].get("message"))
                return False
            log.info(
                "Instagram connected: page=%s (%s)", data.get("name"), data.get("id")
            )
            return True
        except Exception as exc:
            log.error("Instagram connection error: %s", exc)
            return False

    async def poll(self) -> list[ChannelMessage]:
        return []

    async def send(self, response: ChannelResponse) -> bool:
        url = f"{_GRAPH_API}/{self._page_id}/messages"
        payload = {
            "recipient": {"id": response.recipient_id},
            "message": {"text": response.text},
            "access_token": self._token,
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(url, json=payload)
            data = resp.json()
            if "error" in data:
                log.error("Instagram send failed: %s", data["error"].get("message"))
                return False
            return True
        except Exception as exc:
            log.error("Instagram send exception: %s", exc)
            return False

    def parse_webhook(self, payload: dict[str, Any]) -> list[ChannelMessage]:
        """Parse a raw Messenger/Instagram webhook payload into ChannelMessages.

        The Meta webhook for Instagram DMs follows the same structure as
        Messenger webhooks (object: "instagram" or "page").
        """
        messages: list[ChannelMessage] = []
        try:
            for entry in payload.get("entry", []):
                for event in entry.get("messaging", []):
                    msg = event.get("message", {})
                    text = msg.get("text", "")
                    if not text or msg.get("is_echo"):
                        continue
                    sender_id = event.get("sender", {}).get("id", "unknown")
                    ts = event.get("timestamp", time.time() * 1000) / 1000
                    messages.append(ChannelMessage(
                        id=msg.get("mid", str(ts)),
                        channel="instagram",
                        sender_id=sender_id,
                        sender_name=sender_id,
                        text=text,
                        timestamp=ts,
                        thread_id=msg.get("mid"),
                        raw=event,
                    ))
        except Exception as exc:
            log.error("Instagram webhook parse error: %s", exc)
        return messages

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        """Handle Meta's webhook verification handshake."""
        if mode == "subscribe" and token == self._verify_token:
            return challenge
        return None

    async def get_user_name(self, user_id: str) -> str:
        """Fetch the display name for an Instagram user (requires permissions)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_GRAPH_API}/{user_id}",
                    params={"fields": "name", "access_token": self._token},
                )
            data = resp.json()
            return data.get("name", user_id)
        except Exception:
            return user_id
