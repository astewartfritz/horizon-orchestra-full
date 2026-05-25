"""Auto-issue owner session cookie for localhost requests.

When ORCHESTRA_OWNER_EMAIL is set and the request comes from 127.0.0.1 / ::1,
we silently inject a long-lived owner session cookie into the response if the
browser doesn't already have one.  The owner never has to type credentials.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

_log = logging.getLogger("orchestra.owner_autologin")

# Cache the token so we don't hit the DB on every request
_cached: dict[str, tuple[str, float]] = {}  # email -> (token, expires_at)
_TOKEN_TTL = 25 * 24 * 3600  # 25 days — reissue well before JWT expiry


def _localhost_ip(scope: dict) -> bool:
    client = scope.get("client")
    if not client:
        return False
    ip = client[0]
    return ip in ("127.0.0.1", "::1", "localhost", "0.0.0.0")


def _has_session(scope: dict) -> bool:
    headers = dict(scope.get("headers", []))
    raw = headers.get(b"cookie", b"").decode("utf-8", errors="ignore")
    return "session=" in raw


def _get_owner_token(owner_email: str) -> str | None:
    cached = _cached.get(owner_email)
    if cached and cached[1] > time.time():
        return cached[0]
    try:
        from orchestra.code_agent.auth.user_store import UserStore
        from orchestra.code_agent.ui.handlers.v1_compat import _encode_local_token
        user = UserStore.get().get_user_by_email(owner_email)
        if not user or not user.get("is_owner"):
            return None
        token = _encode_local_token(
            user["id"],
            role="admin",
            tier="unlimited",
            prof_role=user.get("prof_role", ""),
        )
        _cached[owner_email] = (token, time.time() + _TOKEN_TTL)
        return token
    except Exception as e:
        _log.debug("Owner autologin token error: %s", e)
        return None


class OwnerAutoLoginMiddleware:
    """Inject owner session cookie transparently for localhost requests."""

    def __init__(self, app: Any, owner_email: str) -> None:
        self.app = app
        self.owner_email = owner_email.strip().lower()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not _localhost_ip(scope) or _has_session(scope):
            await self.app(scope, receive, send)
            return

        token = _get_owner_token(self.owner_email)
        if not token:
            await self.app(scope, receive, send)
            return

        cookie_header = (
            f"session={token}; Path=/; Max-Age=2592000; SameSite=Lax; HttpOnly"
        ).encode()

        async def _send_with_cookie(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"set-cookie", cookie_header))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send_with_cookie)
