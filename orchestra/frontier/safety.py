"""Frontier Browser — Safety Guard and boundary enforcement.

Hard boundaries and safety enforcement for Frontier browser tasks.
Prevents prompt injection, blocks sensitive URLs, requires approval
for state-changing actions, and enforces rate limits.

Three layers of defense:
    1. URL filtering — block internal/sensitive URLs
    2. Action gating — require approval for state-changing operations
       on sensitive pages (banking, admin panels, payment forms)
    3. Prompt injection detection — flag pages with suspicious hidden
       text that could manipulate the LLM agent
"""

from __future__ import annotations

import fnmatch
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "FrontierSafetyGuard",
    "SafetyConfig",
    "ApprovalRequest",
]

log = logging.getLogger("orchestra.frontier.safety")

# ---------------------------------------------------------------------------
# Try importing core-layer types; fall back to Any stubs
# ---------------------------------------------------------------------------
try:
    from orchestra.frontier.dom_interpreter import DOMAction, DOMSnapshot
except Exception:  # pragma: no cover
    DOMAction = Any  # type: ignore[assignment,misc]
    DOMSnapshot = Any  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Prompt-injection patterns (compiled once)
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "system_override",
        re.compile(
            r"(ignore\s+(previous|all|prior)\s+(instructions?|prompts?)"
            r"|you\s+are\s+now\s+a"
            r"|new\s+system\s+prompt"
            r"|override\s+(system|safety)\s+(prompt|instructions?)"
            r"|disregard\s+(all|your)\s+(rules|instructions?)"
            r")",
            re.IGNORECASE,
        ),
    ),
    (
        "role_injection",
        re.compile(
            r"(\bsystem\s*:\s*you\b"
            r"|<\s*system\s*>"
            r"|\[SYSTEM\]"
            r"|assistant\s*:\s*understood"
            r"|human\s*:\s*please\s+forget"
            r")",
            re.IGNORECASE,
        ),
    ),
    (
        "data_exfiltration",
        re.compile(
            r"(send\s+(all|this|the)\s+(data|info|text|content)\s+to"
            r"|fetch\s+https?://[^\s]+\?.*="
            r"|webhook\s*[.:]\s*https?://"
            r"|exfiltrate|POST\s+to\s+https?://"
            r")",
            re.IGNORECASE,
        ),
    ),
    (
        "hidden_instruction",
        re.compile(
            r"(<!--\s*(ignore|override|system|instruction)"
            r"|display\s*:\s*none[^>]*>(.*?(ignore|override|click|navigate))"
            r"|font-size\s*:\s*0"
            r"|opacity\s*:\s*0[^.]"
            r"|color\s*:\s*transparent"
            r")",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_leak",
        re.compile(
            r"(print\s+your\s+(system\s+)?prompt"
            r"|reveal\s+your\s+instructions?"
            r"|what\s+are\s+your\s+instructions?"
            r"|show\s+me\s+your\s+prompt"
            r"|output\s+the\s+system\s+message"
            r")",
            re.IGNORECASE,
        ),
    ),
]

# Sensitive field indicators — actions on these require approval
_SENSITIVE_FIELD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"pass\s?wd", re.IGNORECASE),
    re.compile(r"credit[_\-\s]?card", re.IGNORECASE),
    re.compile(r"card[_\-\s]?number", re.IGNORECASE),
    re.compile(r"cvv|cvc|csv", re.IGNORECASE),
    re.compile(r"expir(y|ation)", re.IGNORECASE),
    re.compile(r"ssn|social[_\-\s]?security", re.IGNORECASE),
    re.compile(r"bank[_\-\s]?account", re.IGNORECASE),
    re.compile(r"routing[_\-\s]?number", re.IGNORECASE),
    re.compile(r"pin[_\-\s]?code", re.IGNORECASE),
]

# Sensitive URL path segments — pages that need extra caution
_SENSITIVE_URL_SEGMENTS: list[str] = [
    "admin", "settings", "password", "billing", "payment",
    "checkout", "account", "security", "banking", "transfer",
    "wire", "delete", "deactivate", "close-account",
]


# =========================================================================
# Data classes
# =========================================================================

@dataclass
class SafetyConfig:
    """Configuration for FrontierSafetyGuard.

    Controls URL restrictions, action gating, prompt injection defense,
    and rate limiting for Frontier browser tasks.
    """

    # URL restrictions
    blocked_url_patterns: list[str] = field(default_factory=lambda: [
        "chrome://*", "chrome-extension://*", "about:*", "file://*",
        "javascript:*", "data:*",
        "*://*/admin*", "*://*/settings*", "*://*/password*",
        "*://*/billing*", "*://*/payment*",
    ])
    allowed_domains: list[str] = field(default_factory=list)  # Empty = all

    # Action restrictions
    require_approval_actions: list[str] = field(default_factory=lambda: [
        "submit_form", "type_text",  # Only for password/payment fields
    ])
    block_download_types: list[str] = field(default_factory=lambda: [
        ".exe", ".dmg", ".msi", ".bat", ".sh", ".cmd",
    ])

    # Prompt injection defense
    enable_injection_detection: bool = True
    max_hidden_text_ratio: float = 0.3  # Flag if >30% of text is hidden

    # Rate limiting
    max_actions_per_minute: int = 60
    max_navigations_per_minute: int = 20

    # Approval settings
    approval_timeout_seconds: float = 120.0
    max_pending_approvals: int = 20


@dataclass
class ApprovalRequest:
    """A request for user approval before executing a sensitive action."""

    request_id: str
    task_id: str
    action: Any  # DOMAction when available
    page_url: str
    reason: str          # Why approval is needed
    risk_level: str      # "low" | "medium" | "high"
    context: str         # Description of what will happen
    created_at: float
    status: str = "pending"   # "pending" | "approved" | "rejected" | "expired"
    expires_at: float = 0.0

    def is_expired(self) -> bool:
        """Check whether this approval request has expired."""
        if self.expires_at <= 0.0:
            return False
        return time.time() > self.expires_at

    def approve(self) -> None:
        """Mark this request as approved."""
        if self.is_expired():
            self.status = "expired"
            return
        self.status = "approved"

    def reject(self) -> None:
        """Mark this request as rejected."""
        self.status = "rejected"


# =========================================================================
# FrontierSafetyGuard
# =========================================================================

class FrontierSafetyGuard:
    """Safety enforcement for Frontier browser tasks.

    Three layers of defense:

    1. URL filtering — block internal/sensitive URLs
    2. Action gating — require approval for state-changing operations
       on sensitive pages (banking, admin panels, payment forms)
    3. Prompt injection detection — flag pages with suspicious hidden
       text that could manipulate the LLM agent

    Hard boundaries (always enforced, cannot be overridden):
    - No chrome:// or internal page access
    - No file:// access
    - No JavaScript: URL execution
    - Rate limiting on actions

    Soft boundaries (configurable):
    - Domain allowlist/blocklist
    - Approval requirements
    - Download restrictions
    """

    # Hard-blocked schemes — cannot be overridden regardless of config.
    _HARD_BLOCKED_SCHEMES: frozenset[str] = frozenset({
        "chrome", "chrome-extension", "file", "javascript",
        "data", "about", "blob", "view-source",
    })

    def __init__(self, config: SafetyConfig | None = None) -> None:
        self.config = config or SafetyConfig()

        # Rate-limit tracking: deque of timestamps per action type
        self._action_timestamps: dict[str, deque[float]] = {}
        self._navigation_timestamps: deque[float] = deque()

        # Audit log — every check recorded
        self._audit_log: list[dict[str, Any]] = []
        self._blocked_actions: list[dict[str, Any]] = []

        # Pending approvals
        self._pending_approvals: dict[str, ApprovalRequest] = {}

        log.info(
            "FrontierSafetyGuard initialised — %d blocked URL patterns, "
            "injection detection=%s, rate limit=%d actions/min",
            len(self.config.blocked_url_patterns),
            self.config.enable_injection_detection,
            self.config.max_actions_per_minute,
        )

    # -----------------------------------------------------------------
    # Pre-action checks — URL
    # -----------------------------------------------------------------

    async def check_url(self, url: str) -> tuple[bool, str]:
        """Check whether a URL is allowed.

        Returns:
            (allowed, reason) — *allowed* is ``True`` when navigation is
            permitted; *reason* explains any block.
        """
        url_stripped = url.strip()
        if not url_stripped:
            return False, "Empty URL"

        # 1. Hard-blocked schemes
        try:
            parsed = urlparse(url_stripped)
        except Exception:
            return False, f"Malformed URL: {url_stripped!r}"

        scheme = parsed.scheme.lower()
        if scheme in self._HARD_BLOCKED_SCHEMES:
            reason = f"Hard-blocked scheme: {scheme}://"
            self._record_blocked("check_url", url_stripped, reason)
            return False, reason

        # 2. Pattern-based blocking
        for pattern in self.config.blocked_url_patterns:
            if fnmatch.fnmatch(url_stripped, pattern):
                reason = f"URL matches blocked pattern: {pattern}"
                self._record_blocked("check_url", url_stripped, reason)
                return False, reason

        # 3. Domain allowlist (if configured)
        if self.config.allowed_domains:
            domain = parsed.hostname or ""
            allowed = any(
                domain == d or domain.endswith("." + d)
                for d in self.config.allowed_domains
            )
            if not allowed:
                reason = f"Domain {domain!r} not in allowed list"
                self._record_blocked("check_url", url_stripped, reason)
                return False, reason

        self._record_audit("check_url", url_stripped, allowed=True)
        return True, ""

    # -----------------------------------------------------------------
    # Pre-action checks — action gating
    # -----------------------------------------------------------------

    async def check_action(
        self,
        action: Any,
        dom: Any,
        page_url: str,
    ) -> tuple[bool, str, bool]:
        """Check whether a browser action is allowed.

        Returns:
            (allowed, reason, needs_approval) — when *needs_approval* is
            ``True`` the caller should pause and request user confirmation
            before executing the action.
        """
        action_type = getattr(action, "action_type", "") or getattr(action, "command_type", "")
        target = getattr(action, "target", "") or ""
        value = getattr(action, "value", "") or ""

        # Rate limit
        rate_ok, rate_reason = self.check_rate_limit(action_type)
        if not rate_ok:
            self._record_blocked("check_action", str(action), rate_reason)
            return False, rate_reason, False

        # Check if page URL is sensitive
        page_is_sensitive = self._url_is_sensitive(page_url)

        # Determine if approval is needed
        needs_approval = False
        reason = ""

        if action_type in self.config.require_approval_actions:
            # For type_text, only require approval on sensitive fields
            if action_type == "type_text":
                if self._target_is_sensitive(target, dom):
                    needs_approval = True
                    reason = (
                        f"Typing into sensitive field ({target!r}) — "
                        f"approval required"
                    )
            elif action_type == "submit_form":
                if page_is_sensitive:
                    needs_approval = True
                    reason = (
                        f"Submitting form on sensitive page ({page_url}) — "
                        f"approval required"
                    )
                else:
                    needs_approval = True
                    reason = "Form submission requires approval"

        # Navigate actions on sensitive URLs need approval
        if action_type == "navigate":
            url_allowed, url_reason = await self.check_url(value or target)
            if not url_allowed:
                return False, url_reason, False

        self.record_action(action_type)
        self._record_audit("check_action", str(action), allowed=True, needs_approval=needs_approval)
        return True, reason, needs_approval

    # -----------------------------------------------------------------
    # Download checks
    # -----------------------------------------------------------------

    async def check_download(self, url: str, filename: str) -> tuple[bool, str]:
        """Check whether a download should be allowed.

        Returns:
            (allowed, reason)
        """
        lower_name = filename.lower()
        for ext in self.config.block_download_types:
            if lower_name.endswith(ext):
                reason = f"Blocked download type: {ext} (file: {filename})"
                self._record_blocked("check_download", url, reason)
                return False, reason

        # Check the URL too
        url_lower = url.lower()
        for ext in self.config.block_download_types:
            if url_lower.endswith(ext):
                reason = f"Blocked download type from URL: {ext}"
                self._record_blocked("check_download", url, reason)
                return False, reason

        self._record_audit("check_download", url, allowed=True)
        return True, ""

    # -----------------------------------------------------------------
    # Prompt injection detection
    # -----------------------------------------------------------------

    async def scan_page(
        self,
        dom: Any,
        page_text: str,
    ) -> dict[str, Any]:
        """Scan a page for prompt injection indicators.

        Returns a dict with:
            - ``safe`` (bool): overall safety verdict
            - ``warnings`` (list[str]): human-readable warnings
            - ``injection_patterns`` (list[str]): detected pattern names
            - ``hidden_text_ratio`` (float): ratio of hidden text
            - ``hidden_instructions`` (list[str]): suspicious hidden text
        """
        result: dict[str, Any] = {
            "safe": True,
            "warnings": [],
            "injection_patterns": [],
            "hidden_text_ratio": 0.0,
            "hidden_instructions": [],
        }

        if not self.config.enable_injection_detection:
            return result

        # 1. Detect injection patterns in full page text
        patterns_found = self.detect_injection_patterns(page_text)
        if patterns_found:
            result["injection_patterns"] = patterns_found
            result["warnings"].append(
                f"Detected {len(patterns_found)} prompt injection "
                f"pattern(s): {', '.join(patterns_found)}"
            )
            result["safe"] = False
            log.warning("Prompt injection patterns detected: %s", patterns_found)

        # 2. Hidden text analysis
        visible_text = self._extract_visible_text(dom)
        hidden_instructions = self.detect_hidden_instructions(page_text, visible_text)
        if hidden_instructions:
            result["hidden_instructions"] = hidden_instructions
            result["warnings"].append(
                f"Found {len(hidden_instructions)} hidden instruction(s)"
            )
            result["safe"] = False
            log.warning("Hidden instructions detected on page")

        # 3. Hidden text ratio
        if page_text:
            visible_len = len(visible_text)
            total_len = len(page_text)
            if total_len > 0:
                hidden_ratio = 1.0 - (visible_len / total_len) if visible_len < total_len else 0.0
                result["hidden_text_ratio"] = round(hidden_ratio, 3)
                if hidden_ratio > self.config.max_hidden_text_ratio:
                    result["warnings"].append(
                        f"High hidden text ratio: {hidden_ratio:.1%} "
                        f"(threshold: {self.config.max_hidden_text_ratio:.0%})"
                    )
                    result["safe"] = False

        self._record_audit("scan_page", f"safe={result['safe']}", allowed=result["safe"])
        return result

    def detect_hidden_instructions(
        self,
        page_text: str,
        visible_text: str,
    ) -> list[str]:
        """Identify text present in page source but not in visible text.

        Returns a list of suspicious hidden fragments that look like
        instructions to an LLM agent.
        """
        if not page_text or not visible_text:
            return []

        hidden_fragments: list[str] = []
        visible_lower = visible_text.lower()

        # Split page text into sentences and check each
        sentences = re.split(r'[.!?\n]+', page_text)
        for sentence in sentences:
            sentence_stripped = sentence.strip()
            if len(sentence_stripped) < 10:
                continue
            # If this sentence isn't visible, check if it's suspicious
            if sentence_stripped.lower() not in visible_lower:
                for _name, pattern in _INJECTION_PATTERNS:
                    if pattern.search(sentence_stripped):
                        hidden_fragments.append(sentence_stripped[:200])
                        break

        return hidden_fragments

    def detect_injection_patterns(self, text: str) -> list[str]:
        """Scan text for known prompt injection patterns.

        Returns a list of pattern category names that matched.
        """
        if not text:
            return []
        found: list[str] = []
        for name, pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                found.append(name)
        return found

    # -----------------------------------------------------------------
    # Rate limiting
    # -----------------------------------------------------------------

    def check_rate_limit(self, action_type: str) -> tuple[bool, str]:
        """Check whether the action is within rate limits.

        Returns:
            (allowed, reason)
        """
        now = time.time()
        window = 60.0  # 1 minute

        # Per-action-type tracking
        if action_type not in self._action_timestamps:
            self._action_timestamps[action_type] = deque()

        # Global action rate
        all_timestamps = self._action_timestamps.setdefault("__all__", deque())
        self._prune_timestamps(all_timestamps, now, window)
        if len(all_timestamps) >= self.config.max_actions_per_minute:
            reason = (
                f"Global rate limit exceeded: {len(all_timestamps)}/"
                f"{self.config.max_actions_per_minute} actions/min"
            )
            return False, reason

        # Navigation-specific rate
        if action_type == "navigate":
            self._prune_timestamps(self._navigation_timestamps, now, window)
            if len(self._navigation_timestamps) >= self.config.max_navigations_per_minute:
                reason = (
                    f"Navigation rate limit exceeded: "
                    f"{len(self._navigation_timestamps)}/"
                    f"{self.config.max_navigations_per_minute} nav/min"
                )
                return False, reason

        return True, ""

    def record_action(self, action_type: str) -> None:
        """Record an action for rate-limiting purposes."""
        now = time.time()

        # Global
        all_ts = self._action_timestamps.setdefault("__all__", deque())
        all_ts.append(now)

        # Per-type
        type_ts = self._action_timestamps.setdefault(action_type, deque())
        type_ts.append(now)

        # Navigation tracking
        if action_type == "navigate":
            self._navigation_timestamps.append(now)

    # -----------------------------------------------------------------
    # Approval management
    # -----------------------------------------------------------------

    def create_approval_request(
        self,
        task_id: str,
        action: Any,
        page_url: str,
        reason: str,
        risk_level: str = "medium",
        context: str = "",
    ) -> ApprovalRequest:
        """Create a new approval request for a sensitive action.

        Returns the ``ApprovalRequest`` object. The caller is
        responsible for pausing the task until the request is resolved.
        """
        req = ApprovalRequest(
            request_id=str(uuid.uuid4()),
            task_id=task_id,
            action=action,
            page_url=page_url,
            reason=reason,
            risk_level=risk_level,
            context=context or reason,
            created_at=time.time(),
            expires_at=time.time() + self.config.approval_timeout_seconds,
        )
        self._pending_approvals[req.request_id] = req

        # Enforce max pending limit (evict oldest)
        while len(self._pending_approvals) > self.config.max_pending_approvals:
            oldest_id = next(iter(self._pending_approvals))
            old = self._pending_approvals.pop(oldest_id)
            old.status = "expired"
            log.debug("Evicted oldest approval request %s", oldest_id)

        log.info(
            "Approval request created: id=%s task=%s risk=%s reason=%r",
            req.request_id, task_id, risk_level, reason,
        )
        return req

    def resolve_approval(
        self,
        request_id: str,
        approved: bool,
    ) -> ApprovalRequest | None:
        """Resolve an approval request.

        Returns the updated ``ApprovalRequest`` or ``None`` if not found.
        """
        req = self._pending_approvals.get(request_id)
        if req is None:
            log.warning("Approval request %s not found", request_id)
            return None

        if req.is_expired():
            req.status = "expired"
            log.info("Approval request %s expired", request_id)
        elif approved:
            req.approve()
            log.info("Approval request %s approved", request_id)
        else:
            req.reject()
            log.info("Approval request %s rejected", request_id)

        return req

    def get_pending_approvals(self, task_id: str = "") -> list[ApprovalRequest]:
        """Return pending approval requests, optionally filtered by task."""
        result: list[ApprovalRequest] = []
        for req in self._pending_approvals.values():
            if req.is_expired():
                req.status = "expired"
                continue
            if req.status != "pending":
                continue
            if task_id and req.task_id != task_id:
                continue
            result.append(req)
        return result

    # -----------------------------------------------------------------
    # Audit
    # -----------------------------------------------------------------

    def get_audit_log(self) -> list[dict[str, Any]]:
        """Return the full audit log of all safety checks performed."""
        return list(self._audit_log)

    def get_blocked_actions(self) -> list[dict[str, Any]]:
        """Return a log of all blocked actions."""
        return list(self._blocked_actions)

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _url_is_sensitive(self, url: str) -> bool:
        """Check whether a URL path contains sensitive segments."""
        try:
            parsed = urlparse(url)
            path = (parsed.path or "").lower()
        except Exception:
            return True  # err on the side of caution
        return any(seg in path for seg in _SENSITIVE_URL_SEGMENTS)

    def _target_is_sensitive(self, target: str, dom: Any) -> bool:
        """Determine whether a target element is a sensitive field.

        Checks the target string (node_id, selector, or description)
        against known sensitive field patterns. Also inspects the DOM
        snapshot if available.
        """
        target_str = str(target).lower()
        for pattern in _SENSITIVE_FIELD_PATTERNS:
            if pattern.search(target_str):
                return True

        # Inspect DOM node attributes if dom has a lookup method
        if dom is not None and hasattr(dom, "get_node"):
            try:
                node = dom.get_node(target)
                if node is not None:
                    attrs = getattr(node, "attributes", {}) or {}
                    combined = " ".join(str(v) for v in attrs.values()).lower()
                    for pattern in _SENSITIVE_FIELD_PATTERNS:
                        if pattern.search(combined):
                            return True
                    # Check input type
                    input_type = attrs.get("type", "").lower()
                    if input_type in ("password", "hidden"):
                        return True
            except Exception:
                                import logging as _log; _log.getLogger('frontier.safety').debug('Suppressed exception', exc_info=True)

        return False

    def _extract_visible_text(self, dom: Any) -> str:
        """Extract visible text from a DOM snapshot.

        Falls back to returning an empty string if the DOM object
        doesn't support text extraction.
        """
        if dom is None:
            return ""
        # Try common attribute names
        for attr in ("visible_text", "text_content", "page_text"):
            val = getattr(dom, attr, None)
            if val and isinstance(val, str):
                return val
        # Try calling a method
        if hasattr(dom, "get_text"):
            try:
                return dom.get_text()
            except Exception:
                                import logging as _log; _log.getLogger('frontier.safety').debug('Suppressed exception', exc_info=True)
        return ""

    @staticmethod
    def _prune_timestamps(dq: deque[float], now: float, window: float) -> None:
        """Remove timestamps outside the sliding window."""
        while dq and dq[0] < now - window:
            dq.popleft()

    def _record_audit(
        self,
        check_type: str,
        detail: str,
        allowed: bool,
        needs_approval: bool = False,
    ) -> None:
        """Append an entry to the audit log."""
        entry = {
            "timestamp": time.time(),
            "check_type": check_type,
            "detail": detail,
            "allowed": allowed,
            "needs_approval": needs_approval,
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > 10_000:
            self._audit_log = self._audit_log[-5_000:]

    def _record_blocked(self, check_type: str, detail: str, reason: str) -> None:
        """Record a blocked action in both audit log and blocked list."""
        self._record_audit(check_type, detail, allowed=False)
        entry = {
            "timestamp": time.time(),
            "check_type": check_type,
            "detail": detail,
            "reason": reason,
        }
        self._blocked_actions.append(entry)
        log.warning("BLOCKED %s: %s — %s", check_type, detail[:120], reason)
        if len(self._blocked_actions) > 5_000:
            self._blocked_actions = self._blocked_actions[-2_500:]
