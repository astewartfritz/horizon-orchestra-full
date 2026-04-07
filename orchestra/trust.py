"""Horizon Orchestra — Trust Boundary & Secret Management.

Implements a Codex-inspired sandboxed execution model with three distinct
phases, per-phase network policies, encrypted secret storage, and an audit
trail of all permission checks and trust elevations.

Phase model::

    SETUP   → Network ON.  Secrets accessible.  Dependencies installable.
               Intended for: cloning repos, installing packages, reading config.

    AGENT   → Network OFF by default (unless trust ≥ ELEVATED).
               Secrets stripped.  LLM-driven actions execute here.
               Intended for: running generated code, file manipulation.

    CLEANUP → Restricted access.  Temp files wiped.  Audit trail finalised.
               Intended for: persisting results, revoking credentials.

Trust levels (ascending privilege)::

    RESTRICTED → Read-only file access, no network, no shell.
    STANDARD   → Read/write files, no network, safe shell commands.
    ELEVATED   → Standard + network access in AGENT phase, elevated shell.
    ADMIN      → All permissions.  Requires explicit justification and logging.

Usage::

    from orchestra.trust import TrustBoundary, TrustLevel, PermissionGate

    trust = TrustBoundary(trust_level=TrustLevel.STANDARD)
    trust.secrets.add("OPENAI_API_KEY", "sk-...")

    await trust.enter_setup_phase()
    # ... install dependencies, read config ...

    await trust.enter_agent_phase()
    # secrets are now stripped; network is off
    allowed = trust.check_permission("write_file")

    gate = PermissionGate()
    ok = await gate.check_and_confirm("delete_file", {"path": "/tmp/x"}, trust)
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from cryptography.fernet import Fernet  # type: ignore
    _HAS_FERNET = True
except ImportError:
    _HAS_FERNET = False

__all__ = [
    "TrustLevel",
    "SecretStore",
    "NetworkPolicy",
    "ExecutionPhase",
    "TrustBoundary",
    "PermissionGate",
]

log = logging.getLogger("orchestra.trust")

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TrustLevel(str, Enum):
    """Privilege tiers for the trust boundary.

    Higher trust levels grant more permissions:
    RESTRICTED < STANDARD < ELEVATED < ADMIN
    """

    RESTRICTED = "restricted"
    STANDARD = "standard"
    ELEVATED = "elevated"
    ADMIN = "admin"


_TRUST_RANK: dict[TrustLevel, int] = {
    TrustLevel.RESTRICTED: 0,
    TrustLevel.STANDARD: 1,
    TrustLevel.ELEVATED: 2,
    TrustLevel.ADMIN: 3,
}


class ExecutionPhase(str, Enum):
    """Lifecycle phases of a sandboxed execution run.

    Each phase has a distinct permission profile enforced by
    :class:`TrustBoundary`.
    """

    SETUP = "setup"
    AGENT = "agent"
    CLEANUP = "cleanup"


# ---------------------------------------------------------------------------
# SecretStore
# ---------------------------------------------------------------------------


class SecretStore:
    """Encrypted in-memory secret vault with scope-based lifecycle management.

    Secrets are stored symmetrically encrypted using Fernet (AES-128-CBC with
    HMAC-SHA256) when the ``cryptography`` package is available, or obfuscated
    with a simple XOR + base64 fallback otherwise.

    Secrets scoped to ``"session"`` are wiped by :meth:`clear_session`.
    Secrets scoped to ``"persistent"`` survive session resets.

    Args:
        key: Optional Fernet key bytes.  If ``None``, a new key is generated.

    Example::

        store = SecretStore()
        store.add("DB_PASSWORD", "hunter2")
        pw = store.get("DB_PASSWORD")   # "hunter2"
        store.clear_session()
        store.get("DB_PASSWORD")        # None
    """

    def __init__(self, key: bytes | None = None) -> None:
        if _HAS_FERNET:
            self._key: bytes = key or Fernet.generate_key()
            self._fernet = Fernet(self._key)
        else:
            # XOR obfuscation fallback (not cryptographically secure, but better
            # than plaintext — suitable when cryptography is not installed)
            self._xor_key: bytes = key or secrets.token_bytes(32)
        # Internal store: name → (ciphertext, scope)
        self._store: dict[str, tuple[str, str]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, name: str, value: str, scope: str = "session") -> None:
        """Store a secret under *name* with optional lifecycle scope.

        Args:
            name: Unique identifier for the secret (e.g. ``"OPENAI_API_KEY"``).
            value: Plaintext secret value.
            scope: ``"session"`` (default, wiped by :meth:`clear_session`) or
                ``"persistent"`` (survives session resets).
        """
        if scope not in ("session", "persistent"):
            raise ValueError(f"scope must be 'session' or 'persistent', got {scope!r}")
        cipher = self._encrypt(value)
        self._store[name] = (cipher, scope)
        log.debug("SecretStore.add: name=%r scope=%s", name, scope)

    def get(self, name: str) -> str | None:
        """Retrieve a plaintext secret by name.

        Args:
            name: Secret identifier.

        Returns:
            Plaintext value, or ``None`` if the secret does not exist.
        """
        entry = self._store.get(name)
        if entry is None:
            return None
        cipher, _scope = entry
        try:
            return self._decrypt(cipher)
        except Exception as exc:
            log.error("SecretStore.get: decryption failed for %r: %s", name, exc)
            return None

    def delete(self, name: str) -> bool:
        """Remove a secret from the store.

        Args:
            name: Secret identifier.

        Returns:
            ``True`` if the secret existed and was removed; ``False`` otherwise.
        """
        if name in self._store:
            del self._store[name]
            log.debug("SecretStore.delete: %r removed", name)
            return True
        return False

    def list_names(self) -> list[str]:
        """Return names of all stored secrets (never their values).

        Returns:
            Sorted list of secret names.
        """
        return sorted(self._store.keys())

    def clear_session(self) -> int:
        """Wipe all session-scoped secrets from memory.

        Returns:
            Number of secrets removed.
        """
        to_delete = [k for k, (_, scope) in self._store.items() if scope == "session"]
        for key in to_delete:
            del self._store[key]
        log.info("SecretStore.clear_session: removed %d session secrets", len(to_delete))
        return len(to_delete)

    def inject_into_env(self) -> None:
        """Inject all secrets into ``os.environ`` for subprocess access.

        Should only be called during the SETUP phase when secrets are available.
        Persistent secrets remain; session secrets are injected transiently.
        """
        for name in self._store:
            value = self.get(name)
            if value is not None:
                os.environ[name] = value
                log.debug("Injected secret into env: %r", name)

    def strip_from_env(self) -> None:
        """Remove injected secrets from ``os.environ``.

        Call during the AGENT phase to prevent the LLM from reading secrets via
        environment variable enumeration.
        """
        for name in list(self._store.keys()):
            if name in os.environ:
                del os.environ[name]
                log.debug("Stripped secret from env: %r", name)

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def _encrypt(self, value: str) -> str:
        """Encrypt a plaintext string using Fernet (or XOR fallback).

        Args:
            value: Plaintext to encrypt.

        Returns:
            Ciphertext as a string (URL-safe base64 for Fernet, or hex for XOR).
        """
        data = value.encode()
        if _HAS_FERNET:
            return self._fernet.encrypt(data).decode("ascii")
        # XOR + hex fallback
        key = self._xor_key
        xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return xored.hex()

    def _decrypt(self, cipher: str) -> str:
        """Decrypt a ciphertext string.

        Args:
            cipher: Previously encrypted value from :meth:`_encrypt`.

        Returns:
            Original plaintext string.

        Raises:
            Exception: If decryption fails (wrong key, corrupted data, etc.).
        """
        if _HAS_FERNET:
            return self._fernet.decrypt(cipher.encode("ascii")).decode()
        # XOR fallback
        key = self._xor_key
        xored = bytes.fromhex(cipher)
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(xored)).decode()


# ---------------------------------------------------------------------------
# NetworkPolicy
# ---------------------------------------------------------------------------


@dataclass
class NetworkPolicy:
    """Describes the network access rules for a given execution phase.

    Attributes:
        allowed_domains: Whitelist of domain suffixes (e.g. ``["pypi.org",
            "github.com"]``).  Enforced at the application level only —
            kernel-level enforcement requires additional tooling (nftables, etc.)
        blocked_domains: Explicit denylist, takes precedence over
            ``allowed_domains``.
        allow_all: If ``True``, all domains are permitted (equivalent to
            unrestricted internet access).  Should only be ``True`` during
            SETUP with ELEVATED or higher trust.
        phase: The :class:`ExecutionPhase` this policy applies to.  Informational
            only; ``TrustBoundary`` selects the appropriate policy per phase.
    """

    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)
    allow_all: bool = False
    phase: str = "agent"

    def is_allowed(self, domain: str) -> bool:
        """Check whether a given domain is permitted by this policy.

        Args:
            domain: Hostname to check (e.g. ``"api.openai.com"``).

        Returns:
            ``True`` if network access to *domain* is allowed.
        """
        if self.allow_all:
            # Blocked list still takes precedence
            return not any(domain.endswith(blocked) for blocked in self.blocked_domains)
        # Check explicit allow list
        for allowed in self.allowed_domains:
            if domain.endswith(allowed):
                # Confirm not blocked
                if not any(domain.endswith(bl) for bl in self.blocked_domains):
                    return True
        return False


# ---------------------------------------------------------------------------
# Permission tables
# ---------------------------------------------------------------------------

# Actions that are always allowed regardless of phase or trust level
SAFE_ACTIONS: frozenset[str] = frozenset(
    {
        "read_file",
        "list_directory",
        "get_env",
        "log_message",
        "check_permission",
        "get_audit_trail",
        "list_secret_names",
    }
)

# Actions that require user confirmation (shown to operator before proceeding)
CONFIRM_ACTIONS: frozenset[str] = frozenset(
    {
        "write_file",
        "delete_file",
        "run_shell",
        "install_package",
        "send_http_request",
        "send_email",
        "post_message",
        "modify_database",
        "grant_permission",
        "create_process",
        "upload_file",
        "access_secret",
    }
)

# Actions that are always blocked regardless of trust level (require code change
# to add an explicit exception)
BLOCKED_ACTIONS: frozenset[str] = frozenset(
    {
        "disable_audit_log",
        "wipe_audit_trail",
        "escalate_to_root",
        "disable_network_policy",
        "export_all_secrets",
        "impersonate_user",
    }
)

# Per-phase allowed action sets (cumulative with safe actions)
_PHASE_ACTIONS: dict[ExecutionPhase, set[str]] = {
    ExecutionPhase.SETUP: {
        "write_file",
        "install_package",
        "run_shell",
        "send_http_request",
        "access_secret",
    },
    ExecutionPhase.AGENT: {
        "write_file",
        "run_shell",
        "create_process",
        # network access added when trust >= ELEVATED
    },
    ExecutionPhase.CLEANUP: {
        "write_file",
        "delete_file",
    },
}

# Additional actions unlocked by trust level
_TRUST_EXTRA_ACTIONS: dict[TrustLevel, set[str]] = {
    TrustLevel.RESTRICTED: set(),
    TrustLevel.STANDARD: {"run_shell", "write_file", "create_process"},
    TrustLevel.ELEVATED: {"send_http_request", "install_package", "upload_file"},
    TrustLevel.ADMIN: set(CONFIRM_ACTIONS),  # all confirm actions
}


# ---------------------------------------------------------------------------
# TrustBoundary
# ---------------------------------------------------------------------------


class TrustBoundary:
    """Manages sandboxed execution phases, secrets, network policy, and audit.

    This class is the central gatekeeper for all privileged operations within
    Orchestra.  It transitions through :class:`ExecutionPhase` states and
    enforces access control accordingly.

    Args:
        trust_level: Initial trust level.  Defaults to ``STANDARD``.
        network_setup: Network policy override for the SETUP phase.
        network_agent: Network policy override for the AGENT phase.

    Example::

        boundary = TrustBoundary(trust_level=TrustLevel.STANDARD)
        boundary.secrets.add("API_KEY", os.environ.get("API_KEY", ""))

        await boundary.enter_setup_phase()
        # install packages, read config — secrets available, network on

        await boundary.enter_agent_phase()
        # LLM acts here — secrets stripped, network off (unless ELEVATED)

        await boundary.enter_cleanup_phase()
        # persist results, finalise audit trail

        trail = boundary.get_audit_trail()
    """

    def __init__(
        self,
        trust_level: TrustLevel = TrustLevel.STANDARD,
        network_setup: NetworkPolicy | None = None,
        network_agent: NetworkPolicy | None = None,
    ) -> None:
        self.trust_level: TrustLevel = trust_level
        self.current_phase: ExecutionPhase = ExecutionPhase.SETUP
        self.secrets: SecretStore = SecretStore()
        self.network: NetworkPolicy = network_agent or NetworkPolicy(
            allow_all=False,
            phase="agent",
        )
        self._network_setup: NetworkPolicy = network_setup or NetworkPolicy(
            allow_all=True,
            phase="setup",
            blocked_domains=["malicious.example.com"],
        )
        self.audit_log: list[dict[str, Any]] = []
        self._boundary_id: str = str(uuid.uuid4())[:8]
        log.info(
            "TrustBoundary[%s] created: level=%s",
            self._boundary_id,
            trust_level.value,
        )

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    async def enter_setup_phase(self) -> None:
        """Transition to the SETUP phase.

        Network access is enabled (respecting ``_network_setup`` policy).
        Secrets are accessible and can be injected into ``os.environ``.
        Dependencies may be installed.

        This method is idempotent if already in SETUP phase.
        """
        self.current_phase = ExecutionPhase.SETUP
        self.network = self._network_setup
        self._audit("phase_transition", {"to": "SETUP"}, allowed=True)
        log.info("[%s] Entered SETUP phase — network ON, secrets available", self._boundary_id)

    async def enter_agent_phase(self) -> None:
        """Transition to the AGENT phase.

        Network access is disabled by default; ELEVATED or higher trust keeps
        it on but restricted to ``allowed_domains``.
        Session-scoped secrets are stripped from ``os.environ``.
        """
        self.current_phase = ExecutionPhase.AGENT

        rank = _TRUST_RANK[self.trust_level]
        if rank >= _TRUST_RANK[TrustLevel.ELEVATED]:
            # ELEVATED agents may use network with restricted domains
            self.network = NetworkPolicy(
                allowed_domains=["api.openai.com", "openrouter.ai", "api.moonshot.ai",
                                  "api.perplexity.ai"],
                blocked_domains=[],
                allow_all=False,
                phase="agent",
            )
            log.info("[%s] ELEVATED AGENT phase — restricted network ON", self._boundary_id)
        else:
            # Standard: no network
            self.network = NetworkPolicy(allow_all=False, phase="agent")
            log.info("[%s] AGENT phase — network OFF, secrets stripped", self._boundary_id)

        # Strip secrets from environment
        self.secrets.strip_from_env()
        self._audit("phase_transition", {"to": "AGENT"}, allowed=True)

    async def enter_cleanup_phase(self) -> None:
        """Transition to the CLEANUP phase.

        Restricted access: only write_file and delete_file are allowed.
        Network is disabled.  Remaining session secrets are wiped.
        """
        self.current_phase = ExecutionPhase.CLEANUP
        self.network = NetworkPolicy(allow_all=False, phase="cleanup")
        cleared = self.secrets.clear_session()
        self._audit(
            "phase_transition",
            {"to": "CLEANUP", "secrets_cleared": cleared},
            allowed=True,
        )
        log.info(
            "[%s] CLEANUP phase — restricted access, %d secrets cleared",
            self._boundary_id,
            cleared,
        )

    # ------------------------------------------------------------------
    # Permission checking
    # ------------------------------------------------------------------

    def check_permission(self, action: str) -> bool:
        """Determine whether *action* is permitted in the current phase/level.

        Always-blocked actions return ``False``.  Always-safe actions return
        ``True``.  All other actions are checked against the current phase
        and trust level.

        Args:
            action: Action identifier string, e.g. ``"write_file"``,
                ``"send_http_request"``.

        Returns:
            ``True`` if the action is permitted; ``False`` otherwise.
        """
        if action in BLOCKED_ACTIONS:
            self._audit("check_permission", {"action": action}, allowed=False,
                        reason="BLOCKED_ACTION")
            log.warning("[%s] BLOCKED action attempted: %s", self._boundary_id, action)
            return False

        if action in SAFE_ACTIONS:
            self._audit("check_permission", {"action": action}, allowed=True, reason="SAFE")
            return True

        # Phase-based check
        phase_allowed = _PHASE_ACTIONS.get(self.current_phase, set())
        # Trust-based extras
        rank = _TRUST_RANK[self.trust_level]
        trust_extras: set[str] = set()
        for level, extras in _TRUST_EXTRA_ACTIONS.items():
            if _TRUST_RANK[level] <= rank:
                trust_extras |= extras

        allowed = action in (phase_allowed | trust_extras)
        self._audit(
            "check_permission",
            {"action": action, "phase": self.current_phase.value, "trust": self.trust_level.value},
            allowed=allowed,
            reason="PHASE+TRUST" if allowed else "DENIED",
        )
        if not allowed:
            log.info(
                "[%s] Permission DENIED: %s (phase=%s, trust=%s)",
                self._boundary_id,
                action,
                self.current_phase.value,
                self.trust_level.value,
            )
        return allowed

    # ------------------------------------------------------------------
    # Trust elevation
    # ------------------------------------------------------------------

    async def request_elevation(self, reason: str) -> bool:
        """Request an increase in trust level.

        In production this would prompt the operator; here it logs the request
        and auto-approves one level of elevation for STANDARD → ELEVATED.
        ELEVATED → ADMIN always requires manual approval (returns ``False``).

        Args:
            reason: Human-readable justification for the elevation request.

        Returns:
            ``True`` if elevation was granted; ``False`` otherwise.
        """
        current_rank = _TRUST_RANK[self.trust_level]
        log.warning(
            "[%s] Trust elevation requested: current=%s reason=%r",
            self._boundary_id,
            self.trust_level.value,
            reason[:200],
        )

        if self.trust_level == TrustLevel.RESTRICTED:
            new_level = TrustLevel.STANDARD
            granted = True
        elif self.trust_level == TrustLevel.STANDARD:
            new_level = TrustLevel.ELEVATED
            granted = True  # auto-approve one level
        else:
            # ELEVATED → ADMIN requires out-of-band human approval
            new_level = TrustLevel.ADMIN
            granted = False

        self._audit(
            "request_elevation",
            {
                "from": self.trust_level.value,
                "to": new_level.value,
                "reason": reason,
                "granted": granted,
            },
            allowed=granted,
            reason="AUTO_APPROVE" if granted else "MANUAL_REQUIRED",
        )

        if granted:
            self.trust_level = new_level
            log.info(
                "[%s] Trust elevated: %s → %s",
                self._boundary_id,
                self.trust_level.value,
                new_level.value,
            )

        return granted

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def get_audit_trail(self) -> list[dict[str, Any]]:
        """Return an immutable copy of the full audit log.

        Each entry is a dict with keys:
        ``timestamp``, ``event``, ``params``, ``allowed``, ``reason``.

        Returns:
            List of audit event dicts (oldest first).
        """
        return list(self.audit_log)

    def _audit(
        self,
        event: str,
        params: dict[str, Any],
        *,
        allowed: bool,
        reason: str = "",
    ) -> None:
        """Append an entry to the audit log.

        Args:
            event: Event type string (e.g. ``"check_permission"``).
            params: Contextual parameters for the event.
            allowed: Whether the action was permitted.
            reason: Short reason string for the decision.
        """
        entry: dict[str, Any] = {
            "timestamp": time.time(),
            "boundary_id": self._boundary_id,
            "event": event,
            "params": params,
            "allowed": allowed,
            "reason": reason,
            "phase": self.current_phase.value,
            "trust": self.trust_level.value,
        }
        self.audit_log.append(entry)


# ---------------------------------------------------------------------------
# PermissionGate
# ---------------------------------------------------------------------------


class PermissionGate:
    """Interactive permission gate for dangerous actions.

    Wraps :meth:`TrustBoundary.check_permission` with an additional user
    confirmation step for actions in :data:`CONFIRM_ACTIONS`.  In production
    this would surface a UI prompt; the default implementation logs the
    confirmation request and simulates approval via a configurable policy.

    Args:
        auto_confirm: If ``True``, CONFIRM_ACTIONS are automatically approved
            without operator interaction (useful for fully-automated pipelines).
        confirm_callback: Optional async callable that receives the action and
            params dict and returns a bool.  If ``None``, falls back to
            ``auto_confirm``.

    Example::

        gate = PermissionGate(auto_confirm=False)
        ok = await gate.check_and_confirm("delete_file", {"path": "/tmp/x"}, trust)
        if ok:
            os.remove("/tmp/x")
    """

    def __init__(
        self,
        auto_confirm: bool = True,
        confirm_callback: Any = None,
    ) -> None:
        self.auto_confirm = auto_confirm
        self._confirm_callback = confirm_callback
        self._pending_confirmations: list[dict[str, Any]] = []

    async def check_and_confirm(
        self,
        action: str,
        params: dict[str, Any],
        trust: TrustBoundary,
    ) -> bool:
        """Check permissions and optionally prompt for confirmation.

        Decision flow:
        1. If action is in ``BLOCKED_ACTIONS`` → deny immediately.
        2. If action is in ``SAFE_ACTIONS`` → allow immediately.
        3. Call :meth:`TrustBoundary.check_permission`.  If denied → return False.
        4. If action is in ``CONFIRM_ACTIONS`` → request confirmation.
        5. Return final decision.

        Args:
            action: Action identifier (e.g. ``"delete_file"``).
            params: Action parameters (e.g. ``{"path": "/tmp/x"}``).
            trust: The :class:`TrustBoundary` governing this execution context.

        Returns:
            ``True`` if the action may proceed; ``False`` otherwise.
        """
        # Hard block
        if action in BLOCKED_ACTIONS:
            log.error("PermissionGate: BLOCKED action '%s' attempted", action)
            return False

        # Safe pass-through
        if action in SAFE_ACTIONS:
            return True

        # Phase/trust check
        if not trust.check_permission(action):
            return False

        # Confirmation step for sensitive actions
        if action in CONFIRM_ACTIONS:
            confirmed = await self._request_confirmation(action, params)
            log.info(
                "PermissionGate: %s(%s) → %s",
                action,
                params,
                "APPROVED" if confirmed else "DENIED",
            )
            return confirmed

        return True

    async def _request_confirmation(
        self, action: str, params: dict[str, Any]
    ) -> bool:
        """Ask the operator to confirm a sensitive action.

        If a ``confirm_callback`` was provided it is invoked; otherwise falls
        back to ``auto_confirm`` policy.

        Args:
            action: Action identifier.
            params: Parameters for the action.

        Returns:
            ``True`` if confirmed; ``False`` if rejected.
        """
        record: dict[str, Any] = {
            "id": str(uuid.uuid4())[:8],
            "action": action,
            "params": params,
            "timestamp": time.time(),
            "confirmed": None,
        }
        self._pending_confirmations.append(record)

        log.warning(
            "PermissionGate: CONFIRMATION REQUIRED — action=%s params=%s [id=%s]",
            action,
            params,
            record["id"],
        )

        if self._confirm_callback is not None:
            try:
                result = await self._confirm_callback(action, params)
                record["confirmed"] = bool(result)
                return record["confirmed"]
            except Exception as exc:
                log.error("confirm_callback raised: %s", exc)
                record["confirmed"] = False
                return False

        # Auto-confirm policy
        record["confirmed"] = self.auto_confirm
        if self.auto_confirm:
            log.info("PermissionGate: auto-confirmed action '%s'", action)
        else:
            log.warning("PermissionGate: auto-denied action '%s' (auto_confirm=False)", action)
        return self.auto_confirm

    def pending_confirmations(self) -> list[dict[str, Any]]:
        """Return the list of confirmation requests (including outcomes).

        Returns:
            List of confirmation record dicts with fields:
            ``id``, ``action``, ``params``, ``timestamp``, ``confirmed``.
        """
        return list(self._pending_confirmations)

    def resolve(self, confirmation_id: str, approved: bool) -> bool:
        """Manually resolve a pending confirmation from an external UI.

        This allows an operator dashboard to approve or deny requests that
        were not auto-resolved.

        Args:
            confirmation_id: The ``id`` field from a pending confirmation record.
            approved: Whether to approve (``True``) or deny (``False``).

        Returns:
            ``True`` if a pending confirmation with that ID was found and updated;
            ``False`` if the ID was not found.
        """
        for record in self._pending_confirmations:
            if record["id"] == confirmation_id and record["confirmed"] is None:
                record["confirmed"] = approved
                log.info(
                    "PermissionGate.resolve: id=%s → %s",
                    confirmation_id,
                    "APPROVED" if approved else "DENIED",
                )
                return True
        return False
