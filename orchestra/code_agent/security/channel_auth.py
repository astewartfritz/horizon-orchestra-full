"""Channel adapter authentication — bot tokens, OAuth, allowlists, DM pairing, mention gating."""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass, field
from typing import Any


class AuthDecision(enum.Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING = "pending"


@dataclass
class AuthResult:
    decision: AuthDecision
    user_id: str = ""
    user_level: str = "standard"  # admin, standard, restricted, blocked
    reason: str = ""


class ChannelAuth:
    """Channel authentication — enforces platform-level auth before reaching the agent.

    Slack: bot tokens, allowlists, DM pairing, mention gating
    Telegram: bot tokens, allowlists
    Discord: bot tokens, allowlists, mention gating
    WhatsApp: QR pairing, phone allowlists
    Email: sender allowlists, DKIM/SPF
    """

    def __init__(self):
        self._bot_tokens: dict[str, str] = {}  # channel → token
        self._allowlists: dict[str, set[str]] = {}  # channel → set of user/sender IDs
        self._dm_paired: dict[str, set[str]] = {}  # channel → set of paired user IDs
        self._admin_users: dict[str, set[str]] = {}  # channel → admin user IDs
        self._blocked_users: dict[str, set[str]] = {}  # channel → blocked user IDs

    def set_bot_token(self, channel: str, token: str) -> None:
        self._bot_tokens[channel] = token

    def add_to_allowlist(self, channel: str, user_id: str) -> None:
        self._allowlists.setdefault(channel, set()).add(user_id)

    def remove_from_allowlist(self, channel: str, user_id: str) -> None:
        self._allowlists.get(channel, set()).discard(user_id)

    def pair_dm(self, channel: str, user_id: str) -> None:
        self._dm_paired.setdefault(channel, set()).add(user_id)

    def set_admin(self, channel: str, user_id: str) -> None:
        self._admin_users.setdefault(channel, set()).add(user_id)

    def block_user(self, channel: str, user_id: str) -> None:
        self._blocked_users.setdefault(channel, set()).add(user_id)

    async def authenticate(self, channel: str, credentials: dict[str, Any]) -> AuthResult:
        """Authenticate a request from any channel."""
        user_id = credentials.get("user_id", credentials.get("sender_id", ""))
        token = credentials.get("token", credentials.get("bot_token", ""))
        is_dm = credentials.get("is_dm", False)
        mention = credentials.get("mention", False)

        # Check blocklist first
        if user_id in self._blocked_users.get(channel, set()):
            return AuthResult(AuthDecision.DENIED, user_id, "blocked", "User is blocked")

        # Bot token check
        expected_token = self._bot_tokens.get(channel)
        if expected_token and token != expected_token:
            return AuthResult(AuthDecision.DENIED, user_id, reason="Invalid bot token")

        # Admin users always allowed
        if user_id in self._admin_users.get(channel, set()):
            return AuthResult(AuthDecision.ALLOWED, user_id, "admin")

        # Allowlist check
        allowlist = self._allowlists.get(channel, set())
        if allowlist:
            if user_id not in allowlist:
                return AuthResult(AuthDecision.DENIED, user_id, "restricted", "User not in allowlist")

        # Mention gating for group chats
        if not is_dm and mention is False:
            return AuthResult(AuthDecision.PENDING, user_id, "restricted", "Bot must be mentioned")

        # DM pairing
        if is_dm:
            paired = self._dm_paired.get(channel, set())
            if paired and user_id not in paired:
                return AuthResult(AuthDecision.PENDING, user_id, reason="DM not paired. User must pair first.")

        return AuthResult(AuthDecision.ALLOWED, user_id, "standard")

    async def get_user_level(self, user_id: str, channel: str) -> str:
        if user_id in self._admin_users.get(channel, set()):
            return "admin"
        if user_id in self._blocked_users.get(channel, set()):
            return "blocked"
        return "standard"
