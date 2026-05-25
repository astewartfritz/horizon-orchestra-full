"""PlaneConfig — shared configuration for both planes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class PlaneConfig:
    """Configuration shared by AgentPlane, APIPlane, and PlatformGateway."""

    # Agent plane
    agent_concurrency: int = 10
    agent_timeout_s: int = 300

    # API plane
    api_timeout_s: int = 30
    api_max_connections: int = 1000

    # Queue backend
    queue_backend: str = "memory"  # "memory" | "redis" | "postgres"
    queue_dsn: str = ""

    # Database
    db_dsn: str = ""
    db_pool_min: int = 2
    db_pool_max: int = 10

    # CORS
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def from_env(cls) -> PlaneConfig:
        """Build a PlaneConfig from PLANE_* environment variables."""

        def _int(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, default))
            except (ValueError, TypeError):
                return default

        def _str(key: str, default: str) -> str:
            return os.environ.get(key, default)

        def _list(key: str, default: list[str]) -> list[str]:
            raw = os.environ.get(key, "")
            return [o.strip() for o in raw.split(",") if o.strip()] if raw else default

        return cls(
            agent_concurrency=_int("PLANE_AGENT_CONCURRENCY", 10),
            agent_timeout_s=_int("PLANE_AGENT_TIMEOUT_S", 300),
            api_timeout_s=_int("PLANE_API_TIMEOUT_S", 30),
            api_max_connections=_int("PLANE_API_MAX_CONNECTIONS", 1000),
            queue_backend=_str("PLANE_QUEUE_BACKEND", "memory"),
            queue_dsn=_str("PLANE_QUEUE_DSN", ""),
            db_dsn=_str("PLANE_DB_DSN", ""),
            db_pool_min=_int("PLANE_DB_POOL_MIN", 2),
            db_pool_max=_int("PLANE_DB_POOL_MAX", 10),
            cors_origins=_list("PLANE_CORS_ORIGINS", ["*"]),
        )
