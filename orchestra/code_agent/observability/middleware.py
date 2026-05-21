"""Starlette middleware: log HTTP errors and slow requests to the Observatory."""
from __future__ import annotations

import time
import traceback
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .store import add_event

# Routes that generate too much noise to log unconditionally
_SKIP = ("/sw.js", "/icon", "/manifest.json", "/miles", "/api/logs")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in _SKIP):
            return await call_next(request)

        rid = str(uuid.uuid4())[:8]
        t0 = time.perf_counter()

        try:
            response = await call_next(request)
            ms = (time.perf_counter() - t0) * 1000

            if response.status_code >= 500:
                add_event(
                    level="ERROR",
                    source=f"http.{request.method.lower()}",
                    message=f"{request.method} {path} → {response.status_code} ({ms:.0f}ms)",
                    details={"status": response.status_code, "ms": round(ms, 1)},
                    request_id=rid,
                )
            elif response.status_code >= 400:
                add_event(
                    level="WARNING",
                    source=f"http.{request.method.lower()}",
                    message=f"{request.method} {path} → {response.status_code} ({ms:.0f}ms)",
                    details={"status": response.status_code, "ms": round(ms, 1)},
                    request_id=rid,
                )
            elif ms > 5000:
                # Slow request threshold: 5 s
                add_event(
                    level="WARNING",
                    source="http.slow",
                    message=f"Slow: {request.method} {path} took {ms:.0f}ms",
                    details={"status": response.status_code, "ms": round(ms, 1)},
                    request_id=rid,
                )
            return response

        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            add_event(
                level="CRITICAL",
                source=f"http.{request.method.lower()}",
                message=f"Unhandled exception: {request.method} {path} — {type(exc).__name__}: {exc}",
                details={"traceback": traceback.format_exc(), "ms": round(ms, 1)},
                request_id=rid,
            )
            raise
