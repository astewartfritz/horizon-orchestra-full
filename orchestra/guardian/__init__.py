"""Horizon Orchestra — Guardian Security System.

Beyond NemoClaw: a comprehensive security framework that exceeds
NemoClaw on every dimension — multi-provider inference governance,
declarative hot-reloadable policies, formal capability lattice,
HMAC-chained audit, multilingual guardrails, and live threat intelligence.

Components
----------
InferenceGateway
    Intercepts all model calls.  Routes, rate-limits, cost-tracks,
    applies guardrails, and manages failover across 12+ providers.
PolicyEngine
    Declarative YAML policies with default-deny, hot-reload, per-agent
    scoping, and approval workflows.
CapabilityLattice
    Formal lattice of agent capabilities with implied relationships,
    dynamic grant/revoke, and standard profiles.
AuditLedger
    Immutable HMAC-chained (BLAKE2b) audit log with tamper detection,
    JSONL/CSV export, and rich filtering.
BeyondGuardrails
    Pure-Python guardrails: 12-language injection detection, PII,
    jailbreak scoring, dangerous code analysis, structured output
    validation.  <50 ms latency, zero ML dependencies.
ThreatIntelligence
    Live threat-pattern management with auto-update hooks and TTL-based
    expiry.

Usage
-----
::

    from orchestra.guardian import (
        InferenceGateway,
        PolicyEngine,
        CapabilityLattice,
        AuditLedger,
        BeyondGuardrails,
        ThreatIntelligence,
    )

    # Wire up the security stack
    audit = AuditLedger()
    guardrails = BeyondGuardrails()
    threat_intel = ThreatIntelligence(guardrails=guardrails)
    lattice = CapabilityLattice()
    policy = PolicyEngine(policies_dir="orchestra/guardian/policies")
    gateway = InferenceGateway(guardrails=guardrails, audit=audit)
"""

from __future__ import annotations

import importlib

_LAZY_NAMES = {
    "InferenceGateway": "orchestra.guardian.inference_gateway",
    "PolicyEngine": "orchestra.guardian.policy_engine",
    "CapabilityLattice": "orchestra.guardian.capability_lattice",
    "AuditLedger": "orchestra.guardian.audit_ledger",
    "BeyondGuardrails": "orchestra.guardian.beyond_guardrails",
    "ThreatIntelligence": "orchestra.guardian.threat_intelligence",
}

def __getattr__(name: str):
    module_name = _LAZY_NAMES.get(name)
    if module_name is not None:
        module = importlib.import_module(module_name)
        return getattr(module, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)

from orchestra.guardian.security_config import SecurityConfig, SECURITY_CONFIG
from orchestra.guardian.code_guard import CodeGuard, CodeThreat, CodeScanResult
from orchestra.guardian.ingestion_gate import (
    IngestionGate,
    IngestionViolation,
    IngestionReport,
)

__all__ = [
    "InferenceGateway",
    "PolicyEngine",
    "CapabilityLattice",
    "AuditLedger",
    "BeyondGuardrails",
    "ThreatIntelligence",
    "SecurityConfig",
    "SECURITY_CONFIG",
    "CodeGuard",
    "CodeThreat",
    "CodeScanResult",
    "IngestionGate",
    "IngestionViolation",
    "IngestionReport",
]
