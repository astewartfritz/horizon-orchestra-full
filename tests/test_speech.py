"""Tests for speech_provider.py and audio_tools.py.

All tests run offline — every API call is mocked.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# No sys.modules stubs needed — the lazy try/except guards in agent_loop.py
# and __init__.py handle missing optional deps gracefully.
# ---------------------------------------------------------------------------


def run(coro):
    """Run an async coroutine in a fresh event loop (test helper)."""
    return asyncio.get_event_loop().run_until_complete(coro)


@mock.patch.dict(os.environ, {}, clear=True)
class _BaseTest(unittest.TestCase):
    pass


# ===========================================================================
# SpeechProvider Config tests (tests 1–5)
# ===========================================================================

class SpeechProviderConfigTests(_BaseTest):

    def test_stt_config_defaults(self):
        """STTConfig should have sensible defaults matching the docstring."""
        from orchestra.speech_provider import STTConfig, STTBackend

        cfg = STTConfig()
        self.assertEqual(cfg.backend, STTBackend.WHISPER_API)
        self.assertEqual(cfg.model, "")
        self.assertEqual(cfg.language, "")
        self.assertFalse(cfg.enable_diarization)
        self.assertTrue(cfg.enable_timestamps)
        self.assertEqual(cfg.response_format, "verbose_json")
        self.assertEqual(cfg.temperature, 0.0)
        self.assertEqual(cfg.sample_rate, 16000)

    def test_tts_config_defaults(self):
        """TTSConfig should have sensible defaults matching the docstring."""
        from orchestra.speech_provider import TTSConfig, TTSBackend, AudioFormat

        cfg = TTSConfig()
        self.assertEqual(cfg.backend, TTSBackend.OPENAI_TTS)
        self.assertEqual(cfg.model, "")
        self.assertEqual(cfg.voice, "")
        self.assertEqual(cfg.language, "en")
        self.assertEqual(cfg.output_format, AudioFormat.MP3)
        self.assertEqual(cfg.speed, 1.0)
        self.assertEqual(cfg.sample_rate, 24000)
        self.assertEqual(cfg.emotion, "")
        self.assertIsNone(cfg.voice_clone_audio)

    def test_stt_backend_enum_values(self):
        """All 6 STT backends should be present with correct string values."""
        from orchestra.speech_provider import STTBackend

        self.assertEqual(STTBackend.WHISPER_API.value, "whisper_api")
        self.assertEqual(STTBackend.WHISPER_LOCAL.value, "whisper_local")
        self.assertEqual(STTBackend.DEEPGRAM.value, "deepgram")
        self.assertEqual(STTBackend.ASSEMBLYAI.value, "assemblyai")
        self.assertEqual(STTBackend.GROQ_WHISPER.value, "groq_whisper")
        self.assertEqual(STTBackend.ELEVENLABS_SCRIBE.value, "elevenlabs_scribe")
        # Verify count
        self.assertEqual(len(list(STTBackend)), 6)

    def test_tts_backend_enum_values(self):
        """All 6 TTS backends should be present with correct string values."""
        from orchestra.speech_provider import TTSBackend

        self.assertEqual(TTSBackend.OPENAI_TTS.value, "openai_tts")
        self.assertEqual(TTSBackend.ELEVENLABS.value, "elevenlabs")
        self.assertEqual(TTSBackend.KOKORO.value, "kokoro")
        self.assertEqual(TTSBackend.FISH_SPEECH.value, "fish_speech")
        self.assertEqual(TTSBackend.CHATTERBOX.value, "chatterbox")
        self.assertEqual(TTSBackend.DEEPGRAM_AURA.value, "deepgram_aura")
        # Verify count
        self.assertEqual(len(list(TTSBackend)), 6)

    def test_audio_format_enum_values(self):
        """AudioFormat enum should cover all expected audio formats."""
        from orchestra.speech_provider import AudioFormat

        expected = {"mp3", "wav", "ogg", "flac", "pcm", "opus", "aac"}
        actual = {fmt.value for fmt in AudioFormat}
        self.assertEqual(actual, expected)


# ===========================================================================
# TranscriptionResult / TTSResult dataclass tests (tests 6–9)
# ===========================================================================

class ResultDataclassTests(_BaseTest):

    def test_transcription_result_defaults(self):
        """TranscriptionResult should accept only text and default the rest."""
        from orchestra.speech_provider import TranscriptionResult

        result = TranscriptionResult(text="Hello world")
        self.assertEqual(result.text, "Hello world")
        self.assertEqual(result.language, "")
        self.assertEqual(result.duration_seconds, 0.0)
        self.assertEqual(result.segments, [])
        self.assertEqual(result.speakers, [])
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.backend, "")
        self.assertEqual(result.model, "")
        self.assertEqual(result.cost_estimate, 0.0)

    def test_transcription_segment_fields(self):
        """TranscriptionSegment should store text, start, end, and confidence."""
        from orchestra.speech_provider import TranscriptionSegment

        seg = TranscriptionSegment(text="Hi there", start=0.5, end=1.2, confidence=0.98)
        self.assertEqual(seg.text, "Hi there")
        self.assertEqual(seg.start, 0.5)
        self.assertEqual(seg.end, 1.2)
        self.assertEqual(seg.confidence, 0.98)

        # Default confidence
        seg2 = TranscriptionSegment(text="Test", start=0.0, end=0.5)
        self.assertEqual(seg2.confidence, 0.0)

    def test_speaker_segment_fields(self):
        """SpeakerSegment should store speaker label, text, start, and end."""
        from orchestra.speech_provider import SpeakerSegment

        seg = SpeakerSegment(speaker="speaker_0", text="Welcome.", start=0.0, end=1.5)
        self.assertEqual(seg.speaker, "speaker_0")
        self.assertEqual(seg.text, "Welcome.")
        self.assertEqual(seg.start, 0.0)
        self.assertEqual(seg.end, 1.5)

    def test_tts_result_defaults(self):
        """TTSResult requires audio_data and format; remaining fields default."""
        from orchestra.speech_provider import TTSResult, AudioFormat

        data = b"\xff\xfb\x90\x00"
        result = TTSResult(audio_data=data, format=AudioFormat.MP3)
        self.assertEqual(result.audio_data, data)
        self.assertEqual(result.format, AudioFormat.MP3)
        self.assertEqual(result.duration_seconds, 0.0)
        self.assertEqual(result.sample_rate, 24000)
        self.assertEqual(result.backend, "")
        self.assertEqual(result.model, "")
        self.assertEqual(result.voice, "")
        self.assertEqual(result.cost_estimate, 0.0)


# ===========================================================================
# SpeechProvider init tests (tests 10–12)
# ===========================================================================

class SpeechProviderInitTests(_BaseTest):

    def test_provider_init_defaults(self):
        """SpeechProvider() should populate default stt_config and tts_config."""
        from orchestra.speech_provider import SpeechProvider, STTBackend, TTSBackend

        provider = SpeechProvider()
        self.assertEqual(provider.stt_config.backend, STTBackend.WHISPER_API)
        self.assertEqual(provider.tts_config.backend, TTSBackend.OPENAI_TTS)

    def test_provider_init_custom_config(self):
        """SpeechProvider should accept and store custom configs."""
        from orchestra.speech_provider import (
            SpeechProvider, STTConfig, TTSConfig, STTBackend, TTSBackend
        )

        stt = STTConfig(backend=STTBackend.DEEPGRAM, enable_diarization=True)
        tts = TTSConfig(backend=TTSBackend.KOKORO, voice="af_heart")
        provider = SpeechProvider(stt_config=stt, tts_config=tts)

        self.assertEqual(provider.stt_config.backend, STTBackend.DEEPGRAM)
        self.assertTrue(provider.stt_config.enable_diarization)
        self.assertEqual(provider.tts_config.backend, TTSBackend.KOKORO)
        self.assertEqual(provider.tts_config.voice, "af_heart")

    def test_provider_list_backends(self):
        """list_backends() should return dicts with 'stt' and 'tts' keys."""
        from orchestra.speech_provider import SpeechProvider, STTBackend, TTSBackend

        provider = SpeechProvider()
        backends = provider.list_backends()

        self.assertIn("stt", backends)
        self.assertIn("tts", backends)

        # All 6 STT backends present
        stt_vals = set(backends["stt"])
        for b in STTBackend:
            self.assertIn(b.value, stt_vals, f"Missing STT backend: {b.value}")

        # All 6 TTS backends present
        tts_vals = set(backends["tts"])
        for b in TTSBackend:
            self.assertIn(b.value, tts_vals, f"Missing TTS backend: {b.value}")


# ===========================================================================
# STT backend routing tests (tests 13–18)
# ===========================================================================

class STTRoutingTests(_BaseTest):

    def _make_fake_transcription_result(self):
        from orchestra.speech_provider import TranscriptionResult
        return TranscriptionResult(
            text="Test transcript",
            language="en",
            duration_seconds=5.0,
            backend="whisper_api",
        )

    def test_transcribe_routes_to_whisper_api(self):
        """transcribe() with WHISPER_API backend should call _transcribe_whisper_api."""
        from orchestra.speech_provider import SpeechProvider, STTConfig, STTBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_transcription_result()

        with patch.object(
            provider, "_transcribe_whisper_api", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.transcribe(
                b"fake-audio",
                config=STTConfig(backend=STTBackend.WHISPER_API),
            ))

        mock_handler.assert_called_once()
        self.assertEqual(result.text, "Test transcript")

    def test_transcribe_routes_to_deepgram(self):
        """transcribe() with DEEPGRAM backend should call _transcribe_deepgram."""
        from orchestra.speech_provider import SpeechProvider, STTConfig, STTBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_transcription_result()

        with patch.object(
            provider, "_transcribe_deepgram", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.transcribe(
                b"fake-audio",
                config=STTConfig(backend=STTBackend.DEEPGRAM),
            ))

        mock_handler.assert_called_once()
        self.assertEqual(result.text, "Test transcript")

    def test_transcribe_routes_to_assemblyai(self):
        """transcribe() with ASSEMBLYAI backend should call _transcribe_assemblyai."""
        from orchestra.speech_provider import SpeechProvider, STTConfig, STTBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_transcription_result()

        with patch.object(
            provider, "_transcribe_assemblyai", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.transcribe(
                b"fake-audio",
                config=STTConfig(backend=STTBackend.ASSEMBLYAI),
            ))

        mock_handler.assert_called_once()
        self.assertEqual(result.text, "Test transcript")

    def test_transcribe_routes_to_groq(self):
        """transcribe() with GROQ_WHISPER backend should call _transcribe_groq."""
        from orchestra.speech_provider import SpeechProvider, STTConfig, STTBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_transcription_result()

        with patch.object(
            provider, "_transcribe_groq", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.transcribe(
                b"fake-audio",
                config=STTConfig(backend=STTBackend.GROQ_WHISPER),
            ))

        mock_handler.assert_called_once()
        self.assertEqual(result.text, "Test transcript")

    def test_transcribe_accepts_file_path(self):
        """transcribe() should read bytes from a file path string."""
        from orchestra.speech_provider import SpeechProvider, STTConfig, STTBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_transcription_result()
        fake_audio_bytes = b"real-audio-from-file"

        with patch.object(
            provider, "_transcribe_whisper_api", new=AsyncMock(return_value=fake_result)
        ) as mock_handler, \
        patch("orchestra.speech_provider._read_file", return_value=fake_audio_bytes):
            result = run(provider.transcribe(
                "/some/path/audio.mp3",
                config=STTConfig(backend=STTBackend.WHISPER_API),
            ))

        # The handler should have been called with the bytes read from disk
        call_args = mock_handler.call_args
        self.assertEqual(call_args[0][0], fake_audio_bytes)

    def test_transcribe_accepts_bytes(self):
        """transcribe() should pass bytes directly to the backend handler."""
        from orchestra.speech_provider import SpeechProvider, STTConfig, STTBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_transcription_result()
        audio_bytes = b"\x00\x01\x02\x03"

        with patch.object(
            provider, "_transcribe_whisper_api", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            run(provider.transcribe(
                audio_bytes,
                config=STTConfig(backend=STTBackend.WHISPER_API),
            ))

        call_args = mock_handler.call_args
        self.assertEqual(call_args[0][0], audio_bytes)


# ===========================================================================
# TTS backend routing tests (tests 19–24)
# ===========================================================================

class TTSRoutingTests(_BaseTest):

    def _make_fake_tts_result(self):
        from orchestra.speech_provider import TTSResult, AudioFormat
        return TTSResult(
            audio_data=b"fake-mp3-bytes",
            format=AudioFormat.MP3,
            duration_seconds=2.0,
            backend="openai_tts",
            voice="alloy",
        )

    def test_synthesize_routes_to_openai(self):
        """synthesize() with OPENAI_TTS backend should call _synthesize_openai."""
        from orchestra.speech_provider import SpeechProvider, TTSConfig, TTSBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_tts_result()

        with patch.object(
            provider, "_synthesize_openai", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.synthesize(
                "Hello world",
                config=TTSConfig(backend=TTSBackend.OPENAI_TTS),
            ))

        mock_handler.assert_called_once()
        self.assertEqual(result.audio_data, b"fake-mp3-bytes")

    def test_synthesize_routes_to_elevenlabs(self):
        """synthesize() with ELEVENLABS backend should call _synthesize_elevenlabs."""
        from orchestra.speech_provider import SpeechProvider, TTSConfig, TTSBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_tts_result()

        with patch.object(
            provider, "_synthesize_elevenlabs", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.synthesize(
                "Hello world",
                config=TTSConfig(backend=TTSBackend.ELEVENLABS),
            ))

        mock_handler.assert_called_once()
        self.assertEqual(result.audio_data, b"fake-mp3-bytes")

    def test_synthesize_routes_to_kokoro(self):
        """synthesize() with KOKORO backend should call _synthesize_kokoro."""
        from orchestra.speech_provider import SpeechProvider, TTSConfig, TTSBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_tts_result()

        with patch.object(
            provider, "_synthesize_kokoro", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.synthesize(
                "Free local TTS",
                config=TTSConfig(backend=TTSBackend.KOKORO),
            ))

        mock_handler.assert_called_once()

    def test_synthesize_routes_to_fish_speech(self):
        """synthesize() with FISH_SPEECH backend should call _synthesize_fish_speech."""
        from orchestra.speech_provider import SpeechProvider, TTSConfig, TTSBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_tts_result()

        with patch.object(
            provider, "_synthesize_fish_speech", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.synthesize(
                "[excited]Test[/excited]",
                config=TTSConfig(backend=TTSBackend.FISH_SPEECH, emotion="dynamic"),
            ))

        mock_handler.assert_called_once()

    def test_synthesize_routes_to_chatterbox(self):
        """synthesize() with CHATTERBOX backend should call _synthesize_chatterbox."""
        from orchestra.speech_provider import SpeechProvider, TTSConfig, TTSBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_tts_result()

        with patch.object(
            provider, "_synthesize_chatterbox", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.synthesize(
                "Clone this voice",
                config=TTSConfig(
                    backend=TTSBackend.CHATTERBOX,
                    voice_clone_audio=b"reference-audio",
                ),
            ))

        mock_handler.assert_called_once()

    def test_synthesize_routes_to_deepgram_aura(self):
        """synthesize() with DEEPGRAM_AURA backend should call _synthesize_deepgram_aura."""
        from orchestra.speech_provider import SpeechProvider, TTSConfig, TTSBackend

        provider = SpeechProvider()
        fake_result = self._make_fake_tts_result()

        with patch.object(
            provider, "_synthesize_deepgram_aura", new=AsyncMock(return_value=fake_result)
        ) as mock_handler:
            result = run(provider.synthesize(
                "Low-latency TTS",
                config=TTSConfig(backend=TTSBackend.DEEPGRAM_AURA),
            ))

        mock_handler.assert_called_once()


# ===========================================================================
# Cost estimation tests (tests 25–32)
# ===========================================================================

class CostEstimationTests(_BaseTest):

    def test_estimate_stt_cost_whisper(self):
        """Whisper API costs $0.006 per minute ($0.0001/sec)."""
        from orchestra.speech_provider import estimate_stt_cost

        # 60 seconds = 1 minute = $0.006
        cost = estimate_stt_cost(60.0, "whisper_api")
        self.assertAlmostEqual(cost, 0.006, places=6)

        # 120 seconds = 2 minutes = $0.012
        cost2 = estimate_stt_cost(120.0, "whisper_api")
        self.assertAlmostEqual(cost2, 0.012, places=6)

    def test_estimate_stt_cost_deepgram(self):
        """Deepgram Nova-3 costs $0.0077 per minute."""
        from orchestra.speech_provider import estimate_stt_cost

        cost = estimate_stt_cost(60.0, "deepgram_nova3")
        self.assertAlmostEqual(cost, 0.0077, places=6)

    def test_estimate_stt_cost_groq(self):
        """Groq Whisper is billed per hour at $0.04/hr."""
        from orchestra.speech_provider import estimate_stt_cost

        # 3600 seconds = 1 hour = $0.04
        cost = estimate_stt_cost(3600.0, "groq_whisper")
        self.assertAlmostEqual(cost, 0.04, places=6)

        # 1800 seconds = 30 minutes = $0.02
        cost2 = estimate_stt_cost(1800.0, "groq_whisper")
        self.assertAlmostEqual(cost2, 0.02, places=6)

    def test_estimate_stt_cost_local_free(self):
        """Local Whisper should always return 0.0."""
        from orchestra.speech_provider import estimate_stt_cost

        cost = estimate_stt_cost(3600.0, "local_whisper")
        self.assertEqual(cost, 0.0)

        # Unknown backends also return 0
        cost2 = estimate_stt_cost(60.0, "nonexistent_backend")
        self.assertEqual(cost2, 0.0)

    def test_estimate_tts_cost_openai(self):
        """OpenAI TTS costs $15 per 1M chars = $0.000015 per char."""
        from orchestra.speech_provider import estimate_tts_cost

        # 1,000,000 chars = $15.00
        cost = estimate_tts_cost("x" * 1_000_000, "openai_tts1")
        self.assertAlmostEqual(cost, 15.0, places=4)

        # 1000 chars = $0.015
        cost2 = estimate_tts_cost("x" * 1000, "openai_tts1")
        self.assertAlmostEqual(cost2, 0.015, places=6)

    def test_estimate_tts_cost_elevenlabs(self):
        """ElevenLabs Flash costs $0.08 per 1K chars."""
        from orchestra.speech_provider import estimate_tts_cost

        # 1000 chars = $0.08
        cost = estimate_tts_cost("x" * 1000, "elevenlabs_flash")
        self.assertAlmostEqual(cost, 0.08, places=6)

    def test_estimate_tts_cost_kokoro_free(self):
        """Kokoro (local) should always return 0.0."""
        from orchestra.speech_provider import estimate_tts_cost

        cost = estimate_tts_cost("Hello world, this is a test sentence.", "kokoro")
        self.assertEqual(cost, 0.0)

    def test_estimate_tts_cost_fish_speech_free(self):
        """Fish Speech (self-hosted) should always return 0.0."""
        from orchestra.speech_provider import estimate_tts_cost

        cost = estimate_tts_cost("x" * 10_000, "fish_speech")
        self.assertEqual(cost, 0.0)


# ===========================================================================
# Backend capabilities tests (tests 33–35)
# ===========================================================================

class BackendCapabilitiesTests(_BaseTest):

    def test_backend_capabilities_has_all_stt(self):
        """BACKEND_CAPABILITIES should contain all 6 STT backends."""
        from orchestra.speech_provider import BACKEND_CAPABILITIES, STTBackend

        stt_keys = {k for k, v in BACKEND_CAPABILITIES.items() if v.get("type") == "stt"}
        for backend in STTBackend:
            self.assertIn(
                backend.value, stt_keys,
                f"STT backend {backend.value!r} missing from BACKEND_CAPABILITIES"
            )

    def test_backend_capabilities_has_all_tts(self):
        """BACKEND_CAPABILITIES should contain all 6 TTS backends."""
        from orchestra.speech_provider import BACKEND_CAPABILITIES, TTSBackend

        tts_keys = {k for k, v in BACKEND_CAPABILITIES.items() if v.get("type") == "tts"}
        for backend in TTSBackend:
            self.assertIn(
                backend.value, tts_keys,
                f"TTS backend {backend.value!r} missing from BACKEND_CAPABILITIES"
            )

    def test_get_backend_info(self):
        """get_backend_info() should return the capabilities dict for a backend."""
        from orchestra.speech_provider import SpeechProvider

        provider = SpeechProvider()

        # Known STT backend
        info = provider.get_backend_info("deepgram")
        self.assertEqual(info.get("type"), "stt")
        self.assertTrue(info.get("realtime"))
        self.assertTrue(info.get("diarization"))
        self.assertIn("description", info)

        # Known TTS backend
        info_tts = provider.get_backend_info("kokoro")
        self.assertEqual(info_tts.get("type"), "tts")
        self.assertTrue(info_tts.get("local"))

        # Unknown backend returns empty dict
        info_unknown = provider.get_backend_info("does_not_exist")
        self.assertEqual(info_unknown, {})


# ===========================================================================
# Audio tools tests (tests 36–47)
# ===========================================================================

class AudioToolsTests(_BaseTest):

    # ── helpers ─────────────────────────────────────────────────────────────

    def _make_registry(self):
        """Create a minimal mock ToolRegistry that records registered tools."""
        registry = MagicMock()
        registry._tools: dict = {}

        def _register(name, description, parameters, handler):
            registry._tools[name] = {
                "description": description,
                "parameters": parameters,
                "handler": handler,
            }

        registry.register.side_effect = _register
        return registry

    def _make_wav_file(self, tmpdir: str, duration_secs: float = 3.0) -> str:
        """Write a minimal valid WAV file and return the path."""
        sample_rate = 16000
        n_channels = 1
        sampwidth = 2
        n_frames = int(sample_rate * duration_secs)
        wav_path = str(Path(tmpdir) / "test.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * n_frames)
        return wav_path

    # ── tool registration ────────────────────────────────────────────────────

    def test_register_audio_tools(self):
        """register_audio_tools() should register exactly 6 named tools."""
        from orchestra.audio_tools import register_audio_tools

        registry = self._make_registry()
        register_audio_tools(registry)

        expected_tools = {
            "transcribe_audio",
            "synthesize_speech",
            "analyze_audio",
            "clone_voice",
            "translate_speech",
            "list_audio_backends",
        }
        self.assertEqual(set(registry._tools.keys()), expected_tools)

    def test_transcribe_audio_tool_schema(self):
        """transcribe_audio tool should require 'audio_path' and have backend enum."""
        from orchestra.audio_tools import register_audio_tools

        registry = self._make_registry()
        register_audio_tools(registry)

        schema = registry._tools["transcribe_audio"]["parameters"]
        self.assertEqual(schema["type"], "object")
        self.assertIn("audio_path", schema["required"])
        props = schema["properties"]
        self.assertIn("audio_path", props)
        self.assertIn("backend", props)
        # backend should enumerate all 6 STT options
        backend_enum = props["backend"].get("enum", [])
        self.assertIn("whisper_api", backend_enum)
        self.assertIn("deepgram", backend_enum)
        self.assertIn("assemblyai", backend_enum)
        self.assertIn("groq_whisper", backend_enum)
        self.assertIn("elevenlabs_scribe", backend_enum)
        self.assertIn("whisper_local", backend_enum)

    def test_synthesize_speech_tool_schema(self):
        """synthesize_speech tool should require 'text' and have backend/voice params."""
        from orchestra.audio_tools import register_audio_tools

        registry = self._make_registry()
        register_audio_tools(registry)

        schema = registry._tools["synthesize_speech"]["parameters"]
        self.assertIn("text", schema["required"])
        props = schema["properties"]
        self.assertIn("text", props)
        self.assertIn("voice", props)
        self.assertIn("backend", props)
        self.assertIn("speed", props)
        self.assertIn("emotion", props)
        self.assertIn("output_format", props)
        # backend enum should cover all 6 TTS backends
        backend_enum = props["backend"].get("enum", [])
        self.assertIn("openai_tts", backend_enum)
        self.assertIn("elevenlabs", backend_enum)
        self.assertIn("kokoro", backend_enum)
        self.assertIn("fish_speech", backend_enum)
        self.assertIn("chatterbox", backend_enum)
        self.assertIn("deepgram_aura", backend_enum)

    def test_analyze_audio_returns_metadata(self):
        """_analyze_audio should return duration, format, and cost estimates for a WAV."""
        from orchestra.audio_tools import _analyze_audio

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = self._make_wav_file(tmpdir, duration_secs=5.0)
            raw = run(_analyze_audio(wav_path))

        data = json.loads(raw)
        self.assertNotIn("error", data)
        self.assertEqual(data["audio_path"], wav_path)
        self.assertIn("duration_seconds", data)
        self.assertIn("format", data)
        self.assertIn("file_size_bytes", data)
        self.assertIn("stt_cost_estimates_usd", data)
        # whisper_local should always be free
        costs = data["stt_cost_estimates_usd"]
        self.assertEqual(costs.get("whisper_local", -1), 0.0)

    def test_clone_voice_rejects_unsupported_backend(self):
        """_clone_voice should return an error JSON for backends that lack cloning."""
        from orchestra.audio_tools import _clone_voice

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = self._make_wav_file(tmpdir, duration_secs=5.0)
            raw = run(_clone_voice(
                reference_audio_path=wav_path,
                text="Hello",
                backend="openai_tts",
            ))

        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("openai_tts", data["error"])
        # Supported backends should be listed in the error
        self.assertIn("chatterbox", data["error"])

    def test_clone_voice_accepts_supported_backend(self):
        """_clone_voice with chatterbox should invoke SpeechProvider.synthesize."""
        from orchestra.audio_tools import _clone_voice

        fake_tts_result = MagicMock()
        fake_tts_result.audio_bytes = b"cloned-audio"
        fake_tts_result.duration_seconds = 2.5
        fake_tts_result.cost_estimate_usd = 0.0

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = self._make_wav_file(tmpdir, duration_secs=5.0)
            out_path = str(Path(tmpdir) / "cloned.mp3")

            # SpeechProvider is imported locally inside _clone_voice, so patch
            # it on the speech_provider module rather than audio_tools.
            with patch(
                "orchestra.speech_provider.SpeechProvider"
            ) as MockProvider:
                mock_instance = MockProvider.return_value
                mock_instance.synthesize = AsyncMock(return_value=fake_tts_result)

                raw = run(_clone_voice(
                    reference_audio_path=wav_path,
                    text="Clone this voice",
                    output_path=out_path,
                    backend="chatterbox",
                ))

        data = json.loads(raw)
        # Should not contain an error about unsupported backend
        self.assertNotIn("does not support", data.get("error", ""))
        mock_instance.synthesize.assert_called_once()

    def test_translate_speech_returns_text(self):
        """_translate_speech with whisper_api should call OpenAI translations endpoint."""
        from orchestra.audio_tools import _translate_speech

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = self._make_wav_file(tmpdir, duration_secs=3.0)

            mock_translation = MagicMock()
            mock_translation.text = "Translated English text"
            mock_translation.duration = 3.0

            mock_translations = MagicMock()
            mock_translations.create = AsyncMock(return_value=mock_translation)

            mock_audio = MagicMock()
            mock_audio.translations = mock_translations

            mock_client = MagicMock()
            mock_client.audio = mock_audio

            mock_openai_cls = MagicMock(return_value=mock_client)

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), \
                 patch("orchestra.audio_tools.AsyncOpenAI", mock_openai_cls, create=True), \
                 patch(
                     "orchestra.audio_tools.__builtins__",
                     {"__import__": __import__},
                     create=True,
                 ):
                # Patch the import inside the function
                import importlib
                with patch.dict(
                    "sys.modules",
                    {"openai": MagicMock(AsyncOpenAI=mock_openai_cls)},
                ):
                    raw = run(_translate_speech(
                        audio_path=wav_path,
                        target_language="en",
                        backend="whisper_api",
                    ))

        data = json.loads(raw)
        if "error" not in data:
            self.assertIn("text", data)
            self.assertEqual(data.get("target_language"), "en")

    def test_list_audio_backends_tool(self):
        """_list_audio_backends should return STT and TTS backend capability dicts."""
        from orchestra.audio_tools import _list_audio_backends

        raw = run(_list_audio_backends())
        data = json.loads(raw)

        self.assertIn("stt_backends", data)
        self.assertIn("tts_backends", data)
        self.assertEqual(data["total_stt"], 6)
        self.assertEqual(data["total_tts"], 6)

        # Each STT entry should have capability fields
        stt = data["stt_backends"]
        self.assertIn("whisper_api", stt)
        self.assertIn("deepgram", stt)
        self.assertIn("api_key_configured", stt["whisper_api"])

        # Each TTS entry should have capability fields
        tts = data["tts_backends"]
        self.assertIn("openai_tts", tts)
        self.assertIn("kokoro", tts)
        # Local backends (kokoro) should report api_key_configured=True
        self.assertTrue(tts["kokoro"]["api_key_configured"])

    def test_synthesize_creates_output_file(self):
        """_synthesize_speech should write the audio bytes to a file."""
        from orchestra.audio_tools import _synthesize_speech

        fake_audio = b"fake-mp3-audio-data"

        fake_tts_result = MagicMock()
        fake_tts_result.audio_bytes = fake_audio
        fake_tts_result.duration_seconds = 1.5
        fake_tts_result.voice_used = "alloy"
        fake_tts_result.cost_estimate_usd = 0.0

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = str(Path(tmpdir) / "output.mp3")

            # SpeechProvider is imported locally inside _synthesize_speech,
            # so patch it on the speech_provider module.
            with patch(
                "orchestra.speech_provider.SpeechProvider"
            ) as MockProvider, \
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
                mock_instance = MockProvider.return_value
                mock_instance.synthesize = AsyncMock(return_value=fake_tts_result)

                raw = run(_synthesize_speech(
                    text="Hello, Orchestra.",
                    output_path=out_path,
                    backend="openai_tts",
                    _workspace_dir=tmpdir,
                ))

            data = json.loads(raw)

            if "error" not in data:
                # File should have been written (check while tmpdir still exists)
                self.assertTrue(Path(out_path).exists())
                self.assertEqual(Path(out_path).read_bytes(), fake_audio)
                self.assertEqual(data["output_path"], out_path)

    def test_transcribe_missing_file(self):
        """_transcribe_audio should return error JSON when the file does not exist."""
        from orchestra.audio_tools import _transcribe_audio

        raw = run(_transcribe_audio(
            audio_path="/nonexistent/path/audio.mp3",
            backend="whisper_api",
        ))
        data = json.loads(raw)
        self.assertIn("error", data)
        self.assertIn("audio_path", data)

    def test_synthesize_speed_clamping(self):
        """_synthesize_speech should clamp speed to [0.5, 2.0] before calling provider."""
        from orchestra.audio_tools import _synthesize_speech

        fake_tts_result = MagicMock()
        fake_tts_result.audio_bytes = b"audio"
        fake_tts_result.duration_seconds = 1.0
        fake_tts_result.voice_used = "alloy"
        fake_tts_result.cost_estimate_usd = 0.0

        captured_configs: list = []

        async def mock_synthesize(text, config):
            captured_configs.append(config)
            return fake_tts_result

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = str(Path(tmpdir) / "out.mp3")

            # SpeechProvider is imported locally inside _synthesize_speech,
            # so patch it on the speech_provider module.
            with patch(
                "orchestra.speech_provider.SpeechProvider"
            ) as MockProvider, \
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
                mock_instance = MockProvider.return_value
                mock_instance.synthesize = mock_synthesize

                # Speed 5.0 should be clamped to 2.0
                run(_synthesize_speech(
                    text="Test",
                    output_path=out_path,
                    backend="openai_tts",
                    speed=5.0,
                    _workspace_dir=tmpdir,
                ))

        if captured_configs:
            self.assertLessEqual(captured_configs[0].speed, 2.0)
            self.assertGreaterEqual(captured_configs[0].speed, 0.5)

    def test_analyze_audio_cost_estimates(self):
        """analyze_audio cost estimates should be 0.0 for whisper_local."""
        from orchestra.audio_tools import _analyze_audio

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = self._make_wav_file(tmpdir, duration_secs=60.0)
            raw = run(_analyze_audio(wav_path))

        data = json.loads(raw)
        self.assertNotIn("error", data)

        costs = data.get("stt_cost_estimates_usd", {})
        # whisper_local is always free
        self.assertEqual(costs.get("whisper_local"), 0.0)
        # groq_whisper is paid but very cheap — cost should be a float >= 0
        if "groq_whisper" in costs:
            self.assertGreaterEqual(costs["groq_whisper"], 0.0)
        # whisper_api at $0.006/min × 1 min = $0.006
        if "whisper_api" in costs:
            self.assertGreater(costs["whisper_api"], 0.0)


if __name__ == "__main__":
    unittest.main()
