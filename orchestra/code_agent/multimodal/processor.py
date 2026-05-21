from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any


class ImageProcessor:
    """Process images for multi-modal LLM input."""

    SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

    @staticmethod
    def encode_image(path: str) -> str:
        p = Path(path)
        if not p.exists():
            return ""
        with open(p, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def get_mime_type(path: str) -> str:
        ext = Path(path).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        return mime_map.get(ext, "image/png")

    @staticmethod
    def make_content_block(path: str, detail: str = "auto") -> dict[str, Any]:
        b64 = ImageProcessor.encode_image(path)
        if not b64:
            return {"type": "text", "text": f"(Image not found: {path})"}

        mime = ImageProcessor.get_mime_type(path)
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{b64}",
                "detail": detail,
            },
        }

    @staticmethod
    def describe_image_locally(path: str) -> str:
        """Return basic image metadata without LLM."""
        p = Path(path)
        if not p.exists():
            return f"File not found: {path}"

        size_kb = p.stat().st_size / 1024
        ext = p.suffix.upper()
        return f"[Image: {p.name}, {ext}, {size_kb:.1f}KB]"

    @staticmethod
    def split_data_url(data_url: str) -> tuple[str, bytes]:
        """Parse a data URL into (mime_type, bytes)."""
        try:
            _, encoded = data_url.split(",", 1)
            mime = data_url.split(";")[0].split(":")[1]
            return mime, base64.b64decode(encoded)
        except (ValueError, IndexError):
            return "", b""

    @staticmethod
    def save_data_url(data_url: str, output_path: str) -> bool:
        """Save a data URL to a file."""
        try:
            mime, data = ImageProcessor.split_data_url(data_url)
            ext_map = {"image/png": ".png", "image/jpeg": ".jpg",
                       "image/gif": ".gif", "image/webp": ".webp"}
            ext = ext_map.get(mime, ".bin")
            p = Path(output_path)
            if p.suffix.lower() not in ImageProcessor.SUPPORTED_FORMATS:
                p = p.with_suffix(ext)
            p.write_bytes(data)
            return True
        except Exception:
            return False
