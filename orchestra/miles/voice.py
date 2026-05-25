"""
voice.py — Speech-to-text and text-to-speech integration for MILES.

Supports OpenAI Whisper API, Deepgram, and local Whisper CLI for STT;
OpenAI TTS and ElevenLabs for synthesis.
"""
from __future__ import annotations

__all__ = [
    "VoiceConfig",
    "TranscriptionResult",
    "SpeechToText",
    "TextToSpeech",
    "VoiceResponse",
    "VoiceAssistant",
]

import asyncio
import io
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class VoiceConfig:
    """Configuration for the voice interface."""

    stt_provider: str = "whisper_api"   # "whisper_api" | "deepgram" | "local_whisper"
    tts_provider: str = "openai"         # "openai" | "elevenlabs" | "local"
    voice_id: str = "alloy"              # OpenAI TTS voice or ElevenLabs voice ID
    language: str = "en"
    sample_rate: int = 16_000

    # API keys — read from environment if not supplied
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    deepgram_api_key: str = field(default_factory=lambda: os.getenv("DEEPGRAM_API_KEY", ""))
    elevenlabs_api_key: str = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", ""))


# ---------------------------------------------------------------------------
# Transcription result
# ---------------------------------------------------------------------------


@dataclass
class TranscriptionResult:
    """Result of a speech-to-text conversion."""

    text: str
    language: str
    duration: float          # audio duration in seconds
    confidence: float        # 0.0–1.0
    segments: list[dict[str, Any]] = field(default_factory=list)  # {start, end, text}


# ---------------------------------------------------------------------------
# Speech-to-Text
# ---------------------------------------------------------------------------


class SpeechToText:
    """
    Transcribes raw audio bytes to text using the configured STT provider.
    """

    def __init__(self, config: VoiceConfig) -> None:
        self._config = config
        logger.info("SpeechToText initialised with provider=%s", config.stt_provider)

    async def transcribe(
        self,
        audio_data: bytes,
        format: str = "wav",
    ) -> TranscriptionResult:
        """
        Convert *audio_data* to text.

        Args:
            audio_data: Raw audio bytes.
            format: Audio format hint (``"wav"``, ``"mp3"``, ``"ogg"``…).

        Returns:
            A :class:`TranscriptionResult`.
        """
        provider = self._config.stt_provider
        if provider == "whisper_api":
            return await self._transcribe_whisper_api(audio_data, format)
        elif provider == "deepgram":
            return await self._transcribe_deepgram(audio_data, format)
        elif provider == "local_whisper":
            return await self._transcribe_local_whisper(audio_data, format)
        else:
            raise ValueError(f"Unknown STT provider: '{provider}'")

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    async def _transcribe_whisper_api(
        self,
        audio_data: bytes,
        fmt: str,
    ) -> TranscriptionResult:
        """POST to OpenAI /v1/audio/transcriptions using multipart form."""
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._config.openai_api_key}"}
        filename = f"audio.{fmt}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"file": (filename, io.BytesIO(audio_data), f"audio/{fmt}")}
            data = {
                "model": "whisper-1",
                "language": self._config.language,
                "response_format": "verbose_json",
            }
            resp = await client.post(url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            body = resp.json()

        text = body.get("text", "")
        language = body.get("language", self._config.language)
        duration = float(body.get("duration", 0.0))
        segments: list[dict[str, Any]] = [
            {
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "text": seg.get("text", ""),
            }
            for seg in body.get("segments", [])
        ]
        # Whisper API does not expose a top-level confidence; derive from segments
        confidences = [seg.get("avg_logprob", -0.5) for seg in body.get("segments", [])]
        # avg_logprob is typically -0.5 to 0; map to 0–1
        confidence = (
            float(sum(confidences) / len(confidences)) + 0.5
            if confidences
            else 0.8
        )
        confidence = max(0.0, min(1.0, confidence + 0.5))

        logger.debug("Whisper API transcribed %d chars, duration=%.1fs", len(text), duration)
        return TranscriptionResult(
            text=text,
            language=language,
            duration=duration,
            confidence=confidence,
            segments=segments,
        )

    async def _transcribe_deepgram(
        self,
        audio_data: bytes,
        fmt: str,
    ) -> TranscriptionResult:
        """POST audio to Deepgram's streaming transcription endpoint."""
        url = "https://api.deepgram.com/v1/listen"
        headers = {
            "Authorization": f"Token {self._config.deepgram_api_key}",
            "Content-Type": f"audio/{fmt}",
        }
        params = {
            "language": self._config.language,
            "model": "nova-2",
            "smart_format": "true",
            "punctuate": "true",
            "utterances": "true",
            "diarize": "false",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, params=params, content=audio_data)
            resp.raise_for_status()
            body = resp.json()

        channel = body.get("results", {}).get("channels", [{}])[0]
        alternative = (channel.get("alternatives") or [{}])[0]
        text = alternative.get("transcript", "")
        confidence = float(alternative.get("confidence", 0.8))
        duration = float(
            body.get("metadata", {}).get("duration", 0.0)
        )
        words = alternative.get("words", [])
        # Build segments from utterance breaks (every ~5 words for simplicity)
        segments: list[dict[str, Any]] = []
        chunk: list[dict[str, Any]] = []
        for word in words:
            chunk.append(word)
            if len(chunk) >= 5:
                segments.append(
                    {
                        "start": chunk[0].get("start", 0),
                        "end": chunk[-1].get("end", 0),
                        "text": " ".join(w.get("word", "") for w in chunk),
                    }
                )
                chunk = []
        if chunk:
            segments.append(
                {
                    "start": chunk[0].get("start", 0),
                    "end": chunk[-1].get("end", 0),
                    "text": " ".join(w.get("word", "") for w in chunk),
                }
            )

        logger.debug("Deepgram transcribed %d chars, confidence=%.2f", len(text), confidence)
        return TranscriptionResult(
            text=text,
            language=self._config.language,
            duration=duration,
            confidence=confidence,
            segments=segments,
        )

    async def _transcribe_local_whisper(
        self,
        audio_data: bytes,
        fmt: str,
    ) -> TranscriptionResult:
        """Run the local ``whisper`` CLI via subprocess."""
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as tmp_audio:
            tmp_audio.write(audio_data)
            tmp_audio_path = tmp_audio.name

        tmp_dir = tempfile.mkdtemp()
        try:
            cmd = [
                "whisper",
                tmp_audio_path,
                "--language", self._config.language,
                "--output_dir", tmp_dir,
                "--output_format", "json",
                "--model", "base",
            ]
            t0 = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            elapsed = time.monotonic() - t0

            if proc.returncode != 0:
                raise RuntimeError(
                    f"whisper CLI exited with code {proc.returncode}: {stderr.decode()}"
                )

            # Find the JSON output file
            import glob as _glob
            import json as _json
            json_files = _glob.glob(f"{tmp_dir}/*.json")
            text = ""
            segments: list[dict[str, Any]] = []
            if json_files:
                with open(json_files[0]) as f:
                    data = _json.load(f)
                text = data.get("text", "")
                for seg in data.get("segments", []):
                    segments.append({
                        "start": seg.get("start", 0),
                        "end": seg.get("end", 0),
                        "text": seg.get("text", ""),
                    })
            else:
                text = stdout.decode().strip()

            logger.debug("Local whisper transcribed in %.2fs: %d chars", elapsed, len(text))
            return TranscriptionResult(
                text=text,
                language=self._config.language,
                duration=elapsed,
                confidence=0.85,  # local whisper doesn't expose confidence
                segments=segments,
            )
        finally:
            # Cleanup temp files
            import os as _os
            try:
                _os.unlink(tmp_audio_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Text-to-Speech
# ---------------------------------------------------------------------------


class TextToSpeech:
    """
    Synthesizes text to audio bytes using the configured TTS provider.
    """

    def __init__(self, config: VoiceConfig) -> None:
        self._config = config
        logger.info("TextToSpeech initialised with provider=%s", config.tts_provider)

    async def synthesize(self, text: str, voice: str = "") -> bytes:
        """
        Convert *text* to audio bytes (MP3).

        Args:
            text: The text to speak.
            voice: Override the config voice ID.

        Returns:
            MP3 audio bytes.
        """
        effective_voice = voice or self._config.voice_id
        provider = self._config.tts_provider

        if provider == "openai":
            return await self._synthesize_openai(text, effective_voice)
        elif provider == "elevenlabs":
            return await self._synthesize_elevenlabs(text, effective_voice)
        else:
            raise ValueError(f"Unknown TTS provider: '{provider}'")

    async def synthesize_to_file(
        self,
        text: str,
        path: str,
        voice: str = "",
    ) -> str:
        """
        Synthesize *text* and save the MP3 to *path*.

        Returns:
            The absolute path where the file was written.
        """
        audio_bytes = await self.synthesize(text, voice)
        with open(path, "wb") as f:
            f.write(audio_bytes)
        logger.info("Audio saved to %s (%d bytes)", path, len(audio_bytes))
        return os.path.abspath(path)

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    async def _synthesize_openai(self, text: str, voice: str) -> bytes:
        """POST to OpenAI /v1/audio/speech."""
        url = "https://api.openai.com/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {self._config.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "response_format": "mp3",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            audio = resp.content

        logger.debug("OpenAI TTS synthesized %d chars → %d bytes", len(text), len(audio))
        return audio

    async def _synthesize_elevenlabs(self, text: str, voice: str) -> bytes:
        """POST to ElevenLabs text-to-speech endpoint."""
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
        headers = {
            "xi-api-key": self._config.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            audio = resp.content

        logger.debug("ElevenLabs TTS synthesized %d chars → %d bytes", len(text), len(audio))
        return audio


# ---------------------------------------------------------------------------
# Voice Response
# ---------------------------------------------------------------------------


@dataclass
class VoiceResponse:
    """Complete voice interaction result — both text and audio."""

    transcript: str
    response_text: str
    response_audio: bytes
    duration: float  # total round-trip seconds


# ---------------------------------------------------------------------------
# Voice Assistant
# ---------------------------------------------------------------------------


class VoiceAssistant:
    """
    End-to-end voice pipeline: audio in → agent → audio out.

    Wires together :class:`SpeechToText`, an Orchestra agent,
    and :class:`TextToSpeech`.
    """

    def __init__(
        self,
        stt: SpeechToText,
        tts: TextToSpeech,
        agent: Any,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._agent = agent
        logger.info("VoiceAssistant initialised.")

    async def process_voice(self, audio_data: bytes) -> VoiceResponse:
        """
        Full pipeline:

        1. STT: Transcribe *audio_data* to text.
        2. Agent: Run text through the Orchestra agent.
        3. TTS: Synthesize the agent's response to audio.
        4. Return :class:`VoiceResponse`.
        """
        t_start = time.monotonic()

        # Step 1 — Transcribe
        logger.info("VoiceAssistant: transcribing %d bytes of audio", len(audio_data))
        transcription = await self._stt.transcribe(audio_data)
        transcript = transcription.text
        logger.info("Transcript: %s", transcript[:120])

        # Step 2 — Run through agent
        response_text = await self._run_agent(transcript)
        logger.info("Agent response: %s", response_text[:120])

        # Step 3 — Synthesize
        response_audio = await self._tts.synthesize(response_text)
        logger.info("Synthesized %d bytes of audio", len(response_audio))

        duration = time.monotonic() - t_start
        return VoiceResponse(
            transcript=transcript,
            response_text=response_text,
            response_audio=response_audio,
            duration=round(duration, 3),
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _run_agent(self, text: str) -> str:
        """
        Invoke the agent.  Supports both coroutine-based agents (``await agent.run()``)
        and simpler callable interfaces.
        """
        try:
            # Try async .run(text)
            if hasattr(self._agent, "run"):
                result = self._agent.run(text)
                if asyncio.iscoroutine(result):
                    result = await result
                return str(result)

            # Try async callable
            result = self._agent(text)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)

        except Exception as exc:  # noqa: BLE001
            logger.error("Agent call failed: %s", exc)
            return "I'm sorry, I encountered an error processing your request."
