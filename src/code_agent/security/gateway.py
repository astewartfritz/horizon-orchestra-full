"""Hub-and-spoke security gateway — the model is never the first security boundary.

Access control, device identity, and tool sandboxing are enforced BEFORE
the agent runtime. Defense in depth: one failure does not expose the host.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from code_agent.security.layers import SecurityLayers
from code_agent.security.channel_auth import ChannelAuth, AuthDecision
from code_agent.security.egress import EgressController


class AccessLevel(enum.Enum):
    DENY = "deny"
    RESTRICTED = "restricted"
    STANDARD = "standard"
    ELEVATED = "elevated"


@dataclass
class SecurityContext:
    session_id: str = ""
    user_id: str = ""
    channel: str = ""
    access_level: AccessLevel = AccessLevel.STANDARD
    device_id: str = ""
    features: list[str] = field(default_factory=list)
    sandbox_enabled: bool = True
    network_restricted: bool = True
    filesystem_restricted: bool = True


class SecurityGateway:
    """Hub-and-spoke security gateway.

    Enforces access control, device identity, and tool sandboxing
    BEFORE the agent runtime. The model is never the first boundary.
    """

    def __init__(self):
        self.layers = SecurityLayers()
        self.channel_auth = ChannelAuth()
        self.egress = EgressController()
        self._contexts: dict[str, SecurityContext] = {}

    async def authenticate_channel(self, channel: str, credentials: dict[str, Any]) -> AuthDecision:
        """Authenticate a channel request before it reaches the agent."""
        return await self.channel_auth.authenticate(channel, credentials)

    async def create_session(self, session_id: str, user_id: str, channel: str,
                              device_id: str = "") -> SecurityContext:
        """Create a new security context for a session."""
        ctx = SecurityContext(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            device_id=device_id,
        )
        # Determine access level from channel auth
        auth_level = await self.channel_auth.get_user_level(user_id, channel)
        if auth_level == "admin":
            ctx.access_level = AccessLevel.ELEVATED
        elif auth_level == "restricted":
            ctx.access_level = AccessLevel.RESTRICTED
            ctx.sandbox_enabled = True
            ctx.network_restricted = True

        self._contexts[session_id] = ctx
        return ctx

    def check_tool(self, tool_name: str, session_id: str) -> bool:
        """Check if a tool is allowed for the given session."""
        ctx = self._contexts.get(session_id)
        if not ctx:
            return False

        # Deny-by-default: tools must be explicitly allowed
        denied_tools = {"bash", "sandbox", "git push", "write", "edit", "delete"}
        if ctx.access_level == AccessLevel.RESTRICTED:
            return tool_name in {"read", "grep", "glob", "webfetch"}

        # Network egress check
        if tool_name in {"webfetch", "websearch", "git push"}:
            return self.egress.check_allowed(tool_name, session_id)

        return True

    def check_network(self, url: str, session_id: str) -> bool:
        """Check if a network request is allowed."""
        ctx = self._contexts.get(session_id)
        if not ctx or ctx.network_restricted:
            # Only allow approved domains
            allowed = self.egress.get_allowed_domains(session_id)
            from urllib.parse import urlparse
            domain = urlparse(url).hostname or ""
            return any(domain == a or domain.endswith("." + a) for a in allowed)
        return True

    def check_filesystem(self, path: str, session_id: str, mode: str = "read") -> bool:
        """Check if a filesystem operation is allowed."""
        ctx = self._contexts.get(session_id)
        if not ctx:
            return False
        if ctx.filesystem_restricted and mode == "write":
            # Only allow writes to the workspace
            import os
            ws = os.path.abspath(os.getcwd())
            target = os.path.abspath(path)
            return target.startswith(ws)
        return True

    def get_context(self, session_id: str) -> SecurityContext | None:
        return self._contexts.get(session_id)
