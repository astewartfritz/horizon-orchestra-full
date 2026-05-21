"""FastAPI server with OrchestraGateway middleware stack."""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from orchestra.code_agent.api_gateway.gateway import OrchestraGateway


def create_app() -> FastAPI:
    """Create the FastAPI application with the full gateway middleware stack."""
    jwt_secret = os.environ.get("JWT_SECRET", uuid.uuid4().hex)

    app = FastAPI(
        title="Orchestra API Gateway",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS (outermost) ──────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-trace-id", "x-response-time-ms", "Retry-After"],
    )

    # ── Gateway middleware stack ──────────────────────────────
    gateway = OrchestraGateway(jwt_secret=jwt_secret)

    @app.middleware("http")
    async def gateway_middleware(request: Request, call_next):
        return await gateway.handle(request, call_next)

    # ── Health ────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "orchestra-gateway", "version": "1.0.0"}

    # ── Chat endpoint ─────────────────────────────────────────
    @app.post("/api/chat")
    async def chat(request: Request, body: dict[str, Any]):
        return await _chat_handler(request, body, gateway)

    # ── Sessions ──────────────────────────────────────────────
    @app.get("/api/sessions")
    async def list_sessions():
        return {"sessions": []}

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        return {"session_id": session_id, "messages": []}

    # ── Auth ──────────────────────────────────────────────────
    @app.post("/auth/token")
    async def create_token(body: dict[str, str]):
        user_id = body.get("user_id", "")
        role = body.get("role", "user")
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required")
        token = gateway.auth.jwt.create_token(user_id, role)
        return {"access_token": token, "token_type": "bearer", "expires_in": 86400}

    @app.post("/auth/api-key")
    async def create_api_key(body: dict[str, str]):
        user_id = body.get("user_id", "")
        role = body.get("role", "user")
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required")
        key = gateway.auth.api_keys.create_key(user_id, role)
        return {"api_key": key, "key_type": "permanent"}

    # ── Gateway admin ─────────────────────────────────────────
    @app.get("/admin/gateway/stats")
    async def gateway_stats():
        return gateway.get_stats()

    @app.get("/admin/gateway/routes")
    async def gateway_routes():
        return list(gateway._routes.keys())

    return app


async def _chat_handler(request: Request, body: dict[str, Any], gateway: OrchestraGateway) -> dict[str, Any]:
    """Unified chat handler — delegates to the backend agent runtime."""
    from orchestra.code_agent.channels.manager import ChannelType
    from orchestra.code_agent.gateway.runtime import GatewayEvent

    task = body.get("task", body.get("content", ""))
    channel = body.get("channel", "web")
    sender = body.get("sender", getattr(request.state, "user_id", "") or "user")

    event = GatewayEvent(
        content=task,
        channel=ChannelType(channel),
        sender=sender,
        metadata={
            "trace_id": request.state.trace_id,
            "user_id": request.state.user_id,
            "role": request.state.role,
        },
    )

    try:
        from orchestra.code_agent.gateway.runtime import Gateway
        gw = Gateway()
        result = await gw.handle_event(event, api_key=request.headers.get("X-API-Key", ""))
        return {"response": result, "session_id": event.session_id, "trace_id": request.state.trace_id}
    except PermissionError:
        raise HTTPException(status_code=401, detail="Authentication required")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Entry points ──────────────────────────────────────────────

app = create_app()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("GATEWAY_PORT", "8080"))
    host = os.environ.get("GATEWAY_HOST", "0.0.0.0")
    uvicorn.run("api_gateway.server:app", host=host, port=port, reload=True)
