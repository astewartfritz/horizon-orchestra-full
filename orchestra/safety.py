"""Horizon Orchestra — Safety Layer.

Input/output guardrails, PII detection, action confirmation gates,
and content filtering.  Runs before and after every agent loop iteration.

Usage::

    from orchestra.safety import SafetyLayer
    safety = SafetyLayer()
    # Check input
    result = safety.check_input("What's John's SSN?")
    if result.blocked: ...
    # Check output
    result = safety.check_output(agent_response)
    cleaned = result.cleaned_text
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SafetyLayer",
    "SafetyConfig",
    "SafetyResult",
    "ActionConfirmation",
]

log = logging.getLogger("orchestra.safety")


# ---------------------------------------------------------------------------
# PII patterns
# ---------------------------------------------------------------------------

PII_PATTERNS: dict[str, re.Pattern] = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone_us": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "aws_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "api_key_generic": re.compile(r"\b(?:sk-|pk-|api[_-]?key[_-]?)[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
}

# Actions that require confirmation before execution
DANGEROUS_ACTIONS = {
    "gmail_send", "slack_post_message",
    "github_create_issue", "jira_create_issue",
    "hubspot_create_contact", "hubspot_create_deal",
    "stripe_create_customer",
    "aws_s3_write", "aws_lambda_invoke",
    "snowflake_query",  # when allow_write=True
    "notion_create_page",
}

# Blocked input patterns
BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:DAN|jailbr)", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*(?:is|:)", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SafetyConfig:
    check_pii: bool = True
    redact_pii: bool = True
    check_injection: bool = True
    require_confirmation: bool = True
    max_input_length: int = 100_000
    max_output_length: int = 500_000
    blocked_domains: list[str] = field(default_factory=list)


@dataclass
class PIIDetection:
    type: str
    match: str
    position: tuple[int, int]


@dataclass
class SafetyResult:
    safe: bool = True
    blocked: bool = False
    block_reason: str = ""
    pii_found: list[PIIDetection] = field(default_factory=list)
    cleaned_text: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class ActionConfirmation:
    """Request for user confirmation before executing a dangerous action."""
    action: str
    params: dict[str, Any]
    risk_level: str = "medium"     # low, medium, high
    description: str = ""
    confirmed: bool = False


# ---------------------------------------------------------------------------
# Safety layer
# ---------------------------------------------------------------------------

class SafetyLayer:
    """Pre/post processing guardrails for agent I/O."""

    def __init__(self, config: SafetyConfig | None = None) -> None:
        self.config = config or SafetyConfig()

    def check_input(self, text: str) -> SafetyResult:
        """Check user input for safety issues."""
        result = SafetyResult(cleaned_text=text)

        # Length check
        if len(text) > self.config.max_input_length:
            result.safe = False
            result.blocked = True
            result.block_reason = f"Input exceeds max length ({len(text)} > {self.config.max_input_length})"
            return result

        # Injection detection
        if self.config.check_injection:
            for pattern in BLOCKED_PATTERNS:
                if pattern.search(text):
                    result.safe = False
                    result.blocked = True
                    result.block_reason = "Potential prompt injection detected"
                    log.warning("Blocked input: prompt injection attempt")
                    return result

        # PII detection in input (warn but don't block)
        if self.config.check_pii:
            result.pii_found = self._detect_pii(text)
            if result.pii_found:
                result.warnings.append(
                    f"Input contains {len(result.pii_found)} PII element(s): "
                    f"{', '.join(set(p.type for p in result.pii_found))}"
                )

        return result

    def check_output(self, text: str) -> SafetyResult:
        """Check agent output for safety issues and redact PII if needed."""
        result = SafetyResult(cleaned_text=text)

        if len(text) > self.config.max_output_length:
            result.cleaned_text = text[:self.config.max_output_length]
            result.warnings.append("Output truncated to max length")

        # PII detection + redaction
        if self.config.check_pii:
            result.pii_found = self._detect_pii(text)
            if result.pii_found and self.config.redact_pii:
                result.cleaned_text = self._redact_pii(result.cleaned_text)
                result.warnings.append(
                    f"Redacted {len(result.pii_found)} PII element(s) from output"
                )

        return result

    def check_action(self, action: str, params: dict[str, Any]) -> ActionConfirmation | None:
        """Check if an action requires user confirmation.

        Returns an ActionConfirmation if the action is dangerous,
        or None if the action is safe to proceed.
        """
        if not self.config.require_confirmation:
            return None

        if action not in DANGEROUS_ACTIONS:
            return None

        # Determine risk level
        risk = "medium"
        if action in ("aws_lambda_invoke", "aws_s3_write", "snowflake_query"):
            risk = "high"
        elif action in ("gmail_send", "slack_post_message"):
            risk = "medium"

        descriptions = {
            "gmail_send": f"Send email to {params.get('to', '?')}: {params.get('subject', '?')}",
            "slack_post_message": f"Post to #{params.get('channel', '?')}: {params.get('message', '?')[:80]}",
            "github_create_issue": f"Create issue in {params.get('repo', '?')}: {params.get('title', '?')}",
            "aws_s3_write": f"Write to s3://{params.get('bucket', '?')}/{params.get('key', '?')}",
            "aws_lambda_invoke": f"Invoke Lambda: {params.get('function_name', '?')}",
            "stripe_create_customer": f"Create Stripe customer: {params.get('email', '?')}",
        }
        desc = descriptions.get(action, f"Execute {action} with {len(params)} params")

        return ActionConfirmation(
            action=action,
            params=params,
            risk_level=risk,
            description=desc,
        )

    # -- PII helpers --------------------------------------------------------

    def _detect_pii(self, text: str) -> list[PIIDetection]:
        """Scan text for PII patterns."""
        found: list[PIIDetection] = []
        for pii_type, pattern in PII_PATTERNS.items():
            for match in pattern.finditer(text):
                found.append(PIIDetection(
                    type=pii_type,
                    match=match.group()[:20] + "..." if len(match.group()) > 20 else match.group(),
                    position=(match.start(), match.end()),
                ))
        return found

    def _redact_pii(self, text: str) -> str:
        """Replace PII with redaction markers."""
        redacted = text
        for pii_type, pattern in PII_PATTERNS.items():
            label = f"[{pii_type.upper()}_REDACTED]"
            redacted = pattern.sub(label, redacted)
        return redacted
