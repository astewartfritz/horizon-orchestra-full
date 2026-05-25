"""
Conversation history REST API.

GET    /api/history                                 list user's conversations
POST   /api/history                                 create conversation
GET    /api/history/search?q=...                    search conversations
GET    /api/history/stats                           token/message stats
GET    /api/history/{conv_id}                       get conversation
PATCH  /api/history/{conv_id}                       update (title, pin, archive)
DELETE /api/history/{conv_id}                       delete conversation
GET    /api/history/{conv_id}/messages              list messages
POST   /api/history/{conv_id}/messages              append message
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException, Query

from orchestra.code_agent.history import store as _s

_log = logging.getLogger("orchestra.history")


def _get_user_id(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    from orchestra.code_agent.auth.jwt import JWTManager
    from orchestra.code_agent.settings import settings
    payload = JWTManager(secret=settings.jwt_secret).verify(authorization[7:])
    if not payload:
        raise HTTPException(401, "Invalid token")
    return payload["sub"]


def register_history_routes(app: FastAPI) -> None:
    _s.init_db()

    @app.get("/api/history")
    async def list_convs(
        archived: bool = False,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        convs = _s.list_conversations(user_id, archived=archived, limit=limit, offset=offset)
        return [asdict(c) for c in convs]

    @app.post("/api/history", status_code=201)
    async def create_conv(
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        conv = _s.create_conversation(
            user_id=user_id,
            title=body.get("title", "New conversation"),
            model=body.get("model", ""),
            provider=body.get("provider", ""),
            tags=body.get("tags", []),
        )
        return asdict(conv)

    @app.get("/api/history/search")
    async def search_convs(
        q: str = Query(..., min_length=1),
        limit: int = Query(20, ge=1, le=50),
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        results = _s.search_conversations(user_id, q, limit=limit)
        return [asdict(c) for c in results]

    @app.get("/api/history/stats")
    async def history_stats(authorization: str | None = Header(default=None)):
        user_id = _get_user_id(authorization)
        return _s.conversation_stats(user_id)

    @app.get("/api/history/{conv_id}")
    async def get_conv(conv_id: str, authorization: str | None = Header(default=None)):
        user_id = _get_user_id(authorization)
        conv = _s.get_conversation(conv_id, user_id)
        if not conv:
            raise HTTPException(404, "Conversation not found")
        return asdict(conv)

    @app.patch("/api/history/{conv_id}")
    async def update_conv(
        conv_id: str,
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        allowed = {"title", "model", "provider", "archived", "pinned", "tags"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            raise HTTPException(400, f"No valid fields. Allowed: {sorted(allowed)}")
        conv = _s.update_conversation(conv_id, user_id, **updates)
        if not conv:
            raise HTTPException(404, "Conversation not found")
        return asdict(conv)

    @app.delete("/api/history/{conv_id}", status_code=204)
    async def delete_conv(conv_id: str, authorization: str | None = Header(default=None)):
        user_id = _get_user_id(authorization)
        if not _s.delete_conversation(conv_id, user_id):
            raise HTTPException(404, "Conversation not found")

    @app.get("/api/history/{conv_id}/messages")
    async def list_msgs(
        conv_id: str,
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        conv = _s.get_conversation(conv_id, user_id)
        if not conv:
            raise HTTPException(404, "Conversation not found")
        msgs = _s.list_messages(conv_id, limit=limit, offset=offset)
        return [asdict(m) for m in msgs]

    @app.post("/api/history/{conv_id}/messages", status_code=201)
    async def add_msg(
        conv_id: str,
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        conv = _s.get_conversation(conv_id, user_id)
        if not conv:
            raise HTTPException(404, "Conversation not found")
        role = body.get("role", "user")
        if role not in ("user", "assistant", "system", "tool"):
            raise HTTPException(400, "role must be user | assistant | system | tool")
        content = body.get("content", "")
        if not content:
            raise HTTPException(400, "content is required")
        msg = _s.add_message(
            conversation_id=conv_id,
            role=role,
            content=content,
            token_count=int(body.get("token_count", 0)),
            model=body.get("model", ""),
            metadata=body.get("metadata"),
        )
        return asdict(msg)
