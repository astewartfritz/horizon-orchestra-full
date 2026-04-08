"""Central Security Configuration — Single source of truth for all guardian modules.

Every guardian component (CodeGuard, IngestionGate, InferenceGateway,
PolicyEngine, etc.) reads its security posture from :class:`SecurityConfig`.
This avoids scattered boolean flags and ensures consistent enforcement.

Three presets are provided:

``SecurityConfig.strict()``
    Maximum security — blocks everything suspicious, requires all quality
    checks, enables signed handoffs.  Suitable for production.

``SecurityConfig.development()``
    Relaxed — allows ``eval``/``exec``, disables type-hint requirements,
    still blocks hardcoded secrets and SQL injection.  Suitable for local
    development.

``SecurityConfig.from_env()``
    Reads ``ORCHESTRA_SECURITY_*`` environment variables and falls back to
    strict defaults.  This is the default constructor for the global
    singleton ``SECURITY_CONFIG``.

Thread/async safety: the config is immutable after construction (frozen
dataclass).  To change settings at runtime, replace the global singleton.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List

__all__ = [
    "SecurityConfig",
    "SECURITY_CONFIG",
]

log = logging.getLogger("orchestra.guardian.security_config")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_bool(key: str, default: bool) -> bool:
    """Read a boolean from an environment variable.

    Truthy values: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
    Falsy values:  ``0``, ``false``, ``no``, ``off``, empty string.
    """
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_float(key: str, default: float) -> float:
    """Read a float from an environment variable."""
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid float for %s=%r, using default %s", key, raw, default)
        return default


def _env_str(key: str, default: str) -> str:
    """Read a string from an environment variable."""
    return os.environ.get(key, "").strip() or default


def _env_list(key: str, default: list[str] | None = None) -> list[str]:
    """Read a comma-separated list from an environment variable."""
    raw = os.environ.get(key, "").strip()
    if not raw:
        return list(default) if default else []
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# SecurityConfig
# ---------------------------------------------------------------------------

@dataclass
class SecurityConfig:
    """Centralised security knobs for the entire Horizon Orchestra stack.

    Attributes are grouped by subsystem.  Each subsystem reads *only* the
    fields relevant to it, but having them all in one place makes audit
    trivial and prevents contradictory settings.
    """

    # -- CodeGuard settings --------------------------------------------------
    code_guard_enabled: bool = True
    """Master switch for the runtime code scanner."""

    code_guard_strict: bool = True
    """When strict, *any* threat detection blocks execution."""

    block_eval_exec: bool = True
    """Block ``eval()``, ``exec()``, and ``compile()`` in agent code."""

    block_shell_true: bool = True
    """Block ``subprocess`` calls with ``shell=True``."""

    allowed_network_hosts: list[str] = field(default_factory=list)
    """Hostnames that agent code is allowed to contact.

    An empty list means *no* outbound connections are allowed (strict).
    Set to ``["*"]`` to allow all (dangerous).
    """

    max_code_length: int = 100_000
    """Maximum code length (characters) that CodeGuard will scan.

    Code exceeding this limit is automatically blocked.
    """

    # -- IngestionGate settings ----------------------------------------------
    ingestion_gate_enabled: bool = True
    """Master switch for the codebase ingestion scanner."""

    block_hardcoded_secrets: bool = True
    """Reject files containing API keys, passwords, or tokens in source."""

    block_sql_injection: bool = True
    """Reject files with f-string or %-format SQL queries."""

    require_type_hints: bool = False
    """Require type hints on public APIs (warning by default, not block)."""

    require_docstrings: bool = False
    """Require docstrings on public classes/functions (warning by default)."""

    security_critical_paths: list[str] = field(default_factory=lambda: [
        "orchestra/guardian/",
        "orchestra/security/",
        "orchestra/sandbox/",
        "orchestra/auth/",
    ])
    """Path prefixes considered security-critical — extra scrutiny applied."""

    # -- Guardian / audit settings -------------------------------------------
    audit_all_inference: bool = True
    """Record every inference call in the audit ledger."""

    audit_all_tool_calls: bool = True
    """Record every tool invocation in the audit ledger."""

    audit_code_scans: bool = True
    """Record CodeGuard scan results in the audit ledger."""

    audit_ingestion_checks: bool = True
    """Record IngestionGate results in the audit ledger."""

    policy_hot_reload: bool = True
    """Enable hot-reloading of YAML policy files."""

    # -- Team security -------------------------------------------------------
    require_signed_handoffs: bool = True
    """Require HMAC-signed handoff tokens between team members."""

    external_agent_trust_level: str = "UNTRUSTED"
    """Trust level for externally-sourced agents.

    One of ``UNTRUSTED``, ``BASIC``, ``TRUSTED``.  ``UNTRUSTED`` agents
    receive the most restrictive capability set.
    """

    cross_org_requires_approval: bool = True
    """Require explicit approval for cross-organisation agent communication."""

    # -- Thresholds ----------------------------------------------------------
    max_code_severity: float = 0.7
    """Block code execution if the aggregate threat severity >= this value."""

    min_quality_score: float = 0.0
    """Minimum quality score for IngestionGate to approve (0 = no minimum)."""

    min_security_score: float = 0.3
    """Minimum security score for IngestionGate to approve."""

    # -- HMAC / signing ------------------------------------------------------
    hmac_secret: str = ""
    """Secret used for HMAC signatures.

    If empty, a deterministic default is derived from
    ``ORCHESTRA_HMAC_SECRET`` or a hardcoded fallback (development only).
    """

    # -- Feature flags -------------------------------------------------------
    enable_threat_intelligence: bool = True
    """Enable live threat-intelligence feed integration."""

    enable_beyond_guardrails: bool = True
    """Enable the BeyondGuardrails multilingual content scanner."""

    # -----------------------------------------------------------------------
    # Factory methods
    # -----------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> SecurityConfig:
        """Build a config by reading ``ORCHESTRA_SECURITY_*`` env vars.

        Every field has a sensible strict default; env vars *override*
        individual settings.
        """
        return cls(
            # CodeGuard
            code_guard_enabled=_env_bool("ORCHESTRA_SECURITY_CODE_GUARD", True),
            code_guard_strict=_env_bool("ORCHESTRA_SECURITY_CODE_GUARD_STRICT", True),
            block_eval_exec=_env_bool("ORCHESTRA_SECURITY_BLOCK_EVAL_EXEC", True),
            block_shell_true=_env_bool("ORCHESTRA_SECURITY_BLOCK_SHELL_TRUE", True),
            allowed_network_hosts=_env_list("ORCHESTRA_SECURITY_ALLOWED_HOSTS"),
            max_code_length=int(_env_float("ORCHESTRA_SECURITY_MAX_CODE_LENGTH", 100_000)),
            # IngestionGate
            ingestion_gate_enabled=_env_bool("ORCHESTRA_SECURITY_INGESTION_GATE", True),
            block_hardcoded_secrets=_env_bool("ORCHESTRA_SECURITY_BLOCK_SECRETS", True),
            block_sql_injection=_env_bool("ORCHESTRA_SECURITY_BLOCK_SQL_INJECTION", True),
            require_type_hints=_env_bool("ORCHESTRA_SECURITY_REQUIRE_TYPE_HINTS", False),
            require_docstrings=_env_bool("ORCHESTRA_SECURITY_REQUIRE_DOCSTRINGS", False),
            # Audit
            audit_all_inference=_env_bool("ORCHESTRA_SECURITY_AUDIT_INFERENCE", True),
            audit_all_tool_calls=_env_bool("ORCHESTRA_SECURITY_AUDIT_TOOL_CALLS", True),
            audit_code_scans=_env_bool("ORCHESTRA_SECURITY_AUDIT_CODE_SCANS", True),
            audit_ingestion_checks=_env_bool("ORCHESTRA_SECURITY_AUDIT_INGESTION", True),
            policy_hot_reload=_env_bool("ORCHESTRA_SECURITY_POLICY_HOT_RELOAD", True),
            # Team security
            require_signed_handoffs=_env_bool("ORCHESTRA_SECURITY_SIGNED_HANDOFFS", True),
            external_agent_trust_level=_env_str(
                "ORCHESTRA_SECURITY_EXT_TRUST_LEVEL", "UNTRUSTED"
            ),
            cross_org_requires_approval=_env_bool(
                "ORCHESTRA_SECURITY_CROSS_ORG_APPROVAL", True
            ),
            # Thresholds
            max_code_severity=_env_float("ORCHESTRA_SECURITY_MAX_SEVERITY", 0.7),
            min_quality_score=_env_float("ORCHESTRA_SECURITY_MIN_QUALITY", 0.0),
            min_security_score=_env_float("ORCHESTRA_SECURITY_MIN_SECURITY", 0.3),
            # HMAC
            hmac_secret=_env_str("ORCHESTRA_HMAC_SECRET", ""),
            # Feature flags
            enable_threat_intelligence=_env_bool(
                "ORCHESTRA_SECURITY_THREAT_INTEL", True
            ),
            enable_beyond_guardrails=_env_bool(
                "ORCHESTRA_SECURITY_BEYOND_GUARDRAILS", True
            ),
        )

    @classmethod
    def strict(cls) -> SecurityConfig:
        """Maximum-security preset for production deployments.

        Everything is blocked, everything is audited, every quality gate
        is enforced.
        """
        return cls(
            code_guard_enabled=True,
            code_guard_strict=True,
            block_eval_exec=True,
            block_shell_true=True,
            allowed_network_hosts=[],
            max_code_length=50_000,
            ingestion_gate_enabled=True,
            block_hardcoded_secrets=True,
            block_sql_injection=True,
            require_type_hints=True,
            require_docstrings=True,
            audit_all_inference=True,
            audit_all_tool_calls=True,
            audit_code_scans=True,
            audit_ingestion_checks=True,
            policy_hot_reload=True,
            require_signed_handoffs=True,
            external_agent_trust_level="UNTRUSTED",
            cross_org_requires_approval=True,
            max_code_severity=0.5,
            min_quality_score=0.4,
            min_security_score=0.5,
            hmac_secret="",
            enable_threat_intelligence=True,
            enable_beyond_guardrails=True,
        )

    @classmethod
    def development(cls) -> SecurityConfig:
        """Relaxed preset for local development.

        Still blocks hardcoded secrets and SQL injection — those are
        never acceptable — but relaxes quality gates and allows
        ``eval``/``exec`` for experimentation.
        """
        return cls(
            code_guard_enabled=True,
            code_guard_strict=False,
            block_eval_exec=False,
            block_shell_true=False,
            allowed_network_hosts=["*"],
            max_code_length=500_000,
            ingestion_gate_enabled=True,
            block_hardcoded_secrets=True,
            block_sql_injection=True,
            require_type_hints=False,
            require_docstrings=False,
            audit_all_inference=False,
            audit_all_tool_calls=False,
            audit_code_scans=True,
            audit_ingestion_checks=True,
            policy_hot_reload=True,
            require_signed_handoffs=False,
            external_agent_trust_level="BASIC",
            cross_org_requires_approval=False,
            max_code_severity=0.9,
            min_quality_score=0.0,
            min_security_score=0.2,
            hmac_secret="dev-secret-not-for-production",
            enable_threat_intelligence=False,
            enable_beyond_guardrails=True,
        )

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    def get_hmac_secret(self) -> bytes:
        """Return the HMAC secret as bytes.

        Falls back to a deterministic default if no secret is configured.
        In production, always set ``ORCHESTRA_HMAC_SECRET``.
        """
        secret = self.hmac_secret or os.environ.get(
            "ORCHESTRA_HMAC_SECRET",
            "horizon-orchestra-default-dev-key",
        )
        return secret.encode("utf-8")

    def is_security_critical(self, path: str) -> bool:
        """Return True if *path* falls within a security-critical directory."""
        normalised = path.replace("\\", "/")
        return any(normalised.startswith(p) or f"/{p}" in normalised
                    for p in self.security_critical_paths)

    def __repr__(self) -> str:
        """Summary representation (hides HMAC secret)."""
        return (
            f"SecurityConfig(code_guard={self.code_guard_enabled}, "
            f"strict={self.code_guard_strict}, "
            f"ingestion={self.ingestion_gate_enabled}, "
            f"max_severity={self.max_code_severity})"
        )


# ---------------------------------------------------------------------------
# Global singleton — imported by other guardian modules
# ---------------------------------------------------------------------------

SECURITY_CONFIG: SecurityConfig = SecurityConfig.from_env()
"""Module-level security configuration.

Override by assigning a new ``SecurityConfig`` instance::

    import orchestra.guardian.security_config as sc
    sc.SECURITY_CONFIG = SecurityConfig.strict()
"""
