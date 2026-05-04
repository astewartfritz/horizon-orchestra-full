"""Horizon Orchestra — Video Generation.

Unified interface for AI-powered video generation via Google Veo,
OpenAI Sora, and Runway Gen-3 APIs.  Supports text-to-video,
image-to-video, and async polling for completion.

Usage::

    from orchestra.media.video_gen import VideoGenerator

    gen = VideoGenerator()
    result = await gen.generate("a cat playing piano", model="veo")
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "VideoGenerator",
    "VideoResult",
    "VideoModel",
    "GenerationStatus",
]

log = logging.getLogger("orchestra.media.video_gen")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_media"))
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
_GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
_RUNWAY_API_KEY = os.environ.get("RUNWAY_API_KEY", "")

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

class VideoModel(str, Enum):
    """Supported video generation models."""

    VEO = "veo"
    VEO_2 = "veo-2"
    SORA = "sora"
    RUNWAY_GEN3 = "runway-gen3"


class GenerationStatus(str, Enum):
    """Status of an async video generation job."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class VideoResult:
    """Result from a video generation operation."""

    url: str = ""
    local_path: str = ""
    prompt: str = ""
    model: str = ""
    duration: float = 0.0
    resolution: str = ""
    generation_id: str = ""
    status: str = "succeeded"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_file(self) -> bool:
        return bool(self.local_path) and Path(self.local_path).exists()


# ---------------------------------------------------------------------------
# VideoGenerator
# ---------------------------------------------------------------------------

class VideoGenerator:
    """Unified video generation across multiple AI models.

    Parameters
    ----------
    workspace:
        Directory for saving generated videos.
    openai_api_key:
        OpenAI API key for Sora.
    google_api_key:
        Google API key for Veo.
    runway_api_key:
        Runway API key for Gen-3.
    default_model:
        Default model when none is specified.
    poll_interval:
        Seconds between status checks during async generation.
    max_poll_time:
        Maximum seconds to wait for generation to complete.
    """

    SUPPORTED_MODELS = {m.value for m in VideoModel}

    def __init__(
        self,
        workspace: str | Path | None = None,
        openai_api_key: str | None = None,
        google_api_key: str | None = None,
        runway_api_key: str | None = None,
        default_model: str = "veo",
        poll_interval: float = 5.0,
        max_poll_time: float = 600.0,
    ) -> None:
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "videos"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._openai_key = openai_api_key or _OPENAI_API_KEY
        self._google_key = google_api_key or _GOOGLE_API_KEY
        self._runway_key = runway_api_key or _RUNWAY_API_KEY
        self._default_model = default_model
        self._poll_interval = poll_interval
        self._max_poll_time = max_poll_time

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_path(self, ext: str = "mp4") -> Path:
        return self.workspace / f"{uuid.uuid4().hex[:12]}.{ext}"

    async def _download(self, url: str, path: Path | None = None) -> Path:
        """Download a video from a URL."""
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")
        save_to = path or self._save_path("mp4")
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            save_to.write_bytes(resp.content)
        log.debug("Saved video to %s (%d bytes)", save_to, save_to.stat().st_size)
        return save_to

    # ------------------------------------------------------------------
    # Google Veo
    # ------------------------------------------------------------------

    async def _generate_veo(
        self,
        prompt: str,
        duration: float = 4.0,
        resolution: str = "1080p",
        aspect_ratio: str = "16:9",
    ) -> VideoResult:
        """Generate video via Google Veo / Imagen Video API."""
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")
        if not self._google_key:
            raise ValueError("GOOGLE_API_KEY is required for Veo video generation.")

        payload = {
            "instances": [{
                "prompt": prompt,
            }],
            "parameters": {
                "sampleCount": 1,
                "durationSeconds": int(duration),
                "aspectRatio": aspect_ratio,
                "resolution": resolution,
            },
        }
        headers = {
            "Authorization": f"Bearer {self._google_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/veo:generateVideo",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        operation_name = data.get("name", "")
        generation_id = operation_name or uuid.uuid4().hex

        # Poll for completion
        video_url = ""
        elapsed = 0.0
        while elapsed < self._max_poll_time:
            await asyncio.sleep(self._poll_interval)
            elapsed += self._poll_interval

            async with httpx.AsyncClient(timeout=30.0) as client:
                status_resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/{operation_name}",
                    headers=headers,
                )
                if status_resp.status_code != 200:
                    continue
                status_data = status_resp.json()

            if status_data.get("done"):
                response_data = status_data.get("response", {})
                videos = response_data.get("generatedSamples", [])
                if videos:
                    video_url = videos[0].get("video", {}).get("uri", "")
                break

        if not video_url:
            return VideoResult(
                prompt=prompt,
                model="veo",
                generation_id=generation_id,
                status=GenerationStatus.FAILED.value,
            )

        local_path = str(await self._download(video_url))
        return VideoResult(
            url=video_url,
            local_path=local_path,
            prompt=prompt,
            model="veo",
            duration=duration,
            resolution=resolution,
            generation_id=generation_id,
            status=GenerationStatus.SUCCEEDED.value,
        )

    # ------------------------------------------------------------------
    # OpenAI Sora
    # ------------------------------------------------------------------

    async def _generate_sora(
        self,
        prompt: str,
        duration: float = 5.0,
        resolution: str = "1080p",
    ) -> VideoResult:
        """Generate video via OpenAI Sora API."""
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")
        if not self._openai_key:
            raise ValueError("OPENAI_API_KEY is required for Sora video generation.")

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "sora",
            "prompt": prompt,
            "duration": int(duration),
            "resolution": resolution,
            "n": 1,
        }

        generation_id = ""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/videos/generations",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            generation_id = data.get("id", uuid.uuid4().hex)

        # Poll for completion
        video_url = ""
        elapsed = 0.0
        while elapsed < self._max_poll_time:
            await asyncio.sleep(self._poll_interval)
            elapsed += self._poll_interval

            async with httpx.AsyncClient(timeout=30.0) as client:
                status_resp = await client.get(
                    f"https://api.openai.com/v1/videos/generations/{generation_id}",
                    headers=headers,
                )
                if status_resp.status_code != 200:
                    continue
                status_data = status_resp.json()

            status = status_data.get("status", "")
            if status == "succeeded":
                video_url = status_data.get("video", {}).get("url", "")
                if not video_url:
                    outputs = status_data.get("data", [])
                    if outputs:
                        video_url = outputs[0].get("url", "")
                break
            elif status == "failed":
                return VideoResult(
                    prompt=prompt,
                    model="sora",
                    generation_id=generation_id,
                    status=GenerationStatus.FAILED.value,
                    metadata={"error": status_data.get("error", "Unknown error")},
                )

        if not video_url:
            return VideoResult(
                prompt=prompt,
                model="sora",
                generation_id=generation_id,
                status=GenerationStatus.FAILED.value,
            )

        local_path = str(await self._download(video_url))
        return VideoResult(
            url=video_url,
            local_path=local_path,
            prompt=prompt,
            model="sora",
            duration=duration,
            resolution=resolution,
            generation_id=generation_id,
            status=GenerationStatus.SUCCEEDED.value,
        )

    # ------------------------------------------------------------------
    # Runway Gen-3
    # ------------------------------------------------------------------

    async def _generate_runway(
        self,
        prompt: str,
        duration: float = 4.0,
        resolution: str = "1080p",
        image_url: str = "",
    ) -> VideoResult:
        """Generate video via Runway Gen-3 Alpha API."""
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")
        if not self._runway_key:
            raise ValueError("RUNWAY_API_KEY is required for Runway video generation.")

        headers = {
            "Authorization": f"Bearer {self._runway_key}",
            "Content-Type": "application/json",
            "X-Runway-Version": "2024-11-06",
        }
        payload: dict[str, Any] = {
            "promptText": prompt,
            "model": "gen3a_turbo",
            "duration": int(duration),
            "ratio": "16:9",
        }
        if image_url:
            payload["promptImage"] = image_url

        generation_id = ""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.dev.runwayml.com/v1/image_to_video",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            generation_id = data.get("id", uuid.uuid4().hex)

        # Poll for completion
        video_url = ""
        elapsed = 0.0
        while elapsed < self._max_poll_time:
            await asyncio.sleep(self._poll_interval)
            elapsed += self._poll_interval

            async with httpx.AsyncClient(timeout=30.0) as client:
                status_resp = await client.get(
                    f"https://api.dev.runwayml.com/v1/tasks/{generation_id}",
                    headers=headers,
                )
                if status_resp.status_code != 200:
                    continue
                status_data = status_resp.json()

            status = status_data.get("status", "")
            if status == "SUCCEEDED":
                output = status_data.get("output", [])
                if output:
                    video_url = output[0] if isinstance(output, list) else output
                break
            elif status == "FAILED":
                return VideoResult(
                    prompt=prompt,
                    model="runway-gen3",
                    generation_id=generation_id,
                    status=GenerationStatus.FAILED.value,
                    metadata={"error": status_data.get("failure", "Unknown error")},
                )

        if not video_url:
            return VideoResult(
                prompt=prompt,
                model="runway-gen3",
                generation_id=generation_id,
                status=GenerationStatus.FAILED.value,
            )

        local_path = str(await self._download(video_url))
        return VideoResult(
            url=video_url,
            local_path=local_path,
            prompt=prompt,
            model="runway-gen3",
            duration=duration,
            resolution=resolution,
            generation_id=generation_id,
            status=GenerationStatus.SUCCEEDED.value,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        duration: float = 4.0,
        resolution: str = "1080p",
    ) -> VideoResult:
        """Generate a video from a text prompt.

        Parameters
        ----------
        prompt:
            Text description of the desired video.
        model:
            Generation model (``veo``, ``sora``, ``runway-gen3``).
        duration:
            Video duration in seconds.
        resolution:
            Target resolution (``720p``, ``1080p``, ``4k``).

        Returns
        -------
        VideoResult
            Generated video with URL and/or local path.
        """
        use_model = model or self._default_model

        if use_model in ("veo", "veo-2"):
            return await self._generate_veo(prompt, duration=duration, resolution=resolution)
        elif use_model == "sora":
            return await self._generate_sora(prompt, duration=duration, resolution=resolution)
        elif use_model == "runway-gen3":
            return await self._generate_runway(prompt, duration=duration, resolution=resolution)
        else:
            log.warning("Unknown model '%s', falling back to veo.", use_model)
            return await self._generate_veo(prompt, duration=duration, resolution=resolution)

    async def image_to_video(
        self,
        image: str | Path,
        prompt: str = "",
        *,
        model: str | None = None,
        duration: float = 4.0,
    ) -> VideoResult:
        """Generate a video from a source image.

        Parameters
        ----------
        image:
            Path to the source image or a URL.
        prompt:
            Optional text prompt for guiding the animation.
        model:
            Generation model.
        duration:
            Video duration in seconds.

        Returns
        -------
        VideoResult
            Generated video.
        """
        use_model = model or self._default_model
        image_str = str(image)

        # For Runway, pass the image URL directly
        if use_model == "runway-gen3":
            return await self._generate_runway(
                prompt=prompt or "animate this image",
                duration=duration,
                image_url=image_str,
            )

        # For other models, include image reference in prompt
        augmented_prompt = f"{prompt} [source image: {image_str}]" if prompt else f"Animate this image: {image_str}"
        return await self.generate(prompt=augmented_prompt, model=use_model, duration=duration)

    async def get_status(
        self,
        generation_id: str,
        *,
        model: str | None = None,
    ) -> GenerationStatus:
        """Check the status of an ongoing generation.

        Parameters
        ----------
        generation_id:
            The ID returned from a generation call.
        model:
            Which provider to query.

        Returns
        -------
        GenerationStatus
            Current status of the generation.
        """
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")

        use_model = model or self._default_model
        status_str = "pending"

        try:
            if use_model in ("veo", "veo-2"):
                headers = {"Authorization": f"Bearer {self._google_key}"}
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        f"https://generativelanguage.googleapis.com/v1beta/{generation_id}",
                        headers=headers,
                    )
                    data = resp.json()
                    if data.get("done"):
                        status_str = "succeeded" if "response" in data else "failed"
                    else:
                        status_str = "processing"

            elif use_model == "sora":
                headers = {"Authorization": f"Bearer {self._openai_key}"}
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        f"https://api.openai.com/v1/videos/generations/{generation_id}",
                        headers=headers,
                    )
                    data = resp.json()
                    status_str = data.get("status", "pending")

            elif use_model == "runway-gen3":
                headers = {
                    "Authorization": f"Bearer {self._runway_key}",
                    "X-Runway-Version": "2024-11-06",
                }
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        f"https://api.dev.runwayml.com/v1/tasks/{generation_id}",
                        headers=headers,
                    )
                    data = resp.json()
                    raw_status = data.get("status", "PENDING").lower()
                    status_str = raw_status

        except Exception as exc:
            log.warning("Failed to check status for %s: %s", generation_id, exc)
            return GenerationStatus.PENDING

        # Normalize
        mapping = {
            "pending": GenerationStatus.PENDING,
            "processing": GenerationStatus.PROCESSING,
            "running": GenerationStatus.PROCESSING,
            "succeeded": GenerationStatus.SUCCEEDED,
            "completed": GenerationStatus.SUCCEEDED,
            "failed": GenerationStatus.FAILED,
            "cancelled": GenerationStatus.CANCELLED,
        }
        return mapping.get(status_str, GenerationStatus.PENDING)
