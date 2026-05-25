"""Horizon Orchestra — Auth + Multi-Tenancy.

JWT authentication, user isolation, org-level sharing, rate limiting.
Every API request is authenticated and scoped to a user/org.

Usage::

    from orchestra.auth import AuthManager, User
    auth = AuthManager(secret="your-jwt-secret")
    token = auth.create_token(user_id="ashton", org_id="horizon")
    user = auth.verify_token(token)
    auth.check_rate_limit(user)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import base64
from dataclasses import dataclass, field
from typing import Any

__all__ = ["AuthManager", "User", "Org", "AuthConfig", "RateLimiter", "OWNER_EMAIL", "is_owner"]

log = logging.getLogger("orchestra.auth")

# The sole account permitted to see AI-generated code output.
# Set OWNER_EMAIL in the environment to override.
OWNER_EMAIL: str = os.environ.get("OWNER_EMAIL", "ashton@horizon-orchestra.com")


@dataclass
class User:
    id: str
    email: str = ""
    name: str = ""
    org_id: str = ""
    role: str = "user"             # user, admin, org_admin
    tier: str = "free"             # free, pro, enterprise
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


def is_owner(user: "User") -> bool:
    """Return True if this user is the platform owner."""
    return user.email.lower() == OWNER_EMAIL.lower()


@dataclass
class Org:
    id: str
    name: str = ""
    owner_id: str = ""
    members: list[str] = field(default_factory=list)
    tier: str = "free"
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthConfig:
    secret: str = os.environ.get("JWT_SECRET", "")

    def __post_init__(self) -> None:
        if not self.secret:
            import logging as _lg
            _lg.getLogger("orchestra.auth").warning(
                "JWT_SECRET not set! Using an auto-generated volatile secret. "
                "Auth tokens will be invalidated on every restart. "
                "Set JWT_SECRET in your .env or environment."
            )
            self.secret = hashlib.sha256(os.urandom(64)).hexdigest()

    token_expiry_hours: int = 24
    enable_rate_limiting: bool = True
    rate_limit_per_minute: int = 60
    rate_limit_per_hour: int = 1000


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, per_minute: int = 60, per_hour: int = 1000) -> None:
        self._per_minute = per_minute
        self._per_hour = per_hour
        self._minute_buckets: dict[str, list[float]] = {}
        self._hour_buckets: dict[str, list[float]] = {}

    def check(self, user_id: str) -> tuple[bool, dict[str, Any]]:
        """Check if the user is within rate limits. Returns (allowed, info)."""
        now = time.time()

        # Minute window
        minute_key = user_id
        if minute_key not in self._minute_buckets:
            self._minute_buckets[minute_key] = []
        self._minute_buckets[minute_key] = [
            t for t in self._minute_buckets[minute_key] if now - t < 60
        ]
        if len(self._minute_buckets[minute_key]) >= self._per_minute:
            return False, {"error": "Rate limit exceeded (per minute)", "retry_after": 60}

        # Hour window
        if minute_key not in self._hour_buckets:
            self._hour_buckets[minute_key] = []
        self._hour_buckets[minute_key] = [
            t for t in self._hour_buckets[minute_key] if now - t < 3600
        ]
        if len(self._hour_buckets[minute_key]) >= self._per_hour:
            return False, {"error": "Rate limit exceeded (per hour)", "retry_after": 3600}

        # Record this request
        self._minute_buckets[minute_key].append(now)
        self._hour_buckets[minute_key].append(now)

        return True, {
            "remaining_minute": self._per_minute - len(self._minute_buckets[minute_key]),
            "remaining_hour": self._per_hour - len(self._hour_buckets[minute_key]),
        }


class AuthManager:
    """JWT-based authentication and authorization.

    Uses HMAC-SHA256 for token signing (swap to RS256 / PyJWT for production).
    """

    def __init__(self, config: AuthConfig | None = None) -> None:
        self.config = config or AuthConfig()
        self._users: dict[str, User] = {}
        self._orgs: dict[str, Org] = {}
        self._rate_limiter = RateLimiter(
            per_minute=self.config.rate_limit_per_minute,
            per_hour=self.config.rate_limit_per_hour,
        ) if self.config.enable_rate_limiting else None

    # -- user management ----------------------------------------------------

    def create_user(self, user_id: str, email: str = "", name: str = "",
                    org_id: str = "", role: str = "user", tier: str = "free") -> User:
        user = User(id=user_id, email=email, name=name, org_id=org_id, role=role, tier=tier)
        self._users[user_id] = user
        return user

    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    # -- org management -----------------------------------------------------

    def create_org(self, org_id: str, name: str, owner_id: str) -> Org:
        org = Org(id=org_id, name=name, owner_id=owner_id, members=[owner_id])
        self._orgs[org_id] = org
        return org

    def add_member(self, org_id: str, user_id: str) -> bool:
        org = self._orgs.get(org_id)
        if not org:
            return False
        if user_id not in org.members:
            org.members.append(user_id)
        return True

    # -- JWT tokens ---------------------------------------------------------

    def create_token(self, user_id: str, org_id: str = "", role: str = "user") -> str:
        """Create a JWT token."""
        now = time.time()
        payload = {
            "sub": user_id,
            "org": org_id,
            "role": role,
            "iat": int(now),
            "exp": int(now + self.config.token_expiry_hours * 3600),
        }
        return self._encode_jwt(payload)

    def verify_token(self, token: str) -> User | None:
        """Verify a JWT token and return the User."""
        payload = self._decode_jwt(token)
        if not payload:
            return None
        if payload.get("exp", 0) < time.time():
            log.warning("Token expired for user %s", payload.get("sub"))
            return None
        user_id = payload.get("sub", "")
        user = self._users.get(user_id)
        if not user:
            # Auto-create user from token
            user = User(
                id=user_id,
                org_id=payload.get("org", ""),
                role=payload.get("role", "user"),
            )
            self._users[user_id] = user
        return user

    def check_rate_limit(self, user: User) -> tuple[bool, dict[str, Any]]:
        """Check if a user is within rate limits."""
        if not self._rate_limiter:
            return True, {}
        # Enterprise users get 10x limits
        if user.tier == "enterprise":
            limiter = RateLimiter(
                per_minute=self.config.rate_limit_per_minute * 10,
                per_hour=self.config.rate_limit_per_hour * 10,
            )
            return limiter.check(user.id)
        return self._rate_limiter.check(user.id)

    # -- JWT encoding (simplified HMAC-SHA256) ------------------------------

    def _encode_jwt(self, payload: dict[str, Any]) -> str:
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        sig_input = f"{header}.{body}"
        sig = hmac.new(self.config.secret.encode(), sig_input.encode(), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        return f"{header}.{body}.{sig_b64}"

    def _decode_jwt(self, token: str) -> dict[str, Any] | None:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            header, body, sig = parts
            # Verify signature
            sig_input = f"{header}.{body}"
            expected = hmac.new(self.config.secret.encode(), sig_input.encode(), hashlib.sha256).digest()
            expected_b64 = base64.urlsafe_b64encode(expected).rstrip(b"=").decode()
            if not hmac.compare_digest(sig, expected_b64):
                return None
            # Decode payload (add padding)
            body_padded = body + "=" * (4 - len(body) % 4)
            return json.loads(base64.urlsafe_b64decode(body_padded))
        except Exception:
            return None

    # -- authorization checks -----------------------------------------------

    def check_permission(self, user: User, action: str, resource: str = "") -> bool:
        """Check if a user has permission for an action."""
        if user.role == "admin":
            return True

        # Org-level isolation
        if resource and resource.startswith("org:"):
            org_id = resource.split(":")[1]
            org = self._orgs.get(org_id)
            if org and user.id not in org.members:
                return False

        # Tier-based restrictions
        restricted_actions = {
            "free": {"deploy", "schedule_cron", "multi_model_council"},
            "pro": {"deploy_production"},
        }
        blocked = restricted_actions.get(user.tier, set())
        if action in blocked:
            return False

        return True
