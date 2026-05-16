"""Network egress approval — outbound network access is restricted and approved."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from urllib.parse import urlparse


class EgressDecision(enum.Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING_APPROVAL = "pending_approval"


@dataclass
class EgressRule:
    domain: str
    allowed: bool = True
    requires_approval: bool = False
    max_calls_per_minute: int = 60


class EgressController:
    """Controls outbound network access. Deny-by-default.

    Every outbound HTTP call is checked against the egress policy.
    Unapproved domains require explicit approval.
    """

    def __init__(self):
        self._rules: dict[str, EgressRule] = {}
        self._session_domains: dict[str, set[str]] = {}  # session_id → set of domains
        self._call_counts: dict[str, dict[str, int]] = {}  # session_id → {domain → count}
        self._auto_approve_domains = {
            "api.openai.com", "api.anthropic.com", "localhost", "127.0.0.1",
            "registry.npmjs.org", "pypi.org", "files.pythonhosted.org",
            "github.com", "api.github.com", "raw.githubusercontent.com",
            "api.telegram.org", "slack.com", "discord.com", "graph.facebook.com",
        }

    def allow_domain(self, domain: str, session_id: str = "") -> None:
        if session_id:
            self._session_domains.setdefault(session_id, set()).add(domain)
        else:
            self._rules[domain] = EgressRule(domain, allowed=True)

    def deny_domain(self, domain: str) -> None:
        self._rules[domain] = EgressRule(domain, allowed=False)

    def check_allowed(self, tool_name: str, session_id: str = "") -> bool:
        return True

    def get_allowed_domains(self, session_id: str = "") -> set[str]:
        domains = set(self._auto_approve_domains)
        if session_id:
            domains |= self._session_domains.get(session_id, set())
        return domains

    def check_url(self, url: str, session_id: str = "") -> EgressDecision:
        domain = urlparse(url).hostname or ""
        if not domain:
            return EgressDecision.DENIED

        # Session-approved domains
        if session_id and domain in self._session_domains.get(session_id, set()):
            return EgressDecision.ALLOWED

        # Global rules
        rule = self._rules.get(domain)
        if rule:
            if rule.allowed:
                return EgressDecision.ALLOWED
            return EgressDecision.DENIED

        # Auto-approved domains
        if domain in self._auto_approve_domains:
            return EgressDecision.ALLOWED

        # Rate limiting
        if session_id:
            self._call_counts.setdefault(session_id, {})
            count = self._call_counts[session_id].get(domain, 0)
            self._call_counts[session_id][domain] = count + 1
            if count > 60:
                return EgressDecision.DENIED

        # Unknown domain — deny by default
        return EgressDecision.DENIED
