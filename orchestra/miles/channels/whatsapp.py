"""MILES WhatsApp channel adapter.

Requires: WHATSAPP_TOKEN, WHATSAPP_PHONE_ID env vars.
Uses the Meta Cloud API (WhatsApp Business Platform).

Inbound messages arrive via webhook (set WHATSAPP_VERIFY_TOKEN for verification).
Polling is not supported — WhatsApp is push-only.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from orchestra.miles.channels.base import ChannelAdapter, ChannelMessage, ChannelResponse

__all__ = ["WhatsAppChannelAdapter"]

log = logging.getLogger("orchestra.miles.channels.whatsapp")

_API = "https://graph.facebook.com/v19.0"


class WhatsAppChannelAdapter(ChannelAdapter):
    """Send/receive WhatsApp messages via the Meta Cloud API."""

    channel_name = "whatsapp"
    supports_polling = False
    supports_webhook = True

    def __init__(
        self,
        token: str = "",
        phone_number_id: str = "",
        verify_token: str = "",
    ) -> None:
        self._token = token or os.environ.get("WHATSAPP_TOKEN", "")
        self._phone_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_ID", "")
        self._verify_token = verify_token or os.environ.get("WHATSAPP_VERIFY_TOKEN", "")

    async def connect(self) -> bool:
        if not self._token or not self._phone_id:
            log.error("WHATSAPP_TOKEN and WHATSAPP_PHONE_ID must be set.")
            return False
        # Verify credentials with a lightweight GET
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_API}/{self._phone_id}",
                headers={"Authorization": f"Bearer {self._token}"},
            )
        if resp.status_code == 200:
            log.info("WhatsApp connected: phone_id=%s", self._phone_id)
            return True
        log.error("WhatsApp auth failed: %s", resp.text)
        return False

    async def poll(self) -> list[ChannelMessage]:
        # WhatsApp is webhook-only; polling is not available via the Cloud API.
        return []

    async def send(self, response: ChannelResponse) -> bool:
        url = f"{_API}/{self._phone_id}/messages"
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": response.recipient_id,
            "type": "text",
            "text": {"body": response.text},
        }
        if response.thread_id:
            payload["context"] = {"message_id": response.thread_id}

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                json=payload,
            )
        if resp.status_code in (200, 201):
            return True
        log.error("WhatsApp send failed (%s): %s", resp.status_code, resp.text)
        return False

    def parse_webhook(self, payload: dict[str, Any]) -> list[ChannelMessage]:
        """Parse a raw WhatsApp webhook payload into ChannelMessages.

        Call this from your webhook handler and pass each message to
        ``ChannelHub.ingest()``.
        """
        messages: list[ChannelMessage] = []
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    contacts = {c["wa_id"]: c for c in value.get("contacts", [])}
                    for raw in value.get("messages", []):
                        wa_id = raw.get("from", "unknown")
                        contact = contacts.get(wa_id, {})
                        name = contact.get("profile", {}).get("name", wa_id)
                        text = ""
                        if raw.get("type") == "text":
                            text = raw.get("text", {}).get("body", "")
                        elif raw.get("type") == "interactive":
                            ir = raw.get("interactive", {})
                            text = (
                                ir.get("button_reply", {}).get("title")
                                or ir.get("list_reply", {}).get("title")
                                or ""
                            )
                        if not text:
                            continue
                        ts = float(raw.get("timestamp", 0))
                        messages.append(ChannelMessage(
                            id=raw.get("id", str(ts)),
                            channel="whatsapp",
                            sender_id=wa_id,
                            sender_name=name,
                            text=text,
                            timestamp=ts,
                            thread_id=raw.get("id"),
                            raw=raw,
                        ))
        except Exception as exc:
            log.error("WhatsApp webhook parse error: %s", exc)
        return messages

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        """Handle Meta's webhook verification handshake.

        Returns the challenge string if verification passes, None otherwise.
        """
        if mode == "subscribe" and token == self._verify_token:
            return challenge
        return None
