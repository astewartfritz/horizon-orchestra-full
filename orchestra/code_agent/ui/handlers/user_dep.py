"""FastAPI dependency for extracting the authenticated user from a request.

Usage:
    from orchestra.code_agent.ui.handlers.user_dep import current_user_id

    @app.get("/api/something")
    async def handler(uid: str = Depends(current_user_id)):
        ...
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request


def _extract_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get("session", "")


def current_user_id(request: Request) -> str:
    """Return the authenticated user's ID or raise 401."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from orchestra.code_agent.ui.handlers.v1_compat import _decode_local_token
    uid = _decode_local_token(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return uid


def optional_user_id(request: Request) -> str | None:
    """Return the authenticated user's ID or None (no 401)."""
    token = _extract_token(request)
    if not token:
        return None
    from orchestra.code_agent.ui.handlers.v1_compat import _decode_local_token
    return _decode_local_token(token)
