"""Horizon Orchestra — Unified Speech Provider.

Provides a single, consistent interface for speech-to-text (STT) and
text-to-speech (TTS) across cloud APIs and self-hosted open-source models.

Supported STT backends:
- **whisper_api** — OpenAI Whisper API (whisper-1, gpt-4o-transcribe,
  gpt-4o-mini-transcribe).  Reliable, 50+ languages, $0.006/min.
- **whisper_local** — Self-hosted faster-whisper (large-v3, large-v3-turbo)
  via an OpenAI-compatible local HTTP server.  Free after hardware cost.
- **deepgram** — Deepgram Nova-3.  Fastest real-time (<300ms), speaker
  diarization, 36+ languages, $0.0077/min.
- **assemblyai** — AssemblyAI async pipeline.  99+ languages, sentiment
  analysis, PII redaction, LeMUR audio intelligence.
- **groq_whisper** — Groq-hosted whisper-large-v3-turbo.  15x faster than
  real-time, $0.04/hour — extremely cost-effective.
- **elevenlabs_scribe** — ElevenLabs Scribe v2.  98%+ accuracy, 90+
  languages, $0.40–1.10/hour.

Supported TTS backends:
- **openai_tts** — OpenAI TTS (tts-1, tts-1-hd, gpt-4o-mini-tts).
  ~500ms latency, 10 voices, $15–30/1M chars.
- **elevenlabs** — ElevenLabs.  10,000+ voices, instant voice cloning,
  74 languages, 75ms Flash latency.
- **kokoro** — Local Kokoro TTS (82M params, Apache 2.0).  Highest MOS
  (4.5), runs on CPU, OpenAI-compatible endpoint.  Free.
- **fish_speech** — Fish Speech S2 (4B+400M dual-AR).  80+ languages,
  15,000+ emotion tags, zero-shot voice cloning.  Free (self-hosted).
- **chatterbox** — Chatterbox Turbo by Resemble AI (MIT).  Beats
  ElevenLabs in blind tests, 5s voice cloning, emotion control.  Free.
- **deepgram_aura** — Deepgram Aura-2.  Sub-200ms streaming TTS,
  $30/1M chars (same as OpenAI HD).

Quick-start examples::

    import asyncio
    from orchestra.speech_provider import SpeechProvider, STTConfig, TTSConfig
    from orchestra.speech_provider import STTBackend, TTSBackend

    provider = SpeechProvider()

    # Transcribe audio file
    async def demo():
        with open("speech.mp3", "rb") as f:
            audio_bytes = f.read()

        result = await provider.transcribe(audio_bytes)
        print(result.text)
        print(f"Language: {result.language}, Duration: {result.duration_seconds:.1f}s")

        # Transcribe with Deepgram + diarization
        dg_config = STTConfig(
            backend=STTBackend.DEEPGRAM,
            enable_diarization=True,
        )
        result2 = await provider.transcribe("conversation.wav", config=dg_config)
        for seg in result2.speakers:
            print(f"{seg.speaker}: {seg.text}")

        # Synthesise speech via OpenAI TTS
        tts_result = await provider.synthesize("Hello, world!")
        with open("output.mp3", "wb") as f:
            f.write(tts_result.audio_data)

        # Synthesise with ElevenLabs voice cloning
        with open("reference.wav", "rb") as f:
            ref_audio = f.read()
        el_config = TTSConfig(
            backend=TTSBackend.ELEVENLABS,
            voice="JBFqnCBsd6RMkjVDRZzb",
            voice_clone_audio=ref_audio,
        )
        cloned = await provider.synthesize("Welcome to Horizon Orchestra.", config=el_config)

        # Local Kokoro (free, CPU-viable)
        ko_config = TTSConfig(backend=TTSBackend.KOKORO, voice="af_heart")
        local_tts = await provider.synthesize("Free local speech!", config=ko_config)

    asyncio.run(demo())

Environment variables:
    OPENAI_API_KEY          — OpenAI Whisper + TTS
    DEEPGRAM_API_KEY        — Deepgram STT + Aura TTS
    ASSEMBLYAI_API_KEY      — AssemblyAI
    GROQ_API_KEY            — Groq Whisper
    ELEVENLABS_API_KEY      — ElevenLabs Scribe + TTS
    FISH_AUDIO_API_KEY      — Fish Audio hosted API
    KOKORO_BASE_URL         — Local Kokoro (default: http://localhost:8880/v1)
    FISH_SPEECH_BASE_URL    — Local Fish Speech (default: http://localhost:8080/v1)
    CHATTERBOX_BASE_URL     — Local Chatterbox (default: http://localhost:8765/v1)
    WHISPER_LOCAL_BASE_URL  — Local faster-whisper (default: http://localhost:8787/v1)
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Optional SDK imports
# ---------------------------------------------------------------------------

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    AsyncOpenAI = None  # type: ignore[assignment,misc]
    HAS_OPENAI = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    HAS_HTTPX = False

try:
    from faster_whisper import WhisperModel as FasterWhisperModel
    HAS_FASTER_WHISPER = True
except ImportError:
    FasterWhisperModel = None  # type: ignore[assignment,misc]
    HAS_FASTER_WHISPER = False

__all__ = [
    # Enums
    "STTBackend",
    "TTSBackend",
    "AudioFormat",
    # Config dataclasses
    "STTConfig",
    "TTSConfig",
    # Result dataclasses
    "TranscriptionResult",
    "TranscriptionSegment",
    "SpeakerSegment",
    "TTSResult",
    # Pricing helpers
    "STT_PRICING",
    "TTS_PRICING",
    "BACKEND_CAPABILITIES",
    "estimate_stt_cost",
    "estimate_tts_cost",
    # Provider
    "SpeechProvider",
]

log = logging.getLogger("orchestra.speech_provider")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class STTBackend(str, Enum):
    """Available speech-to-text backends."""
    WHISPER_API = "whisper_api"           # OpenAI Whisper API
    WHISPER_LOCAL = "whisper_local"       # Self-hosted via faster-whisper
    DEEPGRAM = "deepgram"                 # Deepgram Nova-3
    ASSEMBLYAI = "assemblyai"             # AssemblyAI
    GROQ_WHISPER = "groq_whisper"         # Groq-hosted Whisper
    ELEVENLABS_SCRIBE = "elevenlabs_scribe"  # ElevenLabs Scribe


class TTSBackend(str, Enum):
    """Available text-to-speech backends."""
    OPENAI_TTS = "openai_tts"            # OpenAI TTS
    ELEVENLABS = "elevenlabs"            # ElevenLabs
    KOKORO = "kokoro"                    # Local Kokoro TTS
    FISH_SPEECH = "fish_speech"          # Fish Speech S2
    CHATTERBOX = "chatterbox"            # Chatterbox/Resemble AI
    DEEPGRAM_AURA = "deepgram_aura"      # Deepgram Aura-2


class AudioFormat(str, Enum):
    """Supported audio output formats."""
    MP3 = "mp3"
    WAV = "wav"
    OGG = "ogg"
    FLAC = "flac"
    PCM = "pcm"
    OPUS = "opus"
    AAC = "aac"


# ---------------------------------------------------------------------------
# Pricing tables
# ---------------------------------------------------------------------------

STT_PRICING: dict[str, dict[str, Any]] = {
    "whisper_api": {"per_minute": 0.006, "model": "whisper-1"},
    "gpt4o_transcribe": {"per_minute": 0.006, "model": "gpt-4o-transcribe"},
    "gpt4o_mini_transcribe": {"per_minute": 0.003, "model": "gpt-4o-mini-transcribe"},
    "deepgram_nova3": {"per_minute": 0.0077, "model": "nova-3"},
    "groq_whisper": {"per_hour": 0.04, "model": "whisper-large-v3-turbo"},
    "elevenlabs_scribe": {"per_hour": 0.40, "model": "scribe-v2"},
    "local_whisper": {"per_minute": 0.0, "model": "large-v3-turbo"},
}

TTS_PRICING: dict[str, dict[str, Any]] = {
    "openai_tts1": {"per_1m_chars": 15.00, "model": "tts-1"},
    "openai_tts1_hd": {"per_1m_chars": 30.00, "model": "tts-1-hd"},
    "gpt4o_mini_tts": {"per_minute": 0.015, "model": "gpt-4o-mini-tts"},
    "elevenlabs_flash": {"per_1k_chars": 0.08, "model": "eleven_flash_v2_5"},
    "elevenlabs_multilingual": {"per_1k_chars": 0.12, "model": "eleven_multilingual_v2"},
    "kokoro": {"per_1m_chars": 0.0, "model": "kokoro"},
    "fish_speech": {"per_1m_chars": 0.0, "model": "fish-speech-s2"},
    "chatterbox": {"per_1m_chars": 0.0, "model": "chatterbox-turbo"},
    "deepgram_aura": {"per_1m_chars": 30.00, "model": "aura-2-en"},
}


# ---------------------------------------------------------------------------
# Backend capability table
# ---------------------------------------------------------------------------

BACKEND_CAPABILITIES: dict[str, dict[str, Any]] = {
    # STT backends
    "whisper_api": {
        "type": "stt", "provider": "openai", "languages": 50,
        "realtime": False, "diarization": False, "local": False,
        "description": "OpenAI hosted Whisper — reliable, 50+ languages, $0.006/min",
    },
    "whisper_local": {
        "type": "stt", "provider": "local", "languages": 99,
        "realtime": False, "diarization": False, "local": True,
        "description": "faster-whisper (large-v3-turbo) — self-hosted, free, CPU/GPU",
    },
    "deepgram": {
        "type": "stt", "provider": "deepgram", "languages": 36,
        "realtime": True, "diarization": True, "local": False,
        "description": "Deepgram Nova-3 — <300ms latency, best for real-time, $0.0077/min",
    },
    "assemblyai": {
        "type": "stt", "provider": "assemblyai", "languages": 99,
        "realtime": False, "diarization": True, "local": False,
        "description": "AssemblyAI — 99+ languages, sentiment, PII redaction, audio intelligence",
    },
    "groq_whisper": {
        "type": "stt", "provider": "groq", "languages": 99,
        "realtime": False, "diarization": False, "local": False,
        "description": "Groq Whisper large-v3-turbo — 15x real-time speed, $0.04/hour",
    },
    "elevenlabs_scribe": {
        "type": "stt", "provider": "elevenlabs", "languages": 90,
        "realtime": False, "diarization": False, "local": False,
        "description": "ElevenLabs Scribe v2 — 98%+ accuracy, 90+ languages, $0.40/hour",
    },
    # TTS backends
    "openai_tts": {
        "type": "tts", "provider": "openai", "languages": 50,
        "realtime": False, "voice_cloning": False, "local": False,
        "description": "OpenAI TTS — 10 voices, ~500ms latency, $15/1M chars",
    },
    "elevenlabs": {
        "type": "tts", "provider": "elevenlabs", "languages": 74,
        "realtime": True, "voice_cloning": True, "local": False,
        "description": "ElevenLabs — 10,000+ voices, 75ms Flash latency, voice cloning",
    },
    "kokoro": {
        "type": "tts", "provider": "local", "languages": 6,
        "realtime": True, "voice_cloning": False, "local": True,
        "description": "Kokoro — 82M params, Apache 2.0, runs on CPU, highest MOS (4.5)",
    },
    "fish_speech": {
        "type": "tts", "provider": "fish_audio", "languages": 80,
        "realtime": True, "voice_cloning": True, "local": True,
        "description": "Fish Speech S2 — emotion tags, voice cloning, 80+ languages, SOTA quality",
    },
    "chatterbox": {
        "type": "tts", "provider": "resemble", "languages": 1,
        "realtime": True, "voice_cloning": True, "local": True,
        "description": "Chatterbox Turbo — MIT license, beats ElevenLabs, 5s voice cloning",
    },
    "deepgram_aura": {
        "type": "tts", "provider": "deepgram", "languages": 1,
        "realtime": True, "voice_cloning": False, "local": False,
        "description": "Deepgram Aura-2 — sub-200ms streaming TTS, $30/1M chars",
    },
}


# ---------------------------------------------------------------------------
# Cost estimation helpers
# ---------------------------------------------------------------------------

def estimate_stt_cost(duration_seconds: float, backend: str) -> float:
    """Estimate the cost (USD) of transcribing ``duration_seconds`` of audio.

    Args:
        duration_seconds: Length of audio clip in seconds.
        backend: STT backend key from :data:`STT_PRICING` (e.g. ``"whisper_api"``).

    Returns:
        Estimated cost in USD.  Returns 0.0 for unknown or free backends.

    Example::

        cost = estimate_stt_cost(120.0, "deepgram_nova3")   # $0.0154
    """
    pricing = STT_PRICING.get(backend)
    if not pricing:
        return 0.0
    if "per_minute" in pricing:
        return (duration_seconds / 60.0) * pricing["per_minute"]
    if "per_hour" in pricing:
        return (duration_seconds / 3600.0) * pricing["per_hour"]
    return 0.0


def estimate_tts_cost(text: str, backend: str) -> float:
    """Estimate the cost (USD) of synthesising ``text`` to speech.

    Args:
        text: The input text to synthesise.
        backend: TTS backend key from :data:`TTS_PRICING`
                 (e.g. ``"elevenlabs_flash"``).

    Returns:
        Estimated cost in USD.  Returns 0.0 for unknown or free backends.

    Example::

        cost = estimate_tts_cost("Hello, world!", "openai_tts1")
    """
    pricing = TTS_PRICING.get(backend)
    if not pricing:
        return 0.0
    char_count = len(text)
    if "per_1m_chars" in pricing:
        return (char_count / 1_000_000.0) * pricing["per_1m_chars"]
    if "per_1k_chars" in pricing:
        return (char_count / 1_000.0) * pricing["per_1k_chars"]
    # per_minute: rough estimate assuming ~150 words/min and ~5 chars/word
    if "per_minute" in pricing:
        words = char_count / 5.0
        minutes = words / 150.0
        return minutes * pricing["per_minute"]
    return 0.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class STTConfig:
    """Configuration for a speech-to-text request.

    Attributes:
        backend: Which STT provider to use.
        model: Model identifier — auto-selected per backend when empty.
        language: BCP-47 language code (e.g. ``"en"``, ``"fr"``).
                  Leave empty for auto-detection.
        enable_diarization: Request speaker labels (Deepgram, AssemblyAI).
        enable_timestamps: Include word/segment timestamps in results.
        response_format: Whisper response format — ``"json"``, ``"text"``,
                         ``"srt"``, ``"vtt"``, or ``"verbose_json"``.
        temperature: Sampling temperature (0.0 = deterministic).
        sample_rate: Expected audio sample rate in Hz.
    """
    backend: STTBackend = STTBackend.WHISPER_API
    model: str = ""
    language: str = ""
    enable_diarization: bool = False
    enable_timestamps: bool = True
    response_format: str = "verbose_json"
    temperature: float = 0.0
    sample_rate: int = 16000


@dataclass
class TTSConfig:
    """Configuration for a text-to-speech request.

    Attributes:
        backend: Which TTS provider to use.
        model: Model identifier — auto-selected per backend when empty.
        voice: Voice ID or name — auto-selected per backend when empty.
        language: BCP-47 language code.
        output_format: Desired audio encoding.
        speed: Playback speed multiplier (1.0 = normal).
        sample_rate: Output audio sample rate in Hz.
        emotion: Emotion hint for Fish Speech / Chatterbox
                 (e.g. ``"happy"``, ``"[whisper]"``).
        voice_clone_audio: Raw reference audio bytes for zero-shot voice
                           cloning (ElevenLabs, Fish Speech, Chatterbox).
    """
    backend: TTSBackend = TTSBackend.OPENAI_TTS
    model: str = ""
    voice: str = ""
    language: str = "en"
    output_format: AudioFormat = AudioFormat.MP3
    speed: float = 1.0
    sample_rate: int = 24000
    emotion: str = ""
    voice_clone_audio: bytes | None = None


@dataclass
class TranscriptionSegment:
    """A timed segment of transcribed text.

    Attributes:
        text: Transcript text for this segment.
        start: Start time in seconds from the beginning of the audio.
        end: End time in seconds.
        confidence: Per-segment confidence score in [0, 1].
    """
    text: str
    start: float
    end: float
    confidence: float = 0.0


@dataclass
class SpeakerSegment:
    """A speaker-labelled segment (diarization output).

    Attributes:
        speaker: Speaker label, e.g. ``"speaker_0"``, ``"speaker_1"``.
        text: The words spoken by this speaker in this segment.
        start: Start time in seconds.
        end: End time in seconds.
    """
    speaker: str
    text: str
    start: float
    end: float


@dataclass
class TranscriptionResult:
    """Full result of a speech-to-text operation.

    Attributes:
        text: Full transcript as a plain string.
        language: Detected/specified language code.
        duration_seconds: Duration of the source audio.
        segments: List of timed :class:`TranscriptionSegment` objects.
        speakers: List of :class:`SpeakerSegment` objects (diarization).
        confidence: Overall confidence score in [0, 1].
        backend: Backend that produced this result.
        model: Specific model used.
        cost_estimate: Estimated cost in USD.
    """
    text: str
    language: str = ""
    duration_seconds: float = 0.0
    segments: list[TranscriptionSegment] = field(default_factory=list)
    speakers: list[SpeakerSegment] = field(default_factory=list)
    confidence: float = 0.0
    backend: str = ""
    model: str = ""
    cost_estimate: float = 0.0


@dataclass
class TTSResult:
    """Full result of a text-to-speech operation.

    Attributes:
        audio_data: Raw audio bytes in the requested format.
        format: Audio encoding of ``audio_data``.
        duration_seconds: Approximate duration of the synthesised audio.
        sample_rate: Sample rate of ``audio_data``.
        backend: Backend that produced this result.
        model: Specific model used.
        voice: Voice used for synthesis.
        cost_estimate: Estimated cost in USD.
    """
    audio_data: bytes
    format: AudioFormat
    duration_seconds: float = 0.0
    sample_rate: int = 24000
    backend: str = ""
    model: str = ""
    voice: str = ""
    cost_estimate: float = 0.0


# ---------------------------------------------------------------------------
# Default voice / model maps
# ---------------------------------------------------------------------------

_STT_DEFAULT_MODELS: dict[STTBackend, str] = {
    STTBackend.WHISPER_API: "whisper-1",
    STTBackend.WHISPER_LOCAL: "large-v3-turbo",
    STTBackend.DEEPGRAM: "nova-3",
    STTBackend.ASSEMBLYAI: "best",
    STTBackend.GROQ_WHISPER: "whisper-large-v3-turbo",
    STTBackend.ELEVENLABS_SCRIBE: "scribe_v1",
}

_TTS_DEFAULT_MODELS: dict[TTSBackend, str] = {
    TTSBackend.OPENAI_TTS: "tts-1",
    TTSBackend.ELEVENLABS: "eleven_multilingual_v2",
    TTSBackend.KOKORO: "kokoro",
    TTSBackend.FISH_SPEECH: "fish-speech-s2",
    TTSBackend.CHATTERBOX: "chatterbox-turbo",
    TTSBackend.DEEPGRAM_AURA: "aura-2-en",
}

_TTS_DEFAULT_VOICES: dict[TTSBackend, str] = {
    TTSBackend.OPENAI_TTS: "alloy",
    TTSBackend.ELEVENLABS: "JBFqnCBsd6RMkjVDRZzb",   # Rachel (multilingual)
    TTSBackend.KOKORO: "af_heart",
    TTSBackend.FISH_SPEECH: "default",
    TTSBackend.CHATTERBOX: "default",
    TTSBackend.DEEPGRAM_AURA: "aura-luna-en",
}

# Canonical voice lists (non-exhaustive; backends may have many more)
_TTS_VOICES: dict[TTSBackend, list[dict[str, str]]] = {
    TTSBackend.OPENAI_TTS: [
        {"id": "alloy", "name": "Alloy", "gender": "neutral"},
        {"id": "ash", "name": "Ash", "gender": "male"},
        {"id": "ballad", "name": "Ballad", "gender": "male"},
        {"id": "coral", "name": "Coral", "gender": "female"},
        {"id": "echo", "name": "Echo", "gender": "male"},
        {"id": "fable", "name": "Fable", "gender": "male"},
        {"id": "nova", "name": "Nova", "gender": "female"},
        {"id": "onyx", "name": "Onyx", "gender": "male"},
        {"id": "sage", "name": "Sage", "gender": "female"},
        {"id": "shimmer", "name": "Shimmer", "gender": "female"},
    ],
    TTSBackend.KOKORO: [
        {"id": "af_heart", "name": "Heart (AF)", "gender": "female", "lang": "en"},
        {"id": "af_bella", "name": "Bella (AF)", "gender": "female", "lang": "en"},
        {"id": "af_nicole", "name": "Nicole (AF)", "gender": "female", "lang": "en"},
        {"id": "af_sarah", "name": "Sarah (AF)", "gender": "female", "lang": "en"},
        {"id": "am_adam", "name": "Adam (AM)", "gender": "male", "lang": "en"},
        {"id": "am_michael", "name": "Michael (AM)", "gender": "male", "lang": "en"},
        {"id": "bf_emma", "name": "Emma (BF)", "gender": "female", "lang": "en-GB"},
        {"id": "bm_george", "name": "George (BM)", "gender": "male", "lang": "en-GB"},
    ],
    TTSBackend.DEEPGRAM_AURA: [
        {"id": "aura-asteria-en", "name": "Asteria", "gender": "female", "lang": "en"},
        {"id": "aura-luna-en", "name": "Luna", "gender": "female", "lang": "en"},
        {"id": "aura-stella-en", "name": "Stella", "gender": "female", "lang": "en"},
        {"id": "aura-athena-en", "name": "Athena", "gender": "female", "lang": "en"},
        {"id": "aura-hera-en", "name": "Hera", "gender": "female", "lang": "en"},
        {"id": "aura-orion-en", "name": "Orion", "gender": "male", "lang": "en"},
        {"id": "aura-arcas-en", "name": "Arcas", "gender": "male", "lang": "en"},
        {"id": "aura-perseus-en", "name": "Perseus", "gender": "male", "lang": "en"},
        {"id": "aura-angus-en", "name": "Angus", "gender": "male", "lang": "en-IE"},
        {"id": "aura-orpheus-en", "name": "Orpheus", "gender": "male", "lang": "en"},
        {"id": "aura-helios-en", "name": "Helios", "gender": "male", "lang": "en-GB"},
        {"id": "aura-zeus-en", "name": "Zeus", "gender": "male", "lang": "en"},
    ],
}


# ---------------------------------------------------------------------------
# SpeechProvider
# ---------------------------------------------------------------------------

class SpeechProvider:
    """Unified speech provider with pluggable STT and TTS backends.

    Supports both cloud APIs and local open-source models through
    a consistent interface.

    Args:
        stt_config: Default STT configuration (used when :meth:`transcribe`
                    is called without an explicit config override).
        tts_config: Default TTS configuration (used when :meth:`synthesize`
                    is called without an explicit config override).

    Example::

        provider = SpeechProvider(
            stt_config=STTConfig(backend=STTBackend.DEEPGRAM),
            tts_config=TTSConfig(backend=TTSBackend.KOKORO, voice="af_heart"),
        )
    """

    def __init__(
        self,
        stt_config: STTConfig | None = None,
        tts_config: TTSConfig | None = None,
    ) -> None:
        self.stt_config = stt_config or STTConfig()
        self.tts_config = tts_config or TTSConfig()
        self._openai_client: Any = None
        self._groq_client: Any = None
        self._kokoro_client: Any = None

    # ── Lazy client initialisation ─────────────────────────────────────────

    def _get_openai_client(self) -> Any:
        """Lazy-initialise the AsyncOpenAI client."""
        if self._openai_client is not None:
            return self._openai_client
        if not HAS_OPENAI:
            raise RuntimeError(
                "openai SDK is required for OpenAI backends. "
                "Install with: pip install openai"
            )
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is required.")
        self._openai_client = AsyncOpenAI(api_key=api_key)
        return self._openai_client

    def _get_groq_client(self) -> Any:
        """Lazy-initialise an OpenAI-compatible client pointing at Groq."""
        if self._groq_client is not None:
            return self._groq_client
        if not HAS_OPENAI:
            raise RuntimeError(
                "openai SDK is required for Groq backend. "
                "Install with: pip install openai"
            )
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is required.")
        self._groq_client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        return self._groq_client

    def _get_kokoro_client(self) -> Any:
        """Lazy-initialise an OpenAI-compatible client pointing at Kokoro."""
        if self._kokoro_client is not None:
            return self._kokoro_client
        if not HAS_OPENAI:
            raise RuntimeError(
                "openai SDK is required for Kokoro backend. "
                "Install with: pip install openai"
            )
        base_url = os.environ.get("KOKORO_BASE_URL", "http://localhost:8880/v1")
        # Kokoro may not require a key; use a placeholder so the SDK is happy
        self._kokoro_client = AsyncOpenAI(
            api_key=os.environ.get("KOKORO_API_KEY", "kokoro"),
            base_url=base_url,
        )
        return self._kokoro_client

    def _require_httpx(self) -> None:
        """Raise if httpx is not available."""
        if not HAS_HTTPX:
            raise RuntimeError(
                "httpx is required for REST-based backends. "
                "Install with: pip install httpx"
            )

    # ── Audio loading utility ──────────────────────────────────────────────

    async def _load_audio(self, audio: bytes | str) -> bytes:
        """Return audio bytes, reading from disk if ``audio`` is a file path."""
        if isinstance(audio, (bytes, bytearray)):
            return bytes(audio)
        # Treat as a file path — read in a thread to avoid blocking the loop
        path = str(audio)
        data = await asyncio.to_thread(_read_file, path)
        return data

    # =========================================================================
    # STT — public entry point
    # =========================================================================

    async def transcribe(
        self,
        audio: bytes | str,
        config: STTConfig | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio to text.

        Args:
            audio: Raw audio bytes or a file-system path to an audio file.
                   Accepts any format supported by the chosen backend
                   (mp3, wav, flac, ogg, m4a, webm, …).
            config: Optional per-call config that overrides the instance
                    default.  If ``None``, uses :attr:`stt_config`.

        Returns:
            :class:`TranscriptionResult` with transcript, timestamps, and
            optional speaker segments.

        Raises:
            RuntimeError: If a required SDK/package is not installed, or if
                          an API key is missing.
            ValueError: If the backend is unknown.
        """
        cfg = config or self.stt_config
        audio_bytes = await self._load_audio(audio)

        dispatch = {
            STTBackend.WHISPER_API: self._transcribe_whisper_api,
            STTBackend.WHISPER_LOCAL: self._transcribe_local_whisper,
            STTBackend.DEEPGRAM: self._transcribe_deepgram,
            STTBackend.ASSEMBLYAI: self._transcribe_assemblyai,
            STTBackend.GROQ_WHISPER: self._transcribe_groq,
            STTBackend.ELEVENLABS_SCRIBE: self._transcribe_elevenlabs,
        }

        handler = dispatch.get(cfg.backend)
        if handler is None:
            raise ValueError(f"Unknown STT backend: {cfg.backend!r}")

        log.debug("transcribe: backend=%s audio_size=%d bytes", cfg.backend, len(audio_bytes))
        result = await handler(audio_bytes, cfg)
        log.debug(
            "transcribe: backend=%s text_len=%d lang=%s duration=%.1fs cost=$%.5f",
            cfg.backend, len(result.text), result.language,
            result.duration_seconds, result.cost_estimate,
        )
        return result

    # =========================================================================
    # STT — backend implementations
    # =========================================================================

    async def _transcribe_whisper_api(
        self,
        audio: bytes,
        config: STTConfig,
    ) -> TranscriptionResult:
        """Transcribe via OpenAI Whisper API.

        Supports models: ``whisper-1``, ``gpt-4o-transcribe``,
        ``gpt-4o-mini-transcribe``.  Response format is set to
        ``verbose_json`` to retrieve segments and detected language.
        """
        client = self._get_openai_client()
        model = config.model or _STT_DEFAULT_MODELS[STTBackend.WHISPER_API]

        # Wrap bytes in a file-like object that the SDK can stream
        audio_file = io.BytesIO(audio)
        audio_file.name = "audio.mp3"  # hint for MIME detection

        kwargs: dict[str, Any] = {
            "model": model,
            "file": audio_file,
            "response_format": "verbose_json",
            "temperature": config.temperature,
        }
        if config.language:
            kwargs["language"] = config.language

        response = await client.audio.transcriptions.create(**kwargs)

        segments: list[TranscriptionSegment] = []
        raw_segments = getattr(response, "segments", None) or []
        for seg in raw_segments:
            segments.append(TranscriptionSegment(
                text=seg.get("text", ""),
                start=float(seg.get("start", 0.0)),
                end=float(seg.get("end", 0.0)),
                confidence=float(seg.get("avg_logprob", 0.0)),
            ))

        duration = getattr(response, "duration", 0.0) or 0.0
        language = getattr(response, "language", "") or ""
        text = getattr(response, "text", "") or ""

        pricing_key = (
            "gpt4o_transcribe" if "gpt-4o-transcribe" in model
            else "gpt4o_mini_transcribe" if "gpt-4o-mini" in model
            else "whisper_api"
        )
        cost = estimate_stt_cost(float(duration), pricing_key)

        return TranscriptionResult(
            text=text,
            language=language,
            duration_seconds=float(duration),
            segments=segments,
            backend=STTBackend.WHISPER_API.value,
            model=model,
            cost_estimate=cost,
        )

    async def _transcribe_local_whisper(
        self,
        audio: bytes,
        config: STTConfig,
    ) -> TranscriptionResult:
        """Transcribe via local faster-whisper.

        Falls back to an OpenAI-compatible local HTTP server if the
        ``faster_whisper`` Python package is not installed.  Set
        ``WHISPER_LOCAL_BASE_URL`` to point at your server
        (default: ``http://localhost:8787/v1``).
        """
        model_name = config.model or _STT_DEFAULT_MODELS[STTBackend.WHISPER_LOCAL]

        if HAS_FASTER_WHISPER:
            return await self._transcribe_faster_whisper_native(audio, config, model_name)

        # Fall back to OpenAI-compatible local server
        base_url = os.environ.get("WHISPER_LOCAL_BASE_URL", "http://localhost:8787/v1")
        if not HAS_OPENAI:
            raise RuntimeError(
                "Either faster_whisper or the openai SDK is required for the "
                "whisper_local backend. Install with: pip install faster-whisper "
                "or pip install openai"
            )
        client = AsyncOpenAI(
            api_key=os.environ.get("WHISPER_LOCAL_API_KEY", "local"),
            base_url=base_url,
        )
        audio_file = io.BytesIO(audio)
        audio_file.name = "audio.mp3"

        kwargs: dict[str, Any] = {
            "model": model_name,
            "file": audio_file,
            "response_format": "verbose_json",
            "temperature": config.temperature,
        }
        if config.language:
            kwargs["language"] = config.language

        response = await client.audio.transcriptions.create(**kwargs)
        text = getattr(response, "text", "") or ""
        language = getattr(response, "language", "") or ""
        duration = float(getattr(response, "duration", 0.0) or 0.0)

        return TranscriptionResult(
            text=text,
            language=language,
            duration_seconds=duration,
            backend=STTBackend.WHISPER_LOCAL.value,
            model=model_name,
            cost_estimate=0.0,
        )

    async def _transcribe_faster_whisper_native(
        self,
        audio: bytes,
        config: STTConfig,
        model_name: str,
    ) -> TranscriptionResult:
        """Transcribe using the faster-whisper Python library directly."""
        log.debug("faster-whisper: loading model %s", model_name)
        device = "cuda" if _cuda_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

        def _run() -> tuple[Any, Any]:
            model = FasterWhisperModel(model_name, device=device, compute_type=compute_type)
            audio_buffer = io.BytesIO(audio)
            segments_iter, info = model.transcribe(
                audio_buffer,
                language=config.language or None,
                beam_size=5,
                vad_filter=True,
                word_timestamps=config.enable_timestamps,
                temperature=config.temperature,
            )
            segs = list(segments_iter)
            return segs, info

        raw_segments, info = await asyncio.to_thread(_run)

        segments: list[TranscriptionSegment] = []
        full_text_parts: list[str] = []
        for seg in raw_segments:
            text_part = seg.text.strip()
            full_text_parts.append(text_part)
            segments.append(TranscriptionSegment(
                text=text_part,
                start=float(seg.start),
                end=float(seg.end),
                confidence=float(getattr(seg, "avg_logprob", 0.0)),
            ))

        return TranscriptionResult(
            text=" ".join(full_text_parts),
            language=getattr(info, "language", "") or "",
            duration_seconds=float(getattr(info, "duration", 0.0) or 0.0),
            segments=segments,
            backend=STTBackend.WHISPER_LOCAL.value,
            model=model_name,
            cost_estimate=0.0,
        )

    async def _transcribe_deepgram(
        self,
        audio: bytes,
        config: STTConfig,
    ) -> TranscriptionResult:
        """Transcribe via Deepgram Nova-3.

        Uses the REST ``/v1/listen`` endpoint.  Supports speaker
        diarization, smart formatting, and punctuation.
        """
        self._require_httpx()
        api_key = os.environ.get("DEEPGRAM_API_KEY", "")
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY environment variable is required.")

        model = config.model or _STT_DEFAULT_MODELS[STTBackend.DEEPGRAM]

        params: dict[str, Any] = {
            "model": model,
            "punctuate": "true",
            "smart_format": "true",
        }
        if config.language:
            params["language"] = config.language
        if config.enable_diarization:
            params["diarize"] = "true"
        if config.enable_timestamps:
            params["utterances"] = "true"

        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "audio/mpeg",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.deepgram.com/v1/listen",
                content=audio,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        results = data.get("results", {})
        channels = results.get("channels", [{}])
        alternatives = channels[0].get("alternatives", [{}]) if channels else [{}]
        best = alternatives[0] if alternatives else {}

        text = best.get("transcript", "")
        confidence = float(best.get("confidence", 0.0))
        words = best.get("words", [])

        segments: list[TranscriptionSegment] = []
        # Build coarse segments from words
        if words and config.enable_timestamps:
            current_words: list[str] = []
            seg_start = 0.0
            seg_end = 0.0
            for i, w in enumerate(words):
                if i == 0:
                    seg_start = float(w.get("start", 0.0))
                current_words.append(w.get("punctuated_word") or w.get("word", ""))
                seg_end = float(w.get("end", 0.0))
                # Flush segment every ~10 words or at end
                if len(current_words) >= 10 or i == len(words) - 1:
                    segments.append(TranscriptionSegment(
                        text=" ".join(current_words),
                        start=seg_start,
                        end=seg_end,
                        confidence=float(w.get("confidence", confidence)),
                    ))
                    current_words = []
                    seg_start = seg_end

        # Speaker diarization
        speakers: list[SpeakerSegment] = []
        if config.enable_diarization:
            utterances = results.get("utterances", [])
            for utt in utterances:
                speakers.append(SpeakerSegment(
                    speaker=f"speaker_{utt.get('speaker', 0)}",
                    text=utt.get("transcript", ""),
                    start=float(utt.get("start", 0.0)),
                    end=float(utt.get("end", 0.0)),
                ))

        metadata = data.get("metadata", {})
        duration = float(metadata.get("duration", 0.0) or 0.0)
        detected_lang = channels[0].get("detected_language", "") if channels else ""

        cost = estimate_stt_cost(duration, "deepgram_nova3")

        return TranscriptionResult(
            text=text,
            language=detected_lang or config.language,
            duration_seconds=duration,
            segments=segments,
            speakers=speakers,
            confidence=confidence,
            backend=STTBackend.DEEPGRAM.value,
            model=model,
            cost_estimate=cost,
        )

    async def _transcribe_assemblyai(
        self,
        audio: bytes,
        config: STTConfig,
    ) -> TranscriptionResult:
        """Transcribe via AssemblyAI.

        Three-step process:
        1. Upload audio bytes to get a hosted ``upload_url``.
        2. Submit a transcript request (async).
        3. Poll until ``status == "completed"`` or ``"error"``.
        """
        self._require_httpx()
        api_key = os.environ.get("ASSEMBLYAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("ASSEMBLYAI_API_KEY environment variable is required.")

        headers = {"authorization": api_key, "content-type": "application/json"}
        upload_headers = {"authorization": api_key}

        async with httpx.AsyncClient(timeout=120.0) as client:
            # Step 1 — upload audio
            upload_resp = await client.post(
                "https://api.assemblyai.com/v2/upload",
                content=audio,
                headers=upload_headers,
            )
            upload_resp.raise_for_status()
            upload_url = upload_resp.json()["upload_url"]

            # Step 2 — create transcript
            body: dict[str, Any] = {
                "audio_url": upload_url,
                "punctuate": True,
                "format_text": True,
            }
            if config.language:
                body["language_code"] = config.language
            else:
                body["language_detection"] = True
            if config.enable_diarization:
                body["speaker_labels"] = True
            if config.enable_timestamps:
                body["word_boost"] = []

            transcript_resp = await client.post(
                "https://api.assemblyai.com/v2/transcript",
                json=body,
                headers=headers,
            )
            transcript_resp.raise_for_status()
            transcript_id: str = transcript_resp.json()["id"]

            # Step 3 — poll for completion
            poll_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
            result_data: dict[str, Any] = {}
            for attempt in range(120):  # up to 120 * 2s = 4 minutes
                await asyncio.sleep(2.0)
                poll_resp = await client.get(poll_url, headers=headers)
                poll_resp.raise_for_status()
                result_data = poll_resp.json()
                status = result_data.get("status", "")
                if status == "completed":
                    break
                if status == "error":
                    raise RuntimeError(
                        f"AssemblyAI transcription error: {result_data.get('error')}"
                    )
                log.debug("AssemblyAI polling: attempt=%d status=%s", attempt, status)
            else:
                raise RuntimeError("AssemblyAI transcription timed out after 4 minutes.")

        text = result_data.get("text", "") or ""
        words = result_data.get("words", [])
        duration_ms = result_data.get("audio_duration", 0) or 0
        duration = float(duration_ms) / 1000.0 if duration_ms > 1000 else float(duration_ms)
        confidence = float(result_data.get("confidence", 0.0) or 0.0)
        detected_lang = result_data.get("language_code", "") or ""

        segments: list[TranscriptionSegment] = []
        if config.enable_timestamps and words:
            current_words_text: list[str] = []
            seg_start = 0.0
            seg_end = 0.0
            for i, w in enumerate(words):
                if i == 0:
                    seg_start = float(w.get("start", 0)) / 1000.0
                current_words_text.append(w.get("text", ""))
                seg_end = float(w.get("end", 0)) / 1000.0
                if len(current_words_text) >= 10 or i == len(words) - 1:
                    segments.append(TranscriptionSegment(
                        text=" ".join(current_words_text),
                        start=seg_start,
                        end=seg_end,
                        confidence=float(w.get("confidence", confidence)),
                    ))
                    current_words_text = []
                    seg_start = seg_end

        speakers: list[SpeakerSegment] = []
        if config.enable_diarization:
            for utt in result_data.get("utterances", []):
                speakers.append(SpeakerSegment(
                    speaker=f"speaker_{utt.get('speaker', 'A')}",
                    text=utt.get("text", ""),
                    start=float(utt.get("start", 0)) / 1000.0,
                    end=float(utt.get("end", 0)) / 1000.0,
                ))

        cost = estimate_stt_cost(duration, "elevenlabs_scribe")  # comparable tier

        return TranscriptionResult(
            text=text,
            language=detected_lang or config.language,
            duration_seconds=duration,
            segments=segments,
            speakers=speakers,
            confidence=confidence,
            backend=STTBackend.ASSEMBLYAI.value,
            model=config.model or _STT_DEFAULT_MODELS[STTBackend.ASSEMBLYAI],
            cost_estimate=cost,
        )

    async def _transcribe_groq(
        self,
        audio: bytes,
        config: STTConfig,
    ) -> TranscriptionResult:
        """Transcribe via Groq-hosted Whisper.

        Uses an OpenAI-compatible endpoint at ``https://api.groq.com/openai/v1``
        with ``whisper-large-v3-turbo`` — 15x faster than real-time.
        """
        client = self._get_groq_client()
        model = config.model or _STT_DEFAULT_MODELS[STTBackend.GROQ_WHISPER]

        audio_file = io.BytesIO(audio)
        audio_file.name = "audio.mp3"

        kwargs: dict[str, Any] = {
            "model": model,
            "file": audio_file,
            "response_format": "verbose_json",
            "temperature": config.temperature,
        }
        if config.language:
            kwargs["language"] = config.language

        response = await client.audio.transcriptions.create(**kwargs)

        segments: list[TranscriptionSegment] = []
        raw_segments = getattr(response, "segments", None) or []
        for seg in raw_segments:
            segments.append(TranscriptionSegment(
                text=seg.get("text", ""),
                start=float(seg.get("start", 0.0)),
                end=float(seg.get("end", 0.0)),
            ))

        duration = float(getattr(response, "duration", 0.0) or 0.0)
        language = getattr(response, "language", "") or ""
        text = getattr(response, "text", "") or ""
        cost = estimate_stt_cost(duration, "groq_whisper")

        return TranscriptionResult(
            text=text,
            language=language,
            duration_seconds=duration,
            segments=segments,
            backend=STTBackend.GROQ_WHISPER.value,
            model=model,
            cost_estimate=cost,
        )

    async def _transcribe_elevenlabs(
        self,
        audio: bytes,
        config: STTConfig,
    ) -> TranscriptionResult:
        """Transcribe via ElevenLabs Scribe.

        Posts to ``/v1/speech-to-text`` as a multipart form upload.
        """
        self._require_httpx()
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            raise RuntimeError("ELEVENLABS_API_KEY environment variable is required.")

        model = config.model or _STT_DEFAULT_MODELS[STTBackend.ELEVENLABS_SCRIBE]

        files = {"audio": ("audio.mp3", audio, "audio/mpeg")}
        data: dict[str, Any] = {"model_id": model}
        if config.language:
            data["language_code"] = config.language
        if config.enable_timestamps:
            data["timestamps_granularity"] = "word"

        headers = {"xi-api-key": api_key}

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.elevenlabs.io/v1/speech-to-text",
                files=files,
                data=data,
                headers=headers,
            )
            response.raise_for_status()
            result_data: dict[str, Any] = response.json()

        text = result_data.get("text", "") or ""
        language = result_data.get("language_code", "") or ""
        duration_ms = result_data.get("audio_duration_ms", 0) or 0
        duration = float(duration_ms) / 1000.0

        segments: list[TranscriptionSegment] = []
        for word_info in result_data.get("words", []):
            segments.append(TranscriptionSegment(
                text=word_info.get("text", ""),
                start=float(word_info.get("start_time_ms", 0)) / 1000.0,
                end=float(word_info.get("end_time_ms", 0)) / 1000.0,
            ))

        cost = estimate_stt_cost(duration, "elevenlabs_scribe")

        return TranscriptionResult(
            text=text,
            language=language,
            duration_seconds=duration,
            segments=segments,
            backend=STTBackend.ELEVENLABS_SCRIBE.value,
            model=model,
            cost_estimate=cost,
        )

    # =========================================================================
    # TTS — public entry point
    # =========================================================================

    async def synthesize(
        self,
        text: str,
        config: TTSConfig | None = None,
    ) -> TTSResult:
        """Convert text to speech audio.

        Args:
            text: The input text to synthesise.
            config: Optional per-call config that overrides the instance
                    default.  If ``None``, uses :attr:`tts_config`.

        Returns:
            :class:`TTSResult` containing raw audio bytes, format metadata,
            and cost estimate.

        Raises:
            RuntimeError: If a required SDK/package is not installed or an
                          API key is missing.
            ValueError: If the backend is unknown.
        """
        cfg = config or self.tts_config

        dispatch = {
            TTSBackend.OPENAI_TTS: self._synthesize_openai,
            TTSBackend.ELEVENLABS: self._synthesize_elevenlabs,
            TTSBackend.KOKORO: self._synthesize_kokoro,
            TTSBackend.FISH_SPEECH: self._synthesize_fish_speech,
            TTSBackend.CHATTERBOX: self._synthesize_chatterbox,
            TTSBackend.DEEPGRAM_AURA: self._synthesize_deepgram_aura,
        }

        handler = dispatch.get(cfg.backend)
        if handler is None:
            raise ValueError(f"Unknown TTS backend: {cfg.backend!r}")

        log.debug("synthesize: backend=%s text_len=%d", cfg.backend, len(text))
        result = await handler(text, cfg)
        log.debug(
            "synthesize: backend=%s audio_size=%d cost=$%.5f",
            cfg.backend, len(result.audio_data), result.cost_estimate,
        )
        return result

    # =========================================================================
    # TTS — backend implementations
    # =========================================================================

    async def _synthesize_openai(
        self,
        text: str,
        config: TTSConfig,
    ) -> TTSResult:
        """TTS via OpenAI.

        Supports ``tts-1``, ``tts-1-hd``, and ``gpt-4o-mini-tts``.
        Returns audio in the requested format (default mp3).
        """
        client = self._get_openai_client()
        model = config.model or _TTS_DEFAULT_MODELS[TTSBackend.OPENAI_TTS]
        voice = config.voice or _TTS_DEFAULT_VOICES[TTSBackend.OPENAI_TTS]
        fmt = config.output_format.value

        kwargs: dict[str, Any] = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": fmt,
        }
        if config.speed != 1.0:
            kwargs["speed"] = config.speed

        response = await client.audio.speech.create(**kwargs)
        audio_data = response.content

        pricing_key = (
            "gpt4o_mini_tts" if "gpt-4o-mini" in model
            else "openai_tts1_hd" if "hd" in model
            else "openai_tts1"
        )
        cost = estimate_tts_cost(text, pricing_key)

        return TTSResult(
            audio_data=audio_data,
            format=config.output_format,
            sample_rate=config.sample_rate,
            backend=TTSBackend.OPENAI_TTS.value,
            model=model,
            voice=voice,
            cost_estimate=cost,
        )

    async def _synthesize_elevenlabs(
        self,
        text: str,
        config: TTSConfig,
    ) -> TTSResult:
        """TTS via ElevenLabs.

        Supports voice cloning via ``config.voice_clone_audio`` (instant
        cloning from 5s reference audio).  Uses ``eleven_multilingual_v2``
        or ``eleven_flash_v2_5`` depending on the configured model.
        """
        self._require_httpx()
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            raise RuntimeError("ELEVENLABS_API_KEY environment variable is required.")

        model = config.model or _TTS_DEFAULT_MODELS[TTSBackend.ELEVENLABS]
        voice_id = config.voice or _TTS_DEFAULT_VOICES[TTSBackend.ELEVENLABS]

        body: dict[str, Any] = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        params: dict[str, str] = {"output_format": "mp3_44100_128"}
        if config.output_format in (AudioFormat.WAV, AudioFormat.PCM):
            params["output_format"] = "pcm_44100"
        elif config.output_format == AudioFormat.OPUS:
            params["output_format"] = "opus_48000_32"

        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            response = await client.post(url, json=body, headers=headers, params=params)
            response.raise_for_status()
            audio_data = response.content

        pricing_key = (
            "elevenlabs_flash" if "flash" in model or "turbo" in model
            else "elevenlabs_multilingual"
        )
        cost = estimate_tts_cost(text, pricing_key)

        return TTSResult(
            audio_data=audio_data,
            format=config.output_format,
            sample_rate=config.sample_rate,
            backend=TTSBackend.ELEVENLABS.value,
            model=model,
            voice=voice_id,
            cost_estimate=cost,
        )

    async def _synthesize_kokoro(
        self,
        text: str,
        config: TTSConfig,
    ) -> TTSResult:
        """TTS via local Kokoro (OpenAI-compatible endpoint).

        Kokoro runs as a local HTTP server with an OpenAI-compatible
        ``/v1/audio/speech`` endpoint.  Set ``KOKORO_BASE_URL`` to point at
        your server (default: ``http://localhost:8880/v1``).

        Kokoro is free (Apache 2.0), achieves MOS 4.5, and is CPU-viable
        at ~5x real-time on modern hardware.
        """
        client = self._get_kokoro_client()
        model = config.model or _TTS_DEFAULT_MODELS[TTSBackend.KOKORO]
        voice = config.voice or _TTS_DEFAULT_VOICES[TTSBackend.KOKORO]
        fmt = config.output_format.value

        kwargs: dict[str, Any] = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": fmt,
        }
        if config.speed != 1.0:
            kwargs["speed"] = config.speed

        response = await client.audio.speech.create(**kwargs)
        audio_data = response.content

        return TTSResult(
            audio_data=audio_data,
            format=config.output_format,
            sample_rate=config.sample_rate,
            backend=TTSBackend.KOKORO.value,
            model=model,
            voice=voice,
            cost_estimate=0.0,
        )

    async def _synthesize_fish_speech(
        self,
        text: str,
        config: TTSConfig,
    ) -> TTSResult:
        """TTS via Fish Speech S2.

        Supports emotion tags inline — e.g. ``"[whisper]Hello[/whisper]"`` or
        ``"[laughing nervously]I'm not sure about this."`` — using the model's
        15,000+ emotion/tone vocabulary.

        Voice cloning: supply a reference WAV/MP3 in
        ``config.voice_clone_audio``.  Fish Speech performs zero-shot cloning
        from 3–10 seconds of reference audio.

        If ``FISH_SPEECH_BASE_URL`` is set, uses the local server endpoint;
        otherwise falls back to the hosted Fish Audio API
        (requires ``FISH_AUDIO_API_KEY``).
        """
        self._require_httpx()

        local_base = os.environ.get("FISH_SPEECH_BASE_URL", "")
        input_text = text

        # Wrap with emotion tag if requested and not already tagged
        if config.emotion and not input_text.startswith("["):
            tag = config.emotion.strip("[]")
            input_text = f"[{tag}]{input_text}[/{tag}]"

        if local_base:
            return await self._synthesize_fish_local(input_text, config, local_base)
        return await self._synthesize_fish_cloud(input_text, config)

    async def _synthesize_fish_local(
        self,
        text: str,
        config: TTSConfig,
        base_url: str,
    ) -> TTSResult:
        """Fish Speech via local OpenAI-compatible server."""
        if not HAS_OPENAI:
            raise RuntimeError(
                "openai SDK is required for local Fish Speech. "
                "Install with: pip install openai"
            )
        client = AsyncOpenAI(
            api_key=os.environ.get("FISH_SPEECH_API_KEY", "local"),
            base_url=base_url.rstrip("/"),
        )
        model = config.model or _TTS_DEFAULT_MODELS[TTSBackend.FISH_SPEECH]
        voice = config.voice or _TTS_DEFAULT_VOICES[TTSBackend.FISH_SPEECH]

        response = await client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format=config.output_format.value,
        )
        audio_data = response.content

        return TTSResult(
            audio_data=audio_data,
            format=config.output_format,
            sample_rate=config.sample_rate,
            backend=TTSBackend.FISH_SPEECH.value,
            model=model,
            voice=voice,
            cost_estimate=0.0,
        )

    async def _synthesize_fish_cloud(
        self,
        text: str,
        config: TTSConfig,
    ) -> TTSResult:
        """Fish Speech via hosted Fish Audio API."""
        api_key = os.environ.get("FISH_AUDIO_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "FISH_AUDIO_API_KEY is required for cloud Fish Speech, "
                "or set FISH_SPEECH_BASE_URL for local deployment."
            )

        model = config.model or _TTS_DEFAULT_MODELS[TTSBackend.FISH_SPEECH]
        voice = config.voice or ""

        body: dict[str, Any] = {
            "text": text,
            "format": config.output_format.value,
            "mp3_bitrate": 128,
            "normalize": True,
            "latency": "normal",
        }
        if voice and voice != "default":
            body["reference_id"] = voice
        if config.voice_clone_audio:
            # Inline reference audio for zero-shot voice cloning
            import base64 as _b64
            body["references"] = [
                {"audio": _b64.b64encode(config.voice_clone_audio).decode()}
            ]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.fish.audio/v1/tts",
                json=body,
                headers=headers,
            )
            response.raise_for_status()
            audio_data = response.content

        return TTSResult(
            audio_data=audio_data,
            format=config.output_format,
            sample_rate=config.sample_rate,
            backend=TTSBackend.FISH_SPEECH.value,
            model=model,
            voice=voice,
            cost_estimate=0.0,
        )

    async def _synthesize_chatterbox(
        self,
        text: str,
        config: TTSConfig,
    ) -> TTSResult:
        """TTS via Chatterbox (Resemble AI, MIT license).

        Chatterbox Turbo achieves sub-150ms first-token latency and beats
        ElevenLabs in blind preference tests (63.75% preference rate).

        Voice cloning: supply ``config.voice_clone_audio`` with 5+ seconds
        of reference audio.  Emotion control is available via
        ``config.emotion`` (e.g. ``"happy"``, ``"sad"``, ``"excited"``).

        Set ``CHATTERBOX_BASE_URL`` to point at your local server
        (default: ``http://localhost:8765/v1``).
        """
        self._require_httpx()
        base_url = os.environ.get("CHATTERBOX_BASE_URL", "http://localhost:8765/v1")

        body: dict[str, Any] = {
            "text": text,
            "output_format": config.output_format.value,
            "sample_rate": config.sample_rate,
        }
        if config.voice and config.voice != "default":
            body["voice"] = config.voice
        if config.emotion:
            body["emotion"] = config.emotion
        if config.speed != 1.0:
            body["speed"] = config.speed
        if config.voice_clone_audio:
            import base64 as _b64
            body["reference_audio"] = _b64.b64encode(config.voice_clone_audio).decode()

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/octet-stream",
        }
        api_key = os.environ.get("CHATTERBOX_API_KEY", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        model = config.model or _TTS_DEFAULT_MODELS[TTSBackend.CHATTERBOX]
        voice = config.voice or _TTS_DEFAULT_VOICES[TTSBackend.CHATTERBOX]

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/audio/speech",
                json=body,
                headers=headers,
            )
            response.raise_for_status()
            audio_data = response.content

        return TTSResult(
            audio_data=audio_data,
            format=config.output_format,
            sample_rate=config.sample_rate,
            backend=TTSBackend.CHATTERBOX.value,
            model=model,
            voice=voice,
            cost_estimate=0.0,
        )

    async def _synthesize_deepgram_aura(
        self,
        text: str,
        config: TTSConfig,
    ) -> TTSResult:
        """TTS via Deepgram Aura-2.

        Sub-200ms first-chunk latency, streaming-capable.  Uses the
        ``/v1/speak`` REST endpoint with a model query parameter.
        """
        self._require_httpx()
        api_key = os.environ.get("DEEPGRAM_API_KEY", "")
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY environment variable is required.")

        model = config.model or _TTS_DEFAULT_MODELS[TTSBackend.DEEPGRAM_AURA]
        voice = config.voice or _TTS_DEFAULT_VOICES[TTSBackend.DEEPGRAM_AURA]

        # Aura-2 uses the voice name as the model parameter when a specific
        # voice is requested; otherwise fall back to the model field
        effective_model = voice if voice.startswith("aura-") else model

        params: dict[str, str] = {"model": effective_model}
        # Map AudioFormat to Deepgram encoding
        encoding_map = {
            AudioFormat.MP3: "mp3",
            AudioFormat.WAV: "linear16",
            AudioFormat.OPUS: "opus",
            AudioFormat.FLAC: "flac",
            AudioFormat.PCM: "linear16",
            AudioFormat.AAC: "aac",
            AudioFormat.OGG: "opus",
        }
        encoding = encoding_map.get(config.output_format, "mp3")
        params["encoding"] = encoding

        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.deepgram.com/v1/speak",
                json={"text": text},
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            audio_data = response.content

        cost = estimate_tts_cost(text, "deepgram_aura")

        return TTSResult(
            audio_data=audio_data,
            format=config.output_format,
            sample_rate=config.sample_rate,
            backend=TTSBackend.DEEPGRAM_AURA.value,
            model=effective_model,
            voice=voice,
            cost_estimate=cost,
        )

    # =========================================================================
    # Utility / introspection methods
    # =========================================================================

    def get_backend_info(self, backend: str) -> dict[str, Any]:
        """Return the capability info dict for a backend.

        Args:
            backend: Backend key (e.g. ``"deepgram"``, ``"kokoro"``).

        Returns:
            Dict from :data:`BACKEND_CAPABILITIES`, or an empty dict if
            the backend is unknown.

        Example::

            info = provider.get_backend_info("deepgram")
            print(info["description"])
        """
        return BACKEND_CAPABILITIES.get(backend, {})

    def list_backends(self) -> dict[str, list[str]]:
        """Return all available STT and TTS backend identifiers.

        Returns:
            Dict with keys ``"stt"`` and ``"tts"``, each containing a list
            of backend identifier strings.

        Example::

            backends = provider.list_backends()
            print(backends["tts"])  # ['openai_tts', 'elevenlabs', ...]
        """
        stt: list[str] = []
        tts: list[str] = []
        for key, info in BACKEND_CAPABILITIES.items():
            if info.get("type") == "stt":
                stt.append(key)
            elif info.get("type") == "tts":
                tts.append(key)
        return {"stt": stt, "tts": tts}

    def list_voices(self, backend: TTSBackend) -> list[dict[str, str]]:
        """Return the built-in voice list for a TTS backend.

        Note: For ElevenLabs, Fish Speech, and Chatterbox the full voice
        catalogues are much larger and available via their respective APIs.
        This returns only the commonly used preset voices known at
        build time.

        Args:
            backend: A :class:`TTSBackend` enum value.

        Returns:
            List of dicts with at least ``"id"`` and ``"name"`` keys.

        Example::

            voices = provider.list_voices(TTSBackend.OPENAI_TTS)
            for v in voices:
                print(v["id"], v["name"])
        """
        return list(_TTS_VOICES.get(backend, []))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_file(path: str) -> bytes:
    """Synchronous file read — called in a thread via asyncio.to_thread."""
    with open(path, "rb") as fh:
        return fh.read()


def _cuda_available() -> bool:
    """Return True if a CUDA GPU is available (best-effort)."""
    try:
        import torch  # type: ignore[import]
        return torch.cuda.is_available()
    except ImportError:
        pass
    try:
        import subprocess  # noqa: S603
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False
