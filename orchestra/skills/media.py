"""Horizon Orchestra — Media Skill.

Image generation (DALL-E 3 / Replicate Flux) and audio/video transcription
(OpenAI Whisper).  Mirrors Perplexity's media-handling capability.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import Skill

if TYPE_CHECKING:
    from ..router import ModelRouter

__all__ = [
    "ImageGenerator",
    "Transcriber",
    "TranscriptionResult",
]

log = logging.getLogger("orchestra.skills.media")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_media"))
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
_REPLICATE_API_KEY = os.environ.get("REPLICATE_API_TOKEN", "")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TranscriptionResult:
    """Structured result from an audio/video transcription."""

    text: str
    language: str = ""
    duration_seconds: float = 0.0
    segments: list[dict[str, Any]] = field(default_factory=list)  # [{start, end, text}]
    source: str = ""


# ---------------------------------------------------------------------------
# Image Generator
# ---------------------------------------------------------------------------

class ImageGenerator(Skill):
    """Generate and edit images via OpenAI DALL-E or Replicate Flux.

    Falls back from DALL-E → Replicate Flux if OPENAI_API_KEY is missing.
    """

    name: str = "image_generator"
    description: str = (
        "Generate images from text prompts (DALL-E 3 or Replicate Flux). "
        "Also supports image editing via OpenAI."
    )

    def __init__(self, workspace: str | Path | None = None) -> None:
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "images"
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        prompt: str,
        model: str = "dall-e-3",
        size: str = "1024x1024",
        output: str = "",
    ) -> dict[str, Any]:
        """Generate an image from a text prompt.

        Tries OpenAI DALL-E first; falls back to Replicate Flux if no
        OPENAI_API_KEY is available.

        Returns a dict with ``path``, ``url``, ``model``, and ``prompt``.
        """
        log.info("generate() prompt=%r model=%s size=%s", prompt[:80], model, size)

        api_key = os.environ.get("OPENAI_API_KEY", _OPENAI_API_KEY)
        if api_key:
            try:
                return await self._openai_generate(prompt, model, size, output, api_key)
            except Exception as exc:
                log.warning("OpenAI image generation failed: %s — trying Replicate", exc)

        # Fallback: Replicate Flux
        replicate_key = os.environ.get("REPLICATE_API_TOKEN", _REPLICATE_API_KEY)
        if replicate_key:
            try:
                return await self._replicate_generate(prompt, size, output, replicate_key)
            except Exception as exc:
                log.error("Replicate image generation failed: %s", exc)
                return {"error": str(exc), "prompt": prompt}

        return {
            "error": "No image generation API key available (OPENAI_API_KEY or REPLICATE_API_TOKEN)",
            "prompt": prompt,
        }

    async def edit(
        self,
        image_path: str,
        prompt: str,
        output: str = "",
    ) -> dict[str, Any]:
        """Edit an existing image using OpenAI's image edit endpoint.

        Returns a dict with ``path``, ``url``, and ``prompt``.
        """
        log.info("edit() image=%s prompt=%r", image_path, prompt[:80])
        api_key = os.environ.get("OPENAI_API_KEY", _OPENAI_API_KEY)
        if not api_key:
            return {"error": "OPENAI_API_KEY not set — image editing requires OpenAI"}

        output_path = output or str(self.workspace / f"edit_{uuid.uuid4().hex[:8]}.png")
        try:
            import httpx  # type: ignore[import]

            img_data = Path(image_path).read_bytes()
            form_data = {
                "prompt": prompt,
                "model": "dall-e-2",  # dall-e-2 supports edits
                "n": "1",
                "size": "1024x1024",
            }
            files = {"image": ("image.png", img_data, "image/png")}
            headers = {"Authorization": f"Bearer {api_key}"}

            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/images/edits",
                    headers=headers,
                    data=form_data,
                    files=files,
                )
                resp.raise_for_status()
                data = resp.json()

            image_url = data["data"][0].get("url") or data["data"][0].get("b64_json", "")
            saved_path = await self._download_or_save(image_url, output_path)
            return {"path": saved_path, "url": image_url, "prompt": prompt}

        except Exception as exc:
            log.error("Image edit failed: %s", exc)
            return {"error": str(exc), "prompt": prompt}

    # ------------------------------------------------------------------
    # Private generation backends
    # ------------------------------------------------------------------

    async def _openai_generate(
        self, prompt: str, model: str, size: str, output: str, api_key: str
    ) -> dict[str, Any]:
        """Generate via OpenAI DALL-E API."""
        import httpx  # type: ignore[import]

        output_path = output or str(self.workspace / f"img_{uuid.uuid4().hex[:8]}.png")
        payload = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "url",
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        image_url = data["data"][0].get("url") or data["data"][0].get("b64_json", "")
        revised_prompt = data["data"][0].get("revised_prompt", prompt)
        saved_path = await self._download_or_save(image_url, output_path)

        log.info("OpenAI DALL-E image saved: %s", saved_path)
        return {
            "path": saved_path,
            "url": image_url,
            "model": model,
            "prompt": prompt,
            "revised_prompt": revised_prompt,
        }

    async def _replicate_generate(
        self, prompt: str, size: str, output: str, api_key: str
    ) -> dict[str, Any]:
        """Generate via Replicate Flux model."""
        import httpx  # type: ignore[import]

        # Parse size string
        parts = size.split("x")
        width = int(parts[0]) if len(parts) >= 1 else 1024
        height = int(parts[1]) if len(parts) >= 2 else 1024

        output_path = output or str(self.workspace / f"flux_{uuid.uuid4().hex[:8]}.webp")

        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "version": "black-forest-labs/flux-1.1-pro",
            "input": {
                "prompt": prompt,
                "width": width,
                "height": height,
                "output_format": "webp",
                "output_quality": 90,
            },
        }

        async with httpx.AsyncClient(timeout=180) as client:
            # Create prediction
            resp = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            prediction = resp.json()
            pred_id = prediction["id"]

            # Poll for completion
            for _ in range(60):
                await asyncio.sleep(3)
                poll_resp = await client.get(
                    f"https://api.replicate.com/v1/predictions/{pred_id}",
                    headers=headers,
                )
                poll_resp.raise_for_status()
                poll_data = poll_resp.json()
                status = poll_data.get("status")
                if status == "succeeded":
                    output_url = poll_data["output"]
                    if isinstance(output_url, list):
                        output_url = output_url[0]
                    saved_path = await self._download_or_save(output_url, output_path)
                    log.info("Replicate Flux image saved: %s", saved_path)
                    return {
                        "path": saved_path,
                        "url": output_url,
                        "model": "flux-1.1-pro",
                        "prompt": prompt,
                    }
                if status in ("failed", "canceled"):
                    raise RuntimeError(f"Replicate prediction {status}: {poll_data.get('error')}")

        raise RuntimeError("Replicate prediction timed out after 3 minutes")

    async def _download_or_save(self, url_or_b64: str, output_path: str) -> str:
        """Download an image URL or decode base64 to *output_path*."""
        import httpx  # type: ignore[import]
        import base64

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if url_or_b64.startswith("http"):
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(url_or_b64)
                resp.raise_for_status()
                Path(output_path).write_bytes(resp.content)
        else:
            # base64 encoded image
            img_bytes = base64.b64decode(url_or_b64)
            Path(output_path).write_bytes(img_bytes)

        return output_path

    # ------------------------------------------------------------------
    # Skill ABC interface
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "media_generate_image",
                    "description": (
                        "Generate an image from a text prompt using DALL-E 3 or Replicate Flux. "
                        "Returns the local file path."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prompt": {"type": "string", "description": "Image generation prompt."},
                            "model": {
                                "type": "string",
                                "description": "Model to use.",
                                "enum": ["dall-e-3", "dall-e-2", "flux"],
                                "default": "dall-e-3",
                            },
                            "size": {
                                "type": "string",
                                "description": "Image dimensions (e.g. 1024x1024).",
                                "default": "1024x1024",
                            },
                            "output": {"type": "string", "description": "Output file path (optional).", "default": ""},
                        },
                        "required": ["prompt"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "media_edit_image",
                    "description": "Edit an existing image using a text prompt via OpenAI.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "image_path": {"type": "string", "description": "Path to the source image."},
                            "prompt": {"type": "string", "description": "Edit instruction."},
                            "output": {"type": "string", "description": "Output file path (optional).", "default": ""},
                        },
                        "required": ["image_path", "prompt"],
                    },
                },
            },
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "media_generate_image":
            return await self.generate(
                prompt=params["prompt"],
                model=params.get("model", "dall-e-3"),
                size=params.get("size", "1024x1024"),
                output=params.get("output", ""),
            )
        if action == "media_edit_image":
            return await self.edit(
                image_path=params["image_path"],
                prompt=params["prompt"],
                output=params.get("output", ""),
            )
        return {"error": f"Unknown action: {action!r}"}


# ---------------------------------------------------------------------------
# Transcriber
# ---------------------------------------------------------------------------

class Transcriber(Skill):
    """Transcribe audio/video files using OpenAI Whisper.

    Supports direct file transcription (mp3, wav, mp4, m4a, webm) and
    URL transcription (YouTube via yt-dlp, or direct HTTP download).
    Provides LLM-based summarisation of transcripts.
    """

    name: str = "transcriber"
    description: str = (
        "Transcribe audio or video files to text using OpenAI Whisper. "
        "Supports file paths, direct URLs, and YouTube links. "
        "Can summarise transcripts in multiple styles."
    )

    SUPPORTED_FORMATS = {".mp3", ".wav", ".mp4", ".m4a", ".webm", ".ogg", ".flac"}

    def __init__(
        self,
        router: ModelRouter | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        self.router = router
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "transcripts"
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def transcribe_file(
        self,
        file_path: str,
        language: str = "",
    ) -> TranscriptionResult:
        """Transcribe an audio/video file at *file_path*.

        Uses OpenAI Whisper API. Returns structured :class:`TranscriptionResult`.
        """
        api_key = os.environ.get("OPENAI_API_KEY", _OPENAI_API_KEY)
        if not api_key:
            return TranscriptionResult(
                text="[Error: OPENAI_API_KEY not set for Whisper transcription]",
                source=file_path,
            )

        path = Path(file_path)
        if not path.exists():
            return TranscriptionResult(
                text=f"[Error: File not found: {file_path}]",
                source=file_path,
            )

        suffix = path.suffix.lower()
        if suffix not in self.SUPPORTED_FORMATS:
            return TranscriptionResult(
                text=f"[Error: Unsupported format {suffix}. Supported: {self.SUPPORTED_FORMATS}]",
                source=file_path,
            )

        log.info("transcribe_file() file=%s language=%s", file_path, language or "auto")
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._call_whisper_api, file_path, language, api_key
            )
            return result
        except Exception as exc:
            log.error("Whisper transcription failed: %s", exc)
            return TranscriptionResult(
                text=f"[Transcription error: {exc}]",
                source=file_path,
            )

    def _call_whisper_api(
        self, file_path: str, language: str, api_key: str
    ) -> TranscriptionResult:
        """Blocking Whisper API call (run in executor)."""
        import httpx  # type: ignore[import]

        headers = {"Authorization": f"Bearer {api_key}"}
        with open(file_path, "rb") as f:
            files = {"file": (Path(file_path).name, f, "audio/mpeg")}
            data: dict[str, str] = {
                "model": "whisper-1",
                "response_format": "verbose_json",
            }
            if language:
                data["language"] = language

            with httpx.Client(timeout=300) as client:
                resp = client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                )
                resp.raise_for_status()
                result = resp.json()

        segments: list[dict[str, Any]] = []
        for seg in result.get("segments", []):
            segments.append({
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "text": seg.get("text", "").strip(),
            })

        return TranscriptionResult(
            text=result.get("text", "").strip(),
            language=result.get("language", ""),
            duration_seconds=result.get("duration", 0.0),
            segments=segments,
            source=file_path,
        )

    async def transcribe_url(
        self,
        url: str,
        output: str = "",
    ) -> TranscriptionResult:
        """Download audio/video from *url*, then transcribe it.

        For YouTube URLs, uses yt-dlp to extract audio.
        For direct media URLs, downloads via httpx.
        """
        log.info("transcribe_url() url=%s", url)
        download_dir = self.workspace / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)

        local_path = ""
        try:
            if _is_youtube_url(url):
                local_path = await self._download_youtube(url, download_dir)
            else:
                local_path = await self._download_direct(url, download_dir)

            if not local_path:
                return TranscriptionResult(
                    text="[Error: Failed to download audio]",
                    source=url,
                )

            result = await self.transcribe_file(local_path)
            result.source = url
            return result

        except Exception as exc:
            log.error("transcribe_url() failed: %s", exc)
            return TranscriptionResult(text=f"[Error: {exc}]", source=url)
        finally:
            # Clean up temp download
            if local_path and not output:
                try:
                    Path(local_path).unlink(missing_ok=True)
                except OSError:
                    pass

    async def summarize_transcript(
        self,
        transcript: str,
        style: str = "summary",
    ) -> str:
        """Summarise a transcript using an LLM.

        Args:
            transcript: Full transcript text.
            style: One of "summary", "bullets", "chapters", "action_items".

        Returns the summarised text.
        """
        if not transcript.strip():
            return "[Empty transcript]"

        style_prompts = {
            "summary": (
                "Write a clear, concise 2-4 paragraph summary of this transcript, "
                "covering the main topics, key points, and conclusions."
            ),
            "bullets": (
                "Extract the key points from this transcript as a bullet-point list. "
                "Group related points under brief subheadings."
            ),
            "chapters": (
                "Divide this transcript into logical chapters/sections. For each, "
                "provide a chapter title and a 2-3 sentence summary of its content. "
                "Format as: ## Chapter Title\n[summary]"
            ),
            "action_items": (
                "Extract all action items, decisions, and next steps mentioned in this "
                "transcript. Format as a numbered list. Include the responsible party "
                "and deadline if mentioned."
            ),
        }

        instruction = style_prompts.get(style, style_prompts["summary"])
        # Truncate very long transcripts to fit context windows
        max_chars = 30_000
        if len(transcript) > max_chars:
            transcript = transcript[:max_chars] + "\n\n[...transcript truncated...]"

        prompt = f"{instruction}\n\n=== TRANSCRIPT ===\n{transcript}"

        if self.router:
            model_name = self.router.route("summarization")
            client, model_id = self.router.get_client(model_name)
            try:
                resp = await client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2000,
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                log.error("LLM summarisation failed: %s", exc)
                return f"[Summarisation error: {exc}]"

        return f"[No router configured for summarisation]\n\nTranscript ({len(transcript)} chars) begins:\n{transcript[:500]}..."

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    async def _download_youtube(self, url: str, dest_dir: Path) -> str:
        """Download audio from a YouTube URL using yt-dlp."""
        out_template = str(dest_dir / "%(id)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "--quiet",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "192K",
            "--output", out_template,
            url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("yt-dlp timed out after 3 minutes")

        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp failed (rc={proc.returncode}): {stderr.decode()[:500]}")

        # Find the downloaded file
        for f in sorted(dest_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True):
            return str(f)

        raise RuntimeError("yt-dlp succeeded but no .mp3 file found")

    async def _download_direct(self, url: str, dest_dir: Path) -> str:
        """Download a direct audio/video URL via httpx."""
        import httpx  # type: ignore[import]

        # Guess extension from URL
        url_path = url.split("?")[0].rstrip("/")
        ext = Path(url_path).suffix.lower()
        if ext not in self.SUPPORTED_FORMATS:
            ext = ".mp3"  # assume mp3 if unknown

        out_path = dest_dir / f"dl_{uuid.uuid4().hex[:8]}{ext}"

        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(out_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

        return str(out_path)

    # ------------------------------------------------------------------
    # Skill ABC interface
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "media_transcribe",
                    "description": (
                        "Transcribe an audio or video file to text using Whisper. "
                        "Supports mp3, wav, mp4, m4a, webm."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Path to the audio/video file."},
                            "language": {
                                "type": "string",
                                "description": "ISO 639-1 language code (e.g. 'en', 'es'). Auto-detected if empty.",
                                "default": "",
                            },
                        },
                        "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "media_transcribe_url",
                    "description": (
                        "Download audio/video from a URL (or YouTube) and transcribe it. "
                        "Returns the full transcript text."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "URL to the audio/video or a YouTube URL."},
                            "output": {"type": "string", "description": "Optional output path for the download.", "default": ""},
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "media_summarize_transcript",
                    "description": (
                        "Summarise a transcript using an LLM. "
                        "Style options: summary, bullets, chapters, action_items."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "transcript": {"type": "string", "description": "Full transcript text."},
                            "style": {
                                "type": "string",
                                "enum": ["summary", "bullets", "chapters", "action_items"],
                                "description": "Summarisation style.",
                                "default": "summary",
                            },
                        },
                        "required": ["transcript"],
                    },
                },
            },
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "media_transcribe":
            result = await self.transcribe_file(
                file_path=params["file_path"],
                language=params.get("language", ""),
            )
            return {
                "text": result.text,
                "language": result.language,
                "duration_seconds": result.duration_seconds,
                "segments": result.segments,
                "source": result.source,
            }

        if action == "media_transcribe_url":
            result = await self.transcribe_url(
                url=params["url"],
                output=params.get("output", ""),
            )
            return {
                "text": result.text,
                "language": result.language,
                "duration_seconds": result.duration_seconds,
                "segments": result.segments,
                "source": result.source,
            }

        if action == "media_summarize_transcript":
            summary = await self.summarize_transcript(
                transcript=params["transcript"],
                style=params.get("style", "summary"),
            )
            return {"summary": summary}

        return {"error": f"Unknown action: {action!r}"}


# ---------------------------------------------------------------------------
# MediaSkill — composite skill wrapping both image generator and transcriber
# ---------------------------------------------------------------------------

class MediaSkill(Skill):
    """Composite skill exposing both ImageGenerator and Transcriber tools."""

    name: str = "media"
    description: str = "Image generation (DALL-E / Flux) and audio/video transcription (Whisper)."

    def __init__(
        self,
        router: ModelRouter | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        self._image = ImageGenerator(workspace=workspace)
        self._transcriber = Transcriber(router=router, workspace=workspace)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return self._image.get_tool_definitions() + self._transcriber.get_tool_definitions()

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action in ("media_generate_image", "media_edit_image"):
            return await self._image.execute(action, params)
        if action in ("media_transcribe", "media_transcribe_url", "media_summarize_transcript"):
            return await self._transcriber.execute(action, params)
        return {"error": f"Unknown action: {action!r}"}


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _is_youtube_url(url: str) -> bool:
    """Return True if *url* appears to be a YouTube video URL."""
    patterns = [
        r"https?://(www\.)?youtube\.com/watch",
        r"https?://youtu\.be/",
        r"https?://(www\.)?youtube\.com/shorts/",
    ]
    return any(re.match(p, url) for p in patterns)
