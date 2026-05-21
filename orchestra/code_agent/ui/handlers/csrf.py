from __future__ import annotations

import logging
import os
import secrets

from fastapi import FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("orchestra.csrf")

EXEMPT_PATHS = frozenset({
    "/v1/auth/login",
    "/v1/auth/register",
    "/health",
})


def _is_exempt(path: str, content_type: str = "") -> bool:
    if path in EXEMPT_PATHS:
        return True
    if path.startswith("/webhook/") or path.startswith("/api/"):
        return True
    # JSON requests can't be sent cross-origin without CORS — exempt them
    if content_type.startswith("application/json"):
        return True
    return False


def _client_ip(scope: Scope) -> str:
    headers = Headers(scope=scope)
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    if client:
        return client[0]
    return "unknown"


class CSRFMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        headers = Headers(scope=scope)
        content_type = headers.get("content-type", "")
        if _is_exempt(path, content_type):
            await self.app(scope, receive, send)
            return

        cookies = self._parse_cookies(headers)

        if method in ("POST", "PUT", "DELETE", "PATCH"):
            token_cookie = cookies.get("csrf_token")
            if not token_cookie:
                ip = _client_ip(scope)
                log.warning("CSRF violation — missing cookie — %s %s from %s", method, path, ip)
                await self._respond_403(send)
                return

            token_header = headers.get("x-csrf-token")
            token_field = None

            if method in ("POST", "PUT", "PATCH"):
                content_type = headers.get("content-type", "")
                if content_type.startswith("application/x-www-form-urlencoded") or content_type.startswith("multipart/form-data"):
                    body = await self._read_body(receive)
                    token_field = self._parse_form_field(body, "csrf_token")

            token = token_header or token_field
            if not token or not secrets.compare_digest(token, token_cookie):
                ip = _client_ip(scope)
                log.warning(
                    "CSRF violation — token mismatch — %s %s from %s (header=%s, field=%s)",
                    method, path, ip, bool(token_header), bool(token_field),
                )
                await self._respond_403(send)
                return

            await self.app(scope, receive, send)

        elif method == "GET":
            if "csrf_token" not in cookies:
                token = secrets.token_urlsafe(32)
                await self._set_cookie_and_forward(scope, receive, send, token)
            else:
                await self.app(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_cookies(headers: Headers) -> dict[str, str]:
        raw = headers.get("cookie", "")
        result: dict[str, str] = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            key, _, val = part.partition("=")
            result[key.strip()] = val.strip()
        return result

    @staticmethod
    async def _read_body(receive: Receive) -> bytes:
        chunks: list[bytes] = []
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                break
            chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        return b"".join(chunks)

    @staticmethod
    def _parse_form_field(body: bytes, field_name: str) -> str | None:
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            return None
        for part in text.split("&"):
            if "=" not in part:
                continue
            key, _, val = part.partition("=")
            from urllib.parse import unquote_plus
            if key.strip() == field_name:
                return unquote_plus(val.strip())
        return None

    @staticmethod
    async def _respond_403(send: Send) -> None:
        import json
        body = json.dumps({"detail": "CSRF validation failed"}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def _set_cookie_and_forward(self, scope: Scope, receive: Receive, send: Send, token: str) -> None:
        secure = os.environ.get("ORCHESTRA_ENV") == "production"
        cookie_header = (
            f"csrf_token={token}; Path=/; Max-Age=86400; SameSite=Lax; HttpOnly=False"
            f"{'; Secure' if secure else ''}"
        )

        original_send = send

        async def send_wrapper(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                headers = MutableHeaders(scope=msg)
                headers.append("Set-Cookie", cookie_header)
            await original_send(msg)

        await self.app(scope, receive, send_wrapper)


def register_csrf_middleware(app: FastAPI) -> None:
    app.add_middleware(CSRFMiddleware)
