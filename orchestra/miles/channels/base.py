"""MILES Channel System — Unified schema, adapter ABC, hub, and consent registry.

Every inbound message from any channel is normalised into a ``ChannelMessage``
before entering the pipeline, and every outbound reply is a ``ChannelResponse``.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Awaitable

__all__ = [
    "ChannelMessage",
    "ChannelResponse",
    "ChannelAdapter",
    "ConsentRegistry",
    "ChannelHub",
    "MessageHandler",
]

log = logging.getLogger("orchestra.miles.channels")

MessageHandler = Callable[["ChannelMessage"], Awaitable["ChannelResponse | None"]]


# ---------------------------------------------------------------------------
# Unified message schema
# ---------------------------------------------------------------------------

@dataclass
class ChannelMessage:
    """Normalised message from any channel."""

    id: str
    channel: str                            # "slack" | "whatsapp" | "imessage" |
                                            # "gmail"  | "instagram" | "telegram"
    sender_id: str                          # platform-native user / phone / email
    sender_name: str
    text: str                               # plain-text body (already decoded)
    timestamp: float                        # unix epoch
    thread_id: str | None = None            # conversation thread
    reply_to_id: str | None = None          # message being replied to
    attachments: list[dict[str, Any]] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    is_dm: bool = True                      # False for group/channel messages
    subject: str = ""                       # email subject or thread title
    raw: dict[str, Any] = field(default_factory=dict)   # original payload

    @property
    def fingerprint(self) -> str:
        """Stable dedup key for this message."""
        key = f"{self.channel}:{self.sender_id}:{self.id}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


@dataclass
class ChannelResponse:
    """Response to dispatch back through a channel."""

    channel: str
    recipient_id: str
    text: str
    thread_id: str | None = None
    subject: str = ""                       # for email replies
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adapter ABC
# ---------------------------------------------------------------------------

class ChannelAdapter(ABC):
    """Abstract base for all channel adapters.

    Subclasses implement ``poll()`` (pull-based) or register a webhook handler
    for push-based channels.  Both approaches normalise payloads into
    ``ChannelMessage`` objects.
    """

    channel_name: str = ""
    supports_webhook: bool = False
    supports_polling: bool = True

    @abstractmethod
    async def connect(self) -> bool:
        """Authenticate / establish connection.  Returns True on success."""
        ...

    @abstractmethod
    async def poll(self) -> list[ChannelMessage]:
        """Fetch new unprocessed messages.  Must be idempotent."""
        ...

    @abstractmethod
    async def send(self, response: ChannelResponse) -> bool:
        """Deliver a response.  Returns True on success."""
        ...

    async def disconnect(self) -> None:
        """Optional teardown."""

    def mark_seen(self, message_id: str) -> None:
        """Mark a message as processed so it won't be returned by poll() again."""


# ---------------------------------------------------------------------------
# Consent registry  (SQLite-backed, GDPR-ready)
# ---------------------------------------------------------------------------

class ConsentRegistry:
    """Persistent store tracking which (channel, sender_id) pairs have opted in.

    Opt-in is explicit: a sender must be registered before MILES will process
    their messages.  Opt-out (via "STOP" / "UNSUBSCRIBE") is instant and
    irrevocable until the user re-opts-in.
    """

    OPT_OUT_KEYWORDS = frozenset({
        "stop", "unsubscribe", "opt out", "optout", "remove me",
        "delete my data", "forget me", "cancel",
    })

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db = Path(db_path or Path.home() / ".horizon" / "miles_consent.db")
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._db), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS consent (
                    channel     TEXT NOT NULL,
                    sender_id   TEXT NOT NULL,
                    opted_in    INTEGER DEFAULT 1,
                    opted_in_at REAL,
                    opted_out_at REAL,
                    notes       TEXT DEFAULT '',
                    PRIMARY KEY (channel, sender_id)
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          REAL,
                    channel     TEXT,
                    sender_id   TEXT,
                    action      TEXT,
                    reason      TEXT
                );
            """)

    def is_allowed(self, channel: str, sender_id: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT opted_in FROM consent WHERE channel=? AND sender_id=?",
                (channel, sender_id),
            ).fetchone()
        return bool(row and row["opted_in"])

    def opt_in(self, channel: str, sender_id: str, notes: str = "") -> None:
        now = time.time()
        with self._conn() as c:
            c.execute(
                """INSERT INTO consent (channel, sender_id, opted_in, opted_in_at, notes)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(channel, sender_id) DO UPDATE
                   SET opted_in=1, opted_in_at=excluded.opted_in_at, notes=excluded.notes""",
                (channel, sender_id, now, notes),
            )
            c.execute(
                "INSERT INTO audit_log (ts, channel, sender_id, action, reason) VALUES (?,?,?,?,?)",
                (now, channel, sender_id, "OPT_IN", notes),
            )

    def opt_out(self, channel: str, sender_id: str, reason: str = "user_request") -> None:
        now = time.time()
        with self._conn() as c:
            c.execute(
                """INSERT INTO consent (channel, sender_id, opted_in, opted_out_at)
                   VALUES (?, ?, 0, ?)
                   ON CONFLICT(channel, sender_id) DO UPDATE
                   SET opted_in=0, opted_out_at=excluded.opted_out_at""",
                (channel, sender_id, now),
            )
            c.execute(
                "INSERT INTO audit_log (ts, channel, sender_id, action, reason) VALUES (?,?,?,?,?)",
                (now, channel, sender_id, "OPT_OUT", reason),
            )

    def detect_opt_out(self, message: ChannelMessage) -> bool:
        """Return True if the message text is an opt-out request."""
        return any(kw in message.text.lower() for kw in self.OPT_OUT_KEYWORDS)

    def log(self, channel: str, sender_id: str, action: str, reason: str = "") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO audit_log (ts, channel, sender_id, action, reason) VALUES (?,?,?,?,?)",
                (time.time(), channel, sender_id, action, reason),
            )


# ---------------------------------------------------------------------------
# Channel hub
# ---------------------------------------------------------------------------

class ChannelHub:
    """Orchestrates all channel adapters and routes messages through the pipeline.

    Usage::

        hub = ChannelHub(consent=consent, pipeline=pipeline)
        hub.register(SlackAdapter(...))
        hub.register(TelegramAdapter(...))
        await hub.start(poll_interval=10)
    """

    def __init__(
        self,
        consent: ConsentRegistry,
        pipeline: "MessageHandler",
        poll_interval: float = 10.0,
    ) -> None:
        self._consent = consent
        self._pipeline = pipeline
        self._adapters: dict[str, ChannelAdapter] = {}
        self._seen: set[str] = set()        # dedup fingerprints (in-memory)
        self._poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None

    def register(self, adapter: ChannelAdapter) -> "ChannelHub":
        """Register a channel adapter.  Returns self for chaining."""
        self._adapters[adapter.channel_name] = adapter
        log.info("Registered channel: %s", adapter.channel_name)
        return self

    async def connect_all(self) -> dict[str, bool]:
        """Connect all registered adapters.  Returns {channel: success}."""
        results: dict[str, bool] = {}
        for name, adapter in self._adapters.items():
            try:
                results[name] = await adapter.connect()
            except Exception as exc:
                log.error("Failed to connect %s: %s", name, exc)
                results[name] = False
        return results

    async def ingest(self, message: ChannelMessage) -> ChannelResponse | None:
        """Run a single message through consent check → pipeline → dispatch."""
        # Auto-handle opt-outs before anything else
        if self._consent.detect_opt_out(message):
            self._consent.opt_out(message.channel, message.sender_id, "user_request")
            log.info("Opt-out recorded: %s/%s", message.channel, message.sender_id)
            adapter = self._adapters.get(message.channel)
            if adapter:
                bye = ChannelResponse(
                    channel=message.channel,
                    recipient_id=message.sender_id,
                    text="You've been unsubscribed. Reply START to opt back in.",
                    thread_id=message.thread_id,
                )
                await adapter.send(bye)
            return None

        if not self._consent.is_allowed(message.channel, message.sender_id):
            self._consent.log(message.channel, message.sender_id, "BLOCKED_NO_CONSENT")
            log.debug("Blocked (no consent): %s/%s", message.channel, message.sender_id)
            return None

        # Dedup
        fp = message.fingerprint
        if fp in self._seen:
            return None
        self._seen.add(fp)
        if len(self._seen) > 10_000:
            self._seen = set(list(self._seen)[-5_000:])

        self._consent.log(message.channel, message.sender_id, "MESSAGE_ACCEPTED")

        try:
            response = await self._pipeline(message)
        except Exception as exc:
            log.error("Pipeline error for %s/%s: %s", message.channel, message.sender_id, exc)
            self._consent.log(message.channel, message.sender_id, "PIPELINE_ERROR", str(exc))
            return None

        if response:
            adapter = self._adapters.get(message.channel)
            if adapter:
                await adapter.send(response)

        return response

    async def _poll_loop(self) -> None:
        while self._running:
            tasks = [
                self._poll_adapter(adapter)
                for adapter in self._adapters.values()
                if adapter.supports_polling
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(self._poll_interval)

    async def _poll_adapter(self, adapter: ChannelAdapter) -> None:
        try:
            messages = await adapter.poll()
            for msg in messages:
                await self.ingest(msg)
        except Exception as exc:
            log.warning("Poll error on %s: %s", adapter.channel_name, exc)

    async def start(self) -> None:
        """Connect all adapters and begin the polling loop."""
        await self.connect_all()
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="miles-channel-hub")
        log.info("ChannelHub started with %d adapter(s)", len(self._adapters))

    async def stop(self) -> None:
        """Stop polling and disconnect all adapters."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        for adapter in self._adapters.values():
            try:
                await adapter.disconnect()
            except Exception:
                pass
        log.info("ChannelHub stopped.")
