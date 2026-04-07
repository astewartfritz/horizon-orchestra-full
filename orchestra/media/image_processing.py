"""Horizon Orchestra — Image Processing.

Image manipulation toolkit using Pillow with fallback to ImageMagick CLI.
Supports resize, crop, compress, format conversion, watermarking,
collage creation, and OCR text extraction (via API).

Usage::

    from orchestra.media.image_processing import ImageProcessor

    proc = ImageProcessor()
    await proc.resize("photo.jpg", width=800, height=600)
    text = await proc.extract_text_ocr("document.png")
"""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import os
import shutil
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Sequence

__all__ = [
    "ImageProcessor",
    "CollageLayout",
]

log = logging.getLogger("orchestra.media.image_processing")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_media"))
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Optional dependency: Pillow
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    _HAS_PIL = True
except ImportError:
    Image = None  # type: ignore[assignment, misc]
    ImageDraw = None  # type: ignore[assignment, misc]
    ImageFont = None  # type: ignore[assignment, misc]
    ImageFilter = None  # type: ignore[assignment, misc]
    ImageEnhance = None  # type: ignore[assignment, misc]
    _HAS_PIL = False

# Optional dependency: httpx (for OCR API calls)
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    _HAS_HTTPX = False

# Optional dependency: openai (for OCR via GPT-4 Vision)
try:
    import openai as _openai_mod
    _HAS_OPENAI = True
except ImportError:
    _openai_mod = None  # type: ignore[assignment]
    _HAS_OPENAI = False


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CollageLayout(str, Enum):
    """Layout modes for collage generation."""

    GRID = "grid"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


# ---------------------------------------------------------------------------
# ImageProcessor
# ---------------------------------------------------------------------------

class ImageProcessor:
    """Image processing toolkit with Pillow and ImageMagick fallback.

    Parameters
    ----------
    workspace:
        Directory for saving output images.
    openai_api_key:
        OpenAI API key for OCR via GPT-4 Vision.
    use_imagemagick:
        Force use of ImageMagick CLI even if Pillow is available.
    """

    def __init__(
        self,
        workspace: str | Path | None = None,
        openai_api_key: str | None = None,
        use_imagemagick: bool = False,
    ) -> None:
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "image_proc"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._openai_key = openai_api_key or _OPENAI_API_KEY
        self._force_magick = use_imagemagick

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_path(self, ext: str = "png") -> Path:
        return self.workspace / f"{uuid.uuid4().hex[:12]}.{ext}"

    @property
    def _use_pil(self) -> bool:
        """Whether to use Pillow for image operations."""
        return _HAS_PIL and not self._force_magick

    async def _run_magick(self, *args: str) -> tuple[bytes, bytes]:
        """Run an ImageMagick command asynchronously."""
        magick = shutil.which("magick") or shutil.which("convert") or "convert"
        log.debug("Running: %s %s", magick, " ".join(args))
        proc = await asyncio.create_subprocess_exec(
            magick, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"ImageMagick exited with code {proc.returncode}: "
                f"{stderr.decode(errors='replace')[:1000]}"
            )
        return stdout, stderr

    def _get_ext(self, path: str | Path) -> str:
        """Extract file extension."""
        return Path(path).suffix.lstrip(".").lower() or "png"

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    async def resize(
        self,
        image: str | Path,
        width: int,
        height: int = 0,
        output_path: str | Path | None = None,
        *,
        maintain_aspect: bool = True,
    ) -> Path:
        """Resize an image.

        Parameters
        ----------
        image:
            Source image path.
        width:
            Target width in pixels.
        height:
            Target height in pixels.  If 0, auto-calculated from aspect ratio.
        output_path:
            Destination path.
        maintain_aspect:
            If *True*, maintain aspect ratio when both width and height are given.

        Returns
        -------
        Path
            Path to the resized image.
        """
        ext = self._get_ext(image)
        out = Path(output_path) if output_path else self._save_path(ext)

        if self._use_pil:
            img = Image.open(str(image))
            if height == 0:
                ratio = width / img.width
                height = int(img.height * ratio)
            if maintain_aspect:
                img.thumbnail((width, height), Image.LANCZOS)
            else:
                img = img.resize((width, height), Image.LANCZOS)
            img.save(str(out))
        else:
            size_str = f"{width}x{height}" if height else f"{width}x"
            flag = ">" if maintain_aspect else "!"
            await self._run_magick(
                str(image), "-resize", f"{size_str}{flag}", str(out),
            )

        log.info("Resized %s → %s", image, out)
        return out

    # ------------------------------------------------------------------
    # Crop
    # ------------------------------------------------------------------

    async def crop(
        self,
        image: str | Path,
        x: int,
        y: int,
        w: int,
        h: int,
        output_path: str | Path | None = None,
    ) -> Path:
        """Crop a rectangular region from an image.

        Parameters
        ----------
        image:
            Source image path.
        x, y:
            Top-left corner of the crop region.
        w, h:
            Width and height of the crop region.
        output_path:
            Destination path.

        Returns
        -------
        Path
            Path to the cropped image.
        """
        ext = self._get_ext(image)
        out = Path(output_path) if output_path else self._save_path(ext)

        if self._use_pil:
            img = Image.open(str(image))
            cropped = img.crop((x, y, x + w, y + h))
            cropped.save(str(out))
        else:
            await self._run_magick(
                str(image), "-crop", f"{w}x{h}+{x}+{y}", "+repage", str(out),
            )

        log.info("Cropped %s → %s", image, out)
        return out

    # ------------------------------------------------------------------
    # Compress
    # ------------------------------------------------------------------

    async def compress(
        self,
        image: str | Path,
        quality: int = 80,
        output_path: str | Path | None = None,
    ) -> Path:
        """Compress an image to reduce file size.

        Parameters
        ----------
        image:
            Source image path.
        quality:
            JPEG/WebP quality (1–100).
        output_path:
            Destination path.

        Returns
        -------
        Path
            Path to the compressed image.
        """
        ext = self._get_ext(image)
        if ext not in ("jpg", "jpeg", "webp", "png"):
            ext = "jpg"
        out = Path(output_path) if output_path else self._save_path(ext)

        if self._use_pil:
            img = Image.open(str(image))
            if img.mode == "RGBA" and ext in ("jpg", "jpeg"):
                img = img.convert("RGB")
            save_kwargs: dict[str, Any] = {"quality": quality}
            if ext == "png":
                save_kwargs = {"optimize": True}
            img.save(str(out), **save_kwargs)
        else:
            await self._run_magick(
                str(image), "-quality", str(quality), str(out),
            )

        log.info("Compressed %s (q=%d) → %s", image, quality, out)
        return out

    # ------------------------------------------------------------------
    # Format conversion
    # ------------------------------------------------------------------

    async def convert_format(
        self,
        image: str | Path,
        fmt: str = "png",
        output_path: str | Path | None = None,
    ) -> Path:
        """Convert an image to a different format.

        Parameters
        ----------
        image:
            Source image path.
        fmt:
            Target format (``png``, ``jpg``, ``webp``, ``gif``, ``bmp``, ``tiff``).
        output_path:
            Destination path.

        Returns
        -------
        Path
            Path to the converted image.
        """
        out = Path(output_path) if output_path else self._save_path(fmt)

        if self._use_pil:
            img = Image.open(str(image))
            if fmt in ("jpg", "jpeg") and img.mode == "RGBA":
                img = img.convert("RGB")
            img.save(str(out), format=fmt.upper().replace("JPG", "JPEG"))
        else:
            await self._run_magick(str(image), str(out))

        log.info("Converted %s → %s (%s)", image, out, fmt)
        return out

    # ------------------------------------------------------------------
    # Watermark
    # ------------------------------------------------------------------

    async def add_watermark(
        self,
        image: str | Path,
        text: str,
        output_path: str | Path | None = None,
        *,
        position: str = "bottom-right",
        opacity: float = 0.5,
        font_size: int = 0,
        color: str = "white",
    ) -> Path:
        """Add a text watermark to an image.

        Parameters
        ----------
        image:
            Source image path.
        text:
            Watermark text.
        output_path:
            Destination path.
        position:
            Watermark position (``center``, ``bottom-right``, ``bottom-left``,
            ``top-right``, ``top-left``).
        opacity:
            Text opacity (0.0–1.0).
        font_size:
            Font size in pixels.  Auto-calculated if 0.
        color:
            Text color name or hex.

        Returns
        -------
        Path
            Path to the watermarked image.
        """
        ext = self._get_ext(image)
        out = Path(output_path) if output_path else self._save_path(ext)

        if self._use_pil:
            img = Image.open(str(image)).convert("RGBA")
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            if font_size == 0:
                font_size = max(16, img.width // 20)

            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except (OSError, IOError):
                font = ImageFont.load_default()

            # Calculate text bounding box
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

            # Position mapping
            padding = 20
            positions = {
                "center": ((img.width - tw) // 2, (img.height - th) // 2),
                "bottom-right": (img.width - tw - padding, img.height - th - padding),
                "bottom-left": (padding, img.height - th - padding),
                "top-right": (img.width - tw - padding, padding),
                "top-left": (padding, padding),
            }
            pos = positions.get(position, positions["bottom-right"])

            # Parse color
            alpha = int(opacity * 255)
            fill = (255, 255, 255, alpha)
            if color.lower() == "black":
                fill = (0, 0, 0, alpha)
            elif color.startswith("#") and len(color) == 7:
                r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
                fill = (r, g, b, alpha)

            draw.text(pos, text, font=font, fill=fill)

            result = Image.alpha_composite(img, overlay)
            if ext in ("jpg", "jpeg"):
                result = result.convert("RGB")
            result.save(str(out))
        else:
            gravity_map = {
                "center": "Center",
                "bottom-right": "SouthEast",
                "bottom-left": "SouthWest",
                "top-right": "NorthEast",
                "top-left": "NorthWest",
            }
            gravity = gravity_map.get(position, "SouthEast")
            await self._run_magick(
                str(image),
                "-gravity", gravity,
                "-fill", f"rgba(255,255,255,{opacity})",
                "-pointsize", str(font_size or 36),
                "-annotate", "+20+20", text,
                str(out),
            )

        log.info("Added watermark '%s' → %s", text, out)
        return out

    # ------------------------------------------------------------------
    # Collage
    # ------------------------------------------------------------------

    async def create_collage(
        self,
        images: Sequence[str | Path],
        layout: str | CollageLayout = "grid",
        output_path: str | Path | None = None,
        *,
        cell_width: int = 400,
        cell_height: int = 400,
        padding: int = 10,
        background: str = "white",
    ) -> Path:
        """Create a collage from multiple images.

        Parameters
        ----------
        images:
            List of image paths.
        layout:
            Layout mode (``grid``, ``horizontal``, ``vertical``).
        output_path:
            Destination path.
        cell_width:
            Width of each cell in pixels.
        cell_height:
            Height of each cell in pixels.
        padding:
            Padding between cells.
        background:
            Background color.

        Returns
        -------
        Path
            Path to the collage image.
        """
        if not images:
            raise ValueError("No images provided for collage.")

        out = Path(output_path) if output_path else self._save_path("png")
        layout_str = layout.value if isinstance(layout, CollageLayout) else layout
        n = len(images)

        if not self._use_pil:
            # ImageMagick fallback: use montage
            montage = shutil.which("montage") or "montage"
            tile = ""
            if layout_str == "horizontal":
                tile = f"{n}x1"
            elif layout_str == "vertical":
                tile = f"1x{n}"
            else:
                cols = math.ceil(math.sqrt(n))
                rows = math.ceil(n / cols)
                tile = f"{cols}x{rows}"

            args = [str(p) for p in images]
            args.extend([
                "-tile", tile,
                "-geometry", f"{cell_width}x{cell_height}+{padding}+{padding}",
                "-background", background,
                str(out),
            ])
            proc = await asyncio.create_subprocess_exec(
                montage, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"montage failed: {stderr.decode()[:500]}")
            log.info("Created collage (montage) → %s", out)
            return out

        # Pillow collage
        if layout_str == "horizontal":
            cols, rows = n, 1
        elif layout_str == "vertical":
            cols, rows = 1, n
        else:
            cols = math.ceil(math.sqrt(n))
            rows = math.ceil(n / cols)

        canvas_w = cols * cell_width + (cols + 1) * padding
        canvas_h = rows * cell_height + (rows + 1) * padding
        canvas = Image.new("RGB", (canvas_w, canvas_h), background)

        for idx, img_path in enumerate(images):
            row = idx // cols
            col = idx % cols
            x = col * cell_width + (col + 1) * padding
            y = row * cell_height + (row + 1) * padding

            img = Image.open(str(img_path))
            img.thumbnail((cell_width, cell_height), Image.LANCZOS)

            # Center within cell
            offset_x = x + (cell_width - img.width) // 2
            offset_y = y + (cell_height - img.height) // 2
            canvas.paste(img, (offset_x, offset_y))

        canvas.save(str(out))
        log.info("Created collage (%s, %dx%d) → %s", layout_str, cols, rows, out)
        return out

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------

    async def extract_text_ocr(
        self,
        image: str | Path,
        *,
        prompt: str = "Extract all text from this image. Return only the extracted text.",
        model: str = "gpt-4o",
    ) -> str:
        """Extract text from an image using OCR via GPT-4 Vision.

        Parameters
        ----------
        image:
            Image path.
        prompt:
            Instruction for the vision model.
        model:
            Vision model to use.

        Returns
        -------
        str
            Extracted text.
        """
        if not _HAS_OPENAI:
            raise ImportError("openai package is required for OCR: pip install openai")
        if not self._openai_key:
            raise ValueError("OPENAI_API_KEY is required for OCR.")

        image_bytes = Path(image).read_bytes()
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        ext = self._get_ext(image)
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")

        client = _openai_mod.AsyncOpenAI(api_key=self._openai_key)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}",
                            },
                        },
                    ],
                }],
                max_tokens=4096,
            )
            return response.choices[0].message.content or ""
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # Additional operations
    # ------------------------------------------------------------------

    async def rotate(
        self,
        image: str | Path,
        angle: float,
        output_path: str | Path | None = None,
        *,
        expand: bool = True,
    ) -> Path:
        """Rotate an image by a given angle.

        Parameters
        ----------
        image:
            Source image path.
        angle:
            Rotation angle in degrees (counter-clockwise).
        output_path:
            Destination path.
        expand:
            If *True*, expand canvas to fit rotated image.

        Returns
        -------
        Path
            Path to the rotated image.
        """
        ext = self._get_ext(image)
        out = Path(output_path) if output_path else self._save_path(ext)

        if self._use_pil:
            img = Image.open(str(image))
            rotated = img.rotate(angle, expand=expand, resample=Image.BICUBIC)
            rotated.save(str(out))
        else:
            await self._run_magick(
                str(image), "-rotate", str(angle), str(out),
            )

        log.info("Rotated %s by %.1f° → %s", image, angle, out)
        return out

    async def flip(
        self,
        image: str | Path,
        direction: str = "horizontal",
        output_path: str | Path | None = None,
    ) -> Path:
        """Flip an image horizontally or vertically.

        Parameters
        ----------
        image:
            Source image path.
        direction:
            ``"horizontal"`` or ``"vertical"``.
        output_path:
            Destination path.

        Returns
        -------
        Path
            Path to the flipped image.
        """
        ext = self._get_ext(image)
        out = Path(output_path) if output_path else self._save_path(ext)

        if self._use_pil:
            img = Image.open(str(image))
            if direction == "horizontal":
                flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
            else:
                flipped = img.transpose(Image.FLIP_TOP_BOTTOM)
            flipped.save(str(out))
        else:
            flag = "-flop" if direction == "horizontal" else "-flip"
            await self._run_magick(str(image), flag, str(out))

        log.info("Flipped %s (%s) → %s", image, direction, out)
        return out

    async def blur(
        self,
        image: str | Path,
        radius: int = 5,
        output_path: str | Path | None = None,
    ) -> Path:
        """Apply Gaussian blur to an image.

        Parameters
        ----------
        image:
            Source image path.
        radius:
            Blur radius.
        output_path:
            Destination path.

        Returns
        -------
        Path
            Path to the blurred image.
        """
        ext = self._get_ext(image)
        out = Path(output_path) if output_path else self._save_path(ext)

        if self._use_pil:
            img = Image.open(str(image))
            blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
            blurred.save(str(out))
        else:
            await self._run_magick(
                str(image), "-blur", f"0x{radius}", str(out),
            )

        log.info("Blurred %s (r=%d) → %s", image, radius, out)
        return out

    async def adjust_brightness(
        self,
        image: str | Path,
        factor: float = 1.2,
        output_path: str | Path | None = None,
    ) -> Path:
        """Adjust image brightness.

        Parameters
        ----------
        image:
            Source image path.
        factor:
            Brightness multiplier (< 1.0 darker, > 1.0 brighter).
        output_path:
            Destination path.

        Returns
        -------
        Path
            Path to the adjusted image.
        """
        ext = self._get_ext(image)
        out = Path(output_path) if output_path else self._save_path(ext)

        if self._use_pil:
            img = Image.open(str(image))
            enhancer = ImageEnhance.Brightness(img)
            enhanced = enhancer.enhance(factor)
            enhanced.save(str(out))
        else:
            brightness = int(factor * 100)
            await self._run_magick(
                str(image), "-modulate", f"{brightness},100,100", str(out),
            )

        log.info("Adjusted brightness ×%.2f → %s", factor, out)
        return out
