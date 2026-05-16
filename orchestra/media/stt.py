"""Horizon Orchestra — Speech-to-Text Engine (Whisper).

Async interface for audio/video transcription via OpenAI Whisper API
or local Whisper model.  Supports transcription, translation,
word-level timestamps, and VTT/SRT subtitle generation.

Usage::

    from orchestra.media.stt import STTEngine

    engine = STTEngine()
    result = await engine.transcribe("podcast.mp3")
    print(result.text)
    srt = engine.to_srt(result)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "STTEngine",
    "TranscriptResult",
    "Segment",
    "Word",
]

log = logging.getLogger("orchestra.media.stt")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_media"))
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Optional dependency: openai
try:
    import openai as _openai_mod
    _HAS_OPENAI = True
except ImportError:
    _openai_mod = None  # type: ignore[assignment]
    _HAS_OPENAI = False


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Word:
    """A single word with timing information."""

    text: str = ""
    start: float = 0.0
    end: float = 0.0
    confidence: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Segment:
    """A segment of transcribed audio."""

    id: int = 0
    text: str = ""
    start: float = 0.0
    end: float = 0.0
    words: list[Word] = field(default_factory=list)
    confidence: float = 0.0
    language: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class TranscriptResult:
    """Complete transcription result."""

    text: str = ""
    language: str = ""
    duration: float = 0.0
    segments: list[Segment] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    model: str = ""
    source_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def segment_count(self) -> int:
        return len(self.segments)


# ---------------------------------------------------------------------------
# STTEngine
# ---------------------------------------------------------------------------

class STTEngine:
    """Speech-to-text engine supporting OpenAI Whisper API and local Whisper.

    Parameters
    ----------
    workspace:
        Directory for saving output files.
    openai_api_key:
        OpenAI API key for Whisper API.
    default_model:
        Default Whisper model (``whisper-1`` for API, or local model name).
    use_local:
        If *True*, prefer local Whisper over the API.
    """

    def __init__(
        self,
        workspace: str | Path | None = None,
        openai_api_key: str | None = None,
        default_model: str = "whisper-1",
        use_local: bool = False,
    ) -> None:
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "stt"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._openai_key = openai_api_key or _OPENAI_API_KEY
        self._default_model = default_model
        self._use_local = use_local

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_openai_client(self) -> Any:
        """Instantiate an async OpenAI client."""
        if not _HAS_OPENAI:
            raise ImportError("openai package is required: pip install openai")
        if not self._openai_key:
            raise ValueError("OPENAI_API_KEY is required for Whisper API.")
        return _openai_mod.AsyncOpenAI(api_key=self._openai_key)

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds as ``HH:MM:SS,mmm`` for SRT."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _format_vtt_timestamp(seconds: float) -> str:
        """Format seconds as ``HH:MM:SS.mmm`` for WebVTT."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    def _parse_segments(self, raw_segments: list[dict[str, Any]]) -> list[Segment]:
        """Parse raw segment dicts into Segment dataclasses."""
        segments: list[Segment] = []
        for i, raw in enumerate(raw_segments):
            words: list[Word] = []
            for w in raw.get("words", []):
                words.append(Word(
                    text=w.get("word", ""),
                    start=float(w.get("start", 0)),
                    end=float(w.get("end", 0)),
                ))
            segments.append(Segment(
                id=i,
                text=raw.get("text", "").strip(),
                start=float(raw.get("start", 0)),
                end=float(raw.get("end", 0)),
                words=words,
            ))
        return segments

    # ------------------------------------------------------------------
    # OpenAI Whisper API
    # ------------------------------------------------------------------

    async def _transcribe_openai(
        self,
        audio_path: str | Path,
        language: str | None = None,
        model: str = "whisper-1",
        prompt: str = "",
        timestamps: bool = True,
    ) -> TranscriptResult:
        """Transcribe audio via OpenAI Whisper API."""
        client = self._get_openai_client()
        try:
            with open(str(audio_path), "rb") as f:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "file": f,
                    "response_format": "verbose_json",
                }
                if language:
                    kwargs["language"] = language
                if prompt:
                    kwargs["prompt"] = prompt
                if timestamps:
                    kwargs["timestamp_granularities"] = ["segment", "word"]

                response = await client.audio.transcriptions.create(**kwargs)

            # Parse response
            text = getattr(response, "text", "") or ""
            lang = getattr(response, "language", "") or ""
            duration = float(getattr(response, "duration", 0) or 0)
            raw_segments = getattr(response, "segments", []) or []
            raw_words = getattr(response, "words", []) or []

            segments = self._parse_segments(raw_segments)
            words = [
                Word(
                    text=w.get("word", "") if isinstance(w, dict) else getattr(w, "word", ""),
                    start=float(w.get("start", 0) if isinstance(w, dict) else getattr(w, "start", 0)),
                    end=float(w.get("end", 0) if isinstance(w, dict) else getattr(w, "end", 0)),
                )
                for w in raw_words
            ]

            return TranscriptResult(
                text=text,
                language=lang,
                duration=duration,
                segments=segments,
                words=words,
                model=model,
                source_path=str(audio_path),
            )
        finally:
            await client.close()

    async def _translate_openai(
        self,
        audio_path: str | Path,
        model: str = "whisper-1",
    ) -> TranscriptResult:
        """Translate audio to English via OpenAI Whisper API."""
        client = self._get_openai_client()
        try:
            with open(str(audio_path), "rb") as f:
                response = await client.audio.translations.create(
                    model=model,
                    file=f,
                    response_format="verbose_json",
                )

            text = getattr(response, "text", "") or ""
            duration = float(getattr(response, "duration", 0) or 0)
            raw_segments = getattr(response, "segments", []) or []
            segments = self._parse_segments(raw_segments)

            return TranscriptResult(
                text=text,
                language="en",
                duration=duration,
                segments=segments,
                model=model,
                source_path=str(audio_path),
                metadata={"task": "translation"},
            )
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # Local Whisper
    # ------------------------------------------------------------------

    async def _transcribe_local(
        self,
        audio_path: str | Path,
        language: str | None = None,
        model: str = "base",
    ) -> TranscriptResult:
        """Transcribe audio using local whisper CLI."""
        whisper_bin = shutil.which("whisper")
        if not whisper_bin:
            raise RuntimeError(
                "Local whisper is not installed. "
                "Install it with: pip install openai-whisper"
            )

        output_dir = self.workspace / f"whisper_{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            whisper_bin,
            str(audio_path),
            "--model", model,
            "--output_dir", str(output_dir),
            "--output_format", "json",
        ]
        if language:
            cmd.extend(["--language", language])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"whisper failed: {stderr.decode(errors='replace')[:1000]}")

        # Find output JSON
        json_files = list(output_dir.glob("*.json"))
        if not json_files:
            raise RuntimeError("No transcription output found.")

        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        text = data.get("text", "")
        raw_segments = data.get("segments", [])
        segments = self._parse_segments(raw_segments)
        lang = data.get("language", "")

        # Estimate duration from last segment
        duration = 0.0
        if segments:
            duration = segments[-1].end

        return TranscriptResult(
            text=text,
            language=lang,
            duration=duration,
            segments=segments,
            model=model,
            source_path=str(audio_path),
            metadata={"backend": "local"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        model: str | None = None,
        prompt: str = "",
        timestamps: bool = True,
    ) -> TranscriptResult:
        """Transcribe audio to text.

        Parameters
        ----------
        audio_path:
            Path to the audio/video file.
        language:
            ISO-639-1 language code (``en``, ``es``, ``fr``, …).
            Auto-detected if *None*.
        model:
            Whisper model name.
        prompt:
            Optional prompt to guide transcription.
        timestamps:
            Whether to include word/segment timestamps.

        Returns
        -------
        TranscriptResult
            Structured transcription with segments and timestamps.
        """
        use_model = model or self._default_model

        if self._use_local:
            return await self._transcribe_local(audio_path, language=language, model=use_model)
        return await self._transcribe_openai(
            audio_path, language=language, model=use_model,
            prompt=prompt, timestamps=timestamps,
        )

    async def translate(
        self,
        audio_path: str | Path,
        *,
        target_language: str = "en",
        model: str | None = None,
    ) -> TranscriptResult:
        """Translate audio to a target language.

        Currently only English translation is supported via the Whisper API.

        Parameters
        ----------
        audio_path:
            Path to the audio/video file.
        target_language:
            Target language (currently only ``"en"`` is supported).
        model:
            Whisper model name.

        Returns
        -------
        TranscriptResult
            Translated transcription.
        """
        use_model = model or self._default_model

        if target_language != "en":
            log.warning(
                "Whisper translation only supports English output. "
                "Translating to English instead of '%s'.",
                target_language,
            )

        return await self._translate_openai(audio_path, model=use_model)

    # ------------------------------------------------------------------
    # Subtitle generation
    # ------------------------------------------------------------------

    def to_srt(self, result: TranscriptResult) -> str:
        """Convert a transcription result to SRT subtitle format.

        Parameters
        ----------
        result:
            Transcription result with segments.

        Returns
        -------
        str
            SRT-formatted subtitle string.
        """
        lines: list[str] = []
        for i, seg in enumerate(result.segments, 1):
            start_ts = self._format_timestamp(seg.start)
            end_ts = self._format_timestamp(seg.end)
            lines.append(str(i))
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(seg.text)
            lines.append("")
        return "\n".join(lines)

    def to_vtt(self, result: TranscriptResult) -> str:
        """Convert a transcription result to WebVTT subtitle format.

        Parameters
        ----------
        result:
            Transcription result with segments.

        Returns
        -------
        str
            WebVTT-formatted subtitle string.
        """
        lines: list[str] = ["WEBVTT", ""]
        for seg in result.segments:
            start_ts = self._format_vtt_timestamp(seg.start)
            end_ts = self._format_vtt_timestamp(seg.end)
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(seg.text)
            lines.append("")
        return "\n".join(lines)

    def save_srt(self, result: TranscriptResult, path: str | Path | None = None) -> Path:
        """Save transcription as SRT file.

        Parameters
        ----------
        result:
            Transcription result.
        path:
            Output file path. Auto-generated if *None*.

        Returns
        -------
        Path
            Path to the saved SRT file.
        """
        save_to = Path(path) if path else self.workspace / f"{uuid.uuid4().hex[:12]}.srt"
        srt_content = self.to_srt(result)
        save_to.write_text(srt_content, encoding="utf-8")
        log.info("Saved SRT → %s", save_to)
        return save_to

    def save_vtt(self, result: TranscriptResult, path: str | Path | None = None) -> Path:
        """Save transcription as WebVTT file.

        Parameters
        ----------
        result:
            Transcription result.
        path:
            Output file path. Auto-generated if *None*.

        Returns
        -------
        Path
            Path to the saved VTT file.
        """
        save_to = Path(path) if path else self.workspace / f"{uuid.uuid4().hex[:12]}.vtt"
        vtt_content = self.to_vtt(result)
        save_to.write_text(vtt_content, encoding="utf-8")
        log.info("Saved VTT → %s", save_to)
        return save_to
