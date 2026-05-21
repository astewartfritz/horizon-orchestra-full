from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SentryConfig",
    "init_sentry",
    "SentryMiddleware",
    "register_sentry",
    "safe_capture",
]

log = logging.getLogger("orchestra.sentry")

_HAS_SENTRY = False
try:
    import sentry_sdk  # type: ignore
    _HAS_SENTRY = True
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]


@dataclass
class SentryConfig:
    dsn: str = ""
    environment: str = field(default_factory=lambda: os.environ.get("ORCHESTRA_ENV", "development"))
    traces_sample_rate: float = 0.25
    profiles_sample_rate: float = 0.1


def init_sentry(config: SentryConfig | None = None) -> bool:
    """Initialise Sentry SDK. Returns True on success."""
    if not _HAS_SENTRY:
        log.warning("sentry_sdk not installed — error tracking disabled")
        return False

    cfg = config or SentryConfig()
    if not cfg.dsn:
        cfg.dsn = os.environ.get("SENTRY_DSN", "")

    if not cfg.dsn:
        log.info("SENTRY_DSN not set — error tracking disabled")
        return False

    try:
        sentry_sdk.init(
            dsn=cfg.dsn,
            environment=cfg.environment,
            traces_sample_rate=cfg.traces_sample_rate,
            profiles_sample_rate=cfg.profiles_sample_rate,
            send_default_pii=False,
        )
        log.info("Sentry initialised for environment=%s", cfg.environment)
        return True
    except Exception as exc:
        log.warning("Sentry initialisation failed: %s", exc)
        return False


class SentryMiddleware:
    """ASGI middleware that captures unhandled exceptions to Sentry."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            if _HAS_SENTRY:
                from sentry_sdk import capture_exception, set_tag
                path = scope.get("path", "unknown")
                set_tag("endpoint", path)
                capture_exception(exc)
            log.exception("Unhandled exception at %s", scope.get("path", "unknown"))
            raise


def register_sentry(app: Any, config: SentryConfig | None = None) -> None:
    """Register Sentry on a FastAPI app (init + middleware)."""
    init_sentry(config)
    try:
        app.add_middleware(SentryMiddleware)  # type: ignore[union-attr]
    except Exception as exc:
        log.warning("Failed to add Sentry middleware: %s", exc)


def safe_capture(exception: Exception) -> None:
    """Capture an exception to Sentry without raising."""
    if _HAS_SENTRY:
        try:
            sentry_sdk.capture_exception(exception)
        except Exception as exc:
            log.warning("Failed to capture exception to Sentry: %s", exc)
