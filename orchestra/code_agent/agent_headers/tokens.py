from __future__ import annotations

import json
import time
import hmac
import hashlib
import base64
import secrets
import logging
from typing import Any

from orchestra.code_agent.agent_headers.models import AgentRole, AgentTokenClaims, AgentType

__all__ = [
    "AgentTokenClaims",
    "AgentTokenManager",
    "parse_agent_token",
]

log = logging.getLogger("orchestra.agent_headers.tokens")

_TOKEN_HEADER = "X-Agent-Token"


def parse_agent_token(headers: dict[str, str]) -> str:
    return headers.get(_TOKEN_HEADER) or headers.get(_TOKEN_HEADER.lower(), "")


class AgentTokenManager:
    """Issues and verifies agent-specific tokens.

    Tokens confirm requests originate from verified AI agents,
    carrying claims about the agent's identity, role, and
    permissions.  Uses HMAC-SHA256 for integrity.
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret or secrets.token_hex(32)

    def issue_token(self, claims: AgentTokenClaims) -> str:
        payload = {
            "agent_id": claims.agent_id,
            "agent_role": claims.agent_role.value,
            "agent_type": claims.agent_type.value,
            "issued_at": claims.issued_at,
            "expires_at": claims.expires_at,
            "permissions": claims.permissions,
            "owner_id": claims.owner_id,
            "purpose": claims.purpose,
        }
        body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
        sig = self._sign(body)
        return f"{body}.{sig}"

    def verify_token(self, token: str) -> AgentTokenClaims | None:
        try:
            parts = token.split(".")
            if len(parts) != 2:
                return None
            body, sig = parts
            expected = self._sign(body)
            if not hmac.compare_digest(sig, expected):
                return None
            payload = json.loads(base64.urlsafe_b64decode(body.encode()))
            if time.time() > payload.get("expires_at", 0):
                return None
            return AgentTokenClaims(
                agent_id=payload["agent_id"],
                agent_role=AgentRole(payload.get("agent_role", "system")),
                agent_type=AgentType(payload.get("agent_type", "ai")),
                issued_at=payload.get("issued_at", 0.0),
                expires_at=payload.get("expires_at", 0.0),
                permissions=payload.get("permissions", ["read"]),
                owner_id=payload.get("owner_id", ""),
                purpose=payload.get("purpose", ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError, Exception) as exc:
            log.warning("Agent token verification failed: %s", exc)
            return None

    def _sign(self, body: str) -> str:
        return hmac.new(
            self._secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()
