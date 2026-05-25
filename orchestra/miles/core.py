"""M.I.L.E.S — Machine Intelligence Learning and Execution System.

Top-level façade that wires all MILES subsystems (awareness, intelligence,
voice, routines) into a single coherent interface backed by Orchestra's
multi-model router and memory system.

Usage::

    from orchestra.router import ModelRouter
    from orchestra.memory import MemoryManager
    from orchestra.miles.core import MILES, MILESConfig

    router = ModelRouter()
    memory = MemoryManager(user_id="ashton")

    async with MILES(router=router, memory=memory) as miles:
        response = await miles.run("What should I focus on today?")
        briefing = await miles.brief()
        reminders = await miles.remind()
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from orchestra.miles._utils import extract_content, router_chat
from orchestra.miles.awareness import AmbientAwareness
from orchestra.miles.intelligence import ActionPredictor, ProactiveEngine, Suggestion
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
from orchestra.miles.voice import (
    SpeechToText,
    TextToSpeech,
    VoiceAssistant,
    VoiceConfig,
    VoiceResponse,
)

log = logging.getLogger("orchestra.miles")

# Channels are optional — don't break MILES if the extras aren't installed
try:
    from orchestra.miles.channels.base import ChannelHub, ConsentRegistry
    from orchestra.miles.channels.guardrails import ChannelGuardrails, GuardrailConfig
    from orchestra.miles.channels.pipeline import IngestionPipeline
    _CHANNELS_AVAILABLE = True
except ImportError:
    _CHANNELS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class MILESConfig:
    """Top-level MILES configuration."""

    user_id: str = "default"
    timezone: str = "America/Chicago"
    morning_briefing_time: str = "08:00"
    evening_summary_time: str = "18:00"
    enable_smart_reminders: bool = True
    preferred_model: str = "kimi-k2.5"
    voice_config: VoiceConfig | None = None


# ---------------------------------------------------------------------------
# MILES
# ---------------------------------------------------------------------------

class MILES:
    """M.I.L.E.S — Machine Intelligence Learning and Execution System.

    A proactive AI assistant that unifies Orchestra's full capability stack:
    multi-model routing, persistent memory, ambient context awareness,
    voice I/O, smart reminders, and behavioural learning.

    Designed as the single entry point for all personal-assistant workloads —
    the spiritual successor to every JARVIS-style AI assistant, rebuilt on
    Orchestra's production-grade infrastructure.

    Examples
    --------
    Minimal setup (text-only, no voice, no routines)::

        miles = MILES(router=router, memory=memory)
        response = await miles.run("Summarise my day.")

    Full setup with voice and scheduled routines::

        config = MILESConfig(voice_config=VoiceConfig(), user_id="ashton")
        async with MILES(router, memory, connectors=connectors,
                         config=config, scheduler=scheduler) as miles:
            audio_response = await miles.listen(audio_bytes)
    """

    name = "M.I.L.E.S"
    full_name = "Machine Intelligence Learning and Execution System"

    SYSTEM_PROMPT = (
        "You are M.I.L.E.S (Machine Intelligence Learning and Execution System), "
        "a proactive personal AI assistant powered by Horizon Orchestra. "
        "You are intelligent, concise, and deeply integrated with the user's "
        "calendar, email, tasks, and workflow.\n\n"
        "Personality:\n"
        "- Confident and direct — get to the point immediately\n"
        "- Proactive — volunteer relevant next steps without being asked\n"
        "- Adaptive — acknowledge what you've learned from past interactions\n"
        "- Honest — never fabricate information; say so when you don't know\n\n"
        "Always address the user in second person ('You have…', 'I recommend…')."
    )

    def __init__(
        self,
        router: Any,
        memory: Any,
        connectors: dict[str, Any] | None = None,
        config: MILESConfig | None = None,
        scheduler: Any = None,
        notifications: Any = None,
        channel_hub: Any | None = None,
    ) -> None:
        self._router = router
        self._memory = memory
        self._config = config or MILESConfig()
        self._connectors = connectors or {}

        # -- subsystems -------------------------------------------------------
        self.awareness = AmbientAwareness(
            connectors=self._connectors,
            memory_manager=memory,
            router=router,
            user_id=self._config.user_id,
            timezone_str=self._config.timezone,
        )
        self.intelligence = ProactiveEngine(
            memory_manager=memory,
            router=router,
            user_id=self._config.user_id,
        )
        self.predictor = ActionPredictor(
            memory_manager=memory,
            router=router,
            user_id=self._config.user_id,
        )

        # -- optional voice ---------------------------------------------------
        self._voice: VoiceAssistant | None = None
        if self._config.voice_config:
            stt = SpeechToText(self._config.voice_config)
            tts = TextToSpeech(self._config.voice_config)
            self._voice = VoiceAssistant(stt=stt, tts=tts, agent=self)

        # -- optional channel hub (multi-channel ingestion) -------------------
        self._channel_hub: Any | None = channel_hub

        # -- optional routine manager -----------------------------------------
        self._routines: RoutineManager | None = None
        if scheduler is not None:
            self._routines = RoutineManager(
                config=RoutineConfig(
                    user_id=self._config.user_id,
                    timezone=self._config.timezone,
                    morning_briefing_time=self._config.morning_briefing_time,
                    evening_summary_time=self._config.evening_summary_time,
                    enable_smart_reminders=self._config.enable_smart_reminders,
                ),
                awareness=self.awareness,
                memory=memory,
                scheduler=scheduler,
                notifications=notifications,
            )

        log.info(
            "%s initialised — user=%s model=%s voice=%s routines=%s",
            self.name,
            self._config.user_id,
            self._config.preferred_model,
            "on" if self._voice else "off",
            "on" if self._routines else "off",
        )

    # -- primary text interface -----------------------------------------------

    async def run(
        self,
        user_input: str,
        context: list[dict[str, str]] | None = None,
    ) -> str:
        """Process any text input and return a response.

        Automatically injects ambient awareness context and proactive
        suggestions into the system prompt before calling the LLM.
        """
        awareness_ctx, suggestions = await asyncio.gather(
            self.awareness.get_briefing_context(),
            self.intelligence.suggest(user_input),
        )

        suggestion_block = ""
        if suggestions:
            lines = [f"  [{s.priority}] {s.action}" for s in suggestions[:3]]
            suggestion_block = "\n\nProactive context:\n" + "\n".join(lines)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "system",
                "content": f"Current environment:\n{awareness_ctx}{suggestion_block}",
            },
            *(context or []),
            {"role": "user", "content": user_input},
        ]

        resp = await router_chat(
            self._router,
            messages=messages,
            model=self._config.preferred_model,
            max_tokens=1024,
        )
        reply = extract_content(resp)

        # Persist interaction as a workflow pattern for future suggestions
        asyncio.create_task(
            self.intelligence.learn_pattern(
                action=user_input[:80],
                context=awareness_ctx[:200],
                outcome="ok",
            )
        )

        return reply

    # -- briefing / summary ---------------------------------------------------

    async def brief(self) -> Briefing:
        """Generate a morning briefing from ambient context."""
        return await MorningBriefing(router=self._router).generate(self.awareness)

    async def summarise(self) -> Summary:
        """Generate an end-of-day summary."""
        return await DailySummary(router=self._router).generate(
            self.awareness, self._memory
        )

    async def remind(self) -> list[Reminder]:
        """Return all active smart reminders right now."""
        return await SmartReminder(router=self._router).check(
            self.awareness, self._memory
        )

    async def suggest(self, context: str = "") -> list[Suggestion]:
        """Return proactive action suggestions for the given context."""
        if not context:
            context = await self.awareness.get_briefing_context()
        return await self.intelligence.suggest(context)

    async def predict_next(self, history: list[str]) -> list[str]:
        """Predict the user's most likely next actions given a history list."""
        return await self.predictor.predict_next(history)

    # -- voice interface -------------------------------------------------------

    async def listen(self, audio_data: bytes) -> VoiceResponse:
        """Full voice pipeline: audio bytes → text → agent → audio bytes."""
        if self._voice is None:
            raise RuntimeError(
                "Voice is not configured. "
                "Pass config=MILESConfig(voice_config=VoiceConfig()) to MILES()."
            )
        return await self._voice.process_voice(audio_data)

    async def speak(self, text: str) -> bytes:
        """Synthesize *text* to MP3 audio bytes."""
        if self._voice is None:
            raise RuntimeError(
                "Voice is not configured. "
                "Pass config=MILESConfig(voice_config=VoiceConfig()) to MILES()."
            )
        return await self._voice._tts.synthesize(text)

    # -- lifecycle -------------------------------------------------------------

    async def setup(self) -> None:
        """Initialise all subsystems and register scheduled routines."""
        if self._routines is not None:
            await self._routines.setup_routines()

    def build_channel_hub(
        self,
        consent: Any | None = None,
        guardrail_config: Any | None = None,
        poll_interval: float = 10.0,
    ) -> Any:
        """Create and wire a ChannelHub backed by this MILES instance.

        Call ``hub.register(adapter)`` on the result to add channel adapters,
        then ``await hub.start()`` to begin polling.

        Parameters
        ----------
        consent:
            A ``ConsentRegistry`` instance.  If None, one is created at the
            default path (``~/.horizon/miles_consent.db``).
        guardrail_config:
            A ``GuardrailConfig`` instance.  If None, defaults are used.
        poll_interval:
            Seconds between polling cycles for adapters that support polling.
        """
        if not _CHANNELS_AVAILABLE:
            raise RuntimeError(
                "Multi-channel support requires httpx: pip install httpx"
            )
        if consent is None:
            consent = ConsentRegistry()
        guardrails = ChannelGuardrails(
            config=guardrail_config or GuardrailConfig(),
            router=self._router,
        )
        pipeline = IngestionPipeline(miles=self, guardrails=guardrails)
        hub = ChannelHub(
            consent=consent,
            pipeline=pipeline.process,
            poll_interval=poll_interval,
        )
        self._channel_hub = hub
        return hub

    def start(self) -> None:
        """Start background monitoring (reminder polling loop)."""
        if self._routines is not None:
            self._routines.start()
        log.info("%s background monitoring started.", self.name)

    def stop(self) -> None:
        """Stop all background tasks gracefully."""
        if self._routines is not None:
            self._routines.stop()
        log.info("%s background monitoring stopped.", self.name)

    # -- async context manager -------------------------------------------------

    async def __aenter__(self) -> "MILES":
        await self.setup()
        self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        self.stop()

    # -- VoiceAssistant agent interface ----------------------------------------

    async def run_as_agent(self, text: str) -> str:
        """Called by VoiceAssistant as its backing agent."""
        return await self.run(text)
