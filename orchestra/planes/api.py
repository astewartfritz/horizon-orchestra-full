"""APIPlane — low-latency, stateless FastAPI surface over the AgentPlane."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from .agent import AgentPlane
from .config import PlaneConfig

log = logging.getLogger(__name__)

try:
    import fastapi
    from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    _FASTAPI_AVAILABLE = True
except ImportError:
    fastapi = None  # type: ignore
    _FASTAPI_AVAILABLE = False


# ── Request / response models ─────────────────────────────────────────────────

if _FASTAPI_AVAILABLE:
    class SubmitRequest(BaseModel):  # type: ignore[misc]
        task: str
        model: str = "claude-sonnet-4-6"
        tools: list[str] = []
        context: dict[str, Any] = {}

    class SubmitResponse(BaseModel):  # type: ignore[misc]
        job_id: str

else:
    SubmitRequest = None  # type: ignore
    SubmitResponse = None  # type: ignore


# ── Auth dependency ───────────────────────────────────────────────────────────

_API_KEY = os.environ.get("PLANE_API_KEY", "")


def _bearer_auth(request: Any = None) -> None:  # pragma: no cover
    """Check Bearer token when PLANE_API_KEY is set."""
    if not _FASTAPI_AVAILABLE:
        return
    if not _API_KEY:
        return  # auth disabled
    from fastapi import Request
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    # Extracted manually to keep dependency minimal
    auth_header: str = (
        request.headers.get("authorization", "") if request else ""
    )
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or token != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing Bearer token")


class APIPlane:
    """Wraps the AgentPlane behind a FastAPI application."""

    def __init__(self, config: PlaneConfig, agent_plane: AgentPlane) -> None:
        self._config = config
        self._agent = agent_plane
        self._app: Any = None

    def create_app(self) -> Any:
        """Build and return the FastAPI application."""
        if not _FASTAPI_AVAILABLE:
            raise RuntimeError(
                "fastapi is not installed. Install it with: pip install fastapi"
            )

        app = FastAPI(title="Orchestra API Plane", version="1.0.0")

        app.add_middleware(
            CORSMiddleware,
            allow_origins=self._config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        agent = self._agent
        timeout_s = self._config.api_timeout_s

        # ── /health ───────────────────────────────────────────────────────────

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok", "plane": "api"}

        # ── POST /agent/submit ────────────────────────────────────────────────

        @app.post("/agent/submit", response_model=SubmitResponse)
        async def agent_submit(body: SubmitRequest, request: fastapi.Request) -> SubmitResponse:
            _bearer_auth(request)
            try:
                job_id = await asyncio.wait_for(
                    agent.submit(
                        task=body.task,
                        tools=body.tools,
                        model=body.model,
                        context=body.context,
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="submit timed out")
            return SubmitResponse(job_id=job_id)

        # ── GET /agent/status/{job_id} ────────────────────────────────────────

        @app.get("/agent/status/{job_id}")
        async def agent_status(job_id: str, request: fastapi.Request) -> JSONResponse:
            _bearer_auth(request)
            try:
                result = await asyncio.wait_for(agent.status(job_id), timeout=timeout_s)
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="status timed out")
            return JSONResponse(content=result)

        # ── WS /agent/stream/{job_id} ─────────────────────────────────────────

        @app.websocket("/agent/stream/{job_id}")
        async def agent_stream(websocket: WebSocket, job_id: str) -> None:
            await websocket.accept()
            try:
                while True:
                    snap = await agent.status(job_id)
                    # Drain any buffered events produced by _execute
                    events: list[Any] = []
                    job_meta = agent._jobs.get(job_id, {})
                    if "_events" in job_meta:
                        events = list(job_meta["_events"])
                        job_meta["_events"].clear()

                    for ev in events:
                        await websocket.send_text(
                            json.dumps({"type": "event", "data": _serialise(ev)})
                        )

                    if snap["status"] in ("done", "failed", "not_found"):
                        await websocket.send_text(json.dumps({"type": "final", **snap}))
                        break

                    await asyncio.sleep(0.25)
            except WebSocketDisconnect:
                log.debug("WS client disconnected for job %s", job_id)
            except Exception as exc:
                log.exception("WS error for job %s: %s", job_id, exc)
                try:
                    await websocket.send_text(
                        json.dumps({"type": "error", "detail": str(exc)})
                    )
                except Exception:
                    pass

        self._app = app
        return app


def _serialise(obj: Any) -> Any:
    """Best-effort JSON-safe serialisation of an arbitrary object."""
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
