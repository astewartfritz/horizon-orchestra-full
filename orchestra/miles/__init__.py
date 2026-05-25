"""M.I.L.E.S — Machine Intelligence Learning and Execution System.

Proactive AI assistant layer for Horizon Orchestra.  Import the top-level
``MILES`` class for normal use, or import individual subsystem classes
for custom wiring::

    from orchestra.miles import MILES, MILESConfig
    from orchestra.miles import ProactiveEngine, VoiceAssistant
"""
from __future__ import annotations

__all__ = [
    # Top-level façade
    "MILES",
    "MILESConfig",
    # intelligence
    "Suggestion",
    "Pattern",
    "ProactiveEngine",
    "ActionPredictor",
    # voice
    "VoiceConfig",
    "TranscriptionResult",
    "TextToSpeech",
    "SpeechToText",
    "VoiceResponse",
    "VoiceAssistant",
    # awareness
    "AwarenessState",
    "UrgentItem",
    "AmbientAwareness",
    # routines
    "RoutineConfig",
    "Briefing",
    "Summary",
    "Reminder",
    "MorningBriefing",
    "DailySummary",
    "SmartReminder",
    "RoutineManager",
    # enterprise
    "SSOConfig",
    "SSOEngine",
    "RBACEngine",
    "Role",
    "TenantStore",
    "TenantContext",
    "current_tenant",
    "scim_router",
    "sso_middleware",
    "tenant_middleware",
    "tenant_admin_router",
    "rbac_dependency",
    # channels
    "ChannelHub",
    "ChannelMessage",
    "ChannelResponse",
    "ChannelAdapter",
    "ConsentRegistry",
    "ChannelGuardrails",
    "GuardrailConfig",
    "IngestionPipeline",
    "SlackChannelAdapter",
    "TelegramChannelAdapter",
    "GmailChannelAdapter",
    "WhatsAppChannelAdapter",
    "InstagramChannelAdapter",
    "IMessageChannelAdapter",
]

from orchestra.miles.core import MILES, MILESConfig
from orchestra.miles.intelligence import (
    ActionPredictor,
    Pattern,
    ProactiveEngine,
    Suggestion,
)
from orchestra.miles.awareness import (
    AmbientAwareness,
    AwarenessState,
    UrgentItem,
)
from orchestra.miles.voice import (
    SpeechToText,
    TextToSpeech,
    TranscriptionResult,
    VoiceAssistant,
    VoiceConfig,
    VoiceResponse,
)
from orchestra.miles.routines import (
    Briefing,
    DailySummary,
    MorningBriefing,
    Reminder,
    RoutineConfig,
    RoutineManager,
    SmartReminder,
    Summary,
)
from orchestra.miles.enterprise import (
    SSOConfig,
    SSOEngine,
    RBACEngine,
    Role,
    TenantStore,
    TenantContext,
    current_tenant,
    scim_router,
    sso_middleware,
    tenant_middleware,
    tenant_admin_router,
    rbac_dependency,
)
from orchestra.miles.channels import (
    ChannelAdapter,
    ChannelGuardrails,
    ChannelHub,
    ChannelMessage,
    ChannelResponse,
    ConsentRegistry,
    GmailChannelAdapter,
    GuardrailConfig,
    IMessageChannelAdapter,
    IngestionPipeline,
    InstagramChannelAdapter,
    SlackChannelAdapter,
    TelegramChannelAdapter,
    WhatsAppChannelAdapter,
)
