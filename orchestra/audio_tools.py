"""Horizon Orchestra — Audio Tools for Agent Loop.

Registers speech-to-text and text-to-speech tools into the agent's
tool surface, enabling any agent to:

1. Transcribe audio files to text (STT)
2. Generate speech from text (TTS)
3. Analyse audio content (duration, format, speakers)
4. Clone a voice from reference audio
5. Translate speech across languages

These tools wrap the SpeechProvider backends and integrate with
the standard ToolRegistry from agent_loop.py.

Usage::

    from orchestra.audio_tools import register_audio_tools
    from orchestra.agent_loop import create_default_tools

    tools = create_default_tools(router)
    register_audio_tools(tools)
    # Now agents can call: transcribe_audio, synthesize_speech,
    # analyze_audio, clone_voice, translate_speech
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
import wave
from pathlib import Path
from typing import Any

log = logging.getLogger("orchestra.audio_tools")

__all__ = ["register_audio_tools"]


# ---------------------------------------------------------------------------
# Backend capability table
# ---------------------------------------------------------------------------

# Each entry: (display_name, type, supports_diarization, supports_timestamps,
#              cost_per_minute_usd, notes)
BACKEND_CAPABILITIES: dict[str, dict[str, Any]] = {
    # STT backends
    "whisper_api": {
        "type": "stt",
        "display_name": "OpenAI Whisper API",
        "diarization": False,
        "timestamps": True,
        "cost_per_minute_usd": 0.006,
        "languages": "99+",
        "notes": "Requires OPENAI_API_KEY",
    },
    "deepgram": {
        "type": "stt",
        "display_name": "Deepgram Nova-2",
        "diarization": True,
        "timestamps": True,
        "cost_per_minute_usd": 0.0043,
        "languages": "30+",
        "notes": "Requires DEEPGRAM_API_KEY",
    },
    "assemblyai": {
        "type": "stt",
        "display_name": "AssemblyAI Universal-2",
        "diarization": True,
        "timestamps": True,
        "cost_per_minute_usd": 0.0083,
        "languages": "17+",
        "notes": "Requires ASSEMBLYAI_API_KEY",
    },
    "groq_whisper": {
        "type": "stt",
        "display_name": "Groq Whisper Large v3",
        "diarization": False,
        "timestamps": True,
        "cost_per_minute_usd": 0.0002,
        "languages": "99+",
        "notes": "Requires GROQ_API_KEY. Fastest option.",
    },
    "elevenlabs_scribe": {
        "type": "stt",
        "display_name": "ElevenLabs Scribe v1",
        "diarization": True,
        "timestamps": True,
        "cost_per_minute_usd": 0.004,
        "languages": "30+",
        "notes": "Requires ELEVENLABS_API_KEY",
    },
    "whisper_local": {
        "type": "stt",
        "display_name": "Whisper Local (whisper.cpp / faster-whisper)",
        "diarization": False,
        "timestamps": True,
        "cost_per_minute_usd": 0.0,
        "languages": "99+",
        "notes": "No API key required. Requires local model installation.",
    },
    # TTS backends
    "openai_tts": {
        "type": "tts",
        "display_name": "OpenAI TTS (tts-1 / tts-1-hd)",
        "voice_clone": False,
        "emotion_control": False,
        "cost_per_1k_chars_usd": 0.015,
        "formats": ["mp3", "opus", "aac", "flac", "wav", "pcm"],
        "notes": "Requires OPENAI_API_KEY. Voices: alloy, echo, fable, onyx, nova, shimmer.",
    },
    "elevenlabs": {
        "type": "tts",
        "display_name": "ElevenLabs",
        "voice_clone": True,
        "emotion_control": False,
        "cost_per_1k_chars_usd": 0.03,
        "formats": ["mp3", "pcm", "ulaw"],
        "notes": "Requires ELEVENLABS_API_KEY. Supports voice cloning.",
    },
    "kokoro": {
        "type": "tts",
        "display_name": "Kokoro TTS",
        "voice_clone": False,
        "emotion_control": False,
        "cost_per_1k_chars_usd": 0.0,
        "formats": ["wav", "mp3"],
        "notes": "Open-source, runs locally. No API key required.",
    },
    "fish_speech": {
        "type": "tts",
        "display_name": "Fish Speech",
        "voice_clone": True,
        "emotion_control": True,
        "cost_per_1k_chars_usd": 0.0,
        "formats": ["wav", "mp3"],
        "notes": "Open-source, runs locally. Supports voice cloning and emotion tags.",
    },
    "chatterbox": {
        "type": "tts",
        "display_name": "Chatterbox TTS",
        "voice_clone": True,
        "emotion_control": True,
        "cost_per_1k_chars_usd": 0.0,
        "formats": ["wav", "mp3"],
        "notes": "Open-source. Best voice-cloning quality. Requires GPU for real-time.",
    },
    "deepgram_aura": {
        "type": "tts",
        "display_name": "Deepgram Aura",
        "voice_clone": False,
        "emotion_control": False,
        "cost_per_1k_chars_usd": 0.0135,
        "formats": ["mp3", "opus", "flac", "aac", "wav", "mulaw"],
        "notes": "Requires DEEPGRAM_API_KEY. Ultra-low latency for streaming.",
    },
}

# Cost estimates by STT backend (per minute of audio, in USD)
_STT_COST_PER_MINUTE: dict[str, float] = {
    k: v["cost_per_minute_usd"]
    for k, v in BACKEND_CAPABILITIES.items()
    if v["type"] == "stt"
}


# ---------------------------------------------------------------------------
# Audio metadata helpers
# ---------------------------------------------------------------------------

def _probe_with_ffprobe(audio_path: str) -> dict[str, Any] | None:
    """Use ffprobe to get audio metadata. Returns None if ffprobe not available."""
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            audio_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)

        fmt = data.get("format", {})
        duration = float(fmt.get("duration", 0.0))
        format_name = fmt.get("format_name", "")
        file_size = int(fmt.get("size", 0))

        # Find the first audio stream
        audio_stream: dict[str, Any] = {}
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                audio_stream = stream
                break

        sample_rate = int(audio_stream.get("sample_rate", 0))
        channels = int(audio_stream.get("channels", 0))
        codec = audio_stream.get("codec_name", "")

        return {
            "duration_seconds": round(duration, 3),
            "format": format_name,
            "codec": codec,
            "sample_rate_hz": sample_rate,
            "channels": channels,
            "file_size_bytes": file_size,
            "probe_method": "ffprobe",
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


def _probe_wav_stdlib(audio_path: str) -> dict[str, Any] | None:
    """Use Python's wave module to read WAV metadata. Returns None on failure."""
    try:
        with wave.open(audio_path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            channels = wf.getnchannels()
            duration = frames / float(rate) if rate else 0.0
            file_size = Path(audio_path).stat().st_size
        return {
            "duration_seconds": round(duration, 3),
            "format": "wav",
            "codec": "pcm",
            "sample_rate_hz": rate,
            "channels": channels,
            "file_size_bytes": file_size,
            "probe_method": "wave_stdlib",
        }
    except Exception:
        return None


def _probe_file_basic(audio_path: str) -> dict[str, Any]:
    """Minimal fallback: just file size and extension."""
    p = Path(audio_path)
    size = p.stat().st_size if p.exists() else 0
    return {
        "duration_seconds": None,
        "format": p.suffix.lstrip(".").lower(),
        "codec": None,
        "sample_rate_hz": None,
        "channels": None,
        "file_size_bytes": size,
        "probe_method": "basic",
    }


def _get_audio_metadata(audio_path: str) -> dict[str, Any]:
    """Get audio metadata using best available method."""
    meta = _probe_with_ffprobe(audio_path)
    if meta:
        return meta

    # WAV fallback
    if audio_path.lower().endswith(".wav"):
        meta = _probe_wav_stdlib(audio_path)
        if meta:
            return meta

    return _probe_file_basic(audio_path)


def _estimate_stt_costs(duration_seconds: float | None) -> dict[str, Any]:
    """Estimate transcription cost across all STT backends."""
    if duration_seconds is None:
        return {k: "unknown (duration unavailable)" for k in _STT_COST_PER_MINUTE}
    duration_minutes = duration_seconds / 60.0
    return {
        backend: round(cost_per_min * duration_minutes, 6)
        for backend, cost_per_min in _STT_COST_PER_MINUTE.items()
    }


def _make_output_path(workspace_dir: str, output_format: str) -> str:
    """Generate a timestamped output path for TTS audio."""
    ts = int(time.time() * 1000)
    audio_dir = Path(workspace_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return str(audio_dir / f"tts_{ts}.{output_format}")


def _read_audio_bytes(audio_path: str) -> bytes:
    """Read audio bytes from a file path."""
    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    return p.read_bytes()


def _check_api_key(env_var: str, backend: str) -> str | None:
    """Return the API key or None, producing a helpful error message."""
    key = os.environ.get(env_var)
    if not key:
        return None
    return key


# ---------------------------------------------------------------------------
# Tool handler implementations
# ---------------------------------------------------------------------------

async def _transcribe_audio(
    audio_path: str,
    language: str = "",
    backend: str = "whisper_api",
    enable_diarization: bool = False,
    enable_timestamps: bool = True,
) -> str:
    """Transcribe an audio file to text.

    Reads audio from workspace path, sends to STT backend,
    returns JSON with full transcription result.
    """
    try:
        from .speech_provider import SpeechProvider, STTConfig, STTBackend
    except ImportError:
        # speech_provider not yet available — return informative stub
        return json.dumps({
            "error": (
                "speech_provider module not found. "
                "Ensure orchestra/speech_provider.py is present."
            )
        })

    try:
        audio_bytes = _read_audio_bytes(audio_path)
    except FileNotFoundError as exc:
        return json.dumps({"error": str(exc), "audio_path": audio_path})

    # Map string backend name to enum
    try:
        stt_backend = STTBackend(backend)
    except ValueError:
        valid = [b.value for b in STTBackend]
        return json.dumps({
            "error": f"Unknown STT backend: {backend!r}",
            "valid_backends": valid,
        })

    # Validate API key presence for cloud backends
    _KEY_MAP_STT = {
        "whisper_api": "OPENAI_API_KEY",
        "deepgram": "DEEPGRAM_API_KEY",
        "assemblyai": "ASSEMBLYAI_API_KEY",
        "groq_whisper": "GROQ_API_KEY",
        "elevenlabs_scribe": "ELEVENLABS_API_KEY",
        # whisper_local requires no key
    }
    env_var = _KEY_MAP_STT.get(backend)
    if env_var and not os.environ.get(env_var):
        return json.dumps({
            "error": (
                f"Backend {backend!r} requires {env_var} to be set. "
                "Please configure the API key and try again."
            ),
            "backend": backend,
            "required_env_var": env_var,
        })

    config = STTConfig(
        backend=stt_backend,
        language=language or None,
        enable_diarization=enable_diarization,
        enable_timestamps=enable_timestamps,
    )

    provider = SpeechProvider()
    try:
        result = await provider.transcribe(audio_bytes, config)
    except Exception as exc:
        log.exception("transcribe_audio failed with backend=%s", backend)
        return json.dumps({"error": str(exc), "backend": backend})

    return json.dumps({
        "text": result.text,
        "language": result.language,
        "duration_seconds": result.duration_seconds,
        "segments": result.segments,
        "speakers": result.speakers,
        "cost_estimate_usd": result.cost_estimate_usd,
        "backend": backend,
        "audio_path": audio_path,
    })


async def _synthesize_speech(
    text: str,
    output_path: str = "",
    voice: str = "",
    backend: str = "openai_tts",
    language: str = "en",
    speed: float = 1.0,
    emotion: str = "",
    output_format: str = "mp3",
    *,
    _workspace_dir: str = "/tmp/horizon_workspace",
) -> str:
    """Convert text to speech audio.

    Generates audio and saves to workspace. Returns JSON with
    output path, duration, format, and cost estimate.
    """
    try:
        from .speech_provider import SpeechProvider, TTSConfig, TTSBackend, AudioFormat
    except ImportError:
        return json.dumps({
            "error": (
                "speech_provider module not found. "
                "Ensure orchestra/speech_provider.py is present."
            )
        })

    # Map string backend name to enum
    try:
        tts_backend = TTSBackend(backend)
    except ValueError:
        valid = [b.value for b in TTSBackend]
        return json.dumps({
            "error": f"Unknown TTS backend: {backend!r}",
            "valid_backends": valid,
        })

    # Map format string to enum
    try:
        audio_fmt = AudioFormat(output_format)
    except ValueError:
        valid_fmts = [f.value for f in AudioFormat]
        return json.dumps({
            "error": f"Unknown audio format: {output_format!r}",
            "valid_formats": valid_fmts,
        })

    # Validate API key for cloud backends
    _KEY_MAP_TTS = {
        "openai_tts": "OPENAI_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "deepgram_aura": "DEEPGRAM_API_KEY",
        # kokoro, fish_speech, chatterbox run locally — no key required
    }
    env_var = _KEY_MAP_TTS.get(backend)
    if env_var and not os.environ.get(env_var):
        return json.dumps({
            "error": (
                f"Backend {backend!r} requires {env_var} to be set. "
                "Please configure the API key and try again."
            ),
            "backend": backend,
            "required_env_var": env_var,
        })

    # Clamp speed to valid range
    speed = max(0.5, min(2.0, speed))

    config = TTSConfig(
        backend=tts_backend,
        voice=voice or None,
        language=language,
        speed=speed,
        emotion=emotion or None,
        output_format=audio_fmt,
    )

    provider = SpeechProvider()
    try:
        result = await provider.synthesize(text, config)
    except Exception as exc:
        log.exception("synthesize_speech failed with backend=%s", backend)
        return json.dumps({"error": str(exc), "backend": backend})

    # Determine output path
    if not output_path:
        output_path = _make_output_path(_workspace_dir, output_format)

    # Save audio bytes to file
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_bytes(result.audio_bytes)
    except Exception as exc:
        return json.dumps({"error": f"Failed to write audio file: {exc}", "output_path": output_path})

    return json.dumps({
        "output_path": output_path,
        "duration_seconds": result.duration_seconds,
        "format": output_format,
        "voice": result.voice_used or voice,
        "backend": backend,
        "cost_estimate_usd": result.cost_estimate_usd,
        "characters": len(text),
    })


async def _analyze_audio(audio_path: str) -> str:
    """Analyze an audio file and return metadata.

    Returns duration, format, sample rate, channels, file size,
    and estimated transcription cost across all STT backends.
    """
    p = Path(audio_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {audio_path}", "audio_path": audio_path})

    meta = _get_audio_metadata(audio_path)
    cost_estimates = _estimate_stt_costs(meta.get("duration_seconds"))

    return json.dumps({
        "audio_path": audio_path,
        "file_size_bytes": meta["file_size_bytes"],
        "duration_seconds": meta["duration_seconds"],
        "format": meta["format"],
        "codec": meta["codec"],
        "sample_rate_hz": meta["sample_rate_hz"],
        "channels": meta["channels"],
        "probe_method": meta["probe_method"],
        "stt_cost_estimates_usd": cost_estimates,
    })


async def _clone_voice(
    reference_audio_path: str,
    text: str,
    output_path: str = "",
    backend: str = "chatterbox",
    *,
    _workspace_dir: str = "/tmp/horizon_workspace",
) -> str:
    """Clone a voice from reference audio and generate speech.

    Requires a short (3-10s) audio sample of the target voice.
    Only supported on: chatterbox, fish_speech, elevenlabs.
    """
    try:
        from .speech_provider import SpeechProvider, TTSConfig, TTSBackend, AudioFormat
    except ImportError:
        return json.dumps({
            "error": (
                "speech_provider module not found. "
                "Ensure orchestra/speech_provider.py is present."
            )
        })

    # Validate backend supports voice cloning
    _CLONE_CAPABLE = {"chatterbox", "fish_speech", "elevenlabs"}
    if backend not in _CLONE_CAPABLE:
        return json.dumps({
            "error": (
                f"Backend {backend!r} does not support voice cloning. "
                f"Supported backends: {sorted(_CLONE_CAPABLE)}"
            ),
            "backend": backend,
        })

    # Validate API key for ElevenLabs
    if backend == "elevenlabs" and not os.environ.get("ELEVENLABS_API_KEY"):
        return json.dumps({
            "error": "Backend 'elevenlabs' requires ELEVENLABS_API_KEY to be set.",
            "backend": backend,
            "required_env_var": "ELEVENLABS_API_KEY",
        })

    # Read reference audio
    try:
        reference_bytes = _read_audio_bytes(reference_audio_path)
    except FileNotFoundError as exc:
        return json.dumps({"error": str(exc), "reference_audio_path": reference_audio_path})

    # Probe reference audio duration for informational purposes
    ref_meta = _get_audio_metadata(reference_audio_path)
    ref_duration = ref_meta.get("duration_seconds")
    if ref_duration is not None and ref_duration < 1.0:
        return json.dumps({
            "error": (
                f"Reference audio is too short ({ref_duration:.1f}s). "
                "Provide at least 3 seconds of clear speech for voice cloning."
            ),
            "reference_audio_path": reference_audio_path,
        })
    if ref_duration is not None and ref_duration > 30.0:
        log.warning(
            "Reference audio is %.1fs — voice cloning works best with 3-10s samples. "
            "Proceeding anyway.",
            ref_duration,
        )

    try:
        tts_backend = TTSBackend(backend)
    except ValueError:
        valid = [b.value for b in TTSBackend]
        return json.dumps({
            "error": f"Unknown TTS backend: {backend!r}",
            "valid_backends": valid,
        })

    config = TTSConfig(
        backend=tts_backend,
        voice=None,
        language="en",
        speed=1.0,
        emotion=None,
        output_format=AudioFormat("mp3"),
        voice_clone_audio=reference_bytes,
    )

    provider = SpeechProvider()
    try:
        result = await provider.synthesize(text, config)
    except Exception as exc:
        log.exception("clone_voice failed with backend=%s", backend)
        return json.dumps({"error": str(exc), "backend": backend})

    # Save output
    if not output_path:
        output_path = _make_output_path(_workspace_dir, "mp3")

    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_bytes(result.audio_bytes)
    except Exception as exc:
        return json.dumps({"error": f"Failed to write audio file: {exc}", "output_path": output_path})

    return json.dumps({
        "output_path": output_path,
        "duration_seconds": result.duration_seconds,
        "format": "mp3",
        "backend": backend,
        "reference_audio_path": reference_audio_path,
        "reference_duration_seconds": ref_duration,
        "cost_estimate_usd": result.cost_estimate_usd,
        "characters": len(text),
    })


async def _translate_speech(
    audio_path: str,
    target_language: str = "en",
    backend: str = "whisper_api",
) -> str:
    """Translate speech from one language to English text.

    Uses Whisper's translation capability to convert foreign-language
    audio directly to English text.  For other backends, transcribes
    first (auto-detecting language) then notes that translation is
    Whisper-native.
    """
    try:
        audio_bytes = _read_audio_bytes(audio_path)
    except FileNotFoundError as exc:
        return json.dumps({"error": str(exc), "audio_path": audio_path})

    if target_language != "en":
        # Whisper's built-in translation only targets English.
        # For other target languages, we log a warning and continue
        # (the caller should use a separate translation step).
        log.warning(
            "translate_speech: target_language=%r requested but Whisper translation "
            "only outputs English. Returning English translation.",
            target_language,
        )

    if backend == "whisper_api":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return json.dumps({
                "error": "whisper_api backend requires OPENAI_API_KEY to be set.",
                "required_env_var": "OPENAI_API_KEY",
            })

        try:
            from openai import AsyncOpenAI
            import io

            client = AsyncOpenAI(api_key=api_key)

            # Determine filename hint from extension for proper MIME detection
            suffix = Path(audio_path).suffix or ".mp3"
            file_tuple = (f"audio{suffix}", audio_bytes, f"audio/{suffix.lstrip('.')}")

            translation = await client.audio.translations.create(
                model="whisper-1",
                file=file_tuple,
                response_format="verbose_json",
            )
            text = getattr(translation, "text", "") or ""
            duration = getattr(translation, "duration", None)

            return json.dumps({
                "text": text,
                "source_language": "auto-detected",
                "target_language": "en",
                "duration_seconds": duration,
                "backend": backend,
                "audio_path": audio_path,
            })
        except Exception as exc:
            log.exception("translate_speech (whisper_api) failed")
            return json.dumps({"error": str(exc), "backend": backend})

    elif backend == "groq_whisper":
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return json.dumps({
                "error": "groq_whisper backend requires GROQ_API_KEY to be set.",
                "required_env_var": "GROQ_API_KEY",
            })

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=api_key,
            )
            suffix = Path(audio_path).suffix or ".mp3"
            file_tuple = (f"audio{suffix}", audio_bytes, f"audio/{suffix.lstrip('.')}")

            translation = await client.audio.translations.create(
                model="whisper-large-v3",
                file=file_tuple,
                response_format="verbose_json",
            )
            text = getattr(translation, "text", "") or ""
            duration = getattr(translation, "duration", None)

            return json.dumps({
                "text": text,
                "source_language": "auto-detected",
                "target_language": "en",
                "duration_seconds": duration,
                "backend": backend,
                "audio_path": audio_path,
            })
        except Exception as exc:
            log.exception("translate_speech (groq_whisper) failed")
            return json.dumps({"error": str(exc), "backend": backend})

    else:
        # For non-Whisper backends: transcribe with auto language detection
        # and inform the caller that they should apply a separate translation step.
        try:
            from .speech_provider import SpeechProvider, STTConfig, STTBackend
        except ImportError:
            return json.dumps({
                "error": (
                    "speech_provider module not found. "
                    "Ensure orchestra/speech_provider.py is present."
                )
            })

        try:
            stt_backend = STTBackend(backend)
        except ValueError:
            valid = [b.value for b in STTBackend]
            return json.dumps({
                "error": f"Unknown STT backend: {backend!r}",
                "valid_backends": valid,
            })

        config = STTConfig(
            backend=stt_backend,
            language=None,  # auto-detect
            enable_diarization=False,
            enable_timestamps=False,
        )
        provider = SpeechProvider()
        try:
            result = await provider.transcribe(audio_bytes, config)
        except Exception as exc:
            log.exception("translate_speech (transcribe fallback) failed")
            return json.dumps({"error": str(exc), "backend": backend})

        return json.dumps({
            "text": result.text,
            "source_language": result.language,
            "target_language": target_language,
            "note": (
                f"Backend {backend!r} does not support native translation. "
                "Transcription in the source language was returned. "
                "Use a language model to translate if needed."
            ),
            "duration_seconds": result.duration_seconds,
            "backend": backend,
            "audio_path": audio_path,
        })


async def _list_audio_backends() -> str:
    """List all available STT and TTS backends with capabilities."""
    stt_backends = {
        k: v for k, v in BACKEND_CAPABILITIES.items() if v["type"] == "stt"
    }
    tts_backends = {
        k: v for k, v in BACKEND_CAPABILITIES.items() if v["type"] == "tts"
    }

    # Check which backends have their API keys configured
    _KEY_REQUIRED = {
        "whisper_api": "OPENAI_API_KEY",
        "deepgram": "DEEPGRAM_API_KEY",
        "assemblyai": "ASSEMBLYAI_API_KEY",
        "groq_whisper": "GROQ_API_KEY",
        "elevenlabs_scribe": "ELEVENLABS_API_KEY",
        "openai_tts": "OPENAI_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "deepgram_aura": "DEEPGRAM_API_KEY",
    }

    def _enrich(backend_id: str, caps: dict[str, Any]) -> dict[str, Any]:
        env_var = _KEY_REQUIRED.get(backend_id)
        api_key_configured = (
            bool(os.environ.get(env_var)) if env_var else True  # local backends always ready
        )
        return {**caps, "api_key_configured": api_key_configured}

    return json.dumps({
        "stt_backends": {k: _enrich(k, v) for k, v in stt_backends.items()},
        "tts_backends": {k: _enrich(k, v) for k, v in tts_backends.items()},
        "total_stt": len(stt_backends),
        "total_tts": len(tts_backends),
    })


# ---------------------------------------------------------------------------
# Registration function
# ---------------------------------------------------------------------------

def register_audio_tools(
    tool_registry: Any,  # ToolRegistry from agent_loop
    speech_provider: Any | None = None,  # SpeechProvider | None
    workspace_dir: str = "/tmp/horizon_workspace",
) -> None:
    """Register audio tools into the agent's tool surface.

    Call this after ``create_default_tools()`` to add speech capabilities.

    Args:
        tool_registry: The :class:`~orchestra.agent_loop.ToolRegistry` to
            register tools into.
        speech_provider: Optional pre-configured
            :class:`~orchestra.speech_provider.SpeechProvider`.
            If *None*, a fresh instance is created per-call.
        workspace_dir: Directory for saving generated audio files.
            Defaults to ``/tmp/horizon_workspace``.
    """

    # Bind workspace_dir into the handlers that need it via closures.
    # speech_provider is passed through for future use (currently SpeechProvider()
    # is instantiated inside each handler, but could be pre-shared here).

    async def _handle_transcribe_audio(
        audio_path: str,
        language: str = "",
        backend: str = "whisper_api",
        enable_diarization: bool = False,
        enable_timestamps: bool = True,
    ) -> str:
        return await _transcribe_audio(
            audio_path=audio_path,
            language=language,
            backend=backend,
            enable_diarization=enable_diarization,
            enable_timestamps=enable_timestamps,
        )

    async def _handle_synthesize_speech(
        text: str,
        output_path: str = "",
        voice: str = "",
        backend: str = "openai_tts",
        language: str = "en",
        speed: float = 1.0,
        emotion: str = "",
        output_format: str = "mp3",
    ) -> str:
        return await _synthesize_speech(
            text=text,
            output_path=output_path,
            voice=voice,
            backend=backend,
            language=language,
            speed=speed,
            emotion=emotion,
            output_format=output_format,
            _workspace_dir=workspace_dir,
        )

    async def _handle_analyze_audio(audio_path: str) -> str:
        return await _analyze_audio(audio_path=audio_path)

    async def _handle_clone_voice(
        reference_audio_path: str,
        text: str,
        output_path: str = "",
        backend: str = "chatterbox",
    ) -> str:
        return await _clone_voice(
            reference_audio_path=reference_audio_path,
            text=text,
            output_path=output_path,
            backend=backend,
            _workspace_dir=workspace_dir,
        )

    async def _handle_translate_speech(
        audio_path: str,
        target_language: str = "en",
        backend: str = "whisper_api",
    ) -> str:
        return await _translate_speech(
            audio_path=audio_path,
            target_language=target_language,
            backend=backend,
        )

    async def _handle_list_audio_backends() -> str:
        return await _list_audio_backends()

    # ── transcribe_audio ────────────────────────────────────────────────────
    tool_registry.register(
        name="transcribe_audio",
        description=(
            "Transcribe an audio file to text using a speech-to-text backend. "
            "Supports wav, mp3, m4a, flac, ogg, and webm files. "
            "Returns full transcription with optional timestamps and speaker labels."
        ),
        parameters={
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "Path to audio file (wav, mp3, m4a, flac, ogg, webm)",
                },
                "language": {
                    "type": "string",
                    "description": (
                        "Language code (e.g., 'en', 'es', 'fr'). "
                        "Empty string for auto-detect."
                    ),
                },
                "backend": {
                    "type": "string",
                    "enum": [
                        "whisper_api",
                        "deepgram",
                        "assemblyai",
                        "groq_whisper",
                        "elevenlabs_scribe",
                        "whisper_local",
                    ],
                    "description": "STT backend to use (default: whisper_api)",
                },
                "enable_diarization": {
                    "type": "boolean",
                    "description": (
                        "Enable speaker identification. "
                        "Supported on: deepgram, assemblyai, elevenlabs_scribe."
                    ),
                },
                "enable_timestamps": {
                    "type": "boolean",
                    "description": "Include word/segment timestamps (default: true)",
                },
            },
            "required": ["audio_path"],
        },
        handler=_handle_transcribe_audio,
    )

    # ── synthesize_speech ───────────────────────────────────────────────────
    tool_registry.register(
        name="synthesize_speech",
        description=(
            "Convert text to speech audio and save to a file. "
            "Returns the output file path, duration, and cost estimate."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to convert to speech",
                },
                "output_path": {
                    "type": "string",
                    "description": (
                        "Where to save the audio file. "
                        "Auto-generated timestamped path if empty."
                    ),
                },
                "voice": {
                    "type": "string",
                    "description": (
                        "Voice ID or name (backend-specific). "
                        "Empty for default. "
                        "OpenAI voices: alloy, echo, fable, onyx, nova, shimmer."
                    ),
                },
                "backend": {
                    "type": "string",
                    "enum": [
                        "openai_tts",
                        "elevenlabs",
                        "kokoro",
                        "fish_speech",
                        "chatterbox",
                        "deepgram_aura",
                    ],
                    "description": "TTS backend to use (default: openai_tts)",
                },
                "language": {
                    "type": "string",
                    "description": "Language code (default: en)",
                },
                "speed": {
                    "type": "number",
                    "description": "Speech speed multiplier (0.5–2.0, default: 1.0)",
                },
                "emotion": {
                    "type": "string",
                    "description": (
                        "Emotion tag for Fish Speech / Chatterbox "
                        "(e.g., 'cheerful', 'whisper', 'angry'). "
                        "Ignored by other backends."
                    ),
                },
                "output_format": {
                    "type": "string",
                    "enum": ["mp3", "wav", "ogg", "flac", "opus", "aac"],
                    "description": "Audio output format (default: mp3)",
                },
            },
            "required": ["text"],
        },
        handler=_handle_synthesize_speech,
    )

    # ── analyze_audio ───────────────────────────────────────────────────────
    tool_registry.register(
        name="analyze_audio",
        description=(
            "Analyze an audio file and return metadata: duration, format, "
            "sample rate, channels, file size, and estimated transcription cost "
            "across all STT backends."
        ),
        parameters={
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "Path to the audio file to analyze",
                },
            },
            "required": ["audio_path"],
        },
        handler=_handle_analyze_audio,
    )

    # ── clone_voice ─────────────────────────────────────────────────────────
    tool_registry.register(
        name="clone_voice",
        description=(
            "Clone a voice from a short reference audio sample (3–10 seconds) "
            "and generate speech in that voice. "
            "Supported backends: chatterbox, fish_speech, elevenlabs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reference_audio_path": {
                    "type": "string",
                    "description": (
                        "Path to reference audio file containing the voice to clone "
                        "(3–10 seconds of clear speech recommended)"
                    ),
                },
                "text": {
                    "type": "string",
                    "description": "Text to speak in the cloned voice",
                },
                "output_path": {
                    "type": "string",
                    "description": (
                        "Where to save the generated audio. "
                        "Auto-generated if empty."
                    ),
                },
                "backend": {
                    "type": "string",
                    "enum": ["chatterbox", "fish_speech", "elevenlabs"],
                    "description": (
                        "Voice-cloning backend (default: chatterbox). "
                        "chatterbox and fish_speech run locally; "
                        "elevenlabs requires ELEVENLABS_API_KEY."
                    ),
                },
            },
            "required": ["reference_audio_path", "text"],
        },
        handler=_handle_clone_voice,
    )

    # ── translate_speech ────────────────────────────────────────────────────
    tool_registry.register(
        name="translate_speech",
        description=(
            "Translate speech in a foreign language to English text. "
            "Uses Whisper's native translation capability for whisper_api and "
            "groq_whisper. Other backends transcribe in the source language "
            "and note that further translation is needed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "Path to the foreign-language audio file",
                },
                "target_language": {
                    "type": "string",
                    "description": (
                        "Target language code (default: 'en'). "
                        "Note: Whisper's translation is natively English-only."
                    ),
                },
                "backend": {
                    "type": "string",
                    "enum": [
                        "whisper_api",
                        "deepgram",
                        "assemblyai",
                        "groq_whisper",
                        "elevenlabs_scribe",
                        "whisper_local",
                    ],
                    "description": (
                        "Backend to use for translation (default: whisper_api). "
                        "whisper_api and groq_whisper support native speech translation."
                    ),
                },
            },
            "required": ["audio_path"],
        },
        handler=_handle_translate_speech,
    )

    # ── list_audio_backends ─────────────────────────────────────────────────
    tool_registry.register(
        name="list_audio_backends",
        description=(
            "List all available STT and TTS backends with their capabilities, "
            "pricing, and whether the required API key is configured."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_handle_list_audio_backends,
    )

    log.info(
        "Registered audio tools: transcribe_audio, synthesize_speech, "
        "analyze_audio, clone_voice, translate_speech, list_audio_backends"
    )
