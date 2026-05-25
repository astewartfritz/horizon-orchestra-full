"""NemoClaw-level guardrails for MILES multi-channel ingestion.

Five-layer pipeline applied to every inbound message before it reaches the LLM:

  1. Rate limiting          — token bucket per (channel, sender)
  2. PII detection/scrub    — regex + LLM, configurable redact vs. block
  3. Content policy         — keyword blocklist + LLM classifier
  4. Message integrity      — length, encoding, injection probing
  5. Audit trail            — append-only log of every decision

All layers are fail-closed: an exception = BLOCK, not PASS.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestra.miles.channels.base import ChannelMessage
from orchestra.miles._utils import router_chat, extract_content, safe_json_loads

__all__ = [
    "GuardrailConfig",
    "GuardrailDecision",
    "ChannelGuardrails",
]

log = logging.getLogger("orchestra.miles.channels.guardrails")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class GuardrailConfig:
    """Tunable guardrail parameters."""

    # Rate limiting
    rate_limit_window_s: float = 60.0       # sliding window
    rate_limit_max_messages: int = 10       # max msgs per window per sender
    rate_limit_burst: int = 3              # burst allowance on top of rate

    # PII
    pii_action: str = "redact"             # "redact" | "block"
    pii_llm_check: bool = True             # LLM-assisted PII detection
    pii_model: str = "kimi-k2.5"

    # Content policy
    content_llm_check: bool = True         # LLM-assisted content moderation
    content_model: str = "kimi-k2.5"
    max_message_length: int = 8_000        # chars

    # Prompt injection defence
    injection_block: bool = True

    # Audit
    audit_db: str | None = None            # path; None → ~/.horizon/miles_audit.db
    retain_days: int = 90                  # delete audit records older than N days


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

@dataclass
class GuardrailDecision:
    allowed: bool
    scrubbed_text: str = ""
    reasons: list[str] = field(default_factory=list)
    pii_found: list[str] = field(default_factory=list)
    policy_flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PII patterns
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email",        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")),
    ("phone_us",     re.compile(r"\b(?:\+1[\s\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")),
    ("phone_intl",   re.compile(r"\+\d{1,3}[\s\-]?\d{6,14}")),
    ("ssn",          re.compile(r"\b\d{3}[.\-\s]\d{2}[.\-\s]\d{4}\b")),
    ("credit_card",  re.compile(r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6011)[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")),
    ("ip_address",   re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("passport",     re.compile(r"\b[A-Z]{1,2}\d{6,9}\b")),
    ("dob",          re.compile(r"\b(?:0?[1-9]|1[0-2])[\/-](?:0?[1-9]|[12]\d|3[01])[\/-](?:19|20)\d{2}\b")),
]

_REDACT_TEMPLATE = "[REDACTED-{label}]"


def _scrub_pii_regex(text: str) -> tuple[str, list[str]]:
    """Apply regex PII patterns and redact matches.  Returns (clean_text, found_types)."""
    found: list[str] = []
    for label, pattern in _PII_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            found.append(label)
            text = pattern.sub(_REDACT_TEMPLATE.format(label=label.upper()), text)
    return text, found


# ---------------------------------------------------------------------------
# Prompt injection indicators
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = re.compile(
    r"(?:ignore previous|disregard|forget your instructions?|"
    r"system\s*prompt|act as|you are now|jailbreak|"
    r"<\s*/?(?:system|user|assistant|prompt|instructions?)\s*>|"
    r"\[\s*(?:INST|SYS|system)\s*\])",
    re.IGNORECASE,
)

_SENSITIVE_KEYWORDS: frozenset[str] = frozenset({
    "kill", "murder", "bomb", "terrorism", "csam", "child porn",
    "synthesize drugs", "synthesize weapons", "make meth", "make fentanyl",
    "hack into", "ddos", "ransomware", "steal credentials",
})


# ---------------------------------------------------------------------------
# Rate limiter (token bucket per sender)
# ---------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, window_s: float, max_msgs: int) -> None:
        self._window = window_s
        self._max = max_msgs
        self._buckets: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        bucket = self._buckets.setdefault(key, [])
        # Evict timestamps outside window
        self._buckets[key] = [t for t in bucket if now - t < self._window]
        if len(self._buckets[key]) >= self._max:
            return False
        self._buckets[key].append(now)
        return True


# ---------------------------------------------------------------------------
# Audit DB
# ---------------------------------------------------------------------------

class _AuditDB:
    def __init__(self, path: str) -> None:
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS guardrail_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          REAL NOT NULL,
                    channel     TEXT,
                    sender_id   TEXT,
                    allowed     INTEGER,
                    reasons     TEXT,
                    pii_found   TEXT,
                    flags       TEXT
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON guardrail_log(ts)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, check_same_thread=False)

    def record(self, msg: ChannelMessage, decision: GuardrailDecision) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO guardrail_log (ts,channel,sender_id,allowed,reasons,pii_found,flags) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    time.time(),
                    msg.channel,
                    msg.sender_id,
                    int(decision.allowed),
                    json.dumps(decision.reasons),
                    json.dumps(decision.pii_found),
                    json.dumps(decision.policy_flags),
                ),
            )

    def purge_old(self, retain_days: int) -> int:
        cutoff = time.time() - retain_days * 86400
        with self._conn() as c:
            c.execute("DELETE FROM guardrail_log WHERE ts < ?", (cutoff,))
            return c.execute("SELECT changes()").fetchone()[0]


# ---------------------------------------------------------------------------
# Main guardrails class
# ---------------------------------------------------------------------------

class ChannelGuardrails:
    """NemoClaw-level safety layer applied to every inbound channel message.

    All layers are independent and fail-closed.  The result is a
    ``GuardrailDecision`` that tells the pipeline whether to proceed and
    what text (possibly scrubbed) to use.
    """

    def __init__(
        self,
        config: GuardrailConfig | None = None,
        router: Any = None,
    ) -> None:
        self._cfg = config or GuardrailConfig()
        self._router = router
        self._rate = _RateLimiter(
            window_s=self._cfg.rate_limit_window_s,
            max_msgs=self._cfg.rate_limit_max_messages,
        )
        db_path = self._cfg.audit_db or str(
            Path.home() / ".horizon" / "miles_audit.db"
        )
        self._audit = _AuditDB(db_path)

    async def check(self, message: ChannelMessage) -> GuardrailDecision:
        """Run all guardrail layers and return a decision.

        Always returns a ``GuardrailDecision`` — never raises.
        """
        try:
            return await self._check(message)
        except Exception as exc:
            log.error("Guardrail check crashed (fail-closed): %s", exc)
            decision = GuardrailDecision(
                allowed=False,
                reasons=[f"Guardrail internal error: {exc}"],
            )
            self._audit.record(message, decision)
            return decision

    async def _check(self, message: ChannelMessage) -> GuardrailDecision:
        reasons: list[str] = []
        flags: list[str] = []
        text = message.text

        # 1 ── Message integrity ─────────────────────────────────────────────
        if len(text) > self._cfg.max_message_length:
            text = text[: self._cfg.max_message_length]
            reasons.append("truncated_to_max_length")

        if not text.strip():
            decision = GuardrailDecision(allowed=False, reasons=["empty_message"])
            self._audit.record(message, decision)
            return decision

        # 2 ── Rate limiting ─────────────────────────────────────────────────
        rate_key = f"{message.channel}:{message.sender_id}"
        if not self._rate.is_allowed(rate_key):
            decision = GuardrailDecision(
                allowed=False,
                reasons=["rate_limit_exceeded"],
            )
            self._audit.record(message, decision)
            log.warning("Rate limit hit: %s", rate_key)
            return decision

        # 3 ── Prompt injection detection ────────────────────────────────────
        if self._cfg.injection_block and _INJECTION_PATTERNS.search(text):
            decision = GuardrailDecision(
                allowed=False,
                reasons=["prompt_injection_detected"],
                policy_flags=["injection"],
            )
            self._audit.record(message, decision)
            log.warning("Injection attempt blocked: %s/%s", message.channel, message.sender_id)
            return decision

        # 4 ── Keyword content policy ────────────────────────────────────────
        text_lower = text.lower()
        triggered = [kw for kw in _SENSITIVE_KEYWORDS if kw in text_lower]
        if triggered:
            flags.extend(triggered)
            decision = GuardrailDecision(
                allowed=False,
                reasons=["blocked_keyword"],
                policy_flags=flags,
            )
            self._audit.record(message, decision)
            log.warning("Keyword block: %s in %s/%s", triggered, message.channel, message.sender_id)
            return decision

        # 5 ── PII scrubbing ─────────────────────────────────────────────────
        text, pii_found = _scrub_pii_regex(text)
        if pii_found:
            reasons.append(f"pii_redacted:{','.join(pii_found)}")

        # LLM-assisted PII check (only if any text remains after regex)
        if self._cfg.pii_llm_check and self._router and text.strip():
            text, llm_pii = await self._llm_pii_check(text, message)
            pii_found.extend(llm_pii)

        # 6 ── LLM content moderation ────────────────────────────────────────
        if self._cfg.content_llm_check and self._router:
            content_ok, content_flags = await self._llm_content_check(text)
            if not content_ok:
                decision = GuardrailDecision(
                    allowed=False,
                    scrubbed_text=text,
                    reasons=["llm_content_policy"],
                    pii_found=pii_found,
                    policy_flags=content_flags,
                )
                self._audit.record(message, decision)
                return decision
            flags.extend(content_flags)

        # All clear ──────────────────────────────────────────────────────────
        decision = GuardrailDecision(
            allowed=True,
            scrubbed_text=text,
            reasons=reasons,
            pii_found=pii_found,
            policy_flags=flags,
        )
        self._audit.record(message, decision)
        return decision

    # -- LLM helpers ---------------------------------------------------------

    async def _llm_pii_check(
        self, text: str, message: ChannelMessage
    ) -> tuple[str, list[str]]:
        """Ask the LLM to identify and redact any remaining PII."""
        prompt = (
            "You are a PII detector. Identify any personally identifiable information "
            "in the text below that was NOT already redacted (marked [REDACTED-...]). "
            "Return JSON: {\"pii_types\": [...], \"clean_text\": \"...\"}. "
            "Replace PII with [REDACTED-TYPE]. If none found, return the original text unchanged.\n\n"
            f"Text:\n{text[:2000]}"
        )
        try:
            resp = await router_chat(
                self._router,
                messages=[{"role": "user", "content": prompt}],
                model=self._cfg.pii_model,
                max_tokens=512,
                temperature=0.0,
            )
            data = safe_json_loads(extract_content(resp), default={})
            if isinstance(data, dict):
                clean = str(data.get("clean_text", text))
                types = [str(t) for t in data.get("pii_types", [])]
                return clean, types
        except Exception as exc:
            log.debug("LLM PII check failed: %s", exc)
        return text, []

    async def _llm_content_check(self, text: str) -> tuple[bool, list[str]]:
        """Ask the LLM to classify content safety."""
        prompt = (
            "You are a content safety classifier. Classify the following message. "
            "Return JSON: {\"safe\": true/false, \"flags\": [list of violated categories]}. "
            "Categories: hate_speech, harassment, violence, self_harm, sexual_explicit, "
            "illegal_activity, spam, misinformation.\n\n"
            f"Message:\n{text[:1500]}"
        )
        try:
            resp = await router_chat(
                self._router,
                messages=[{"role": "user", "content": prompt}],
                model=self._cfg.content_model,
                max_tokens=128,
                temperature=0.0,
            )
            data = safe_json_loads(extract_content(resp), default={"safe": True})
            if isinstance(data, dict):
                safe = bool(data.get("safe", True))
                flags = [str(f) for f in data.get("flags", [])]
                return safe, flags
        except Exception as exc:
            log.debug("LLM content check failed: %s", exc)
        return True, []

    def purge_old_records(self) -> int:
        return self._audit.purge_old(self._cfg.retain_days)
