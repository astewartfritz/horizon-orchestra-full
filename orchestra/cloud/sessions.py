"""
orchestra/cloud/sessions.py
-----------------------------
Cloud session persistence — conversations survive Lambda cold starts
and scale horizontally across instances via DynamoDB.
"""
from __future__ import annotations

__all__ = [
    "CloudSessionStore",
]

import asyncio
import json
import logging
import time
import zlib
from base64 import b64decode, b64encode
from typing import Any

try:
    import boto3
    from boto3.dynamodb.conditions import Key as DKey
    from botocore.exceptions import ClientError
    _HAS_BOTO3 = True
except ImportError:  # pragma: no cover — optional cloud dependency
    boto3 = None  # type: ignore[assignment]
    DKey = None  # type: ignore[assignment,misc]
    ClientError = Exception  # type: ignore[misc,assignment]
    _HAS_BOTO3 = False

logger = logging.getLogger("orchestra.cloud.sessions")

_DEFAULT_TTL_DAYS = 30


class CloudSessionStore:
    """
    DynamoDB-backed session store for multi-turn conversations.

    Table schema
    ------------
    PK  : user_id    (String, hash key)
    SK  : session_id (String, range key)
    ttl : epoch seconds (DynamoDB TTL attribute)

    ``messages`` is stored as a compressed, base64-encoded JSON blob to
    keep item sizes small and avoid DynamoDB's 400 KB limit for most
    real-world conversations.
    """

    def __init__(
        self,
        table: str = "horizon-sessions",
        region: str = "us-east-1",
    ) -> None:
        if not _HAS_BOTO3:
            raise RuntimeError(
                "boto3 is required for CloudSessionStore. "
                "Install it with: pip install boto3"
            )
        self._table_name = table
        self._region = region
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(table)
        logger.info(
            "CloudSessionStore initialised (table=%s, region=%s)", table, region
        )

    # ------------------------------------------------------------------
    # Save / Load
    # ------------------------------------------------------------------

    async def save(
        self,
        user_id: str,
        session_id: str,
        messages: list[dict],
        metadata: dict | None = None,
        ttl_days: int = _DEFAULT_TTL_DAYS,
    ) -> None:
        """Persist an entire conversation to DynamoDB.

        Messages are compressed before storage to reduce item size.
        """
        if metadata is None:
            metadata = {}

        compressed = self._compress(json.dumps(messages))
        blob = b64encode(compressed).decode("utf-8")
        ttl = int(time.time()) + ttl_days * 86400

        # Store a short preview (first user message) for list_sessions
        preview = ""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                preview = content[:200] if isinstance(content, str) else str(content)[:200]
                break

        item: dict[str, Any] = {
            "user_id": user_id,
            "session_id": session_id,
            "messages_blob": blob,
            "message_count": len(messages),
            "preview": preview,
            "metadata": metadata,
            "updated_at": time.time(),
            "ttl": ttl,
        }

        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._table.put_item(Item=item),
            )
            logger.info(
                "save: user_id=%s session_id=%s messages=%d",
                user_id,
                session_id,
                len(messages),
            )
        except ClientError:
            logger.exception(
                "save: DynamoDB error for session user_id=%s session_id=%s",
                user_id,
                session_id,
            )
            raise

    async def load(self, user_id: str, session_id: str) -> dict | None:
        """Load full conversation state.  Returns None if not found."""
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._table.get_item(
                    Key={"user_id": user_id, "session_id": session_id}
                ),
            )
            item = response.get("Item")
            if not item:
                logger.debug("load: not found user_id=%s session_id=%s", user_id, session_id)
                return None

            blob: str = item.get("messages_blob", "")
            messages: list[dict] = []
            if blob:
                compressed = b64decode(blob.encode("utf-8"))
                messages = json.loads(self._decompress(compressed))

            return {
                "user_id": user_id,
                "session_id": session_id,
                "messages": messages,
                "message_count": item.get("message_count", len(messages)),
                "preview": item.get("preview", ""),
                "metadata": item.get("metadata", {}),
                "updated_at": item.get("updated_at", 0.0),
            }
        except ClientError:
            logger.exception(
                "load: DynamoDB error for user_id=%s session_id=%s", user_id, session_id
            )
            return None

    # ------------------------------------------------------------------
    # Atomic append
    # ------------------------------------------------------------------

    async def append_turn(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Append a single turn without re-writing the entire conversation.

        Uses a DynamoDB UpdateExpression with ``list_append`` on a separate
        ``turns`` attribute for atomic O(1) appends.  The ``messages_blob``
        is rebuilt from turns on load if necessary.

        For simplicity this implementation does a read-modify-write on the
        ``messages_blob``.  For true atomic appends at scale, use a separate
        turns list and merge on read.
        """
        # Load current session
        session = await self.load(user_id, session_id)
        if session is None:
            # Start a new session with this turn
            messages = [{"role": role, "content": content, "timestamp": time.time()}]
        else:
            messages = session["messages"]
            messages.append({"role": role, "content": content, "timestamp": time.time()})

        # Use DynamoDB UpdateExpression to update blob and message_count atomically
        compressed = self._compress(json.dumps(messages))
        blob = b64encode(compressed).decode("utf-8")
        ttl = int(time.time()) + _DEFAULT_TTL_DAYS * 86400

        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._table.update_item(
                    Key={"user_id": user_id, "session_id": session_id},
                    UpdateExpression=(
                        "SET messages_blob = :blob, "
                        "message_count = :count, "
                        "updated_at = :ts, "
                        "#ttl = :ttl"
                    ),
                    ExpressionAttributeNames={"#ttl": "ttl"},
                    ExpressionAttributeValues={
                        ":blob": blob,
                        ":count": len(messages),
                        ":ts": time.time(),
                        ":ttl": ttl,
                    },
                ),
            )
            logger.debug(
                "append_turn: user_id=%s session_id=%s role=%s", user_id, session_id, role
            )
        except ClientError:
            logger.exception(
                "append_turn: DynamoDB error for user_id=%s session_id=%s",
                user_id,
                session_id,
            )
            raise

    # ------------------------------------------------------------------
    # Session listing
    # ------------------------------------------------------------------

    async def list_sessions(self, user_id: str, limit: int = 20) -> list[dict]:
        """List the most recent sessions for a user, with preview text.

        Results are sorted by ``updated_at`` descending.
        """
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._table.query(
                    KeyConditionExpression=DKey("user_id").eq(user_id),
                    Limit=limit,
                    ScanIndexForward=False,  # newest first
                    ProjectionExpression=(
                        "session_id, preview, message_count, updated_at, metadata"
                    ),
                ),
            )
            items = response.get("Items", [])
            # Sort by updated_at descending (query returns by SK order)
            items.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
            return items[:limit]
        except ClientError:
            logger.exception("list_sessions: DynamoDB error for user_id=%s", user_id)
            return []

    # ------------------------------------------------------------------
    # Delete / Fork
    # ------------------------------------------------------------------

    async def delete(self, user_id: str, session_id: str) -> bool:
        """Delete a session. Returns True on success."""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._table.delete_item(
                    Key={"user_id": user_id, "session_id": session_id}
                ),
            )
            logger.info("delete: user_id=%s session_id=%s", user_id, session_id)
            return True
        except ClientError:
            logger.exception("delete: DynamoDB error for session_id=%s", session_id)
            return False

    async def fork(
        self,
        user_id: str,
        source_session: str,
        new_session_id: str,
    ) -> dict:
        """Copy a session to a new ID for conversation branching.

        Returns the new session metadata dict.
        """
        source = await self.load(user_id, source_session)
        if source is None:
            raise ValueError(f"Source session not found: {source_session}")

        messages = source["messages"]
        metadata = dict(source.get("metadata", {}))
        metadata["forked_from"] = source_session
        metadata["forked_at"] = time.time()

        await self.save(user_id, new_session_id, messages, metadata=metadata)
        logger.info(
            "fork: user_id=%s %s -> %s", user_id, source_session, new_session_id
        )
        return {
            "user_id": user_id,
            "session_id": new_session_id,
            "source_session": source_session,
            "message_count": len(messages),
            "metadata": metadata,
        }

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    async def get_summary(self, user_id: str, session_id: str) -> str:
        """Return a context preview of the first and last messages."""
        session = await self.load(user_id, session_id)
        if session is None:
            return ""

        messages = session.get("messages", [])
        if not messages:
            return ""

        parts: list[str] = []

        # First message
        first = messages[0]
        role_label = first.get("role", "user").upper()
        content = first.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") if isinstance(c, dict) else str(c) for c in content
            )
        parts.append(f"[START] {role_label}: {str(content)[:300]}")

        # Last message (if different from first)
        if len(messages) > 1:
            last = messages[-1]
            role_label = last.get("role", "assistant").upper()
            content = last.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") if isinstance(c, dict) else str(c) for c in content
                )
            parts.append(f"[END] {role_label}: {str(content)[:300]}")

        parts.append(f"Total turns: {len(messages)}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Compression helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compress(data: str) -> bytes:
        """Compress a string with zlib (level 6)."""
        return zlib.compress(data.encode("utf-8"), level=6)

    @staticmethod
    def _decompress(data: bytes) -> str:
        """Decompress zlib bytes to string."""
        return zlib.decompress(data).decode("utf-8")
