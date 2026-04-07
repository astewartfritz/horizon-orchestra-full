"""Horizon Orchestra — Image Generation.

Unified interface for image generation via OpenAI DALL-E 3, Replicate
Flux, and Stable Diffusion (via API).  Supports generation, editing,
variations, and upscaling.

Usage::

    from orchestra.media.image_gen import ImageGenerator

    gen = ImageGenerator()
    result = await gen.generate("a sunset over mountains", model="dall-e-3")
    print(result.url, result.local_path)
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "ImageGenerator",
    "ImageResult",
    "ImageModel",
]

log = logging.getLogger("orchestra.media.image_gen")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_media"))
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
_REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")
_STABILITY_API_KEY = os.environ.get("STABILITY_API_KEY", "")

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

class ImageModel(str, Enum):
    """Supported image generation models."""

    DALLE3 = "dall-e-3"
    DALLE2 = "dall-e-2"
    FLUX_PRO = "flux-pro"
    FLUX_SCHNELL = "flux-schnell"
    STABLE_DIFFUSION_XL = "sdxl"
    STABLE_DIFFUSION_3 = "sd3"


@dataclass
class ImageResult:
    """Result from an image generation operation."""

    url: str = ""
    local_path: str = ""
    base64_data: str = ""
    prompt: str = ""
    revised_prompt: str = ""
    model: str = ""
    size: str = ""
    seed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_file(self) -> bool:
        return bool(self.local_path) and Path(self.local_path).exists()


# ---------------------------------------------------------------------------
# ImageGenerator
# ---------------------------------------------------------------------------

class ImageGenerator:
    """Unified image generation across multiple models.

    Parameters
    ----------
    workspace:
        Directory for saving generated images.
    openai_api_key:
        OpenAI API key for DALL-E.
    replicate_api_token:
        Replicate API token for Flux models.
    stability_api_key:
        Stability AI API key for Stable Diffusion.
    default_model:
        Default model to use when none is specified.
    """

    SUPPORTED_MODELS = {m.value for m in ImageModel}

    def __init__(
        self,
        workspace: str | Path | None = None,
        openai_api_key: str | None = None,
        replicate_api_token: str | None = None,
        stability_api_key: str | None = None,
        default_model: str = "dall-e-3",
    ) -> None:
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "images"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._openai_key = openai_api_key or _OPENAI_API_KEY
        self._replicate_token = replicate_api_token or _REPLICATE_API_TOKEN
        self._stability_key = stability_api_key or _STABILITY_API_KEY
        self._default_model = default_model

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_path(self, ext: str = "png") -> Path:
        """Generate a unique save path."""
        return self.workspace / f"{uuid.uuid4().hex[:12]}.{ext}"

    async def _save_from_url(self, url: str, path: Path | None = None) -> Path:
        """Download an image from URL and save to disk."""
        if not _HAS_HTTPX:
            raise ImportError("httpx is required for image downloads: pip install httpx")
        save_to = path or self._save_path("png")
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            save_to.write_bytes(resp.content)
        log.debug("Saved image to %s (%d bytes)", save_to, save_to.stat().st_size)
        return save_to

    def _save_from_base64(self, b64: str, path: Path | None = None) -> Path:
        """Decode base64 image data and save to disk."""
        save_to = path or self._save_path("png")
        data = base64.b64decode(b64)
        save_to.write_bytes(data)
        log.debug("Saved base64 image to %s (%d bytes)", save_to, len(data))
        return save_to

    def _get_openai_client(self) -> Any:
        """Instantiate an async OpenAI client."""
        if not _HAS_OPENAI:
            raise ImportError("openai package is required for DALL-E: pip install openai")
        if not self._openai_key:
            raise ValueError("OPENAI_API_KEY is required for DALL-E image generation.")
        return _openai_mod.AsyncOpenAI(api_key=self._openai_key)

    # ------------------------------------------------------------------
    # DALL-E
    # ------------------------------------------------------------------

    async def _generate_dalle(
        self,
        prompt: str,
        model: str = "dall-e-3",
        size: str = "1024x1024",
        quality: str = "standard",
        style: str = "vivid",
        n: int = 1,
    ) -> ImageResult:
        """Generate image via OpenAI DALL-E."""
        client = self._get_openai_client()
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "size": size,
                "n": n,
                "response_format": "url",
            }
            if model == "dall-e-3":
                kwargs["quality"] = quality
                kwargs["style"] = style

            response = await client.images.generate(**kwargs)
            image_data = response.data[0]

            url = getattr(image_data, "url", "") or ""
            revised = getattr(image_data, "revised_prompt", "") or ""
            b64 = getattr(image_data, "b64_json", "") or ""

            local_path = ""
            if url:
                saved = await self._save_from_url(url)
                local_path = str(saved)
            elif b64:
                saved = self._save_from_base64(b64)
                local_path = str(saved)

            return ImageResult(
                url=url,
                local_path=local_path,
                base64_data=b64,
                prompt=prompt,
                revised_prompt=revised,
                model=model,
                size=size,
            )
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # Replicate (Flux)
    # ------------------------------------------------------------------

    async def _generate_flux(
        self,
        prompt: str,
        model: str = "flux-pro",
        size: str = "1024x1024",
        steps: int = 25,
        guidance: float = 3.5,
    ) -> ImageResult:
        """Generate image via Replicate Flux models."""
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")
        if not self._replicate_token:
            raise ValueError("REPLICATE_API_TOKEN is required for Flux models.")

        model_versions = {
            "flux-pro": "black-forest-labs/flux-pro",
            "flux-schnell": "black-forest-labs/flux-schnell",
        }
        model_id = model_versions.get(model, model)

        w, h = 1024, 1024
        if "x" in size:
            parts = size.split("x")
            w, h = int(parts[0]), int(parts[1])

        payload = {
            "input": {
                "prompt": prompt,
                "width": w,
                "height": h,
                "num_inference_steps": steps,
                "guidance_scale": guidance,
            },
        }

        headers = {
            "Authorization": f"Token {self._replicate_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=300.0) as client:
            # Create prediction
            resp = await client.post(
                f"https://api.replicate.com/v1/models/{model_id}/predictions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            prediction = resp.json()
            prediction_url = prediction.get("urls", {}).get("get", "")

            # Poll for completion
            output_url = ""
            for _ in range(120):  # up to 10 minutes
                await asyncio.sleep(5)
                status_resp = await client.get(prediction_url, headers=headers)
                status_resp.raise_for_status()
                status_data = status_resp.json()
                status = status_data.get("status", "")

                if status == "succeeded":
                    output = status_data.get("output")
                    if isinstance(output, list) and output:
                        output_url = output[0]
                    elif isinstance(output, str):
                        output_url = output
                    break
                elif status == "failed":
                    error = status_data.get("error", "Unknown error")
                    raise RuntimeError(f"Flux generation failed: {error}")

            if not output_url:
                raise RuntimeError("Flux generation timed out.")

        local_path = str(await self._save_from_url(output_url))
        return ImageResult(
            url=output_url,
            local_path=local_path,
            prompt=prompt,
            model=model,
            size=size,
        )

    # ------------------------------------------------------------------
    # Stability AI (Stable Diffusion)
    # ------------------------------------------------------------------

    async def _generate_stability(
        self,
        prompt: str,
        model: str = "sdxl",
        size: str = "1024x1024",
        steps: int = 30,
        cfg_scale: float = 7.0,
        seed: int = 0,
    ) -> ImageResult:
        """Generate image via Stability AI API."""
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")
        if not self._stability_key:
            raise ValueError("STABILITY_API_KEY is required for Stable Diffusion.")

        engine_map = {
            "sdxl": "stable-diffusion-xl-1024-v1-0",
            "sd3": "sd3-large",
        }
        engine_id = engine_map.get(model, model)

        w, h = 1024, 1024
        if "x" in size:
            parts = size.split("x")
            w, h = int(parts[0]), int(parts[1])

        headers = {
            "Authorization": f"Bearer {self._stability_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "text_prompts": [{"text": prompt, "weight": 1.0}],
            "cfg_scale": cfg_scale,
            "width": w,
            "height": h,
            "steps": steps,
            "samples": 1,
        }
        if seed:
            payload["seed"] = seed

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"https://api.stability.ai/v1/generation/{engine_id}/text-to-image",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        artifacts = data.get("artifacts", [])
        if not artifacts:
            raise RuntimeError("Stability AI returned no artifacts.")

        b64_data = artifacts[0].get("base64", "")
        actual_seed = artifacts[0].get("seed", 0)
        saved = self._save_from_base64(b64_data)

        return ImageResult(
            local_path=str(saved),
            base64_data=b64_data,
            prompt=prompt,
            model=model,
            size=size,
            seed=actual_seed,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        size: str = "1024x1024",
        quality: str = "standard",
        style: str = "vivid",
        steps: int = 25,
        guidance: float = 3.5,
        seed: int = 0,
    ) -> ImageResult:
        """Generate an image from a text prompt.

        Parameters
        ----------
        prompt:
            Text description of the desired image.
        model:
            Generation model (``dall-e-3``, ``flux-pro``, ``sdxl``, …).
        size:
            Image dimensions (``"1024x1024"``, ``"1792x1024"``, …).
        quality:
            DALL-E quality (``standard`` or ``hd``).
        style:
            DALL-E style (``vivid`` or ``natural``).
        steps:
            Inference steps (Flux / SD).
        guidance:
            Guidance scale (Flux / SD).
        seed:
            Random seed (SD).

        Returns
        -------
        ImageResult
            Generated image with URL and/or local path.
        """
        use_model = model or self._default_model

        if use_model in ("dall-e-3", "dall-e-2"):
            return await self._generate_dalle(prompt, model=use_model, size=size, quality=quality, style=style)
        elif use_model in ("flux-pro", "flux-schnell"):
            return await self._generate_flux(prompt, model=use_model, size=size, steps=steps, guidance=guidance)
        elif use_model in ("sdxl", "sd3"):
            return await self._generate_stability(prompt, model=use_model, size=size, steps=steps, seed=seed)
        else:
            log.warning("Unknown model '%s', falling back to dall-e-3.", use_model)
            return await self._generate_dalle(prompt, model="dall-e-3", size=size, quality=quality)

    async def edit(
        self,
        image: str | Path | bytes,
        prompt: str,
        mask: str | Path | bytes | None = None,
        *,
        model: str = "dall-e-2",
        size: str = "1024x1024",
    ) -> ImageResult:
        """Edit an existing image using a text prompt (inpainting).

        Parameters
        ----------
        image:
            Source image (path or raw bytes).
        prompt:
            Description of the desired edit.
        mask:
            Optional mask image indicating areas to edit (transparent = edit).
        model:
            Model for editing (currently only ``dall-e-2`` supports edits).
        size:
            Output dimensions.

        Returns
        -------
        ImageResult
            Edited image.
        """
        client = self._get_openai_client()
        try:
            img_file: Any
            if isinstance(image, (str, Path)):
                img_file = open(str(image), "rb")
            else:
                img_file = io.BytesIO(image)
                img_file.name = "image.png"

            mask_file: Any = None
            if mask is not None:
                if isinstance(mask, (str, Path)):
                    mask_file = open(str(mask), "rb")
                else:
                    mask_file = io.BytesIO(mask)
                    mask_file.name = "mask.png"

            kwargs: dict[str, Any] = {
                "model": model,
                "image": img_file,
                "prompt": prompt,
                "size": size,
                "n": 1,
                "response_format": "url",
            }
            if mask_file:
                kwargs["mask"] = mask_file

            response = await client.images.edit(**kwargs)
            image_data = response.data[0]
            url = getattr(image_data, "url", "") or ""

            local_path = ""
            if url:
                saved = await self._save_from_url(url)
                local_path = str(saved)

            return ImageResult(
                url=url,
                local_path=local_path,
                prompt=prompt,
                model=model,
                size=size,
            )
        finally:
            await client.close()

    async def variations(
        self,
        image: str | Path | bytes,
        count: int = 4,
        *,
        model: str = "dall-e-2",
        size: str = "1024x1024",
    ) -> list[ImageResult]:
        """Generate variations of an existing image.

        Parameters
        ----------
        image:
            Source image (path or raw bytes).
        count:
            Number of variations to generate.
        model:
            Model (currently only ``dall-e-2``).
        size:
            Output dimensions.

        Returns
        -------
        list[ImageResult]
            Variation images.
        """
        client = self._get_openai_client()
        try:
            img_file: Any
            if isinstance(image, (str, Path)):
                img_file = open(str(image), "rb")
            else:
                img_file = io.BytesIO(image)
                img_file.name = "image.png"

            response = await client.images.create_variation(
                model=model,
                image=img_file,
                n=count,
                size=size,
                response_format="url",
            )

            results: list[ImageResult] = []
            for item in response.data:
                url = getattr(item, "url", "") or ""
                local_path = ""
                if url:
                    saved = await self._save_from_url(url)
                    local_path = str(saved)
                results.append(ImageResult(
                    url=url,
                    local_path=local_path,
                    model=model,
                    size=size,
                ))
            return results
        finally:
            await client.close()

    async def upscale(
        self,
        image: str | Path | bytes,
        scale: int = 2,
    ) -> ImageResult:
        """Upscale an image using Stability AI.

        Parameters
        ----------
        image:
            Source image (path or raw bytes).
        scale:
            Upscale factor (2 or 4).

        Returns
        -------
        ImageResult
            Upscaled image.
        """
        if not _HAS_HTTPX:
            raise ImportError("httpx is required: pip install httpx")
        if not self._stability_key:
            raise ValueError("STABILITY_API_KEY is required for upscaling.")

        if isinstance(image, (str, Path)):
            image_bytes = Path(image).read_bytes()
        else:
            image_bytes = image

        headers = {
            "Authorization": f"Bearer {self._stability_key}",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.stability.ai/v1/generation/esrgan-v1-x2plus/image-to-image/upscale",
                headers=headers,
                files={"image": ("image.png", image_bytes, "image/png")},
                data={"width": scale * 1024},
            )
            resp.raise_for_status()
            data = resp.json()

        artifacts = data.get("artifacts", [])
        if not artifacts:
            raise RuntimeError("Upscale returned no artifacts.")

        b64_data = artifacts[0].get("base64", "")
        saved = self._save_from_base64(b64_data)

        return ImageResult(
            local_path=str(saved),
            base64_data=b64_data,
            model="esrgan",
            metadata={"scale": scale},
        )
