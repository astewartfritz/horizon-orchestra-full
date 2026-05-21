"""Central settings for Orchestra — validated at import time.

Reads from environment variables (and .env if python-dotenv is installed).
Any required field that is missing raises a clear error at startup rather
than surfacing as a cryptic runtime failure.

Usage::

    from orchestra.code_agent.settings import settings
    print(settings.jwt_secret)
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any

log = logging.getLogger("orchestra.settings")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(
            f"Required environment variable '{key}' is not set. "
            f"Copy .env.example to .env and fill in the value."
        )
    return val


def _env_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(key, "")
    if not raw:
        return default or []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Settings container
# ---------------------------------------------------------------------------

class OrchestraSettings:
    """Validated settings loaded from environment variables."""

    def __init__(self) -> None:
        self._load()

    def _load(self) -> None:
        # ── Deployment environment ──────────────────────────────────────
        self.env: str = os.environ.get("ORCHESTRA_ENV", "development")
        self.is_production: bool = self.env == "production"

        # ── Server ──────────────────────────────────────────────────────
        self.host: str = os.environ.get("ORCHESTRA_HOST", "127.0.0.1")
        self.port: int = _env_int("ORCHESTRA_PORT", 8000)
        self.log_level: str = os.environ.get("ORCHESTRA_LOG_LEVEL", "info").upper()

        # ── JWT / Auth ───────────────────────────────────────────────────
        self.jwt_secret: str = os.environ.get("JWT_SECRET", "")
        if not self.jwt_secret:
            if self.is_production:
                raise RuntimeError(
                    "JWT_SECRET is required in production. "
                    "Set it to a random 64-char hex string: "
                    "python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            # Dev: auto-generate volatile secret (tokens invalidated on restart)
            self.jwt_secret = secrets.token_hex(32)
            log.warning(
                "JWT_SECRET not set — using a volatile auto-generated secret. "
                "All tokens will be invalidated on server restart. "
                "Set JWT_SECRET in .env to persist sessions."
            )

        self.jwt_access_ttl: int = _env_int("JWT_ACCESS_TTL", 3600)       # 1 hour
        self.jwt_refresh_ttl: int = _env_int("JWT_REFRESH_TTL", 2592000)  # 30 days

        # ── CORS ────────────────────────────────────────────────────────
        default_origins = (
            ["*"] if not self.is_production
            else [f"http://localhost:{self.port}", f"https://localhost:{self.port}"]
        )
        self.cors_origins: list[str] = _env_list("CORS_ORIGINS", default_origins)
        if self.is_production and "*" in self.cors_origins:
            raise RuntimeError(
                "CORS_ORIGINS must not contain '*' in production. "
                "Set CORS_ORIGINS to a comma-separated list of allowed origins."
            )

        # ── API key encryption ───────────────────────────────────────────
        self.api_key_encryption_key: str = os.environ.get("API_KEY_ENCRYPTION_KEY", "")
        if not self.api_key_encryption_key:
            if self.is_production:
                raise RuntimeError(
                    "API_KEY_ENCRYPTION_KEY is required in production. "
                    "Set it to a 32-byte hex string: "
                    "python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            self.api_key_encryption_key = secrets.token_hex(32)
            log.warning(
                "API_KEY_ENCRYPTION_KEY not set — using volatile key. "
                "Stored API keys will not survive restarts. Set in .env."
            )

        # ── Database ─────────────────────────────────────────────────────
        self.db_path: str = os.environ.get("ORCHESTRA_DB", "orchestra.db")
        self.billing_db_path: str = os.environ.get("ORCHESTRA_BILLING_DB", "orchestra_billing.db")
        self.logs_db_path: str = os.environ.get("ORCHESTRA_LOGS_DB",
                                                  os.path.expanduser("~/.orchestra_logs.db"))

        # ── Rate limiting ────────────────────────────────────────────────
        self.rate_limit_enabled: bool = _env_bool("RATE_LIMIT_ENABLED", True)
        self.rate_limit_per_minute: int = _env_int("RATE_LIMIT_PER_MINUTE", 120)
        self.rate_limit_chat_per_minute: int = _env_int("RATE_LIMIT_CHAT_PER_MINUTE", 20)

        # ── LLM providers ────────────────────────────────────────────────
        self.provider: str = os.environ.get("ORCHESTRA_PROVIDER", "ollama")
        self.model: str = os.environ.get("ORCHESTRA_MODEL", "nemotron-mini")
        self.openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
        self.anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
        self.llm_base_url: str = os.environ.get("LLM_BASE_URL", "")

        # ── Stripe ──────────────────────────────────────────────────────
        self.stripe_secret_key: str = os.environ.get("STRIPE_SECRET_KEY", "")
        self.stripe_webhook_secret: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        if self.is_production and not self.stripe_secret_key:
            log.warning("STRIPE_SECRET_KEY not set — billing will be disabled.")

        # ── Sentry ──────────────────────────────────────────────────────
        self.sentry_dsn: str = os.environ.get("SENTRY_DSN", "")

        # ── Workspace ───────────────────────────────────────────────────
        self.workspace: str = os.environ.get("ORCHESTRA_WORKSPACE", "")
        self.session_dir: str = os.environ.get("ORCHESTRA_SESSION_DIR", "")

        # ── Redis (optional) ─────────────────────────────────────────────
        self.redis_url: str = os.environ.get("REDIS_URL", "")

    def validate_production(self) -> list[str]:
        """Return list of warnings for near-production configs."""
        warnings: list[str] = []
        if not self.stripe_secret_key:
            warnings.append("STRIPE_SECRET_KEY not set — billing disabled")
        if not self.sentry_dsn:
            warnings.append("SENTRY_DSN not set — error tracking disabled")
        if not self.redis_url:
            warnings.append("REDIS_URL not set — rate limiting uses in-memory fallback")
        return warnings

    def as_dict(self) -> dict[str, Any]:
        """Return safe (no secrets) settings dict for health endpoint."""
        return {
            "env": self.env,
            "provider": self.provider,
            "model": self.model,
            "rate_limit_enabled": self.rate_limit_enabled,
            "cors_origins": self.cors_origins,
            "stripe_configured": bool(self.stripe_secret_key),
            "sentry_configured": bool(self.sentry_dsn),
            "redis_configured": bool(self.redis_url),
        }


# ---------------------------------------------------------------------------
# Module-level singleton — load on import, fail fast
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(override=False)
    except ImportError:
        pass


_load_dotenv()

try:
    settings = OrchestraSettings()
except RuntimeError as _e:
    import sys
    print(f"\n[Orchestra] FATAL CONFIGURATION ERROR:\n  {_e}\n", file=sys.stderr)
    sys.exit(1)
