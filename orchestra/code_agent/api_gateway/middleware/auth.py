"""JWT + API key authentication middleware for the API Gateway."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request


@dataclass
class AuthConfig:
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24
    api_key_header: str = "X-API-Key"
    enable_jwt: bool = True
    enable_api_keys: bool = True


@dataclass
class AuthResult:
    authenticated: bool
    user_id: str = ""
    role: str = "user"  # admin, user, readonly
    permissions: list[str] = field(default_factory=list)
    token_type: str = ""  # jwt, api_key, none
    error: str = ""


class JWTAuthMiddleware:
    """JWT token creation and verification."""

    def __init__(self, config: AuthConfig | None = None):
        self.config = config or AuthConfig()

    def create_token(self, user_id: str, role: str = "user",
                     permissions: list[str] | None = None) -> str:
        """Create a signed JWT token."""
        import jwt as _jwt
        payload = {
            "sub": user_id,
            "role": role,
            "permissions": permissions or [],
            "iat": int(time.time()),
            "exp": int(time.time()) + self.config.jwt_expiry_hours * 3600,
            "jti": uuid.uuid4().hex[:16],
        }
        return _jwt.encode(payload, self.config.jwt_secret, algorithm=self.config.jwt_algorithm)

    def verify_token(self, token: str) -> AuthResult:
        """Verify a JWT token and return user info."""
        import jwt as _jwt
        try:
            payload = _jwt.decode(
                token, self.config.jwt_secret,
                algorithms=[self.config.jwt_algorithm],
            )
            return AuthResult(
                authenticated=True,
                user_id=payload.get("sub", ""),
                role=payload.get("role", "user"),
                permissions=payload.get("permissions", []),
                token_type="jwt",
            )
        except _jwt.ExpiredSignatureError:
            return AuthResult(authenticated=False, error="Token expired")
        except _jwt.InvalidTokenError as e:
            return AuthResult(authenticated=False, error=f"Invalid token: {e}")


class APIKeyAuth:
    """API key authentication with hashed key storage."""

    def __init__(self):
        self._keys: dict[str, dict[str, Any]] = {}  # key_hash → metadata

    def create_key(self, user_id: str, role: str = "user",
                   permissions: list[str] | None = None) -> str:
        """Generate a new API key and store its hash."""
        key = f"orch_{uuid.uuid4().hex}{uuid.uuid4().hex[:16]}"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        self._keys[key_hash] = {
            "user_id": user_id,
            "role": role,
            "permissions": permissions or [],
            "created_at": time.time(),
        }
        return key

    def verify(self, key: str) -> AuthResult:
        """Verify an API key."""
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        meta = self._keys.get(key_hash)
        if not meta:
            return AuthResult(authenticated=False, error="Invalid API key")
        return AuthResult(
            authenticated=True,
            user_id=meta["user_id"],
            role=meta["role"],
            permissions=meta["permissions"],
            token_type="api_key",
        )

    def revoke(self, key: str) -> bool:
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return self._keys.pop(key_hash, None) is not None


class AuthMiddleware:
    """Combined auth middleware — checks JWT Bearer token, then API key header."""

    def __init__(self, jwt_config: AuthConfig | None = None):
        self.jwt = JWTAuthMiddleware(jwt_config)
        self.api_keys = APIKeyAuth()
        self._public_paths = {"/health", "/api/health", "/docs", "/openapi.json", "/redoc",
                              "/observability", "/api/metrics", "/manifest.json",
                              "/sw.js", "/icon.svg", "/icon-192.png", "/icon-512.png",
                              "/auth/token", "/auth/api-key"}

    def add_public_path(self, path: str) -> None:
        self._public_paths.add(path)

    async def authenticate(self, request: Request) -> AuthResult:
        """Authenticate a request. Checks JWT (Authorization header) then API key."""
        path = request.url.path

        # Public paths don't need auth
        if any(path == p or path.startswith(p) for p in self._public_paths):
            return AuthResult(authenticated=True, user_id="anonymous", role="readonly")

        # Try JWT Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            result = self.jwt.verify_token(token)
            if result.authenticated:
                return result

        # Try API key header
        api_key = request.headers.get(self.jwt.config.api_key_header, "")
        if api_key:
            result = self.api_keys.verify(api_key)
            if result.authenticated:
                return result

        # Allow through for configured unprotected paths
        return AuthResult(authenticated=False, error="Authentication required. Provide Authorization: Bearer <jwt> or X-API-Key header.")
