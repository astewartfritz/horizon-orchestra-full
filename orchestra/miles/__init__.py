"""
miles — Proactive AI assistant layer for Horizon Orchestra.

Exports all public symbols from the MILES sub-modules so callers
can do simple imports, e.g.::

    from orchestra.miles import ProactiveEngine, VoiceAssistant
"""
from __future__ import annotations

__all__ = [
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
]

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
