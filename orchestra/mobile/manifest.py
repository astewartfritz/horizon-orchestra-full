"""
orchestra/mobile/manifest.py
----------------------------
PWA manifest generator and FastAPI routes for Horizon Orchestra.

Generates a standards-compliant Web App Manifest (manifest.json) that
enables installable PWA behaviour on iOS and Android.  Also provides a
helper to produce icon metadata for multiple sizes from a base image.
"""
from __future__ import annotations

__all__ = [
    "ManifestGenerator",
    "ManifestConfig",
    "generate_manifest",
    "register_routes",
]

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("orchestra.mobile.manifest")

# ---------------------------------------------------------------------------
# Brand constants
# ---------------------------------------------------------------------------

BRAND_TEAL = "#01696F"
BRAND_DARK = "#0a0a0a"
APP_NAME = "Horizon Orchestra"
APP_SHORT_NAME = "Orchestra"
APP_DESCRIPTION = "Your AI orchestration layer powered by MILES"

# Standard PWA icon sizes (px)
ICON_SIZES: list[int] = [48, 72, 96, 128, 144, 192, 384, 512]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ManifestConfig:
    """Configuration for PWA manifest generation."""

    name: str = APP_NAME
    short_name: str = APP_SHORT_NAME
    description: str = APP_DESCRIPTION
    theme_color: str = BRAND_TEAL
    background_color: str = BRAND_DARK
    display: str = "standalone"
    orientation: str = "any"
    start_url: str = "/?source=pwa"
    scope: str = "/"
    lang: str = "en"
    dir: str = "ltr"
    icon_base_url: str = "/static/icons"
    icon_sizes: list[int] = field(default_factory=lambda: list(ICON_SIZES))
    categories: list[str] = field(default_factory=lambda: ["productivity", "utilities"])
    include_screenshots: bool = True
    include_shortcuts: bool = True
    include_share_target: bool = True


# ---------------------------------------------------------------------------
# ManifestGenerator
# ---------------------------------------------------------------------------


class ManifestGenerator:
    """Generates the full PWA manifest dict for Horizon Orchestra.

    Usage::

        gen = ManifestGenerator()
        manifest_dict = gen.build()
        manifest_json = gen.to_json()
    """

    def __init__(self, config: ManifestConfig | None = None) -> None:
        self.config = config or ManifestConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        """Return the manifest as a Python dict."""
        cfg = self.config
        manifest: dict[str, Any] = {
            "name": cfg.name,
            "short_name": cfg.short_name,
            "description": cfg.description,
            "theme_color": cfg.theme_color,
            "background_color": cfg.background_color,
            "display": cfg.display,
            "orientation": cfg.orientation,
            "start_url": cfg.start_url,
            "scope": cfg.scope,
            "lang": cfg.lang,
            "dir": cfg.dir,
            "categories": cfg.categories,
            "icons": self._build_icons(),
        }

        if cfg.include_shortcuts:
            manifest["shortcuts"] = self._build_shortcuts()

        if cfg.include_screenshots:
            manifest["screenshots"] = self._build_screenshots()

        if cfg.include_share_target:
            manifest["share_target"] = self._build_share_target()

        manifest["related_applications"] = self._build_related_applications()
        manifest["prefer_related_applications"] = False

        logger.debug("manifest built: name=%s icons=%d", cfg.name, len(manifest["icons"]))
        return manifest

    def to_json(self, indent: int = 2) -> str:
        """Return the manifest serialised as JSON."""
        return json.dumps(self.build(), indent=indent)

    # ------------------------------------------------------------------
    # Icon helpers
    # ------------------------------------------------------------------

    def _build_icons(self) -> list[dict[str, str]]:
        """Build the icons array for all configured sizes."""
        cfg = self.config
        icons: list[dict[str, str]] = []

        for size in cfg.icon_sizes:
            size_str = f"{size}x{size}"
            icons.append(
                {
                    "src": f"{cfg.icon_base_url}/icon-{size}.png",
                    "sizes": size_str,
                    "type": "image/png",
                    "purpose": "any",
                }
            )
            # Maskable variant for adaptive icons (Android)
            if size in (192, 512):
                icons.append(
                    {
                        "src": f"{cfg.icon_base_url}/icon-{size}-maskable.png",
                        "sizes": size_str,
                        "type": "image/png",
                        "purpose": "maskable",
                    }
                )

        # SVG scalable icon
        icons.append(
            {
                "src": f"{cfg.icon_base_url}/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any",
            }
        )
        return icons

    # ------------------------------------------------------------------
    # Shortcuts
    # ------------------------------------------------------------------

    def _build_shortcuts(self) -> list[dict[str, Any]]:
        """Build the shortcuts array for quick-launch actions."""
        base = self.config.icon_base_url
        return [
            {
                "name": "New Chat",
                "short_name": "New Chat",
                "description": "Start a new conversation with MILES",
                "url": "/chat/new?source=shortcut",
                "icons": [{"src": f"{base}/shortcut-chat.png", "sizes": "96x96"}],
            },
            {
                "name": "Resume Task",
                "short_name": "Tasks",
                "description": "Resume your most recent long-horizon task",
                "url": "/tasks?source=shortcut",
                "icons": [{"src": f"{base}/shortcut-tasks.png", "sizes": "96x96"}],
            },
            {
                "name": "Ask MILES",
                "short_name": "MILES",
                "description": "Quick question to your AI assistant",
                "url": "/miles?source=shortcut",
                "icons": [{"src": f"{base}/shortcut-miles.png", "sizes": "96x96"}],
            },
        ]

    # ------------------------------------------------------------------
    # Screenshots
    # ------------------------------------------------------------------

    def _build_screenshots(self) -> list[dict[str, Any]]:
        """Build screenshot entries for app-store-style install sheets."""
        base = "/static/screenshots"
        return [
            {
                "src": f"{base}/mobile-chat.png",
                "sizes": "390x844",
                "type": "image/png",
                "form_factor": "narrow",
                "label": "Chat with MILES on mobile",
            },
            {
                "src": f"{base}/mobile-tasks.png",
                "sizes": "390x844",
                "type": "image/png",
                "form_factor": "narrow",
                "label": "Long-horizon task tracker",
            },
            {
                "src": f"{base}/desktop-dashboard.png",
                "sizes": "1280x800",
                "type": "image/png",
                "form_factor": "wide",
                "label": "Horizon Orchestra desktop dashboard",
            },
        ]

    # ------------------------------------------------------------------
    # Share target
    # ------------------------------------------------------------------

    def _build_share_target(self) -> dict[str, Any]:
        """Build the share_target entry for receiving shared content."""
        return {
            "action": "/share-target",
            "method": "POST",
            "enctype": "multipart/form-data",
            "params": {
                "title": "title",
                "text": "text",
                "url": "url",
                "files": [
                    {"name": "files", "accept": ["image/*", "application/pdf", "text/*"]}
                ],
            },
        }

    # ------------------------------------------------------------------
    # Related applications (placeholder for future native apps)
    # ------------------------------------------------------------------

    def _build_related_applications(self) -> list[dict[str, str]]:
        """Return placeholder related-application entries for future native apps."""
        return [
            {
                "platform": "play",
                "url": "https://play.google.com/store/apps/details?id=ai.horizon.orchestra",
                "id": "ai.horizon.orchestra",
            },
            {
                "platform": "itunes",
                "url": "https://apps.apple.com/app/horizon-orchestra/id0000000000",
            },
        ]


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def generate_manifest(config: ManifestConfig | None = None) -> dict[str, Any]:
    """Generate and return the PWA manifest dict with optional config override."""
    return ManifestGenerator(config).build()


# ---------------------------------------------------------------------------
# Icon size metadata helper
# ---------------------------------------------------------------------------


def generate_icon_metadata(
    base_url: str = "/static/icons",
    sizes: list[int] | None = None,
) -> list[dict[str, str]]:
    """Return icon link metadata dicts for embedding in HTML <head>.

    Each entry has ``rel``, ``sizes``, and ``href`` keys matching the
    HTML ``<link>`` attributes required for Apple touch icons and
    standard favicon declarations.
    """
    sizes = sizes or ICON_SIZES
    entries: list[dict[str, str]] = []

    for size in sizes:
        size_str = f"{size}x{size}"
        entries.append(
            {
                "rel": "apple-touch-icon" if size >= 180 else "icon",
                "sizes": size_str,
                "href": f"{base_url}/icon-{size}.png",
                "type": "image/png",
            }
        )
    return entries


# ---------------------------------------------------------------------------
# FastAPI route registration
# ---------------------------------------------------------------------------


def register_routes(app: Any) -> None:
    """Register PWA manifest routes on a FastAPI application instance.

    Registers:
        GET /manifest.json  — serves the PWA manifest with correct MIME type
        GET /browserconfig.xml — Windows tile metadata
    """
    try:
        from fastapi import Request
        from fastapi.responses import JSONResponse, Response
    except ImportError:  # pragma: no cover — optional web dependency
        logger.warning("FastAPI not installed; manifest routes not registered")
        return

    @app.get("/manifest.json", include_in_schema=False)
    async def serve_manifest(request: Request) -> JSONResponse:
        """Serve the PWA Web App Manifest."""
        config = ManifestConfig()
        # Allow host-relative icon URLs based on incoming request
        base_url = str(request.base_url).rstrip("/")
        config.icon_base_url = f"{base_url}/static/icons"
        manifest_data = ManifestGenerator(config).build()
        return JSONResponse(
            content=manifest_data,
            headers={
                "Content-Type": "application/manifest+json",
                "Cache-Control": "public, max-age=3600",
            },
        )

    @app.get("/browserconfig.xml", include_in_schema=False)
    async def serve_browserconfig() -> Response:
        """Serve Windows tile configuration XML."""
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<browserconfig>
  <msapplication>
    <tile>
      <square150x150logo src="/static/icons/icon-144.png"/>
      <TileColor>{BRAND_TEAL}</TileColor>
    </tile>
  </msapplication>
</browserconfig>"""
        return Response(content=xml, media_type="application/xml")

    logger.info("manifest routes registered: /manifest.json, /browserconfig.xml")
