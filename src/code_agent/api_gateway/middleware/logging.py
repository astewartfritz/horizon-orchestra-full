"""Request logging and tracing middleware."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable

from fastapi import Request, Response


class LoggingMiddleware:
    """Logs every request with trace ID, duration, status, and path."""

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("orchestra.gateway")

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        trace_id = request.headers.get("x-trace-id", uuid.uuid4().hex[:16])
        request.state.trace_id = trace_id

        start = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)

        response.headers["x-trace-id"] = trace_id
        response.headers["x-response-time-ms"] = str(duration_ms)

        self.logger.info(
            "%s %s -> %d [%dms] trace=%s",
            request.method, request.url.path,
            response.status_code, duration_ms, trace_id,
        )

        return response


class TracingMiddleware:
    """Adds trace ID to every request if not present."""

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        trace_id = request.headers.get("x-trace-id", uuid.uuid4().hex[:12])
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response
