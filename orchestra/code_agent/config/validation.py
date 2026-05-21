"""Environment variable validation for Horizon Orchestra.

Provides EnvValidator to check required configuration at startup.
"""

from __future__ import annotations

import logging
import os
from typing import Tuple

__all__ = [
    "EnvValidator",
    "REQUIRED_VARS",
    "OPTIONAL_VARS",
]

logger = logging.getLogger(__name__)

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
    """Validates required environment variables at startup.

    Usage::

        passed, missing = EnvValidator.check()
        if not passed:
            ...  # caller decides what to do
    """

    @staticmethod
    def check() -> Tuple[bool, list[str]]:
        """Read predefined env vars, log ERROR for each missing required one.

        Returns:
            (passed, missing) where passed is True when all required vars
            are present, and missing is the list of missing required vars.
        """
        missing: list[str] = []

        for var in REQUIRED_VARS:
            if not os.environ.get(var):
                logger.error("Missing required env var: %s", var)
                missing.append(var)

        for var, default in OPTIONAL_VARS.items():
            val = os.environ.get(var)
            if not val and default:
                os.environ.setdefault(var, default)
                logger.debug(
                    "Optional env var %s not set, defaulting to %r", var, default
                )
            elif not val:
                logger.debug(
                    "Optional env var %s not set and has no default", var
                )

        env = os.environ.get("ORCHESTRA_ENV", "development")
        if env == "development":
            logger.warning(
                "ORCHESTRA_ENV=development — ensure production env vars are set: %s",
                ", ".join(REQUIRED_VARS + list(OPTIONAL_VARS.keys())),
            )

        return (len(missing) == 0, missing)
