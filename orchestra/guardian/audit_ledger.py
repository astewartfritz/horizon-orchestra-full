"""Audit Ledger — Immutable HMAC-chained audit log.

Every significant action in Horizon Orchestra is recorded as an
:class:`AuditEvent` appended to the ledger.  Each event includes
the HMAC of the previous event, creating a cryptographic chain.
Any tampering (insertion, deletion, modification) breaks the chain
and is detectable via :meth:`AuditLedger.verify_chain`.

Design choices:
    * ``hashlib.blake2b`` — fast (3× SHA-256), 256-bit security, keyed
      MAC mode built-in.
    * Append-only in-memory list backed by optional JSONL flush.
    * Async-safe: all mutations go through an ``asyncio.Lock``.
    * Zero external dependencies (stdlib only).

Beyond NemoClaw: NemoClaw has a basic per-action audit trail with no
tamper detection.  This system provides a cryptographic hash chain,
chain verification, JSONL/CSV export, rich filtering, and aggregate
statistics.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "AuditEvent",
    "AuditLedger",
    "AuditStats",
]

log = logging.getLogger("orchestra.guardian.audit_ledger")

_GENESIS_HASH = "0" * 64  # sentinel for the first entry


# ---------------------------------------------------------------------------
# AuditEvent
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AuditEvent:
    """A single entry in the immutable audit ledger.

    Attributes
    ----------
    event_id : str
        Unique identifier (UUID-4).
    sequence : int
        Monotonically increasing sequence number.
    timestamp : float
        ``time.time()`` when the event was created.
    agent_id : str
        ID of the agent that triggered the event.
    event_type : str
        Category: ``inference_call``, ``tool_call``, ``policy_check``,
        ``handoff``, ``violation``, ``grant``, ``revoke``, ``system``.
    resource : str
        Target of the action (e.g. model name, tool name, file path).
    action : str
        Verb (e.g. ``call``, ``read``, ``write``, ``deny``).
    result : str
        Outcome: ``allow``, ``deny``, ``error``, ``timeout``.
    metadata : dict
        Arbitrary structured data about the event.
    prev_hash : str
        BLAKE2b HMAC of the *previous* event in the chain.
    signature : str
        BLAKE2b HMAC of *this* event (computed over all other fields).
    """

    event_id: str
    sequence: int
    timestamp: float
    agent_id: str
    event_type: str
    resource: str
    action: str
    result: str
    metadata: dict[str, Any]
    prev_hash: str
    signature: str


# ---------------------------------------------------------------------------
# AuditStats
# ---------------------------------------------------------------------------

@dataclass
class AuditStats:
    """Aggregate statistics over the ledger."""

    total_events: int = 0
    events_by_type: dict[str, int] = field(default_factory=dict)
    events_by_agent: dict[str, int] = field(default_factory=dict)
    events_by_result: dict[str, int] = field(default_factory=dict)
    violations: int = 0
    first_event_ts: Optional[float] = None
    last_event_ts: Optional[float] = None
    chain_valid: Optional[bool] = None


# ---------------------------------------------------------------------------
# AuditLedger
# ---------------------------------------------------------------------------

class AuditLedger:
    """Immutable, HMAC-chained audit log for every agent action.

    Each entry includes the HMAC of the previous entry, creating a
    cryptographic chain.  Any tampering breaks the chain and is
    detectable via :meth:`verify_chain`.

    Parameters
    ----------
    hmac_key : bytes
        Secret key used for BLAKE2b HMAC.  Defaults to a random 32-byte
        key generated at instantiation (suitable for single-process use).
    flush_path : str, optional
        If set, events are also flushed as JSONL to this file.
    flush_interval : int
        Number of events between auto-flushes (default 100).
    """

    def __init__(
        self,
        hmac_key: Optional[bytes] = None,
        flush_path: Optional[str] = None,
        flush_interval: int = 100,
    ) -> None:
        self._key: bytes = hmac_key or os.urandom(32)
        self._events: list[AuditEvent] = []
        self._sequence: int = 0
        self._lock = asyncio.Lock()
        self._flush_path = flush_path
        self._flush_interval = flush_interval
        self._unflushed: int = 0

    # -- HMAC helpers -------------------------------------------------------

    def _hmac(self, data: bytes) -> str:
        """Compute a BLAKE2b keyed MAC and return its hex digest."""
        h = hashlib.blake2b(data, key=self._key, digest_size=32)
        return h.hexdigest()

    def _event_bytes(self, event: AuditEvent) -> bytes:
        """Canonical byte representation of an event (excluding signature)."""
        parts = (
            event.event_id,
            str(event.sequence),
            f"{event.timestamp:.6f}",
            event.agent_id,
            event.event_type,
            event.resource,
            event.action,
            event.result,
            json.dumps(event.metadata, sort_keys=True, default=str),
            event.prev_hash,
        )
        return "|".join(parts).encode("utf-8")

    def _compute_signature(self, event: AuditEvent) -> str:
        """Compute the HMAC signature for *event*."""
        return self._hmac(self._event_bytes(event))

    # -- record -------------------------------------------------------------

    async def record(
        self,
        agent_id: str,
        event_type: str,
        resource: str,
        action: str,
        result: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        """Append a new event to the ledger and return it.

        The event is signed with a BLAKE2b HMAC that chains to the
        previous event, making the ledger tamper-evident.
        """
        async with self._lock:
            self._sequence += 1
            prev_hash = (
                self._events[-1].signature if self._events else _GENESIS_HASH
            )

            event = AuditEvent(
                event_id=uuid.uuid4().hex,
                sequence=self._sequence,
                timestamp=time.time(),
                agent_id=agent_id,
                event_type=event_type,
                resource=resource,
                action=action,
                result=result,
                metadata=metadata or {},
                prev_hash=prev_hash,
                signature="",  # computed below
            )
            event.signature = self._compute_signature(event)
            self._events.append(event)

            self._unflushed += 1
            if self._flush_path and self._unflushed >= self._flush_interval:
                await self._flush_to_disk()

        return event

    # -- query --------------------------------------------------------------

    async def get_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        result: Optional[str] = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Return events matching the given filters (most recent first)."""
        out: list[AuditEvent] = []
        for ev in reversed(self._events):
            if agent_id and ev.agent_id != agent_id:
                continue
            if event_type and ev.event_type != event_type:
                continue
            if since and ev.timestamp < since:
                continue
            if until and ev.timestamp > until:
                continue
            if result and ev.result != result:
                continue
            out.append(ev)
            if len(out) >= limit:
                break
        return out

    async def get_violations(
        self,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Return violation events (denied actions)."""
        return await self.get_events(
            event_type="violation", since=since, limit=limit
        )

    # -- chain verification -------------------------------------------------

    async def verify_chain(self) -> bool:
        """Verify the HMAC chain from genesis to the latest event.

        Returns ``True`` if every event's signature is correct and
        each ``prev_hash`` matches the preceding event's signature.
        Returns ``False`` (and logs details) if any tampering is detected.
        """
        if not self._events:
            return True

        expected_prev = _GENESIS_HASH
        for i, event in enumerate(self._events):
            # Check prev_hash linkage
            if event.prev_hash != expected_prev:
                log.error(
                    "Chain broken at seq=%d: expected prev_hash=%s, got %s",
                    event.sequence, expected_prev, event.prev_hash,
                )
                return False

            # Check signature
            computed = self._compute_signature(event)
            if event.signature != computed:
                log.error(
                    "Signature mismatch at seq=%d: expected=%s, got=%s",
                    event.sequence, computed, event.signature,
                )
                return False

            expected_prev = event.signature

        log.info("Chain verified: %d events, integrity OK", len(self._events))
        return True

    # -- export -------------------------------------------------------------

    async def export(self, fmt: str = "jsonl", path: Optional[str] = None) -> str:
        """Export the ledger to a file or return as a string.

        Parameters
        ----------
        fmt : str
            ``"jsonl"`` (default) or ``"csv"``.
        path : str, optional
            If given, write to this file and return the path.
            Otherwise return the serialised string.
        """
        if fmt == "jsonl":
            content = self._to_jsonl()
        elif fmt == "csv":
            content = self._to_csv()
        else:
            raise ValueError(f"Unsupported format: {fmt!r}")

        if path:
            async with asyncio.Lock():
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
            return path
        return content

    def _to_jsonl(self) -> str:
        lines: list[str] = []
        for ev in self._events:
            obj = {
                "event_id": ev.event_id,
                "sequence": ev.sequence,
                "timestamp": ev.timestamp,
                "agent_id": ev.agent_id,
                "event_type": ev.event_type,
                "resource": ev.resource,
                "action": ev.action,
                "result": ev.result,
                "metadata": ev.metadata,
                "prev_hash": ev.prev_hash,
                "signature": ev.signature,
            }
            lines.append(json.dumps(obj, default=str))
        return "\n".join(lines) + ("\n" if lines else "")

    def _to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "event_id", "sequence", "timestamp", "agent_id",
            "event_type", "resource", "action", "result",
            "metadata", "prev_hash", "signature",
        ])
        for ev in self._events:
            writer.writerow([
                ev.event_id, ev.sequence, ev.timestamp, ev.agent_id,
                ev.event_type, ev.resource, ev.action, ev.result,
                json.dumps(ev.metadata, default=str),
                ev.prev_hash, ev.signature,
            ])
        return buf.getvalue()

    # -- statistics ---------------------------------------------------------

    def get_stats(self) -> AuditStats:
        """Return aggregate statistics over the ledger."""
        stats = AuditStats(total_events=len(self._events))
        for ev in self._events:
            stats.events_by_type[ev.event_type] = (
                stats.events_by_type.get(ev.event_type, 0) + 1
            )
            stats.events_by_agent[ev.agent_id] = (
                stats.events_by_agent.get(ev.agent_id, 0) + 1
            )
            stats.events_by_result[ev.result] = (
                stats.events_by_result.get(ev.result, 0) + 1
            )
            if ev.event_type == "violation":
                stats.violations += 1
        if self._events:
            stats.first_event_ts = self._events[0].timestamp
            stats.last_event_ts = self._events[-1].timestamp
        return stats

    # -- flush --------------------------------------------------------------

    async def _flush_to_disk(self) -> None:
        """Append unflushed events to the JSONL file on disk."""
        if not self._flush_path:
            return
        start = len(self._events) - self._unflushed
        events_to_flush = self._events[start:]
        try:
            with open(self._flush_path, "a", encoding="utf-8") as fh:
                for ev in events_to_flush:
                    obj = {
                        "event_id": ev.event_id,
                        "sequence": ev.sequence,
                        "timestamp": ev.timestamp,
                        "agent_id": ev.agent_id,
                        "event_type": ev.event_type,
                        "resource": ev.resource,
                        "action": ev.action,
                        "result": ev.result,
                        "metadata": ev.metadata,
                        "prev_hash": ev.prev_hash,
                        "signature": ev.signature,
                    }
                    fh.write(json.dumps(obj, default=str) + "\n")
            self._unflushed = 0
        except OSError:
            log.exception("Failed to flush audit ledger to %s", self._flush_path)

    async def flush(self) -> None:
        """Force-flush all pending events to disk."""
        async with self._lock:
            await self._flush_to_disk()

    # -- misc ---------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._events)

    def __repr__(self) -> str:
        return f"<AuditLedger events={len(self._events)} seq={self._sequence}>"
