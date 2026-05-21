"""Capability-based dynamic authentication for agentic access control.

Solves the problem: traditional token-based or role-based systems fail to adapt
when agents dynamically request access to sensitive operations.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Capability",
    "AgentIdentity",
    "CapabilityToken",
    "CapabilityVault",
    "DynamicAuthPolicy",
    "JustInTimeGrant",
    "GrantEntry",
    "GrantRequest",
]

log = logging.getLogger("orchestra.capability_auth")

_HAS_JWT = False
try:
    from orchestra.code_agent.auth.jwt import JWTManager  # noqa: F401
    _HAS_JWT = True
except ImportError:
    pass

_SECRET: str = os.environ.get("CAPABILITY_SECRET", hashlib.sha256(os.urandom(64)).hexdigest())


# ── Capability ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Capability:
    name: str
    resource: str
    action: str
    context: dict = field(default_factory=dict)

    def matches(self, other: Capability) -> bool:
        if self.action != other.action:
            return False
        return _resource_matches(self.resource, other.resource)

    def __hash__(self) -> int:
        return hash((self.name, self.resource, self.action))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Capability):
            return NotImplemented
        return (
            self.name == other.name
            and self.resource == other.resource
            and self.action == other.action
        )


def _resource_matches(pattern: str, target: str) -> bool:
    if pattern == target:
        return True
    if pattern.endswith("/*"):
        prefix = pattern[:-2]
        if target.startswith(prefix):
            return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        if target.startswith(prefix):
            return True
    return False


# ── AgentIdentity ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    owner_id: str
    purpose: str
    trust_level: int = 3

    def __post_init__(self) -> None:
        if self.trust_level < 1 or self.trust_level > 5:
            raise ValueError(f"trust_level must be 1-5, got {self.trust_level}")


# ── In-memory grant tracking ──────────────────────────────────────────


@dataclass
class GrantEntry:
    grant_id: str
    capability: Capability
    agent_id: str
    expires_at: float
    revoked: bool = False


@dataclass
class GrantRequest:
    request_id: str
    agent: AgentIdentity
    capability: Capability
    justification: str
    status: str = "pending"  # pending | approved | denied
    created_at: float = field(default_factory=time.time)


# ── CapabilityToken ───────────────────────────────────────────────────


class CapabilityToken:
    """Signed JWT containing capabilities and expiry.

    Delegates to ``JWTManager`` when available; falls back to bare HMAC.
    """

    _jwt_manager: Any = None

    @classmethod
    def create(
        cls,
        agent: AgentIdentity,
        capabilities: list[Capability],
        ttl: int = 3600,
    ) -> str:
        payload: dict[str, Any] = {
            "sub": agent.agent_id,
            "owner": agent.owner_id,
            "purpose": agent.purpose,
            "trust_level": agent.trust_level,
            "caps": [
                {"name": c.name, "resource": c.resource, "action": c.action, "context": c.context}
                for c in capabilities
            ],
            "iat": int(time.time()),
            "exp": int(time.time() + ttl),
            "jti": str(uuid.uuid4()),
        }
        if _HAS_JWT:
            return cls._get_jwt_manager().create_access_token(  # type: ignore[union-attr]
                agent.agent_id, "capability", tier="agent", expires_in=ttl,
            )
        return cls._encode_hmac(payload)

    @classmethod
    def verify(cls, token: str) -> AgentIdentity | None:
        if _HAS_JWT:
            payload = cls._get_jwt_manager().verify(token)
            if payload is None:
                return None
        else:
            try:
                payload = cls._decode_hmac(token)
            except Exception:
                log.debug("CapabilityToken HMAC decode failed", exc_info=True)
                return None
        if payload.get("exp", 0) < time.time():
            log.warning("CapabilityToken expired for agent %s", payload.get("sub"))
            return None
        try:
            return AgentIdentity(
                agent_id=payload["sub"],
                owner_id=payload.get("owner", ""),
                purpose=payload.get("purpose", ""),
                trust_level=payload.get("trust_level", 3),
            )
        except (KeyError, ValueError):
            return None

    # ── internal helpers ──────────────────────────────────────────────

    @classmethod
    def _get_jwt_manager(cls) -> Any:
        if cls._jwt_manager is None:
            cls._jwt_manager = JWTManager(secret=_SECRET)
        return cls._jwt_manager

    @classmethod
    def _encode_hmac(cls, payload: dict[str, Any]) -> str:
        import base64
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "CAP"}).encode()
        ).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).rstrip(b"=").decode()
        sig_input = f"{header}.{body}"
        sig = hmac.new(
            _SECRET.encode(), sig_input.encode(), hashlib.sha256,
        ).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        return f"{header}.{body}.{sig_b64}"

    @classmethod
    def _decode_hmac(cls, token: str) -> dict[str, Any]:
        import base64
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed capability token")
        _header, body, sig = parts
        sig_input = f"{_header}.{body}"
        expected = hmac.new(
            _SECRET.encode(), sig_input.encode(), hashlib.sha256,
        ).digest()
        expected_b64 = base64.urlsafe_b64encode(expected).rstrip(b"=").decode()
        if not hmac.compare_digest(sig, expected_b64):
            raise ValueError("Invalid capability token signature")
        padded = body + "=" * (4 - len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))


# ── CapabilityVault ───────────────────────────────────────────────────


class CapabilityVault:
    """Stores granted capabilities with expiry.

    Production deployments should swap the in-memory dict for Redis.
    """

    def __init__(self) -> None:
        self._grants: dict[str, GrantEntry] = {}
        self._agent_grants: dict[str, set[str]] = {}

    def grant(self, capability: Capability, agent_id: str, ttl: int = 3600) -> str:
        grant_id = str(uuid.uuid4())
        entry = GrantEntry(
            grant_id=grant_id,
            capability=capability,
            agent_id=agent_id,
            expires_at=time.time() + ttl,
        )
        self._grants[grant_id] = entry
        self._agent_grants.setdefault(agent_id, set()).add(grant_id)
        return grant_id

    def revoke(self, grant_id: str) -> bool:
        entry = self._grants.get(grant_id)
        if entry is None:
            return False
        entry.revoked = True
        return True

    def check(self, agent_id: str, required: Capability) -> bool:
        self._sweep_expired()
        for gid in list(self._agent_grants.get(agent_id, set())):
            entry = self._grants.get(gid)
            if entry is None or entry.revoked:
                continue
            if entry.capability.matches(required):
                return True
        return False

    def list_grants(self, agent_id: str) -> list[str]:
        self._sweep_expired()
        return list(self._agent_grants.get(agent_id, set()))

    def _sweep_expired(self) -> None:
        now = time.time()
        expired = [gid for gid, e in self._grants.items() if e.expires_at < now]
        for gid in expired:
            entry = self._grants.pop(gid, None)
            if entry:
                self._agent_grants.get(entry.agent_id, set()).discard(gid)


# ── DynamicAuthPolicy ─────────────────────────────────────────────────


class DynamicAuthPolicy:
    """Defines what operations require what capabilities."""

    def __init__(self, vault: CapabilityVault | None = None) -> None:
        self._vault = vault or CapabilityVault()
        self._policy: dict[str, list[Capability]] = {}

    def register(self, action: str, required_capabilities: list[Capability]) -> None:
        self._policy[action] = required_capabilities

    def check_access(
        self,
        agent: AgentIdentity,
        action: str,
        resource: str,
        context: dict | None = None,
    ) -> bool:
        required_list = self._policy.get(action)
        if required_list is None:
            log.warning("Access check for unregistered action '%s' — denying", action)
            return False
        required_ctx = context or {}
        for rc in required_list:
            candidate = Capability(
                name=rc.name,
                resource=resource,
                action=rc.action,
                context=required_ctx,
            )
            if not self._vault.check(agent.agent_id, candidate):
                log.debug(
                    "Agent %s lacks capability %s for action %s on %s",
                    agent.agent_id, rc.name, action, resource,
                )
                return False
        return True


# ── JustInTimeGrant ───────────────────────────────────────────────────


class JustInTimeGrant:
    """Human-in-the-loop grant approval for sensitive capabilities."""

    def __init__(self, vault: CapabilityVault | None = None) -> None:
        self._vault = vault or CapabilityVault()
        self._requests: dict[str, GrantRequest] = {}

    def request_grant(
        self,
        agent: AgentIdentity,
        capability: Capability,
        justification: str,
    ) -> str | None:
        request_id = str(uuid.uuid4())
        req = GrantRequest(
            request_id=request_id,
            agent=agent,
            capability=capability,
            justification=justification,
        )
        self._requests[request_id] = req
        log.info(
            "JIT grant requested: agent=%s cap=%s/%s/%s reason=%s rid=%s",
            agent.agent_id, capability.name, capability.resource,
            capability.action, justification, request_id,
        )
        return request_id

    def approve_grant(self, grant_request_id: str, ttl: int = 3600) -> bool:
        req = self._requests.get(grant_request_id)
        if req is None or req.status != "pending":
            return False
        self._vault.grant(req.capability, req.agent.agent_id, ttl=ttl)
        req.status = "approved"
        log.info("JIT grant approved: rid=%s", grant_request_id)
        return True

    def deny_grant(self, grant_request_id: str) -> bool:
        req = self._requests.get(grant_request_id)
        if req is None or req.status != "pending":
            return False
        req.status = "denied"
        log.info("JIT grant denied: rid=%s", grant_request_id)
        return True

    def pending_requests(self) -> list[GrantRequest]:
        return [r for r in self._requests.values() if r.status == "pending"]
