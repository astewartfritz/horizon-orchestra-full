"""SIEM log export for Horizon Orchestra.

Structured security-event export compatible with every major SIEM
platform: Splunk HEC, Elastic Common Schema, CEF (ArcSight/QRadar),
LEEF (IBM QRadar), and Syslog RFC 5424.

Usage::

    from orchestra.observability.siem import SIEMExporter, SIEMEvent, SIEMFormat

    exporter = SIEMExporter(
        format=SIEMFormat.SPLUNK_HEC,
        destination_url="https://splunk.corp.example.com:8088",
        api_key="HEC-TOKEN",
    )
    exporter.emit(SIEMEvent(
        severity="HIGH",
        event_type="auth_login_failure",
        src_ip="10.0.0.42",
        user_id="alice",
        org_id="acme-corp",
        action="login",
        result="failure",
        details={"reason": "invalid_password"},
    ))
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence

__all__ = [
    "SIEMFormat",
    "SIEMEvent",
    "SIEMExporter",
    "ORCHESTRA_EVENT_TYPES",
]

logger = logging.getLogger("orchestra.observability.siem")


# ── Format enum ───────────────────────────────────────────────────────

class SIEMFormat(str, Enum):
    """Supported SIEM log export formats."""
    SPLUNK_HEC = "splunk_hec"
    ECS = "ecs"
    CEF = "cef"
    LEEF = "leef"
    SYSLOG = "syslog"


# ── Severity mapping ─────────────────────────────────────────────────

class Severity(str, Enum):
    """Standard severity levels (aligned across all formats)."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    INFO = "INFO"


_CEF_SEVERITY: Dict[str, int] = {
    "INFO": 1,
    "LOW": 3,
    "MEDIUM": 5,
    "HIGH": 7,
    "CRITICAL": 10,
}

_SYSLOG_SEVERITY: Dict[str, int] = {
    "INFO": 6,       # informational
    "LOW": 5,        # notice
    "MEDIUM": 4,     # warning
    "HIGH": 3,       # error
    "CRITICAL": 2,   # critical
}


# ── Pre-built event types ────────────────────────────────────────────

ORCHESTRA_EVENT_TYPES: Dict[str, str] = {
    "auth_login_success": "User authenticated successfully",
    "auth_login_failure": "Authentication attempt failed",
    "api_key_created": "New API key provisioned",
    "api_key_rotated": "API key rotated",
    "api_key_deleted": "API key revoked / deleted",
    "agent_spawned": "Agent instance started",
    "agent_completed": "Agent task completed successfully",
    "agent_failed": "Agent task failed",
    "tool_call_blocked": "Tool invocation blocked by policy engine",
    "policy_violation": "Security policy violation detected",
    "code_guard_blocked": "CodeGuard blocked a dangerous code submission",
    "ingestion_gate_rejected": "Ingestion gate rejected input",
    "rate_limit_exceeded": "Request rate limit exceeded",
    "data_export_gdpr": "GDPR data-export request fulfilled",
    "phi_accessed": "Protected Health Information accessed",
    "admin_action": "Administrative action performed",
}


# ── Event dataclass ──────────────────────────────────────────────────

@dataclass
class SIEMEvent:
    """A single security-relevant event for SIEM export."""

    severity: str = "INFO"
    event_type: str = "generic"
    src_ip: str = ""
    user_id: str = ""
    org_id: str = ""
    action: str = ""
    result: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    hostname: str = field(default_factory=socket.gethostname)
    service: str = "horizon-orchestra"

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


# ── SIEM Exporter ────────────────────────────────────────────────────

class SIEMExporter:
    """Batched, async-safe SIEM event exporter.

    Parameters
    ----------
    format : SIEMFormat
        Target SIEM log format.
    destination_url : str
        HTTP(S) endpoint to ship events to.
    api_key : str
        Token / API key for authenticating with the SIEM backend.
    batch_size : int
        Max events per flush batch.
    flush_interval : float
        Seconds between automatic background flushes.
    """

    def __init__(
        self,
        format: SIEMFormat = SIEMFormat.SPLUNK_HEC,
        destination_url: str = "",
        api_key: str = "",
        batch_size: int = 100,
        flush_interval: float = 5.0,
    ) -> None:
        self.format = SIEMFormat(format) if isinstance(format, str) else format
        self.destination_url = destination_url
        self.api_key = api_key
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        self._queue: Deque[SIEMEvent] = deque()
        self._lock = threading.Lock()
        self._flush_task: Optional[asyncio.Task[None]] = None

        # Stats
        self._total_emitted: int = 0
        self._total_flushed: int = 0
        self._total_errors: int = 0
        self._last_flush_ts: Optional[float] = None

    # ── Public API ────────────────────────────────────────────────────

    def emit(self, event: SIEMEvent) -> None:
        """Queue a single SIEM event for batched delivery."""
        with self._lock:
            self._queue.append(event)
            self._total_emitted += 1

    async def flush(self) -> int:
        """Flush the current batch to the SIEM backend.

        Returns the number of events shipped in this flush.
        """
        with self._lock:
            batch: List[SIEMEvent] = []
            while self._queue and len(batch) < self.batch_size:
                batch.append(self._queue.popleft())

        if not batch:
            return 0

        count = len(batch)
        try:
            await self._send_batch(batch)
            with self._lock:
                self._total_flushed += count
                self._last_flush_ts = time.time()
        except Exception as exc:
            logger.error("SIEM flush failed (%d events): %s", count, exc)
            with self._lock:
                self._total_errors += count
                # Re-queue on failure (best effort)
                for ev in reversed(batch):
                    self._queue.appendleft(ev)
        return count

    def start_background_flush(self, interval_seconds: float = 5.0) -> None:
        """Start an ``asyncio.Task`` that periodically flushes the queue.

        Safe to call from a running event loop.  The task is stored so it
        won't be garbage-collected.
        """
        self.flush_interval = interval_seconds

        async def _loop() -> None:
            while True:
                await asyncio.sleep(self.flush_interval)
                await self.flush()

        try:
            loop = asyncio.get_running_loop()
            self._flush_task = loop.create_task(_loop())
        except RuntimeError:
            logger.warning("No running event loop; background flush not started")

    def get_stats(self) -> Dict[str, Any]:
        """Return current exporter statistics."""
        with self._lock:
            return {
                "format": self.format.value,
                "destination_url": self.destination_url,
                "queue_depth": len(self._queue),
                "total_emitted": self._total_emitted,
                "total_flushed": self._total_flushed,
                "total_errors": self._total_errors,
                "last_flush_ts": self._last_flush_ts,
            }

    # ── Format methods ────────────────────────────────────────────────

    def format_splunk_hec(self, event: SIEMEvent) -> Dict[str, Any]:
        """Format a single event as a Splunk HEC JSON payload."""
        return {
            "time": _epoch_seconds(event.timestamp),
            "host": event.hostname,
            "source": event.service,
            "sourcetype": "orchestra:security",
            "index": "main",
            "event": {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "severity": event.severity,
                "src_ip": event.src_ip,
                "user_id": event.user_id,
                "org_id": event.org_id,
                "action": event.action,
                "result": event.result,
                **event.details,
            },
        }

    def format_ecs(self, event: SIEMEvent) -> Dict[str, Any]:
        """Format event as Elastic Common Schema (ECS) document."""
        return {
            "@timestamp": event.timestamp,
            "ecs": {"version": "8.11.0"},
            "event": {
                "id": event.event_id,
                "kind": "event",
                "category": ["authentication"] if "auth" in event.event_type else ["process"],
                "type": [event.event_type],
                "action": event.action,
                "outcome": event.result,
                "severity": _CEF_SEVERITY.get(event.severity, 1),
                "created": event.timestamp,
            },
            "source": {
                "ip": event.src_ip,
            },
            "user": {
                "id": event.user_id,
            },
            "organization": {
                "id": event.org_id,
            },
            "host": {
                "hostname": event.hostname,
            },
            "service": {
                "name": event.service,
                "type": "orchestra",
            },
            "labels": event.details,
        }

    def format_cef(self, event: SIEMEvent) -> str:
        """Format event as CEF (Common Event Format) for ArcSight / QRadar.

        Format: ``CEF:0|Vendor|Product|Version|SignatureID|Name|Severity|Extensions``
        """
        severity = _CEF_SEVERITY.get(event.severity, 1)
        extensions = (
            f"src={event.src_ip} "
            f"suser={event.user_id} "
            f"cs1={event.org_id} "
            f"cs1Label=org_id "
            f"act={event.action} "
            f"outcome={event.result} "
            f"rt={_epoch_millis(event.timestamp)} "
            f"msg={_cef_escape(json.dumps(event.details))}"
        )
        return (
            f"CEF:0|HorizonOrchestra|Orchestra|1.0"
            f"|{event.event_type}|{event.event_type}|{severity}|{extensions}"
        )

    def format_leef(self, event: SIEMEvent) -> str:
        """Format event as LEEF 2.0 (Log Event Extended Format) for IBM QRadar.

        Format: ``LEEF:2.0|Vendor|Product|Version|EventID|<tab-separated kv>``
        """
        kvs = (
            f"devTime={event.timestamp}\t"
            f"src={event.src_ip}\t"
            f"usrName={event.user_id}\t"
            f"orgId={event.org_id}\t"
            f"action={event.action}\t"
            f"result={event.result}\t"
            f"sev={_CEF_SEVERITY.get(event.severity, 1)}\t"
            f"msg={json.dumps(event.details)}"
        )
        return (
            f"LEEF:2.0|HorizonOrchestra|Orchestra|1.0|{event.event_type}|{kvs}"
        )

    def format_syslog(self, event: SIEMEvent) -> str:
        """Format event as RFC 5424 syslog message.

        ``<PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID [SD] MSG``
        """
        severity = _SYSLOG_SEVERITY.get(event.severity, 6)
        facility = 1  # user-level
        pri = facility * 8 + severity
        structured_data = (
            f'[orchestra@49876 eventType="{event.event_type}" '
            f'userId="{event.user_id}" orgId="{event.org_id}" '
            f'srcIp="{event.src_ip}" action="{event.action}" '
            f'result="{event.result}"]'
        )
        msg = json.dumps(event.details) if event.details else "-"
        return (
            f"<{pri}>1 {event.timestamp} {event.hostname} "
            f"{event.service} - {event.event_id} {structured_data} {msg}"
        )

    # ── Internal delivery ─────────────────────────────────────────────

    async def _send_batch(self, batch: List[SIEMEvent]) -> None:
        """Ship a batch of events to the configured destination."""
        if not self.destination_url:
            logger.debug("SIEM destination not configured; dropping %d events", len(batch))
            return

        payloads = [self._format_one(ev) for ev in batch]

        try:
            import httpx  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("httpx not installed; SIEM events not shipped")
            return

        headers = self._build_headers()

        if self.format == SIEMFormat.SPLUNK_HEC:
            body = "\n".join(json.dumps(p) for p in payloads)
            content_type = "application/json"
        elif self.format in (SIEMFormat.CEF, SIEMFormat.LEEF, SIEMFormat.SYSLOG):
            body = "\n".join(str(p) for p in payloads)
            content_type = "text/plain"
        else:
            body = json.dumps(payloads)
            content_type = "application/json"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self.destination_url,
                content=body,
                headers={**headers, "Content-Type": content_type},
            )
            resp.raise_for_status()

    def _format_one(self, event: SIEMEvent) -> Any:
        """Route event to the correct formatter."""
        if self.format == SIEMFormat.SPLUNK_HEC:
            return self.format_splunk_hec(event)
        elif self.format == SIEMFormat.ECS:
            return self.format_ecs(event)
        elif self.format == SIEMFormat.CEF:
            return self.format_cef(event)
        elif self.format == SIEMFormat.LEEF:
            return self.format_leef(event)
        elif self.format == SIEMFormat.SYSLOG:
            return self.format_syslog(event)
        else:
            return asdict(event)

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers for the SIEM backend."""
        headers: Dict[str, str] = {}
        if self.format == SIEMFormat.SPLUNK_HEC:
            headers["Authorization"] = f"Splunk {self.api_key}"
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


# ── Helpers ───────────────────────────────────────────────────────────

def _epoch_seconds(iso_ts: Optional[str]) -> float:
    """Convert ISO-8601 timestamp to Unix epoch seconds."""
    if iso_ts is None:
        return time.time()
    try:
        dt = datetime.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return time.time()


def _epoch_millis(iso_ts: Optional[str]) -> int:
    """Convert ISO-8601 timestamp to Unix epoch milliseconds."""
    return int(_epoch_seconds(iso_ts) * 1000)


def _cef_escape(value: str) -> str:
    """Escape characters special to CEF format."""
    return (
        value
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("=", "\\=")
        .replace("\n", "\\n")
    )


# ── Convenience factory ──────────────────────────────────────────────

def create_event(
    event_type: str,
    *,
    severity: str = "INFO",
    src_ip: str = "",
    user_id: str = "",
    org_id: str = "",
    action: str = "",
    result: str = "success",
    details: Optional[Dict[str, Any]] = None,
) -> SIEMEvent:
    """Factory for creating :class:`SIEMEvent` instances with defaults."""
    return SIEMEvent(
        severity=severity,
        event_type=event_type,
        src_ip=src_ip,
        user_id=user_id,
        org_id=org_id,
        action=action or event_type,
        result=result,
        details=details or {},
    )
