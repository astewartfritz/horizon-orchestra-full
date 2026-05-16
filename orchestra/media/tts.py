"""Horizon Orchestra — Text-to-Speech Engine.

Unified TTS interface supporting OpenAI TTS (tts-1, tts-1-hd) and
ElevenLabs.  Provides synthesis, streaming, and voice listing.

Usage::

    from orchestra.media.tts import TTSEngine

    engine = TTSEngine()
    result = await engine.synthesize("Hello, world!", voice="alloy")
    print(result.path)
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Optional

__all__ = [
    "TTSEngine",
    "AudioResult",
    "TTSProvider",
]

log = logging.getLogger("orchestra.media.tts")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_media"))
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
_ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# Optional dependency: httpx
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False

# Optional dependency: openai
try:
    import openai as _openai_mod
    _HAS_OPENAI = True
except ImportError:
    _openai_mod = None  # type: ignore[assignment]
    _HAS_OPENAI = False


# ---------------------------------------------------------------------------
# Enums / Dataclasses
# ---------------------------------------------------------------------------

class TTSProvider(str, Enum):
    """Supported TTS providers."""

    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"


# Available voices by provider
OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]
OPENAI_MODELS = ["tts-1", "tts-1-hd"]

ELEVENLABS_DEFAULT_VOICES = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "drew": "29vD33N1CtxCmqQRPOHJ",
    "clyde": "2EiwWnXFnvU5JabPnv8n",
    "paul": "5Q0t7uMcjvnagumLfvZi",
    "domi": "AZnzlk1XvdvUeBnXmlld",
    "dave": "CYw3kZ02Hs0563khs1Fj",
    "fin": "D38z5RcWu1voky8WS1ja",
    "sarah": "EXAVITQu4vr4xnSDxMaL",
    "antoni": "ErXwobaYiN019PkySvjV",
    "thomas": "GBv7mTt0atIp3Br8iCZE",
    "charlie": "IKne3meq5aSn9XLyUdCD",
    "emily": "LcfcDJNUP1GQjkzn1xUU",
}


@dataclass
class AudioResult:
    """Result from a TTS synthesis operation."""

    path: str = ""
    duration: float = 0.0
    format: str = "mp3"
    voice: str = ""
    model: str = ""
    provider: str = ""
    size_bytes: int = 0
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_file(self) -> bool:
        return bool(self.path) and Path(self.path).exists()


# ---------------------------------------------------------------------------
# TTSEngine
# ---------------------------------------------------------------------------

class TTSEngine:
    """Unified text-to-speech engine supporting multiple providers.

    Parameters
    ----------
    workspace:
        Directory for saving audio files.
    openai_api_key:
        OpenAI API key.
    elevenlabs_api_key:
        ElevenLabs API key.
    default_provider:
        Default provider when none is specified.
    default_voice:
        Default voice name.
    """

    def __init__(
        self,
        workspace: str | Path | None = None,
        openai_api_key: str | None = None,
        elevenlabs_api_key: str | None = None,
        default_provider: str = "openai",
        default_voice: str = "alloy",
    ) -> None:
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "tts"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._openai_key = openai_api_key or _OPENAI_API_KEY
        self._elevenlabs_key = elevenlabs_api_key or _ELEVENLABS_API_KEY
        self._default_provider = default_provider
        self._default_voice = default_voice

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_path(self, ext: str = "mp3") -> Path:
        return self.workspace / f"{uuid.uuid4().hex[:12]}.{ext}"

    def _get_openai_client(self) -> Any:
        """Instantiate an async OpenAI client."""
        if not _HAS_OPENAI:
            raise ImportError("openai package is required: pip install openai")
        if not self._openai_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI TTS.")
        return _openai_mod.AsyncOpenAI(api_key=self._openai_key)

    # ------------------------------------------------------------------
    # OpenAI TTS
    # ------------------------------------------------------------------

    async def _synthesize_openai(
        self,
        text: str,
        voice: str = "alloy",
        model: str = "tts-1",
        speed: float = 1.0,
        response_format: str = "mp3",
    ) -> AudioResult:
        """Synthesize speech via OpenAI TTS API."""
        client = self._get_openai_client()
        try:
            response = await client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                speed=speed,
                response_format=response_format,
            )

            save_to = self._save_path(response_format)
            content = response.content
            save_to.write_bytes(content)

            return AudioResult(
                path=str(save_to),
                format=response_format,
                voice=voice,
                model=model,
                provider="openai",
                size_bytes=len(content),
                text=text,
            )
        finally:
            await client.close()

    async def _stream_openai(
        self,
        text: str,
        voice: str = "alloy",
        model: str = "tts-1",
        speed: float = 1.0,
        response_format: str = "mp3",
    ) -> AsyncIterator[bytes]:
        """Stream audio chunks from OpenAI TTS."""
        client = self._get_openai_client()
        try:
            response = await client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                speed=speed,
                response_format=response_format,
            )
            # OpenAI returns the full content; we chunk it for streaming
            content = response.content
            chunk_size = 4096
            for i in range(0, len(content), chunk_size):
                yield content[i:i + chunk_size]
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # ElevenLabs TTS
    # ------------------------------------------------------------------

    async def _synthesize_elevenlabs(
        self,
        text: str,
        voice: str = "rachel",
        model: str = "eleven_multilingual_v2",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        output_format: str = "mp3",
    ) -> AudioResult:
        """Synthesize speech via ElevenLabs API."""
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")
        if not self._elevenlabs_key:
            raise ValueError("ELEVENLABS_API_KEY is required for ElevenLabs TTS.")

        # Resolve voice name to voice_id
        voice_id = ELEVENLABS_DEFAULT_VOICES.get(voice.lower(), voice)

        headers = {
            "xi-api-key": self._elevenlabs_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
            },
        }

        output_format_param = {
            "mp3": "mp3_44100_128",
            "wav": "pcm_44100",
            "opus": "opus_48000",
        }.get(output_format, "mp3_44100_128")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={output_format_param}",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            audio_bytes = resp.content

        ext = output_format if output_format in ("mp3", "wav", "opus") else "mp3"
        save_to = self._save_path(ext)
        save_to.write_bytes(audio_bytes)

        return AudioResult(
            path=str(save_to),
            format=ext,
            voice=voice,
            model=model,
            provider="elevenlabs",
            size_bytes=len(audio_bytes),
            text=text,
        )

    async def _stream_elevenlabs(
        self,
        text: str,
        voice: str = "rachel",
        model: str = "eleven_multilingual_v2",
        output_format: str = "mp3",
    ) -> AsyncIterator[bytes]:
        """Stream audio chunks from ElevenLabs."""
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")
        if not self._elevenlabs_key:
            raise ValueError("ELEVENLABS_API_KEY is required for ElevenLabs TTS.")

        voice_id = ELEVENLABS_DEFAULT_VOICES.get(voice.lower(), voice)
        headers = {
            "xi-api-key": self._elevenlabs_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
                json=payload,
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(4096):
                    yield chunk

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        model: str | None = None,
        speed: float = 1.0,
        provider: str | None = None,
        output_format: str = "mp3",
    ) -> AudioResult:
        """Synthesize speech from text.

        Parameters
        ----------
        text:
            Input text to convert to speech.
        voice:
            Voice name or ID.
        model:
            TTS model (``tts-1``, ``tts-1-hd``, ``eleven_multilingual_v2``).
        speed:
            Playback speed multiplier (OpenAI only, 0.25–4.0).
        provider:
            TTS provider (``openai`` or ``elevenlabs``).
        output_format:
            Audio format (``mp3``, ``wav``, ``opus``, ``aac``, ``flac``).

        Returns
        -------
        AudioResult
            Generated audio file information.
        """
        use_provider = provider or self._default_provider
        use_voice = voice or self._default_voice

        if use_provider == "openai":
            use_model = model or "tts-1"
            return await self._synthesize_openai(
                text, voice=use_voice, model=use_model,
                speed=speed, response_format=output_format,
            )
        elif use_provider == "elevenlabs":
            use_model = model or "eleven_multilingual_v2"
            return await self._synthesize_elevenlabs(
                text, voice=use_voice, model=use_model,
                output_format=output_format,
            )
        else:
            log.warning("Unknown provider '%s', falling back to openai.", use_provider)
            return await self._synthesize_openai(
                text, voice=use_voice, model=model or "tts-1",
                speed=speed, response_format=output_format,
            )

    async def stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        output_format: str = "mp3",
    ) -> AsyncIterator[bytes]:
        """Stream audio chunks for real-time playback.

        Parameters
        ----------
        text:
            Input text.
        voice:
            Voice name or ID.
        model:
            TTS model.
        provider:
            TTS provider.
        output_format:
            Audio format.

        Yields
        ------
        bytes
            Audio data chunks.
        """
        use_provider = provider or self._default_provider
        use_voice = voice or self._default_voice

        if use_provider == "elevenlabs":
            async for chunk in self._stream_elevenlabs(
                text, voice=use_voice,
                model=model or "eleven_multilingual_v2",
                output_format=output_format,
            ):
                yield chunk
        else:
            async for chunk in self._stream_openai(
                text, voice=use_voice,
                model=model or "tts-1",
                response_format=output_format,
            ):
                yield chunk

    def available_voices(self, provider: str | None = None) -> dict[str, list[str]]:
        """List available voices by provider.

        Parameters
        ----------
        provider:
            Filter to a specific provider. Returns all if *None*.

        Returns
        -------
        dict[str, list[str]]
            Mapping of provider → voice names.
        """
        voices: dict[str, list[str]] = {}
        use_provider = provider or "all"

        if use_provider in ("openai", "all"):
            voices["openai"] = list(OPENAI_VOICES)
        if use_provider in ("elevenlabs", "all"):
            voices["elevenlabs"] = list(ELEVENLABS_DEFAULT_VOICES.keys())

        return voices
