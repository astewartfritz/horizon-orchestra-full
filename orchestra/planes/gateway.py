"""PlatformGateway — context manager that wires both planes together."""

from __future__ import annotations

import logging
from typing import Any

from .agent import AgentPlane
from .api import APIPlane
from .config import PlaneConfig

log = logging.getLogger(__name__)

try:
    import uvicorn
    _UVICORN_AVAILABLE = True
except ImportError:
    uvicorn = None  # type: ignore
    _UVICORN_AVAILABLE = False


class PlatformGateway:
    """Orchestrates start/stop of AgentPlane and APIPlane as a unit."""

    def __init__(self, config: PlaneConfig | None = None) -> None:
        self._config: PlaneConfig = config or PlaneConfig()
        self._agent_plane: AgentPlane | None = None
        self._api_plane: APIPlane | None = None
        self._fastapi_app: Any = None

    # ── Context manager ────────────────────────────────────────────────────

    async def __aenter__(self) -> PlatformGateway:
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Create and start both planes."""
        self._agent_plane = AgentPlane(self._config)
        await self._agent_plane.start()

        self._api_plane = APIPlane(self._config, self._agent_plane)
        try:
            self._fastapi_app = self._api_plane.create_app()
        except RuntimeError as exc:
            log.warning("APIPlane app creation skipped: %s", exc)
            self._fastapi_app = None

        log.info("PlatformGateway started")

    async def stop(self) -> None:
        """Stop both planes, cancelling any running agent jobs."""
        if self._agent_plane is not None:
            await self._agent_plane.stop()
            self._agent_plane = None
        self._api_plane = None
        self._fastapi_app = None
        log.info("PlatformGateway stopped")

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def app(self) -> Any:
        """FastAPI application, suitable for passing to uvicorn."""
        if self._fastapi_app is None:
            raise RuntimeError("Gateway not started or FastAPI is not available.")
        return self._fastapi_app

    # ── Run ────────────────────────────────────────────────────────────────

    async def run(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Start the gateway and serve the API plane via uvicorn."""
        if not _UVICORN_AVAILABLE:
            raise RuntimeError(
                "uvicorn is not installed. Install it with: pip install uvicorn"
            )
        await self.start()
        config = uvicorn.Config(
            app=self.app,
            host=host,
            port=port,
            log_level="info",
            limit_concurrency=self._config.api_max_connections,
        )
        server = uvicorn.Server(config)
        try:
            await server.serve()
        finally:
            await self.stop()

    # ── Factory ────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> PlatformGateway:
        """Create a gateway fully configured from PLANE_* environment variables."""
        return cls(config=PlaneConfig.from_env())
