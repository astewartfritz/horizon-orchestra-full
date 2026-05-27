"""FastAPI routes for server-side API key management."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger("orchestra.api_keys.routes")

SUPPORTED_PROVIDERS = {
    "openai", "anthropic", "gemini", "groq", "mistral",
    "cohere", "together", "fireworks", "perplexity",
    "stripe", "sendgrid", "twilio", "github", "openrouter",
    "moonshot",
}


def _get_user_id(request: Request) -> str:
    """Extract user_id from JWT cookie or Authorization header."""
    # Try Authorization: Bearer <token>
    auth = request.headers.get("authorization", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    # Try session cookie
    if not token:
        token = request.cookies.get("session", "")
    if not token:
        return "__anonymous__"
    try:
        from orchestra.code_agent.auth.jwt import JWTManager
        payload = JWTManager().verify(token)
        if payload:
            return payload.get("sub", "__anonymous__")
    except Exception:
        pass
    return "__anonymous__"


def register_api_key_routes(app: Any) -> None:
    from orchestra.code_agent.api_keys.store import ApiKeyStore

    router = APIRouter(prefix="/api/keys", tags=["api-keys"])

    @router.get("")
    async def list_keys(request: Request):
        user_id = _get_user_id(request)
        store = ApiKeyStore.get()
        return {"keys": store.list_for_user(user_id)}

    @router.put("/{provider}")
    async def upsert_key(provider: str, body: dict[str, Any], request: Request):
        if provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(400, f"Unsupported provider '{provider}'. "
                                f"Supported: {sorted(SUPPORTED_PROVIDERS)}")
        raw_key = body.get("key", "").strip()
        if not raw_key:
            raise HTTPException(400, "key field is required")
        user_id = _get_user_id(request)
        store = ApiKeyStore.get()
        meta = store.upsert(user_id, provider, raw_key, label=body.get("label", provider))
        log.info("API key stored for user=%s provider=%s", user_id, provider)
        return {"ok": True, "meta": meta}

    @router.get("/{provider}/check")
    async def check_key(provider: str, request: Request):
        user_id = _get_user_id(request)
        store = ApiKeyStore.get()
        meta = store.get_meta(user_id, provider)
        return {"provider": provider, "configured": meta is not None,
                "meta": meta}

    @router.delete("/{provider}")
    async def delete_key(provider: str, request: Request):
        user_id = _get_user_id(request)
        store = ApiKeyStore.get()
        deleted = store.delete(user_id, provider)
        if not deleted:
            raise HTTPException(404, f"No key found for provider '{provider}'")
        log.info("API key deleted for user=%s provider=%s", user_id, provider)
        return {"ok": True}

    # Internal: resolve a key for server-side LLM calls
    @router.get("/{provider}/resolve")
    async def resolve_key(provider: str, request: Request):
        """Return the plaintext key. Only callable server-side (same origin)."""
        # Restrict to localhost for now
        host = request.headers.get("host", "")
        if not (host.startswith("127.0.0.1") or host.startswith("localhost")):
            raise HTTPException(403, "Key resolution only available from localhost")
        user_id = _get_user_id(request)
        store = ApiKeyStore.get()
        key = store.reveal(user_id, provider)
        if not key:
            # Fall back to env var
            import os
            env_map = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "groq": "GROQ_API_KEY",
                "moonshot": "MOONSHOT_API_KEY",
            }
            env_key = os.environ.get(env_map.get(provider, ""), "")
            if env_key:
                return {"key": env_key, "source": "env"}
            raise HTTPException(404, f"No key configured for provider '{provider}'")
        return {"key": key, "source": "db"}

    app.include_router(router)
