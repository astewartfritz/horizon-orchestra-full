"""Trace context propagation — W3C traceparent header support."""

from __future__ import annotations

import re
import uuid

# W3C traceparent format: "00-{trace_id}-{span_id}-{flags}"
# trace_id: 32 hex chars, span_id: 16 hex chars, flags: 2 hex chars
_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def generate_trace_id() -> str:
    """Generate a 32-char hex trace ID."""
    return uuid.uuid4().hex + uuid.uuid4().hex


def generate_span_id() -> str:
    """Generate a 16-char hex span ID."""
    return uuid.uuid4().hex[:16]


def inject_traceparent(trace_id: str, span_id: str, sampled: bool = True) -> str:
    """Create a W3C traceparent header value from trace/span IDs."""
    flags = "01" if sampled else "00"
    # Pad trace_id to 32 chars
    trace_id = trace_id.rjust(32, "0")[:32]
    span_id = span_id.rjust(16, "0")[:16]
    return f"00-{trace_id}-{span_id}-{flags}"


def extract_traceparent(header: str) -> dict[str, str] | None:
    """Parse a W3C traceparent header into trace_id, span_id, flags.

    Returns None if the header is invalid.
    """
    if not header:
        return None
    match = _TRACEPARENT_RE.match(header.strip())
    if not match:
        return None
    return {
        "trace_id": match.group(1),
        "span_id": match.group(2),
        "flags": match.group(3),
    }


# ── Tracestate support ────────────────────────────────

def inject_tracestate(entries: dict[str, str]) -> str:
    """Create a tracestate header from key=value pairs."""
    return ",".join(f"{k}={v}" for k, v in entries.items())


def extract_tracestate(header: str) -> dict[str, str]:
    """Parse a tracestate header into key=value pairs."""
    if not header:
        return {}
    result = {}
    for entry in header.split(","):
        entry = entry.strip()
        if "=" in entry:
            k, v = entry.split("=", 1)
            result[k.strip()] = v.strip()
    return result


class TracePropagator:
    """Handles trace context injection and extraction for various formats."""

    @staticmethod
    def inject(headers: dict[str, str], trace_id: str = "",
               span_id: str = "", sampled: bool = True) -> dict[str, str]:
        """Inject trace context into a headers dict."""
        headers["traceparent"] = inject_traceparent(trace_id, span_id, sampled)
        return headers

    @staticmethod
    def extract(headers: dict[str, str]) -> dict[str, str]:
        """Extract trace context from a headers dict."""
        result = {}
        traceparent = headers.get("traceparent", "")
        parsed = extract_traceparent(traceparent)
        if parsed:
            result.update(parsed)
        tracestate = headers.get("tracestate", "")
        if tracestate:
            result["tracestate"] = tracestate
        return result

    @staticmethod
    def format_otlp(trace_id: str, span_id: str) -> tuple[bytes, bytes]:
        """Format trace_id and span_id as bytes for OTLP export."""
        trace_bytes = bytes.fromhex(trace_id.rjust(32, "0"))
        span_bytes = bytes.fromhex(span_id.rjust(16, "0"))
        return trace_bytes, span_bytes
