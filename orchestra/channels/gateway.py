"""Horizon Orchestra — Channel Gateway.

Unified messaging gateway supporting Telegram, Discord, WhatsApp, and SMS.
Each channel is a concrete implementation of the ``Channel`` ABC. The
``ChannelGateway`` orchestrates registration, connection, fan-out broadcast,
and inbound message routing to the Orchestra agent.

Architecture::

    ChannelGateway
     ├── TelegramChannel  (Telegram Bot API via httpx)
     ├── DiscordChannel   (Discord REST API v10 via httpx)
     ├── WhatsAppChannel  (WhatsApp Business Cloud API via httpx)
     └── SMSChannel       (Twilio REST API via httpx)

    Incoming messages → ChannelGateway.process_incoming()
                      → MonolithicAgent (arch_a)
                      → Response sent back via originating channel

Usage::

    from orchestra.channels import ChannelGateway, TelegramChannel

    gw = ChannelGateway(config=ChannelConfig(enabled_channels=["telegram"]))
    gw.register(TelegramChannel())
    await gw.connect_all({"telegram": {"token": "BOT_TOKEN"}})
    await gw.send("telegram", "123456789", "Hello from Orchestra!")
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

__all__ = [
    "ChannelGateway",
    "Channel",
    "ChannelMessage",
    "ChannelConfig",
    "TelegramChannel",
    "DiscordChannel",
    "WhatsAppChannel",
    "SMSChannel",
]

log = logging.getLogger("orchestra.channels")

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ChannelConfig:
    """Top-level configuration for the channel gateway.

    Attributes:
        enabled_channels: Names of channels that should be connected.
            E.g. ``["telegram", "discord"]``.
        webhook_port: TCP port for the optional HTTP webhook server (not
            started by default — callers must start their own ASGI server).
        default_architecture: Which Orchestra architecture to route inbound
            messages to (``"arch_a"`` = monolithic, ``"arch_c"`` = hybrid,
            ``"arch_e"`` = adaptive).
    """

    enabled_channels: list[str] = field(default_factory=list)
    webhook_port: int = 8080
    default_architecture: str = "arch_a"


@dataclass
class ChannelMessage:
    """Normalised representation of an inbound message from any channel.

    Attributes:
        id: Unique identifier for this message (assigned by the channel).
        channel: Channel name, e.g. ``"telegram"``.
        sender_id: Platform-specific sender identifier.
        sender_name: Human-readable display name of the sender.
        content: Plain-text message body.
        attachments: List of attachment descriptors (file URLs, captions, …).
        timestamp: Unix epoch float when the message was sent/received.
        reply_to: ID of the message being replied to, if any.
        metadata: Raw platform-specific payload fields for advanced processing.
    """

    id: str
    channel: str
    sender_id: str
    sender_name: str
    content: str
    attachments: list[Any] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class Channel(abc.ABC):
    """Abstract base class for a messaging channel integration.

    Subclasses must implement ``connect``, ``send``, ``receive``, and
    ``webhook_handler``.  The ``name`` property uniquely identifies the
    channel within the gateway.
    """

    # Subclasses set this as a class attribute or property
    name: str = ""

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with the channel's API and verify connectivity.

        Args:
            credentials: Channel-specific credential dict.  See concrete
                implementation docstrings for required keys.

        Returns:
            ``True`` if the connection succeeded; ``False`` otherwise.
        """

    @abc.abstractmethod
    async def send(
        self,
        recipient: str,
        message: str,
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Send a message to a recipient.

        Args:
            recipient: Platform-specific recipient identifier (chat ID, user
                ID, phone number, …).
            message: Plain-text message body.
            attachments: Optional list of attachment descriptors.

        Returns:
            Dict with ``success`` (bool) and ``message_id`` (str | None).
        """

    @abc.abstractmethod
    async def receive(self) -> ChannelMessage | None:
        """Poll for the next pending inbound message.

        Returns:
            A :class:`ChannelMessage` if one is available, otherwise ``None``.
        """

    @abc.abstractmethod
    def webhook_handler(self, request: dict[str, Any]) -> ChannelMessage | None:
        """Parse a raw webhook payload into a :class:`ChannelMessage`.

        This method is intentionally synchronous because ASGI webhook
        handlers typically run in a synchronous context.  Async follow-up
        work (e.g. sending a reply) must be scheduled separately.

        Args:
            request: Raw decoded JSON body from the platform's webhook.

        Returns:
            Parsed :class:`ChannelMessage`, or ``None`` if the payload does
            not represent an inbound user message (e.g. delivery receipts).
        """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _make_message(
        self,
        *,
        msg_id: str | None = None,
        sender_id: str,
        sender_name: str,
        content: str,
        attachments: list[Any] | None = None,
        timestamp: float | None = None,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChannelMessage:
        """Construct a :class:`ChannelMessage` with sensible defaults."""
        return ChannelMessage(
            id=msg_id or str(uuid.uuid4()),
            channel=self.name,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            attachments=attachments or [],
            timestamp=timestamp or time.time(),
            reply_to=reply_to,
            metadata=metadata or {},
        )


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


class TelegramChannel(Channel):
    """Telegram Bot API integration.

    Uses the polling (getUpdates) approach for ``receive()`` and webhook-style
    parsing for ``webhook_handler()``.  A bot token is required; obtain one
    from @BotFather on Telegram.

    Credentials dict::

        {"token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"}
    """

    name = "telegram"
    _BASE = "https://api.telegram.org"

    def __init__(self) -> None:
        self._token: str = ""
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=30.0)
        self._update_offset: int = 0
        self._connected: bool = False

    @property
    def _api(self) -> str:
        return f"{self._BASE}/bot{self._token}"

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate and validate the bot token via getMe.

        Args:
            credentials: Must contain key ``"token"`` with the bot token.

        Returns:
            ``True`` if the bot token is valid.
        """
        self._token = credentials.get("token", "")
        if not self._token:
            log.error("Telegram: missing 'token' in credentials")
            return False
        try:
            resp = await self._client.get(f"{self._api}/getMe")
            data = resp.json()
            if data.get("ok"):
                bot = data["result"]
                log.info(
                    "Telegram connected as @%s (id=%s)", bot.get("username"), bot.get("id")
                )
                self._connected = True
                return True
            log.error("Telegram getMe failed: %s", data.get("description"))
            return False
        except httpx.HTTPError as exc:
            log.error("Telegram connect error: %s", exc)
            return False

    async def send(
        self,
        recipient: str,
        message: str,
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Send a text message to a Telegram chat.

        Args:
            recipient: Telegram chat ID (integer as string or username with @).
            message: Text to send (supports Telegram MarkdownV2 if desired).
            attachments: Not used in this implementation (future: send_document).

        Returns:
            Dict with ``success`` and ``message_id``.
        """
        if not self._connected:
            return {"success": False, "message_id": None, "error": "Not connected"}
        try:
            resp = await self._client.post(
                f"{self._api}/sendMessage",
                json={"chat_id": recipient, "text": message},
            )
            data = resp.json()
            if data.get("ok"):
                msg_id = str(data["result"]["message_id"])
                log.debug("Telegram sent message_id=%s to chat=%s", msg_id, recipient)
                return {"success": True, "message_id": msg_id}
            log.error("Telegram sendMessage error: %s", data.get("description"))
            return {"success": False, "message_id": None, "error": data.get("description")}
        except httpx.HTTPError as exc:
            log.error("Telegram send error: %s", exc)
            return {"success": False, "message_id": None, "error": str(exc)}

    async def receive(self) -> ChannelMessage | None:
        """Poll Telegram for new messages via getUpdates.

        Uses ``_update_offset`` to avoid re-processing already-seen messages.

        Returns:
            The oldest pending :class:`ChannelMessage`, or ``None``.
        """
        if not self._connected:
            return None
        try:
            resp = await self._client.get(
                f"{self._api}/getUpdates",
                params={"offset": self._update_offset, "timeout": 5, "limit": 1},
            )
            data = resp.json()
            if not data.get("ok") or not data["result"]:
                return None
            update = data["result"][0]
            self._update_offset = update["update_id"] + 1
            return self._parse_update(update)
        except httpx.HTTPError as exc:
            log.error("Telegram receive error: %s", exc)
            return None

    def webhook_handler(self, request: dict[str, Any]) -> ChannelMessage | None:
        """Parse a Telegram webhook POST body.

        Args:
            request: Decoded JSON from the Telegram webhook endpoint.

        Returns:
            Parsed :class:`ChannelMessage` or ``None`` for non-message updates.
        """
        return self._parse_update(request)

    def _parse_update(self, update: dict[str, Any]) -> ChannelMessage | None:
        """Internal: extract message fields from a Telegram update dict."""
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return None
        sender = msg.get("from", {})
        name_parts = [sender.get("first_name", ""), sender.get("last_name", "")]
        return self._make_message(
            msg_id=str(msg.get("message_id", "")),
            sender_id=str(sender.get("id", "")),
            sender_name=" ".join(p for p in name_parts if p).strip() or sender.get("username", "?"),
            content=msg.get("text") or msg.get("caption") or "",
            timestamp=float(msg.get("date", time.time())),
            reply_to=str(msg["reply_to_message"]["message_id"])
            if msg.get("reply_to_message")
            else None,
            metadata={"chat_id": str(msg.get("chat", {}).get("id", ""))},
        )


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


class DiscordChannel(Channel):
    """Discord REST API v10 integration.

    Supports sending and receiving messages in a single monitored channel.
    For production use, prefer Discord's Gateway WebSocket for real-time
    events.  This implementation uses REST polling for simplicity.

    Credentials dict::

        {"token": "Bot YOUR_BOT_TOKEN", "channel_id": "1234567890"}
    """

    name = "discord"
    _BASE = "https://discord.com/api/v10"

    def __init__(self) -> None:
        self._token: str = ""
        self._channel_id: str = ""
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=30.0)
        self._last_message_id: str | None = None
        self._connected: bool = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._token, "Content-Type": "application/json"}

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with Discord and verify the bot token.

        Args:
            credentials: Must contain ``"token"`` (include ``"Bot "`` prefix)
                and optionally ``"channel_id"`` for polling.

        Returns:
            ``True`` if the token is valid.
        """
        self._token = credentials.get("token", "")
        self._channel_id = credentials.get("channel_id", "")
        if not self._token:
            log.error("Discord: missing 'token' in credentials")
            return False
        try:
            resp = await self._client.get(
                f"{self._BASE}/users/@me", headers=self._headers()
            )
            data = resp.json()
            if resp.status_code == 200:
                log.info(
                    "Discord connected as %s#%s",
                    data.get("username"),
                    data.get("discriminator"),
                )
                self._connected = True
                return True
            log.error("Discord /users/@me failed: %s", data.get("message"))
            return False
        except httpx.HTTPError as exc:
            log.error("Discord connect error: %s", exc)
            return False

    async def send(
        self,
        recipient: str,
        message: str,
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Send a message to a Discord channel.

        Args:
            recipient: Discord channel ID to send the message to.
            message: Text content (up to 2000 characters).
            attachments: Not used in this implementation.

        Returns:
            Dict with ``success`` and ``message_id``.
        """
        if not self._connected:
            return {"success": False, "message_id": None, "error": "Not connected"}
        try:
            resp = await self._client.post(
                f"{self._BASE}/channels/{recipient}/messages",
                headers=self._headers(),
                json={"content": message},
            )
            data = resp.json()
            if resp.status_code in (200, 201):
                msg_id = str(data.get("id", ""))
                log.debug("Discord sent message_id=%s to channel=%s", msg_id, recipient)
                return {"success": True, "message_id": msg_id}
            log.error("Discord send error: %s", data.get("message"))
            return {"success": False, "message_id": None, "error": data.get("message")}
        except httpx.HTTPError as exc:
            log.error("Discord send error: %s", exc)
            return {"success": False, "message_id": None, "error": str(exc)}

    async def receive(self) -> ChannelMessage | None:
        """Poll a Discord channel for new messages.

        Uses ``_last_message_id`` as the ``after`` snowflake to avoid
        re-fetching already-seen messages.

        Returns:
            The oldest unread :class:`ChannelMessage`, or ``None``.
        """
        if not self._connected or not self._channel_id:
            return None
        params: dict[str, Any] = {"limit": 1}
        if self._last_message_id:
            params["after"] = self._last_message_id
        try:
            resp = await self._client.get(
                f"{self._BASE}/channels/{self._channel_id}/messages",
                headers=self._headers(),
                params=params,
            )
            if resp.status_code != 200:
                return None
            msgs = resp.json()
            if not msgs:
                return None
            raw = msgs[0]  # newest first (limit=1)
            self._last_message_id = raw["id"]
            return self._parse_message(raw)
        except httpx.HTTPError as exc:
            log.error("Discord receive error: %s", exc)
            return None

    def webhook_handler(self, request: dict[str, Any]) -> ChannelMessage | None:
        """Parse a Discord interaction or message webhook payload.

        Args:
            request: Decoded JSON from the Discord webhook endpoint.

        Returns:
            Parsed :class:`ChannelMessage` or ``None`` for non-message events.
        """
        # Handle interaction payload (type 2 = APPLICATION_COMMAND)
        interaction_type = request.get("type")
        if interaction_type == 2:
            # Slash command interaction
            data = request.get("data", {})
            options = data.get("options", [])
            content = " ".join(str(o.get("value", "")) for o in options) or data.get("name", "")
            member = request.get("member", {})
            user = member.get("user", request.get("user", {}))
            return self._make_message(
                msg_id=request.get("id", ""),
                sender_id=user.get("id", ""),
                sender_name=user.get("username", "?"),
                content=content,
                metadata={"interaction_token": request.get("token", "")},
            )
        # Handle regular message webhook
        if "content" in request and "author" in request:
            return self._parse_message(request)
        return None

    def _parse_message(self, raw: dict[str, Any]) -> ChannelMessage:
        """Convert a raw Discord message dict to a :class:`ChannelMessage`."""
        author = raw.get("author", {})
        ref = raw.get("message_reference")
        return self._make_message(
            msg_id=str(raw.get("id", "")),
            sender_id=str(author.get("id", "")),
            sender_name=author.get("username", "?"),
            content=raw.get("content", ""),
            attachments=[a.get("url") for a in raw.get("attachments", [])],
            reply_to=str(ref["message_id"]) if ref else None,
            metadata={"channel_id": str(raw.get("channel_id", ""))},
        )


# ---------------------------------------------------------------------------
# WhatsApp Business Cloud API
# ---------------------------------------------------------------------------


class WhatsAppChannel(Channel):
    """WhatsApp Business Cloud API integration (Meta Graph API v18.0).

    Requires a verified Meta Developer App with WhatsApp enabled.

    Credentials dict::

        {
            "token": "EAABsbCS...",          # permanent system-user token
            "phone_number_id": "1234567890"
        }
    """

    name = "whatsapp"
    _BASE = "https://graph.facebook.com/v18.0"

    def __init__(self) -> None:
        self._token: str = ""
        self._phone_number_id: str = ""
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=30.0)
        self._connected: bool = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Verify WhatsApp credentials by fetching phone number metadata.

        Args:
            credentials: Must contain ``"token"`` and ``"phone_number_id"``.

        Returns:
            ``True`` if the token and phone_number_id are valid.
        """
        self._token = credentials.get("token", "")
        self._phone_number_id = credentials.get("phone_number_id", "")
        if not self._token or not self._phone_number_id:
            log.error("WhatsApp: missing 'token' or 'phone_number_id' in credentials")
            return False
        try:
            resp = await self._client.get(
                f"{self._BASE}/{self._phone_number_id}",
                headers=self._headers(),
                params={"fields": "verified_name,code_verification_status"},
            )
            data = resp.json()
            if resp.status_code == 200:
                log.info(
                    "WhatsApp connected: verified_name=%s", data.get("verified_name")
                )
                self._connected = True
                return True
            log.error("WhatsApp connect failed: %s", data.get("error", {}).get("message"))
            return False
        except httpx.HTTPError as exc:
            log.error("WhatsApp connect error: %s", exc)
            return False

    async def send(
        self,
        recipient: str,
        message: str,
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Send a WhatsApp text message.

        Args:
            recipient: Recipient phone number in E.164 format, e.g.
                ``"15551234567"`` (no ``+``).
            message: Text body (max 4096 characters).
            attachments: Not used (future: media messages).

        Returns:
            Dict with ``success`` and ``message_id``.
        """
        if not self._connected:
            return {"success": False, "message_id": None, "error": "Not connected"}
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }
        try:
            resp = await self._client.post(
                f"{self._BASE}/{self._phone_number_id}/messages",
                headers=self._headers(),
                json=payload,
            )
            data = resp.json()
            if resp.status_code in (200, 201):
                msgs = data.get("messages", [])
                msg_id = msgs[0].get("id") if msgs else None
                log.debug("WhatsApp sent message_id=%s to %s", msg_id, recipient)
                return {"success": True, "message_id": msg_id}
            err = data.get("error", {}).get("message", "Unknown error")
            log.error("WhatsApp send failed: %s", err)
            return {"success": False, "message_id": None, "error": err}
        except httpx.HTTPError as exc:
            log.error("WhatsApp send error: %s", exc)
            return {"success": False, "message_id": None, "error": str(exc)}

    async def receive(self) -> ChannelMessage | None:
        """WhatsApp does not support polling; use webhook_handler instead.

        Returns:
            Always ``None``.  Inbound messages arrive via webhooks.
        """
        log.debug("WhatsApp: receive() is a no-op; use webhook_handler()")
        return None

    def webhook_handler(self, request: dict[str, Any]) -> ChannelMessage | None:
        """Parse a WhatsApp webhook notification.

        Handles the nested object → entry → changes → value → messages
        structure from the WhatsApp Business Platform.

        Args:
            request: Decoded JSON from the WhatsApp webhook POST.

        Returns:
            Parsed :class:`ChannelMessage` or ``None`` for status updates.
        """
        try:
            entries = request.get("entry", [])
            if not entries:
                return None
            changes = entries[0].get("changes", [])
            if not changes:
                return None
            value = changes[0].get("value", {})
            messages = value.get("messages", [])
            if not messages:
                return None
            msg = messages[0]
            contacts = value.get("contacts", [{}])
            contact = contacts[0] if contacts else {}
            sender_id = msg.get("from", "")
            sender_name = contact.get("profile", {}).get("name", sender_id)
            text_body = ""
            if msg.get("type") == "text":
                text_body = msg.get("text", {}).get("body", "")
            elif msg.get("type") == "image":
                text_body = msg.get("image", {}).get("caption", "[image]")
            elif msg.get("type") == "document":
                text_body = msg.get("document", {}).get("caption", "[document]")
            else:
                text_body = f"[{msg.get('type', 'unknown')} message]"
            return self._make_message(
                msg_id=msg.get("id", str(uuid.uuid4())),
                sender_id=sender_id,
                sender_name=sender_name,
                content=text_body,
                timestamp=float(msg.get("timestamp", time.time())),
                metadata={"phone_number_id": self._phone_number_id},
            )
        except (KeyError, IndexError, TypeError) as exc:
            log.warning("WhatsApp webhook parse error: %s", exc)
            return None


# ---------------------------------------------------------------------------
# SMS via Twilio
# ---------------------------------------------------------------------------


class SMSChannel(Channel):
    """SMS integration via the Twilio REST API.

    Credentials dict::

        {
            "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "auth_token":  "your_auth_token",
            "from_number": "+15005550006"
        }
    """

    name = "sms"
    _BASE = "https://api.twilio.com/2010-04-01"

    def __init__(self) -> None:
        self._account_sid: str = ""
        self._auth_token: str = ""
        self._from_number: str = ""
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=30.0)
        self._connected: bool = False

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Verify Twilio credentials via the Accounts REST endpoint.

        Args:
            credentials: Must contain ``"account_sid"``, ``"auth_token"``,
                and ``"from_number"``.

        Returns:
            ``True`` if the credentials are valid.
        """
        self._account_sid = credentials.get("account_sid", "")
        self._auth_token = credentials.get("auth_token", "")
        self._from_number = credentials.get("from_number", "")
        if not all([self._account_sid, self._auth_token, self._from_number]):
            log.error("SMS: missing Twilio credentials (account_sid, auth_token, from_number)")
            return False
        try:
            resp = await self._client.get(
                f"{self._BASE}/Accounts/{self._account_sid}.json",
                auth=(self._account_sid, self._auth_token),
            )
            data = resp.json()
            if resp.status_code == 200:
                log.info(
                    "Twilio SMS connected: friendly_name=%s, status=%s",
                    data.get("friendly_name"),
                    data.get("status"),
                )
                self._connected = True
                return True
            log.error("Twilio connect failed: %s", data.get("message"))
            return False
        except httpx.HTTPError as exc:
            log.error("Twilio connect error: %s", exc)
            return False

    async def send(
        self,
        recipient: str,
        message: str,
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Send an SMS message via Twilio.

        Args:
            recipient: E.164 phone number, e.g. ``"+15551234567"``.
            message: SMS text (max 1600 characters; longer messages are
                automatically segmented by Twilio).
            attachments: Not used.

        Returns:
            Dict with ``success`` and ``message_id`` (Twilio SID).
        """
        if not self._connected:
            return {"success": False, "message_id": None, "error": "Not connected"}
        try:
            resp = await self._client.post(
                f"{self._BASE}/Accounts/{self._account_sid}/Messages.json",
                auth=(self._account_sid, self._auth_token),
                data={"From": self._from_number, "To": recipient, "Body": message},
            )
            data = resp.json()
            if resp.status_code in (200, 201):
                sid = data.get("sid")
                log.debug("Twilio SMS sent sid=%s to %s", sid, recipient)
                return {"success": True, "message_id": sid}
            log.error("Twilio send error: %s", data.get("message"))
            return {"success": False, "message_id": None, "error": data.get("message")}
        except httpx.HTTPError as exc:
            log.error("Twilio send error: %s", exc)
            return {"success": False, "message_id": None, "error": str(exc)}

    async def receive(self) -> ChannelMessage | None:
        """Poll Twilio for the most recent inbound SMS to the from_number.

        Note: Twilio's REST API is not designed for high-frequency polling.
        For production, configure a Twilio webhook instead and use
        ``webhook_handler``.

        Returns:
            The most recent inbound :class:`ChannelMessage`, or ``None``.
        """
        if not self._connected:
            return None
        try:
            resp = await self._client.get(
                f"{self._BASE}/Accounts/{self._account_sid}/Messages.json",
                auth=(self._account_sid, self._auth_token),
                params={"To": self._from_number, "PageSize": 1},
            )
            data = resp.json()
            messages = data.get("messages", [])
            if not messages:
                return None
            raw = messages[0]
            if raw.get("direction") not in ("inbound",):
                return None
            return self._make_message(
                msg_id=raw.get("sid", str(uuid.uuid4())),
                sender_id=raw.get("from", ""),
                sender_name=raw.get("from", "?"),
                content=raw.get("body", ""),
                timestamp=time.time(),  # Twilio date_sent is a string; keep simple
                metadata={"status": raw.get("status")},
            )
        except httpx.HTTPError as exc:
            log.error("Twilio receive error: %s", exc)
            return None

    def webhook_handler(self, request: dict[str, Any]) -> ChannelMessage | None:
        """Parse a Twilio SMS webhook (TwiML callback) payload.

        Twilio sends form-encoded data; callers should parse it to a dict before
        passing to this method.

        Args:
            request: Dict of form fields from the Twilio webhook POST.

        Returns:
            Parsed :class:`ChannelMessage` or ``None``.
        """
        body = request.get("Body", "")
        from_number = request.get("From", "")
        if not from_number or not body:
            return None
        return self._make_message(
            msg_id=request.get("MessageSid", str(uuid.uuid4())),
            sender_id=from_number,
            sender_name=from_number,
            content=body,
            metadata={
                "to_number": request.get("To", self._from_number),
                "num_segments": request.get("NumSegments", "1"),
            },
        )


# ---------------------------------------------------------------------------
# ChannelGateway
# ---------------------------------------------------------------------------


class ChannelGateway:
    """Orchestrates all registered channels.

    Provides a unified API for sending, broadcasting, and processing inbound
    messages.  Inbound messages are routed to the Orchestra agent and responses
    are sent back via the originating channel.

    Args:
        config: Gateway configuration.  If ``None``, a default is used.

    Example::

        gw = ChannelGateway()
        gw.register(TelegramChannel())
        await gw.connect_all({"telegram": {"token": "BOT_TOKEN"}})
        await gw.broadcast("Hello from Orchestra!")
    """

    def __init__(self, config: ChannelConfig | None = None) -> None:
        self.config = config or ChannelConfig()
        self._channels: dict[str, Channel] = {}
        self._connected: dict[str, bool] = {}
        self._agent: Any = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Registration & connection
    # ------------------------------------------------------------------

    def register(self, channel: Channel) -> None:
        """Register a channel implementation with the gateway.

        Args:
            channel: Concrete :class:`Channel` subclass instance.
        """
        self._channels[channel.name] = channel
        log.debug("Registered channel: %s", channel.name)

    async def connect_all(
        self, credentials: dict[str, dict[str, str]]
    ) -> dict[str, bool]:
        """Connect all registered channels using provided credentials.

        Args:
            credentials: Mapping of channel name to its credentials dict.

        Returns:
            Mapping of channel name to connection success flag.
        """
        results: dict[str, bool] = {}
        tasks = []

        async def _connect_one(name: str, ch: Channel) -> tuple[str, bool]:
            creds = credentials.get(name, {})
            ok = await ch.connect(creds)
            return name, ok

        async with asyncio.TaskGroup() as tg:
            for name, ch in self._channels.items():
                if name in credentials or name in self.config.enabled_channels:
                    tasks.append(tg.create_task(_connect_one(name, ch)))

        for task in tasks:
            name, ok = task.result()
            self._connected[name] = ok
            results[name] = ok

        log.info(
            "Channel connections: %s",
            ", ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in results.items()),
        )
        return results

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(
        self, channel_name: str, recipient: str, message: str
    ) -> dict[str, Any]:
        """Send a message via a specific channel.

        Args:
            channel_name: Name of the channel, e.g. ``"telegram"``.
            recipient: Platform-specific recipient identifier.
            message: Text to send.

        Returns:
            Result dict from the channel's send method.
        """
        ch = self._channels.get(channel_name)
        if ch is None:
            return {"success": False, "error": f"Channel '{channel_name}' not registered"}
        if not self._connected.get(channel_name):
            return {"success": False, "error": f"Channel '{channel_name}' not connected"}
        return await ch.send(recipient, message)

    async def broadcast(
        self,
        message: str,
        channels: list[str] | None = None,
        recipient_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send a message to all (or a subset of) connected channels.

        Args:
            message: Text to broadcast.
            channels: Subset of channel names to send to.  If ``None``, sends
                to all connected channels.
            recipient_map: Mapping of channel name to recipient ID.  Required
                for channels that need an explicit recipient (Telegram chat ID,
                Discord channel ID, phone number, …).

        Returns:
            Dict mapping channel names to their send results.
        """
        target_names = channels or list(self._channels.keys())
        recipient_map = recipient_map or {}
        results: dict[str, Any] = {}

        async def _send_one(name: str) -> tuple[str, dict]:
            recipient = recipient_map.get(name, "")
            result = await self.send(name, recipient, message)
            return name, result

        tasks = [_send_one(n) for n in target_names if self._connected.get(n)]
        for coro in asyncio.as_completed(tasks):
            name, result = await coro
            results[name] = result
            log.debug("broadcast → %s: %s", name, result.get("success"))

        return results

    # ------------------------------------------------------------------
    # Inbound routing
    # ------------------------------------------------------------------

    async def process_incoming(self, message: ChannelMessage) -> str:
        """Route an inbound message to the Orchestra agent and return the reply.

        The reply is also sent back to the sender via the originating channel if
        ``metadata["chat_id"]`` or ``message.sender_id`` is available.

        Args:
            message: Normalised inbound message.

        Returns:
            Agent's text response.
        """
        log.info(
            "Incoming [%s] from %s: %r",
            message.channel,
            message.sender_name,
            message.content[:80],
        )
        agent = self._get_agent()
        try:
            response = await agent.run(message.content)
        except Exception as exc:
            log.error("Agent error while processing message: %s", exc)
            response = "I'm sorry, something went wrong processing your request."

        # Determine where to send the reply
        reply_to = (
            message.metadata.get("chat_id")  # Telegram
            or message.metadata.get("channel_id")  # Discord
            or message.sender_id  # WhatsApp/SMS (phone number)
        )
        if reply_to and message.channel in self._connected:
            await self.send(message.channel, reply_to, str(response))

        return str(response)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_channels(self) -> list[dict[str, Any]]:
        """List all registered channels and their connection status.

        Returns:
            List of dicts with ``name``, ``connected``, and ``class`` keys.
        """
        return [
            {
                "name": name,
                "connected": self._connected.get(name, False),
                "class": type(ch).__name__,
            }
            for name, ch in self._channels.items()
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_agent(self) -> Any:
        """Lazy-load the Orchestra agent for message processing.

        Returns:
            An agent with a ``run(prompt: str) -> str`` async method.
        """
        if self._agent is None:
            arch = self.config.default_architecture
            try:
                if arch == "arch_a":
                    from orchestra.arch_a import MonolithicAgent  # type: ignore

                    self._agent = MonolithicAgent()
                elif arch == "arch_c":
                    from orchestra.arch_c import HybridOrchestrator  # type: ignore

                    self._agent = HybridOrchestrator()
                elif arch == "arch_e":
                    from orchestra.arch_e import AdaptiveOrchestrator  # type: ignore

                    self._agent = AdaptiveOrchestrator()
                else:
                    raise ImportError(f"Unknown architecture: {arch}")
                log.info("Loaded architecture: %s", arch)
            except ImportError as exc:
                log.warning("Could not load %s: %s — using echo agent", arch, exc)
                self._agent = _EchoAgent()
        return self._agent

    def set_agent(self, agent: Any) -> None:
        """Inject a custom agent for message processing.

        Useful in tests or when a pre-configured agent instance is available.

        Args:
            agent: Any object with an async ``run(prompt: str)`` method.
        """
        self._agent = agent
        log.debug("Custom agent set: %s", type(agent).__name__)


class _EchoAgent:
    """Minimal fallback agent that echoes messages (used when no arch is loaded)."""

    async def run(self, prompt: str) -> str:
        return f"[Echo] {prompt}"
