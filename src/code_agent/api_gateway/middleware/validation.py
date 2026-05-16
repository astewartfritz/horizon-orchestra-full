"""Request validation middleware — content-type, size, schema checks."""

from __future__ import annotations

from fastapi import Request, HTTPException


class ValidationMiddleware:
    """Validates incoming requests: content-type, size limits, required headers."""

    def __init__(self, max_body_size: int = 10 * 1024 * 1024):  # 10MB
        self.max_body_size = max_body_size

    async def __call__(self, request: Request, call_next):
        # Content-Type validation for POST/PUT/PATCH
        if request.method in ("POST", "PUT", "PATCH"):
            content_type = request.headers.get("content-type", "")
            if not content_type:
                raise HTTPException(status_code=415, detail="Content-Type header required")

            # Check body size for JSON requests
            if "application/json" in content_type:
                content_length = request.headers.get("content-length")
                if content_length and int(content_length) > self.max_body_size:
                    raise HTTPException(status_code=413, detail=f"Request body too large (max {self.max_body_size // 1024 // 1024}MB)")

        # Required headers
        if request.url.path.startswith("/api/"):
            host = request.headers.get("host", "")
            if not host:
                raise HTTPException(status_code=400, detail="Host header required")

        response = await call_next(request)
        return response
