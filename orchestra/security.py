"""Horizon Orchestra — Security Middleware Layer.

Five-layer defense-in-depth security architecture for protecting AI agent
systems, particularly long-running autonomous agents backed by high-capability
models such as Opus 4.6.

Layers
------
1. Permission Boundaries  — PermissionPolicy / PermissionGate
2. Input Sanitization     — InputSanitizer
3. Output Monitoring      — OutputMonitor
4. Rate Limiting          — RateLimiter
5. Unified Middleware     — SecurityMiddleware

Plugs into the agent loop via pre_execution / post_execution hooks that wrap
every ToolCallEvent / ToolResultEvent without requiring changes to AgentLoop.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from orchestra.agent_loop import ToolCallEvent, ToolResultEvent

__all__ = [
    # Layer 1
    "PermissionPolicy",
    "PermissionGate",
    # Layer 2
    "SanitizeResult",
    "InjectionAlert",
    "InputSanitizer",
    # Layer 3
    "SecurityAlert",
    "PIIMatch",
    "OutputMonitor",
    # Layer 4
    "RateLimiter",
    # Layer 5
    "SecurityDecision",
    "SecurityMiddleware",
    # Preset policies
    "strict_policy",
    "standard_policy",
    "permissive_policy",
    "safety_critical_policy",
]

log = logging.getLogger("orchestra.security")


# ---------------------------------------------------------------------------
# Layer 1: Permission Boundaries
# ---------------------------------------------------------------------------


@dataclass
class PermissionPolicy:
    """Defines what an agent session is allowed to do.

    All fields have sensible production defaults.  Pass ``None`` to
    ``allowed_tools`` / ``allowed_domains`` to permit everything that is not
    explicitly denied.
    """

    # Tool access
    allowed_tools: set[str] | None = None          # None = all tools allowed
    denied_tools: set[str] = field(default_factory=set)
    max_tool_calls: int = 300                       # hard limit per session
    max_concurrent_tools: int = 10

    # Network access
    allowed_domains: set[str] | None = None        # None = all domains allowed
    denied_domains: set[str] = field(default_factory=lambda: {
        "169.254.169.254",          # AWS IMDS
        "metadata.google.internal", # GCP metadata
        "metadata.azure.internal",  # Azure metadata
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
    })

    # File system access
    allow_file_write: bool = True
    writable_paths: list[str] = field(
        default_factory=lambda: ["/tmp/horizon_workspace"]
    )

    # Egress
    allow_network_egress: bool = True

    # Credentials
    credential_ttl_seconds: int = 900              # 15-minute JIT credentials

    # Confirmation gates — tools that need human approval before running
    require_confirmation_for: set[str] = field(default_factory=lambda: {
        "gmail_send",
        "slack_post",
        "github_create_issue",
        "github_delete_repo",
        "stripe_charge",
        "twilio_send_sms",
    })

    # Size limits
    max_file_size_bytes: int = 50_000_000          # 50 MB
    max_output_length: int = 100_000               # chars


class PermissionGate:
    """Enforces a :class:`PermissionPolicy` before tool execution."""

    def __init__(self, policy: PermissionPolicy) -> None:
        self._policy = policy
        self._tool_call_count: int = 0
        self._active_tools: int = 0

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def check_tool_allowed(self, tool_name: str) -> tuple[bool, str]:
        """Return ``(True, "")`` if the tool may run, else ``(False, reason)``."""
        if tool_name in self._policy.denied_tools:
            return False, f"Tool '{tool_name}' is explicitly denied."

        if self._policy.allowed_tools is not None:
            if tool_name not in self._policy.allowed_tools:
                return False, (
                    f"Tool '{tool_name}' is not in the allowed_tools allowlist."
                )

        return True, ""

    def check_domain_allowed(self, url: str) -> tuple[bool, str]:
        """Return ``(True, "")`` if the URL's host may be contacted."""
        if not self._policy.allow_network_egress:
            return False, "Network egress is disabled by policy."

        try:
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname or ""
        except Exception:
            return False, f"Malformed URL: {url!r}"

        host_lower = host.lower()

        # Deny private / link-local IP ranges
        if _is_private_ip(host_lower):
            return False, f"Host '{host}' resolves to a private/reserved address."

        # Explicit deny list
        for denied in self._policy.denied_domains:
            if host_lower == denied.lower() or host_lower.endswith(f".{denied.lower()}"):
                return False, f"Host '{host}' is in the denied_domains list."

        # Allowlist (if set)
        if self._policy.allowed_domains is not None:
            allowed = any(
                host_lower == d.lower() or host_lower.endswith(f".{d.lower()}")
                for d in self._policy.allowed_domains
            )
            if not allowed:
                return False, (
                    f"Host '{host}' is not in the allowed_domains allowlist."
                )

        return True, ""

    def check_file_path_allowed(
        self, path: str, write: bool = False
    ) -> tuple[bool, str]:
        """Return ``(True, "")`` if the file path is accessible.

        Resolves the path to prevent directory traversal / symlink attacks.
        """
        if write and not self._policy.allow_file_write:
            return False, "File write is disabled by policy."

        try:
            # Resolve without requiring the file to exist (Python 3.6+)
            resolved = str(os.path.realpath(path))
        except Exception as exc:
            return False, f"Cannot resolve path '{path}': {exc}"

        if write:
            allowed = any(
                resolved.startswith(os.path.realpath(wp))
                for wp in self._policy.writable_paths
            )
            if not allowed:
                return False, (
                    f"Path '{resolved}' is outside the allowed writable_paths."
                )

        return True, ""

    def increment_tool_count(self) -> tuple[bool, str]:
        """Increment the session-level tool-call counter.

        Returns ``(True, "")`` if below the limit, else ``(False, reason)``.
        """
        self._tool_call_count += 1
        if self._tool_call_count > self._policy.max_tool_calls:
            return False, (
                f"Session tool-call limit ({self._policy.max_tool_calls}) exceeded."
            )
        return True, ""

    def requires_confirmation(self, tool_name: str) -> bool:
        """Return ``True`` if the tool requires out-of-band human confirmation."""
        return tool_name in self._policy.require_confirmation_for

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "tool_call_count": self._tool_call_count,
            "max_tool_calls": self._policy.max_tool_calls,
            "active_tools": self._active_tools,
        }


# ---------------------------------------------------------------------------
# Helpers for Layer 1
# ---------------------------------------------------------------------------

_PRIVATE_IP_RE = re.compile(
    r"""
    ^(
        10\.\d+\.\d+\.\d+         |   # RFC-1918 10/8
        172\.(1[6-9]|2\d|3[01])\.\d+\.\d+  |  # RFC-1918 172.16-31/12
        192\.168\.\d+\.\d+        |   # RFC-1918 192.168/16
        169\.254\.\d+\.\d+        |   # Link-local
        127\.\d+\.\d+\.\d+        |   # Loopback
        0\.0\.0\.0                |   # Unspecified
        ::1                       |   # IPv6 loopback
        fc[0-9a-f][0-9a-f]:.+     |   # IPv6 ULA
        fd[0-9a-f][0-9a-f]:.+         # IPv6 ULA
    )$
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _is_private_ip(host: str) -> bool:
    return bool(_PRIVATE_IP_RE.match(host))


# ---------------------------------------------------------------------------
# Layer 2: Input Sanitization
# ---------------------------------------------------------------------------


@dataclass
class InjectionAlert:
    """A single detected injection pattern."""

    pattern_name: str
    matched_text: str
    severity: str   # "low" | "medium" | "high" | "critical"
    position: int


@dataclass
class SanitizeResult:
    """Result returned by :class:`InputSanitizer` methods."""

    clean_text: str
    original_text: str
    alerts: list[InjectionAlert]
    was_modified: bool
    risk_score: float  # 0.0 = clean, 1.0 = definitely malicious


# Pre-compiled injection patterns — (name, regex, severity, remove?)
_RAW_INJECTION_PATTERNS: list[tuple[str, str, str]] = [
    # Instruction override
    ("ignore_instructions",
     r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?",
     "critical"),
    ("disregard_instructions",
     r"disregard\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?",
     "critical"),
    # Role injection
    ("you_are_now",
     r"\byou\s+are\s+now\b",
     "high"),
    ("new_role",
     r"\bnew\s+role\b",
     "high"),
    ("act_as",
     r"\bact\s+as\b",
     "medium"),
    ("pretend_to_be",
     r"\bpretend\s+to\s+be\b",
     "high"),
    ("roleplay_as",
     r"\broleplay\s+as\b",
     "medium"),
    # System-prompt markers
    ("system_colon",
     r"(?i)^system\s*:",
     "critical"),
    ("system_bracket",
     r"\[SYSTEM\]",
     "critical"),
    ("llama_sys_tag",
     r"<<\s*SYS\s*>>",
     "critical"),
    ("system_tag",
     r"<\s*system\s*>",
     "high"),
    # Base64-encoded instructions
    ("base64_instruction_block",
     r"(?:[A-Za-z0-9+/]{40,}={0,2})",
     "medium"),
    # Unicode control / homoglyph attacks
    ("rtl_override",
     r"[\u202e\u202d\u200f\u200e]",
     "high"),
    ("zero_width_chars",
     r"[\u200b\u200c\u200d\ufeff\u2060]",
     "medium"),
    # HTML comment injection
    ("html_comment_injection",
     r"<!--.*?-->",
     "medium"),
    # Markdown link with javascript:
    ("js_link_injection",
     r"\[.*?\]\(\s*javascript\s*:",
     "critical"),
    # Data exfiltration — encoding in URLs
    ("data_exfil_base64_url",
     r"https?://[^\s]*(?:data|payload|exfil|dump)[^\s]*=[A-Za-z0-9+/%]{20,}",
     "high"),
    ("data_exfil_webhook",
     r"https?://(?:webhook|hook|pipe|canary|burp|requestbin|ngrok)[^\s]*",
     "high"),
    # Prompt leaking
    ("leak_instructions",
     r"(repeat|print|output|reveal|show)\s+(your|the|all)\s+(instructions?|prompt|system\s+prompt)",
     "high"),
    # Jailbreak patterns
    ("dan_jailbreak",
     r"\bDAN\b|\bdo\s+anything\s+now\b",
     "critical"),
    ("dev_mode",
     r"\bdeveloper\s+mode\b|\benable\s+dev\s+mode\b",
     "high"),
]

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (name, re.compile(pattern, re.IGNORECASE | re.DOTALL), severity)
    for name, pattern, severity in _RAW_INJECTION_PATTERNS
]

_SEVERITY_SCORE: dict[str, float] = {
    "low": 0.15,
    "medium": 0.35,
    "high": 0.65,
    "critical": 1.0,
}


class InputSanitizer:
    """Sanitizes untrusted content before it enters the model context."""

    # Control chars to strip (excludes printable ASCII, newline, tab)
    _CONTROL_CHAR_RE = re.compile(
        r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"  # C0 except \n \t
        r"\x80-\x9f]",                         # C1
    )

    _HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

    def sanitize_user_input(self, text: str) -> SanitizeResult:
        """Sanitize free-form user input."""
        alerts = self.detect_injection_patterns(text)
        clean = self.strip_control_characters(text)
        clean = self.strip_html_comments(clean)
        modified = clean != text
        score = self._compute_risk_score(alerts)
        return SanitizeResult(
            clean_text=clean,
            original_text=text,
            alerts=alerts,
            was_modified=modified,
            risk_score=score,
        )

    def sanitize_tool_output(self, text: str, tool_name: str) -> SanitizeResult:
        """Sanitize output returned by a tool before it is injected into the
        model context.  More aggressive than user-input sanitization."""
        alerts = self.detect_injection_patterns(text)
        clean = self.strip_control_characters(text)
        clean = self.strip_html_comments(clean)

        # Remove RTL/zero-width characters
        clean = re.sub(r"[\u202e\u202d\u200f\u200e\u200b\u200c\u200d\ufeff\u2060]",
                       "", clean)

        # Try to decode and re-check suspicious base64 blobs
        clean = self._neutralize_base64_instructions(clean)

        modified = clean != text
        score = self._compute_risk_score(alerts)
        return SanitizeResult(
            clean_text=clean,
            original_text=text,
            alerts=alerts,
            was_modified=modified,
            risk_score=score,
        )

    def sanitize_url(self, url: str) -> SanitizeResult:
        """Sanitize a URL string — rejects javascript:, data: schemes etc."""
        alerts: list[InjectionAlert] = []
        clean = url.strip()

        try:
            parsed = urllib.parse.urlparse(clean)
            scheme = parsed.scheme.lower()
        except Exception:
            alerts.append(InjectionAlert(
                pattern_name="malformed_url",
                matched_text=url[:200],
                severity="high",
                position=0,
            ))
            return SanitizeResult(
                clean_text="",
                original_text=url,
                alerts=alerts,
                was_modified=True,
                risk_score=0.9,
            )

        if scheme not in ("http", "https", "ftp", "ftps", ""):
            alerts.append(InjectionAlert(
                pattern_name="dangerous_url_scheme",
                matched_text=scheme,
                severity="critical",
                position=0,
            ))
            return SanitizeResult(
                clean_text="",
                original_text=url,
                alerts=alerts,
                was_modified=True,
                risk_score=1.0,
            )

        # Run normal injection checks on URL
        alerts.extend(self.detect_injection_patterns(clean))
        score = self._compute_risk_score(alerts)
        return SanitizeResult(
            clean_text=clean,
            original_text=url,
            alerts=alerts,
            was_modified=False,
            risk_score=score,
        )

    def strip_html_comments(self, text: str) -> str:
        return self._HTML_COMMENT_RE.sub("", text)

    def strip_control_characters(self, text: str) -> str:
        return self._CONTROL_CHAR_RE.sub("", text)

    def detect_injection_patterns(self, text: str) -> list[InjectionAlert]:
        """Scan text against all known injection patterns."""
        alerts: list[InjectionAlert] = []
        for name, pattern, severity in INJECTION_PATTERNS:
            for m in pattern.finditer(text):
                matched = m.group(0)
                # Skip very short base64 blobs that are almost certainly benign
                if name == "base64_instruction_block" and len(matched) < 60:
                    continue
                alerts.append(InjectionAlert(
                    pattern_name=name,
                    matched_text=matched[:200],
                    severity=severity,
                    position=m.start(),
                ))
        return alerts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_risk_score(self, alerts: list[InjectionAlert]) -> float:
        if not alerts:
            return 0.0
        # Take the max severity score and add a small per-alert increment
        max_score = max(_SEVERITY_SCORE.get(a.severity, 0.0) for a in alerts)
        bonus = min(0.1 * (len(alerts) - 1), 0.3)
        return min(max_score + bonus, 1.0)

    def _neutralize_base64_instructions(self, text: str) -> str:
        """Decode base64 blobs and check them for injection patterns.

        If decoded content contains injection indicators, replaces the encoded
        blob with a ``[REDACTED:base64-injection]`` placeholder.
        """
        b64_re = re.compile(r"[A-Za-z0-9+/]{60,}={0,2}")

        def replace_if_malicious(m: re.Match[str]) -> str:
            encoded = m.group(0)
            try:
                decoded = base64.b64decode(encoded + "==").decode("utf-8", errors="replace")
            except Exception:
                return encoded
            alerts = self.detect_injection_patterns(decoded)
            critical_or_high = [
                a for a in alerts if a.severity in ("critical", "high")
            ]
            if critical_or_high:
                log.warning(
                    "Neutralized base64-encoded injection payload (pattern=%s)",
                    critical_or_high[0].pattern_name,
                )
                return "[REDACTED:base64-injection]"
            return encoded

        return b64_re.sub(replace_if_malicious, text)


# ---------------------------------------------------------------------------
# Layer 3: Output Monitor
# ---------------------------------------------------------------------------


@dataclass
class SecurityAlert:
    """A security event produced by the monitoring layer."""

    level: str          # "info" | "warning" | "critical" | "block"
    category: str       # "injection" | "exfiltration" | "looping" | "credential_leak" | "pii" | "anomaly"
    message: str
    tool_name: str = ""
    timestamp: float = field(default_factory=time.monotonic)
    action_taken: str = ""  # "logged" | "blocked" | "redacted"


@dataclass
class PIIMatch:
    """A PII token detected in output."""

    type: str    # "email" | "phone" | "ssn" | "credit_card" | "api_key"
    value: str   # redacted version, e.g. "jo***@e***.com"
    position: int


# PII patterns (compiled once at module load)
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # RFC 5322-ish email
    ("email", re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    )),
    # US/intl phone: +1 (555) 555-5555, 555-555-5555, +44 7700 900000
    ("phone", re.compile(
        r"(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}"
        r"|\+\d{1,3}[\s\-.]?\d{2,4}[\s\-.]?\d{4,10}",
    )),
    # SSN: 123-45-6789
    ("ssn", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
    # Credit card: 13-19 digit groups (Luhn-adjacent)
    ("credit_card", re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d\d)\d{12}|(?:2131|1800|35\d{3})\d{11})\b")),
    # API keys / tokens
    ("api_key", re.compile(
        r"\b("
        r"sk-[A-Za-z0-9]{20,}"           # OpenAI
        r"|ghp_[A-Za-z0-9]{36}"          # GitHub PAT
        r"|gho_[A-Za-z0-9]{36}"          # GitHub OAuth
        r"|xoxb-[0-9]+-[A-Za-z0-9]+"    # Slack bot
        r"|xoxp-[0-9]+-[A-Za-z0-9]+"    # Slack user
        r"|AIza[0-9A-Za-z\-_]{35}"       # Google API key
        r"|AKIA[0-9A-Z]{16}"             # AWS access key
        r"|ASIA[0-9A-Z]{16}"             # AWS STS
        r"|ya29\.[0-9A-Za-z\-_]+"        # Google OAuth
        r")\b",
    )),
    # AWS secret key heuristic (40 char alphanumeric following "secret")
    ("api_key_secret", re.compile(
        r"(?i)(?:secret[_\s]?(?:access[_\s]?)?key|aws[_\s]secret)[\"'\s:=]+([A-Za-z0-9/+]{40})\b",
    )),
]

# Credential leak patterns (subset of PII patterns focused on API keys)
_CREDENTIAL_PATTERNS: list[re.Pattern[str]] = [p for name, p in _PII_PATTERNS if "api_key" in name]

# Tools that are expected to produce large/network-fetched output
_HIGH_VOLUME_TOOLS = frozenset({"web_search", "fetch_url", "file_read", "execute_code"})

# Max consecutive same-tool calls before flagging as loop
_LOOP_THRESHOLD = 5


class OutputMonitor:
    """Real-time behavioral monitoring of agent actions."""

    def __init__(self, policy: PermissionPolicy) -> None:
        self._policy = policy
        self._alerts: list[SecurityAlert] = []
        self._action_history: list[str] = []   # tool names in order
        self._tool_counts: dict[str, int] = {}  # per-tool running total
        self._consecutive: dict[str, int] = {}  # consecutive-call counter
        self._last_tool: str = ""

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def record_action(
        self, event: ToolCallEvent | ToolResultEvent
    ) -> list[SecurityAlert]:
        """Process a single event and return any new alerts."""
        new_alerts: list[SecurityAlert] = []

        if isinstance(event, ToolCallEvent):
            tool_name = event.tool_name
            args = event.arguments
            context = str(args)

            self._action_history.append(tool_name)
            self._tool_counts[tool_name] = self._tool_counts.get(tool_name, 0) + 1

            # Update consecutive counter
            if tool_name == self._last_tool:
                self._consecutive[tool_name] = self._consecutive.get(tool_name, 0) + 1
            else:
                self._consecutive = {tool_name: 1}
            self._last_tool = tool_name

            # Run anomaly checks
            for check in (
                lambda: self._check_tool_looping(tool_name),
                lambda: self._check_data_exfiltration(tool_name, args),
                lambda: self._check_behavioral_discontinuity(event),
            ):
                alert = check()
                if alert:
                    new_alerts.append(alert)
                    self._alerts.append(alert)

        elif isinstance(event, ToolResultEvent):
            tool_name = event.tool_name
            result = event.result

            cred_alert = self._check_credential_leakage(result)
            if cred_alert:
                cred_alert.tool_name = tool_name
                new_alerts.append(cred_alert)
                self._alerts.append(cred_alert)

        return new_alerts

    # ------------------------------------------------------------------
    # Individual detectors
    # ------------------------------------------------------------------

    def _check_unexpected_tool(
        self, tool_name: str, task_context: str
    ) -> SecurityAlert | None:
        """Flag if a tool seems unrelated to the stated task context.

        Uses simple keyword heuristics — kept lightweight to avoid false
        positives in production.
        """
        dangerous_tools_in_benign_context = {
            "execute_code", "browser_action", "file_write",
            "gmail_send", "slack_post", "stripe_charge",
        }
        if tool_name not in dangerous_tools_in_benign_context:
            return None
        # Only flag if the task context looks "read-only"
        read_only_signals = re.compile(
            r"\b(read|search|find|look ?up|fetch|get|list|show|display|summarize)\b",
            re.IGNORECASE,
        )
        write_signals = re.compile(
            r"\b(write|create|send|post|execute|run|deploy|delete|update|modify)\b",
            re.IGNORECASE,
        )
        if read_only_signals.search(task_context) and not write_signals.search(task_context):
            return SecurityAlert(
                level="warning",
                category="anomaly",
                message=(
                    f"Tool '{tool_name}' appears unexpectedly in a read-only task context."
                ),
                tool_name=tool_name,
                action_taken="logged",
            )
        return None

    def _check_data_exfiltration(
        self, tool_name: str, args: dict[str, Any]
    ) -> SecurityAlert | None:
        """Detect patterns consistent with data exfiltration in tool arguments."""
        args_text = str(args)

        # Large payloads sent to external HTTP endpoints
        if tool_name in ("fetch_url", "browser_action"):
            url = args.get("url", "")
            # Suspiciously large query-string values
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            for key, values in qs.items():
                for val in values:
                    if len(val) > 500:
                        return SecurityAlert(
                            level="warning",
                            category="exfiltration",
                            message=(
                                f"Large ({len(val)}-char) query parameter '{key}' "
                                f"in URL may be exfiltrating data."
                            ),
                            tool_name=tool_name,
                            action_taken="logged",
                        )

        # Base64 in outbound HTTP calls
        if tool_name in ("fetch_url", "browser_action", "web_search"):
            b64_blobs = re.findall(r"[A-Za-z0-9+/]{100,}={0,2}", args_text)
            if b64_blobs:
                return SecurityAlert(
                    level="warning",
                    category="exfiltration",
                    message=(
                        f"Possible base64-encoded payload in '{tool_name}' arguments "
                        f"({len(b64_blobs)} blob(s))."
                    ),
                    tool_name=tool_name,
                    action_taken="logged",
                )

        # PII in outbound requests
        pii_matches = self.detect_pii(args_text)
        if pii_matches:
            types = {m.type for m in pii_matches}
            return SecurityAlert(
                level="warning",
                category="exfiltration",
                message=(
                    f"PII detected in '{tool_name}' arguments: {', '.join(sorted(types))}."
                ),
                tool_name=tool_name,
                action_taken="logged",
            )

        return None

    def _check_tool_looping(self, tool_name: str) -> SecurityAlert | None:
        """Detect when the same tool is called more than N times consecutively."""
        count = self._consecutive.get(tool_name, 0)
        if count >= _LOOP_THRESHOLD:
            level = "critical" if count >= _LOOP_THRESHOLD * 2 else "warning"
            return SecurityAlert(
                level=level,
                category="looping",
                message=(
                    f"Tool '{tool_name}' has been called {count} times consecutively "
                    f"(threshold={_LOOP_THRESHOLD}). Possible infinite loop."
                ),
                tool_name=tool_name,
                action_taken="logged",
            )
        return None

    def _check_behavioral_discontinuity(
        self, event: ToolCallEvent
    ) -> SecurityAlert | None:
        """Flag sudden pivot to a high-risk tool with no prior lead-up."""
        high_risk_tools = frozenset({
            "execute_code", "file_write", "gmail_send", "slack_post",
            "github_create_issue", "stripe_charge", "twilio_send_sms",
        })
        if event.tool_name not in high_risk_tools:
            return None

        # If this is one of the first 3 calls and jumps straight to high-risk, flag it
        if len(self._action_history) <= 3 and self._action_history.count(event.tool_name) == 1:
            return SecurityAlert(
                level="warning",
                category="anomaly",
                message=(
                    f"High-risk tool '{event.tool_name}' invoked with very little "
                    f"prior context ({len(self._action_history)} total calls so far)."
                ),
                tool_name=event.tool_name,
                action_taken="logged",
            )
        return None

    def _check_credential_leakage(self, text: str) -> SecurityAlert | None:
        """Detect API keys or tokens appearing in tool output."""
        for pattern in _CREDENTIAL_PATTERNS:
            m = pattern.search(text)
            if m:
                redacted = _redact_value(m.group(0))
                return SecurityAlert(
                    level="critical",
                    category="credential_leak",
                    message=(
                        f"Credential/API key detected in tool output: {redacted}"
                    ),
                    action_taken="logged",
                )
        return None

    # ------------------------------------------------------------------
    # PII
    # ------------------------------------------------------------------

    def detect_pii(self, text: str) -> list[PIIMatch]:
        matches: list[PIIMatch] = []
        for pii_type, pattern in _PII_PATTERNS:
            for m in pattern.finditer(text):
                # For named groups (api_key_secret) use group 1 if present
                raw = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                matches.append(PIIMatch(
                    type=pii_type,
                    value=_redact_value(raw),
                    position=m.start(),
                ))
        return matches

    def redact_pii(self, text: str) -> str:
        """Return a copy of *text* with all detected PII replaced by placeholders."""
        result = text
        for pii_type, pattern in _PII_PATTERNS:
            result = pattern.sub(f"[REDACTED:{pii_type.upper()}]", result)
        return result

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @property
    def alert_history(self) -> list[SecurityAlert]:
        return list(self._alerts)


def _redact_value(value: str) -> str:
    """Return a partially-masked version of a sensitive value."""
    n = len(value)
    if n <= 4:
        return "*" * n
    visible = max(2, n // 6)
    return value[:visible] + "*" * (n - visible * 2) + value[-visible:]


# ---------------------------------------------------------------------------
# Layer 4: Rate Limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Token-bucket rate limiting for API calls and tool execution.

    Two independent buckets:
    - Request bucket  — controls call frequency
    - Token bucket    — controls LLM token consumption
    """

    def __init__(
        self,
        max_requests_per_minute: int = 60,
        max_tokens_per_minute: int = 1_000_000,
    ) -> None:
        self._max_req = max_requests_per_minute
        self._max_tok = max_tokens_per_minute

        # Token bucket state
        self._req_tokens: float = float(max_requests_per_minute)
        self._tok_tokens: float = float(max_tokens_per_minute)
        self._last_refill: float = time.monotonic()

        # Counters
        self._total_requests: int = 0
        self._total_tokens: int = 0
        self._total_waits: float = 0.0

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------

    def _refill(self) -> None:
        """Refill buckets based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now

        # Requests bucket: refill at max_req / 60 per second
        self._req_tokens = min(
            float(self._max_req),
            self._req_tokens + elapsed * (self._max_req / 60.0),
        )
        # Tokens bucket: refill at max_tok / 60 per second
        self._tok_tokens = min(
            float(self._max_tok),
            self._tok_tokens + elapsed * (self._max_tok / 60.0),
        )

    async def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire *tokens* from both buckets.

        Returns ``True`` immediately if capacity is available, ``False`` if
        either bucket is exhausted (non-blocking).
        """
        async with self._lock:
            self._refill()
            if self._req_tokens >= 1 and self._tok_tokens >= tokens:
                self._req_tokens -= 1
                self._tok_tokens -= tokens
                self._total_requests += 1
                self._total_tokens += tokens
                return True
            return False

    async def wait_and_acquire(self, tokens: int = 1) -> float:
        """Block until capacity is available, then acquire.

        Returns the time spent waiting in seconds.
        """
        t0 = time.monotonic()
        while True:
            async with self._lock:
                self._refill()
                if self._req_tokens >= 1 and self._tok_tokens >= tokens:
                    self._req_tokens -= 1
                    self._tok_tokens -= tokens
                    self._total_requests += 1
                    self._total_tokens += tokens
                    wait_time = time.monotonic() - t0
                    self._total_waits += wait_time
                    return wait_time
            # Sleep a fraction of a second and retry
            await asyncio.sleep(0.1)

    def reset(self) -> None:
        """Reset all buckets and counters to their initial state."""
        self._req_tokens = float(self._max_req)
        self._tok_tokens = float(self._max_tok)
        self._last_refill = time.monotonic()
        self._total_requests = 0
        self._total_tokens = 0
        self._total_waits = 0.0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_requests": self._total_requests,
            "total_tokens_consumed": self._total_tokens,
            "total_wait_seconds": round(self._total_waits, 3),
            "current_req_bucket": round(self._req_tokens, 2),
            "current_tok_bucket": round(self._tok_tokens, 2),
            "max_requests_per_minute": self._max_req,
            "max_tokens_per_minute": self._max_tok,
        }


# ---------------------------------------------------------------------------
# Layer 5: Security Middleware
# ---------------------------------------------------------------------------


@dataclass
class SecurityDecision:
    """The outcome of a pre- or post-execution security check."""

    allowed: bool
    reason: str = ""
    modified_args: dict[str, Any] | None = None   # sanitized args
    modified_result: str | None = None             # redacted result
    alerts: list[SecurityAlert] = field(default_factory=list)


class SecurityMiddleware:
    """Unified security layer that wraps agent execution.

    Usage example (plugging into AgentLoop events)::

        middleware = SecurityMiddleware(policy=standard_policy())

        async for event in agent_loop.run(task):
            if isinstance(event, ToolCallEvent):
                decision = await middleware.pre_execution(
                    event.tool_name, event.arguments, context=task
                )
                if not decision.allowed:
                    # Inject a blocked-tool result and continue
                    ...
            elif isinstance(event, ToolResultEvent):
                decision = await middleware.post_execution(
                    event.tool_name, event.result, event.duration
                )
                ...
    """

    def __init__(
        self,
        policy: PermissionPolicy | None = None,
        sanitizer: InputSanitizer | None = None,
        monitor: OutputMonitor | None = None,
        rate_limiter: RateLimiter | None = None,
        on_alert: Callable[[SecurityAlert], Awaitable[None]] | None = None,
        block_on_critical: bool = True,
    ) -> None:
        self._policy = policy or standard_policy()
        self._gate = PermissionGate(self._policy)
        self._sanitizer = sanitizer or InputSanitizer()
        self._monitor = monitor or OutputMonitor(self._policy)
        self._rate_limiter = rate_limiter or RateLimiter()
        self._on_alert = on_alert
        self._block_on_critical = block_on_critical
        self._audit_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Pre-execution hook
    # ------------------------------------------------------------------

    async def pre_execution(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: str = "",
    ) -> SecurityDecision:
        """Run all pre-execution checks.

        Called *before* a tool is invoked.  Returns a :class:`SecurityDecision`
        indicating whether execution should proceed and (optionally) modified
        arguments.
        """
        alerts: list[SecurityAlert] = []
        ts = time.monotonic()

        # 1. Permission gate — tool allowlist / denylist
        allowed, reason = self._gate.check_tool_allowed(tool_name)
        if not allowed:
            alert = SecurityAlert(
                level="block",
                category="anomaly",
                message=reason,
                tool_name=tool_name,
                action_taken="blocked",
            )
            alerts.append(alert)
            await self._fire_alert(alert)
            self._log_audit(ts, tool_name, "pre", "blocked", alerts)
            return SecurityDecision(allowed=False, reason=reason, alerts=alerts)

        # 2. Session tool-call quota
        ok, reason = self._gate.increment_tool_count()
        if not ok:
            alert = SecurityAlert(
                level="block",
                category="anomaly",
                message=reason,
                tool_name=tool_name,
                action_taken="blocked",
            )
            alerts.append(alert)
            await self._fire_alert(alert)
            self._log_audit(ts, tool_name, "pre", "blocked", alerts)
            return SecurityDecision(allowed=False, reason=reason, alerts=alerts)

        # 3. Domain check for URL-taking tools
        url = (
            arguments.get("url")
            or arguments.get("URL")
            or arguments.get("endpoint")
            or ""
        )
        if url:
            ok, reason = self._gate.check_domain_allowed(url)
            if not ok:
                alert = SecurityAlert(
                    level="block",
                    category="exfiltration",
                    message=reason,
                    tool_name=tool_name,
                    action_taken="blocked",
                )
                alerts.append(alert)
                await self._fire_alert(alert)
                self._log_audit(ts, tool_name, "pre", "blocked", alerts)
                return SecurityDecision(allowed=False, reason=reason, alerts=alerts)

            # Sanitize URL
            url_result = self._sanitizer.sanitize_url(url)
            if url_result.risk_score >= 0.8:
                alert = SecurityAlert(
                    level="critical",
                    category="injection",
                    message=f"URL failed sanitization (score={url_result.risk_score:.2f}).",
                    tool_name=tool_name,
                    action_taken="blocked",
                )
                alerts.extend(_injection_alerts_to_security_alerts(url_result.alerts, tool_name))
                alerts.append(alert)
                await self._fire_alert(alert)
                self._log_audit(ts, tool_name, "pre", "blocked", alerts)
                if self._block_on_critical:
                    return SecurityDecision(allowed=False, reason=alert.message, alerts=alerts)

        # 4. File path check for write operations
        path = arguments.get("path") or arguments.get("file_path") or ""
        is_write = tool_name in ("file_write", "tool_file_write")
        if path and is_write:
            ok, reason = self._gate.check_file_path_allowed(path, write=True)
            if not ok:
                alert = SecurityAlert(
                    level="block",
                    category="anomaly",
                    message=reason,
                    tool_name=tool_name,
                    action_taken="blocked",
                )
                alerts.append(alert)
                await self._fire_alert(alert)
                self._log_audit(ts, tool_name, "pre", "blocked", alerts)
                return SecurityDecision(allowed=False, reason=reason, alerts=alerts)

        # 5. Confirmation gate
        if self._gate.requires_confirmation(tool_name):
            alert = SecurityAlert(
                level="warning",
                category="anomaly",
                message=(
                    f"Tool '{tool_name}' requires human confirmation before execution."
                ),
                tool_name=tool_name,
                action_taken="logged",
            )
            alerts.append(alert)
            await self._fire_alert(alert)
            # Note: actual blocking requires external confirmation logic;
            # here we log and continue (caller can inspect alerts).

        # 6. Sanitize string arguments
        modified_args: dict[str, Any] = {}
        for key, val in arguments.items():
            if isinstance(val, str):
                result = self._sanitizer.sanitize_tool_output(val, tool_name)
                modified_args[key] = result.clean_text
                if result.alerts:
                    new_sec_alerts = _injection_alerts_to_security_alerts(
                        result.alerts, tool_name
                    )
                    alerts.extend(new_sec_alerts)
                    for a in new_sec_alerts:
                        await self._fire_alert(a)
            else:
                modified_args[key] = val

        # 7. Behavioral monitoring (ToolCallEvent-like)
        pseudo_event = ToolCallEvent(
            iteration=0,
            tool_name=tool_name,
            arguments=arguments,
            tool_call_id="",
        )
        monitor_alerts = self._monitor.record_action(pseudo_event)
        alerts.extend(monitor_alerts)
        for a in monitor_alerts:
            await self._fire_alert(a)

        # 8. Rate limiting
        allowed_by_rate = await self._rate_limiter.acquire()
        if not allowed_by_rate:
            wait_time = await self._rate_limiter.wait_and_acquire()
            if wait_time > 0:
                alert = SecurityAlert(
                    level="info",
                    category="anomaly",
                    message=(
                        f"Rate limited — waited {wait_time:.2f}s before '{tool_name}'."
                    ),
                    tool_name=tool_name,
                    action_taken="logged",
                )
                alerts.append(alert)

        # 9. Block if any critical alert and policy says so
        critical = [a for a in alerts if a.level in ("block", "critical")]
        if critical and self._block_on_critical:
            self._log_audit(ts, tool_name, "pre", "blocked", alerts)
            return SecurityDecision(
                allowed=False,
                reason=critical[0].message,
                modified_args=modified_args,
                alerts=alerts,
            )

        args_changed = modified_args != arguments
        self._log_audit(ts, tool_name, "pre", "allowed", alerts)
        return SecurityDecision(
            allowed=True,
            reason="",
            modified_args=modified_args if args_changed else None,
            alerts=alerts,
        )

    # ------------------------------------------------------------------
    # Post-execution hook
    # ------------------------------------------------------------------

    async def post_execution(
        self,
        tool_name: str,
        result: str,
        duration: float,
    ) -> SecurityDecision:
        """Run all post-execution checks.

        Called *after* a tool returns.  May redact PII / credentials from the
        result before it is injected back into the model context.
        """
        alerts: list[SecurityAlert] = []
        ts = time.monotonic()

        # 1. Output size check
        if len(result) > self._policy.max_output_length:
            alert = SecurityAlert(
                level="warning",
                category="anomaly",
                message=(
                    f"Tool '{tool_name}' returned {len(result):,} chars — "
                    f"truncated to {self._policy.max_output_length:,}."
                ),
                tool_name=tool_name,
                action_taken="logged",
            )
            alerts.append(alert)
            result = result[:self._policy.max_output_length]

        # 2. Sanitize tool output (injection patterns from web content etc.)
        sanitized = self._sanitizer.sanitize_tool_output(result, tool_name)
        if sanitized.alerts:
            new_sec_alerts = _injection_alerts_to_security_alerts(
                sanitized.alerts, tool_name
            )
            alerts.extend(new_sec_alerts)
            for a in new_sec_alerts:
                await self._fire_alert(a)

        clean_result = sanitized.clean_text

        # 3. PII / credential redaction
        pii_matches = self._monitor.detect_pii(clean_result)
        if pii_matches:
            types = {m.type for m in pii_matches}
            log.info("Redacting PII (%s) from '%s' output.", types, tool_name)
            clean_result = self._monitor.redact_pii(clean_result)
            alert = SecurityAlert(
                level="warning",
                category="pii",
                message=(
                    f"PII ({', '.join(sorted(types))}) detected and redacted "
                    f"from '{tool_name}' output."
                ),
                tool_name=tool_name,
                action_taken="redacted",
            )
            alerts.append(alert)
            await self._fire_alert(alert)

        # 4. Behavioral monitoring
        pseudo_event = ToolResultEvent(
            iteration=0,
            tool_name=tool_name,
            result=clean_result[:500],
            success=True,
            duration=duration,
        )
        monitor_alerts = self._monitor.record_action(pseudo_event)
        alerts.extend(monitor_alerts)
        for a in monitor_alerts:
            await self._fire_alert(a)

        result_changed = clean_result != result
        self._log_audit(ts, tool_name, "post", "allowed", alerts)
        return SecurityDecision(
            allowed=True,
            reason="",
            modified_result=clean_result if result_changed else None,
            alerts=alerts,
        )

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    async def sanitize_input(self, text: str) -> str:
        """Sanitize arbitrary user input text and return the clean version."""
        result = self._sanitizer.sanitize_user_input(text)
        if result.alerts:
            log.warning(
                "Input sanitizer flagged %d pattern(s) (risk=%.2f)",
                len(result.alerts),
                result.risk_score,
            )
        return result.clean_text

    async def check_output(self, text: str) -> tuple[str, list[SecurityAlert]]:
        """Sanitize and monitor arbitrary output text.

        Returns ``(clean_text, alerts)``.
        """
        alerts: list[SecurityAlert] = []

        sanitized = self._sanitizer.sanitize_tool_output(text, "")
        clean = sanitized.clean_text
        if sanitized.alerts:
            alerts.extend(
                _injection_alerts_to_security_alerts(sanitized.alerts, "")
            )

        pii = self._monitor.detect_pii(clean)
        if pii:
            clean = self._monitor.redact_pii(clean)
            alerts.append(SecurityAlert(
                level="warning",
                category="pii",
                message=f"PII redacted: {', '.join({m.type for m in pii})}",
                action_taken="redacted",
            ))

        return clean, alerts

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def get_audit_log(self) -> list[dict[str, Any]]:
        """Return the full in-memory audit trail."""
        return list(self._audit_log)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "gate": self._gate.stats,
            "rate_limiter": self._rate_limiter.stats,
            "monitor_alerts": len(self._monitor.alert_history),
            "audit_log_entries": len(self._audit_log),
            "policy": {
                "max_tool_calls": self._policy.max_tool_calls,
                "allow_file_write": self._policy.allow_file_write,
                "allow_network_egress": self._policy.allow_network_egress,
                "confirmation_gates": list(self._policy.require_confirmation_for),
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fire_alert(self, alert: SecurityAlert) -> None:
        if alert.level in ("warning", "critical", "block"):
            log.warning(
                "[security] %s | %s | %s",
                alert.level.upper(),
                alert.category,
                alert.message,
            )
        else:
            log.info(
                "[security] %s | %s | %s",
                alert.level.upper(),
                alert.category,
                alert.message,
            )
        if self._on_alert is not None:
            try:
                await self._on_alert(alert)
            except Exception:
                log.exception("on_alert callback raised an exception")

    def _log_audit(
        self,
        timestamp: float,
        tool_name: str,
        phase: str,
        decision: str,
        alerts: list[SecurityAlert],
    ) -> None:
        self._audit_log.append({
            "timestamp": timestamp,
            "tool": tool_name,
            "phase": phase,
            "decision": decision,
            "alert_count": len(alerts),
            "alerts": [
                {
                    "level": a.level,
                    "category": a.category,
                    "message": a.message,
                    "action_taken": a.action_taken,
                }
                for a in alerts
            ],
        })


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------


def _injection_alerts_to_security_alerts(
    injection_alerts: list[InjectionAlert],
    tool_name: str,
) -> list[SecurityAlert]:
    """Convert :class:`InjectionAlert` objects to :class:`SecurityAlert` objects."""
    result: list[SecurityAlert] = []
    for ia in injection_alerts:
        level = "critical" if ia.severity == "critical" else (
            "warning" if ia.severity in ("high", "medium") else "info"
        )
        result.append(SecurityAlert(
            level=level,
            category="injection",
            message=(
                f"Injection pattern '{ia.pattern_name}' detected "
                f"(severity={ia.severity}, pos={ia.position})."
            ),
            tool_name=tool_name,
            action_taken="logged",
        ))
    return result


# ---------------------------------------------------------------------------
# Preset policies
# ---------------------------------------------------------------------------


def strict_policy() -> PermissionPolicy:
    """Maximum security — suitable for untrusted user input.

    - No file writes outside of /tmp/horizon_workspace
    - No network egress to private/metadata addresses
    - Low tool-call quota (50)
    - All potentially destructive tools require confirmation
    - Short credential TTL (5 min)
    """
    return PermissionPolicy(
        allowed_tools=None,
        denied_tools={
            "execute_code",      # no arbitrary code execution
            "browser_action",    # no browser automation
        },
        max_tool_calls=50,
        max_concurrent_tools=3,
        allow_file_write=True,
        writable_paths=["/tmp/horizon_workspace"],
        allow_network_egress=True,
        credential_ttl_seconds=300,  # 5 min
        require_confirmation_for={
            "gmail_send", "slack_post", "github_create_issue",
            "github_delete_repo", "stripe_charge", "twilio_send_sms",
            "file_write",
        },
        max_file_size_bytes=10_000_000,   # 10 MB
        max_output_length=50_000,
    )


def standard_policy() -> PermissionPolicy:
    """Balanced security — suitable for most production use.

    Sensible defaults: all tools allowed, sane limits, key gates in place.
    """
    return PermissionPolicy()  # dataclass defaults are the "standard" profile


def permissive_policy() -> PermissionPolicy:
    """Minimal restrictions — suitable for trusted internal / dev use.

    - All tools allowed, no denylist
    - High tool-call quota
    - No confirmation gates
    - Long credential TTL
    """
    return PermissionPolicy(
        allowed_tools=None,
        denied_tools=set(),
        max_tool_calls=1000,
        max_concurrent_tools=20,
        allow_file_write=True,
        writable_paths=["/"],   # unrestricted
        allow_network_egress=True,
        credential_ttl_seconds=3600,  # 1 hour
        require_confirmation_for=set(),
        max_file_size_bytes=500_000_000,   # 500 MB
        max_output_length=500_000,
    )


def safety_critical_policy() -> PermissionPolicy:
    """Extra-strict policy for financial, medical, and legal domains.

    - Very tight tool allowlist (research tools only)
    - All write/send/execute tools require confirmation
    - Low quota, short TTL, small output cap
    - PII redaction enforced (via OutputMonitor)
    """
    return PermissionPolicy(
        allowed_tools={
            "web_search",
            "fetch_url",
            "file_read",
        },
        denied_tools={
            "execute_code",
            "browser_action",
            "gmail_send",
            "slack_post",
            "stripe_charge",
            "twilio_send_sms",
        },
        max_tool_calls=30,
        max_concurrent_tools=2,
        allow_file_write=False,
        writable_paths=[],
        allow_network_egress=True,
        allowed_domains=None,   # inherit deny-list only
        credential_ttl_seconds=180,  # 3 min
        require_confirmation_for={
            "gmail_send", "slack_post", "github_create_issue",
            "github_delete_repo", "stripe_charge", "twilio_send_sms",
            "file_write",
        },
        max_file_size_bytes=5_000_000,    # 5 MB
        max_output_length=20_000,
    )
