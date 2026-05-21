try:
    from orchestra.code_agent.security.capability_auth import (
        Capability, AgentIdentity, CapabilityToken, CapabilityVault,
        DynamicAuthPolicy, JustInTimeGrant, GrantEntry, GrantRequest,
    )
except ImportError:
    Capability = AgentIdentity = CapabilityToken = CapabilityVault = None  # type: ignore[assignment]
    DynamicAuthPolicy = JustInTimeGrant = GrantEntry = GrantRequest = None  # type: ignore[assignment]

from orchestra.code_agent.security.scanner import SecretScanner, ScanResult
from orchestra.code_agent.security.gateway import SecurityGateway, SecurityContext, AccessLevel
from orchestra.code_agent.security.layers import (
    SecurityLayers, NetworkLayer, FilesystemLayer,
    ProcessLayer, InferenceLayer, LayerDecision,
)
from orchestra.code_agent.security.channel_auth import ChannelAuth, AuthResult, AuthDecision
from orchestra.code_agent.security.egress import EgressController, EgressRule, EgressDecision

# ── Agent-aware security modules ────────────────────────────────────────
from orchestra.code_agent.security.pii_redactor import (
    PIIRedactor, PIICategory, PIIType, HIPAAContext, GDPRContext,
)
from orchestra.code_agent.security.data_classifier import (
    DataClassifier, DataTag, ClassificationRule, SensitivityLevel,
)
from orchestra.code_agent.security.consent_manager import (
    ConsentManager, ConsentRecord, ConsentPurpose,
)
from orchestra.code_agent.security.audit import AuditEvent, AuditStore
from orchestra.code_agent.security.anomaly import AnomalyDetector, AnomalyEvent, AnomalyRule, AnomalySeverity
from orchestra.code_agent.security.approval import (
    ApprovalWorkflow, ApprovalRequest, ApprovalPolicy, ApprovalStatus, ApprovalRequired,
)
from orchestra.code_agent.security.middleware import SecurityMiddleware, SecurityContext as SecContext, register_security

__all__ = [
    # Legacy
    "SecretScanner", "ScanResult",
    "SecurityGateway", "SecurityContext", "AccessLevel",
    "SecurityLayers", "NetworkLayer", "FilesystemLayer",
    "ProcessLayer", "InferenceLayer", "LayerDecision",
    "ChannelAuth", "AuthResult", "AuthDecision",
    "EgressController", "EgressRule", "EgressDecision",
    "Capability", "AgentIdentity", "CapabilityToken", "CapabilityVault",
    "DynamicAuthPolicy", "JustInTimeGrant", "GrantEntry", "GrantRequest",
    # Agent-aware security
    "PIIRedactor", "PIICategory", "PIIType", "HIPAAContext", "GDPRContext",
    "DataClassifier", "DataTag", "ClassificationRule", "SensitivityLevel",
    "ConsentManager", "ConsentRecord", "ConsentPurpose",
    "AuditEvent", "AuditStore",
    "AnomalyDetector", "AnomalyEvent", "AnomalyRule", "AnomalySeverity",
    "ApprovalWorkflow", "ApprovalRequest", "ApprovalPolicy", "ApprovalStatus", "ApprovalRequired",
    "SecurityMiddleware", "register_security",
]
