"""Environment configuration via pydantic-settings.

Replaces the legacy EnvValidator with proper typed settings that
validate lazily (no import-time side effects).
"""

from __future__ import annotations

import logging
from typing import Tuple

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class OrchestraSettings(BaseSettings):
    """Typed settings for Horizon Orchestra.

    Reads from environment variables automatically. All fields have
    sensible defaults so importing this module never raises.
    """

    model_config = {"extra": "ignore"}

    # Security
    jwt_secret: str = Field(default="", alias="JWT_SECRET")
    stripe_secret_key: str = Field(default="", alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", alias="STRIPE_WEBHOOK_SECRET")

    # AI Provider Keys
    moonshot_api_key: str = Field(default="", alias="MOONSHOT_API_KEY")

    # Database
    database_url: str = Field(default="sqlite:///orchestra_billing.db", alias="DATABASE_URL")

    # Observability
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    # Email / SMTP
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: str = Field(default="", alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_pass: str = Field(default="", alias="SMTP_PASS")

    # Orchestra
    orchestra_env: str = Field(default="development", alias="ORCHESTRA_ENV")

    @property
    def is_production(self) -> bool:
        return self.orchestra_env.lower() == "production"

    @property
    def missing_required(self) -> list[str]:
        """Return names of required vars that are empty."""
        missing: list[str] = []
        for field_name in ("jwt_secret", "stripe_secret_key", "stripe_webhook_secret"):
            if not getattr(self, field_name):
                missing.append(field_name)
        return missing

    @property
    def is_ready(self) -> bool:
        return len(self.missing_required) == 0


def get_settings() -> OrchestraSettings:
    """Return a fresh OrchestraSettings instance (reads current env vars)."""
    return OrchestraSettings()


# ── Backward compatibility with legacy EnvValidator API ──────────────────────

REQUIRED_VARS: list[str] = [
    "JWT_SECRET",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
]

OPTIONAL_VARS: dict[str, str] = {
    "DATABASE_URL": "sqlite:///orchestra_billing.db",
    "SENTRY_DSN": "",
    "SMTP_HOST": "",
    "SMTP_PORT": "",
    "SMTP_USER": "",
    "SMTP_PASS": "",
}


class EnvValidator:
    """Legacy compatibility wrapper. Prefer ``get_settings()`` directly."""

    @staticmethod
    def check() -> Tuple[bool, list[str]]:
        """Check required env vars. Returns (passed, missing)."""
        settings = get_settings()
        missing = settings.missing_required

        if settings.orchestra_env == "development":
            logger.warning(
                "ORCHESTRA_ENV=development — ensure production env vars are set: %s",
                ", ".join(REQUIRED_VARS + list(OPTIONAL_VARS.keys())),
            )

        return (len(missing) == 0, [v.upper() for v in missing])


__all__ = [
    "OrchestraSettings",
    "get_settings",
    "EnvValidator",
    "REQUIRED_VARS",
    "OPTIONAL_VARS",
]
