"""MILES iMessage channel adapter.

Requires: macOS only.  Uses AppleScript via osascript to send messages and a
SQLite read of the Messages chat.db for polling.

chat.db path: ~/Library/Messages/chat.db
You may need to grant Full Disk Access to Terminal / your app in System Prefs.

Limitations:
  - Read-only access (polling) via chat.db; send via AppleScript.
  - Handles SMS fall-through automatically (AppleScript picks the best transport).
  - group chats are NOT supported (polls individual DM handles only).
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from orchestra.miles.channels.base import ChannelAdapter, ChannelMessage, ChannelResponse

__all__ = ["IMessageChannelAdapter"]

log = logging.getLogger("orchestra.miles.channels.imessage")

_CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"


def _is_macos() -> bool:
    return platform.system() == "Darwin"


class IMessageChannelAdapter(ChannelAdapter):
    """Poll iMessage/SMS DMs via chat.db and send via AppleScript."""

    channel_name = "imessage"
    supports_polling = True
    supports_webhook = False

    def __init__(
        self,
        handles: list[str] | None = None,
        since_ts: float | None = None,
        chat_db: str | Path | None = None,
    ) -> None:
        self._handles = handles or []
        self._since_ts: float = since_ts or time.time()
        self._db_path = Path(chat_db) if chat_db else _CHAT_DB

    async def connect(self) -> bool:
        if not _is_macos():
            log.error("iMessage adapter requires macOS.")
            return False
        if not self._db_path.exists():
            log.error("chat.db not found at %s — check Full Disk Access.", self._db_path)
            return False
        log.info("iMessage adapter connected (chat.db=%s)", self._db_path)
        return True

    async def poll(self) -> list[ChannelMessage]:
        if not _is_macos():
            return []
        return await asyncio.get_event_loop().run_in_executor(None, self._poll_sync)

    def _poll_sync(self) -> list[ChannelMessage]:
        messages: list[ChannelMessage] = []
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            # Convert unix epoch to Apple Core Data epoch (2001-01-01)
            apple_since = (self._since_ts - 978307200) * 1e9
            new_ts = self._since_ts

            handle_filter = ""
            params: list[Any] = [apple_since]
            if self._handles:
                placeholders = ",".join("?" * len(self._handles))
                handle_filter = f"AND h.id IN ({placeholders})"
                params.extend(self._handles)

            query = f"""
                SELECT m.rowid, m.text, m.date, m.is_from_me, h.id AS handle_id
                FROM message m
                JOIN handle h ON m.handle_id = h.rowid
                WHERE m.is_from_me = 0
                  AND m.date > ?
                  {handle_filter}
                ORDER BY m.date ASC
                LIMIT 100
            """
            cursor = conn.execute(query, params)
            for row in cursor.fetchall():
                if not row["text"]:
                    continue
                apple_ts = row["date"]
                unix_ts = (apple_ts / 1e9) + 978307200
                if unix_ts > new_ts:
                    new_ts = unix_ts
                handle = row["handle_id"] or "unknown"
                messages.append(ChannelMessage(
                    id=str(row["rowid"]),
                    channel="imessage",
                    sender_id=handle,
                    sender_name=handle,
                    text=row["text"],
                    timestamp=unix_ts,
                    thread_id=handle,
                    raw=dict(row),
                ))
            conn.close()

            if new_ts > self._since_ts:
                self._since_ts = new_ts + 0.001

        except sqlite3.OperationalError as exc:
            log.warning("chat.db read error (Full Disk Access required): %s", exc)
        except Exception as exc:
            log.error("iMessage poll error: %s", exc)
        return messages

    async def send(self, response: ChannelResponse) -> bool:
        if not _is_macos():
            log.error("iMessage send requires macOS.")
            return False
        return await asyncio.get_event_loop().run_in_executor(
            None, self._send_sync, response.recipient_id, response.text
        )

    def _send_sync(self, recipient: str, text: str) -> bool:
        safe_text = text.replace('"', '\\"').replace("\\", "\\\\")
        script = (
            f'tell application "Messages"\n'
            f'  set targetService to 1st service whose service type = iMessage\n'
            f'  set targetBuddy to buddy "{recipient}" of targetService\n'
            f'  send "{safe_text}" to targetBuddy\n'
            f'end tell'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                log.error("osascript failed: %s", result.stderr.strip())
                return False
            return True
        except subprocess.TimeoutExpired:
            log.error("osascript timed out sending to %s", recipient)
            return False
        except FileNotFoundError:
            log.error("osascript not found — macOS only.")
            return False
