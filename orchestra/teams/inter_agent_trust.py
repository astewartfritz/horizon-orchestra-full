"""Horizon Orchestra — Inter-Agent Trust Negotiation.

This module manages trust boundaries between agents that may belong to
different organisations.  Every :class:`HandoffPacket` is signed with
HMAC-SHA256 so the receiving agent can verify that the packet has not
been tampered with in transit.

Trust levels
------------
+------------+-----------------------------------------------------------+
| Level      | Capabilities                                              |
+============+===========================================================+
| OWNER      | Full access, can modify trust policies, create agents.    |
+------------+-----------------------------------------------------------+
| TEAM       | Read all context, write to team memory, receive handoffs. |
+------------+-----------------------------------------------------------+
| EXTERNAL   | Sandboxed, limited context, human-in-the-loop for         |
|            | sensitive operations.                                     |
+------------+-----------------------------------------------------------+
| UNTRUSTED  | Read-only, no tool execution, all outputs reviewed.       |
+------------+-----------------------------------------------------------+

Example usage::

    trust = InterAgentTrust(secret_key="my-hmac-key")
    trust.register_agent("coder-1", trust_level=TrustLevel.TEAM, org_id="acme")
    signed = await trust.sign_handoff(packet)
    is_valid = await trust.verify_handoff(signed)
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set

__all__ = [
    "TrustLevel",
    "InterAgentTrust",
    "AgentTrustRecord",
    "TrustPolicy",
    "TrustNegotiationResult",
    "TrustViolation",
]

log = logging.getLogger("orchestra.teams.inter_agent_trust")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TrustLevel(enum.Enum):
    """Ordered trust levels for inter-agent interaction.

    Comparison operators reflect trust ordering:
    ``OWNER > TEAM > EXTERNAL > UNTRUSTED``.
    """

    OWNER = 4
    TEAM = 3
    EXTERNAL = 2
    UNTRUSTED = 1

    # Allow comparison so we can write ``if level >= TrustLevel.TEAM``
    def __lt__(self, other: object) -> bool:
        if not isinstance(other, TrustLevel):
            return NotImplemented
        return self.value < other.value

    def __le__(self, other: object) -> bool:
        if not isinstance(other, TrustLevel):
            return NotImplemented
        return self.value <= other.value

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, TrustLevel):
            return NotImplemented
        return self.value > other.value

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, TrustLevel):
            return NotImplemented
        return self.value >= other.value

    @classmethod
    def from_string(cls, label: str) -> "TrustLevel":
        """Parse a trust level from its name (case-insensitive).

        >>> TrustLevel.from_string("team")
        <TrustLevel.TEAM: 3>
        """
        mapping = {
            "owner": cls.OWNER,
            "team": cls.TEAM,
            "external": cls.EXTERNAL,
            "untrusted": cls.UNTRUSTED,
        }
        result = mapping.get(label.lower())
        if result is None:
            raise ValueError(
                f"Unknown trust level {label!r}; "
                f"expected one of {list(mapping.keys())}"
            )
        return result


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

# Capabilities that each trust level is allowed to perform
_DEFAULT_CAPABILITIES: Dict[TrustLevel, FrozenSet[str]] = {
    TrustLevel.OWNER: frozenset({
        "read_context",
        "write_context",
        "read_memory",
        "write_memory",
        "execute_tools",
        "modify_policy",
        "create_agents",
        "delete_agents",
        "handoff_receive",
        "handoff_send",
        "broadcast",
        "access_secrets",
    }),
    TrustLevel.TEAM: frozenset({
        "read_context",
        "write_context",
        "read_memory",
        "write_memory",
        "execute_tools",
        "handoff_receive",
        "handoff_send",
        "broadcast",
    }),
    TrustLevel.EXTERNAL: frozenset({
        "read_context",
        "read_memory",
        "handoff_receive",
    }),
    TrustLevel.UNTRUSTED: frozenset({
        "read_context",
    }),
}


@dataclass
class AgentTrustRecord:
    """Per-agent trust metadata."""

    agent_id: str
    trust_level: TrustLevel
    org_id: str
    capabilities: Set[str] = field(default_factory=set)
    registered_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    revoked: bool = False
    custom_grants: Set[str] = field(default_factory=set)
    custom_denials: Set[str] = field(default_factory=set)
    negotiation_history: List[dict] = field(default_factory=list)

    def effective_capabilities(self) -> Set[str]:
        """Return the union of default + custom grants minus denials."""
        base = set(_DEFAULT_CAPABILITIES.get(self.trust_level, frozenset()))
        return (base | self.custom_grants) - self.custom_denials

    def to_dict(self) -> dict:
        """Serialise to a dictionary."""
        return {
            "agent_id": self.agent_id,
            "trust_level": self.trust_level.name,
            "org_id": self.org_id,
            "capabilities": sorted(self.effective_capabilities()),
            "registered_at": self.registered_at,
            "last_activity": self.last_activity,
            "revoked": self.revoked,
        }


@dataclass
class TrustPolicy:
    """Team-wide trust policy governing cross-agent interaction.

    Attributes
    ----------
    require_hmac:
        If ``True`` all handoff packets must be HMAC-signed.
    allow_cross_org:
        If ``True`` agents from different ``org_id`` values may interact.
    default_external_level:
        Trust level assigned to agents whose org differs from the team.
    max_negotiation_elevation:
        Highest trust level reachable through negotiation (prevents
        an external agent from negotiating to OWNER).
    human_approval_required:
        Set of capabilities that always require a human confirmation.
    """

    require_hmac: bool = True
    allow_cross_org: bool = False
    default_external_level: TrustLevel = TrustLevel.EXTERNAL
    max_negotiation_elevation: TrustLevel = TrustLevel.TEAM
    human_approval_required: FrozenSet[str] = frozenset({
        "access_secrets",
        "delete_agents",
        "modify_policy",
    })
    handoff_expiry_seconds: float = 600.0

    def to_dict(self) -> dict:
        """Serialise to a dictionary."""
        return {
            "require_hmac": self.require_hmac,
            "allow_cross_org": self.allow_cross_org,
            "default_external_level": self.default_external_level.name,
            "max_negotiation_elevation": self.max_negotiation_elevation.name,
            "human_approval_required": sorted(self.human_approval_required),
            "handoff_expiry_seconds": self.handoff_expiry_seconds,
        }


@dataclass
class TrustNegotiationResult:
    """Outcome of a trust negotiation between two agents."""

    success: bool
    from_agent: str
    to_agent: str
    granted_level: TrustLevel
    granted_capabilities: Set[str] = field(default_factory=set)
    denied_capabilities: Set[str] = field(default_factory=set)
    reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialise to a dictionary."""
        return {
            "success": self.success,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "granted_level": self.granted_level.name,
            "granted_capabilities": sorted(self.granted_capabilities),
            "denied_capabilities": sorted(self.denied_capabilities),
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class TrustViolation(Exception):
    """Raised when an agent attempts an action above its trust level."""

    def __init__(
        self,
        agent_id: str,
        capability: str,
        trust_level: TrustLevel,
        message: str = "",
    ) -> None:
        self.agent_id = agent_id
        self.capability = capability
        self.trust_level = trust_level
        super().__init__(
            message or (
                f"Agent {agent_id!r} (trust={trust_level.name}) "
                f"is not permitted to {capability!r}"
            )
        )


# ---------------------------------------------------------------------------
# InterAgentTrust
# ---------------------------------------------------------------------------

class InterAgentTrust:
    """Trust boundary management for multi-agent systems.

    When agents from different organisations interact, trust levels
    determine what data they can access and what actions they can take.
    Handoff packets are HMAC-signed with SHA-256 to prevent tampering.

    Parameters
    ----------
    secret_key:
        Shared secret used for HMAC signing.  Defaults to a random hex
        string generated at instantiation — callers should supply a
        stable key for cross-process verification.
    policy:
        Team-wide :class:`TrustPolicy`.  Uses sensible defaults.
    team_org_id:
        The ``org_id`` of the owning team.  Agents whose ``org_id``
        differs are considered external.
    """

    def __init__(
        self,
        secret_key: Optional[str] = None,
        policy: Optional[TrustPolicy] = None,
        team_org_id: str = "default",
    ) -> None:
        self._secret_key: str = secret_key or uuid.uuid4().hex
        self._policy: TrustPolicy = policy or TrustPolicy()
        self._team_org_id: str = team_org_id

        # agent_id → AgentTrustRecord
        self._records: Dict[str, AgentTrustRecord] = {}
        self._audit_log: List[dict] = []

        log.debug(
            "InterAgentTrust initialised (org=%s, require_hmac=%s)",
            team_org_id,
            self._policy.require_hmac,
        )

    # ===================================================================
    # Agent Registration
    # ===================================================================

    def register_agent(
        self,
        agent_id: str,
        trust_level: TrustLevel = TrustLevel.TEAM,
        org_id: Optional[str] = None,
        custom_grants: Optional[Set[str]] = None,
        custom_denials: Optional[Set[str]] = None,
    ) -> AgentTrustRecord:
        """Register an agent with an initial trust level.

        If *org_id* differs from the team's and the policy disallows
        cross-org interaction, the agent is registered as UNTRUSTED.

        Returns the created :class:`AgentTrustRecord`.
        """
        effective_org = org_id or self._team_org_id
        effective_level = trust_level

        # Cross-org downgrade
        if effective_org != self._team_org_id:
            if not self._policy.allow_cross_org:
                effective_level = TrustLevel.UNTRUSTED
                log.warning(
                    "Agent %s from org %s downgraded to UNTRUSTED "
                    "(cross-org disabled)",
                    agent_id,
                    effective_org,
                )
            else:
                # Cap at default external level
                if effective_level > self._policy.default_external_level:
                    effective_level = self._policy.default_external_level

        record = AgentTrustRecord(
            agent_id=agent_id,
            trust_level=effective_level,
            org_id=effective_org,
            custom_grants=custom_grants or set(),
            custom_denials=custom_denials or set(),
        )
        self._records[agent_id] = record
        self._audit(
            "register",
            agent_id=agent_id,
            level=effective_level.name,
            org=effective_org,
        )
        return record

    # ===================================================================
    # Trust Queries
    # ===================================================================

    def get_trust_level(self, agent_id: str) -> TrustLevel:
        """Return the current trust level for *agent_id*.

        Returns ``TrustLevel.UNTRUSTED`` for unknown agents.
        """
        record = self._records.get(agent_id)
        if record is None or record.revoked:
            return TrustLevel.UNTRUSTED
        return record.trust_level

    def get_record(self, agent_id: str) -> Optional[AgentTrustRecord]:
        """Return the full trust record, or ``None``."""
        return self._records.get(agent_id)

    async def check_capability(
        self,
        agent_id: str,
        capability: str,
    ) -> bool:
        """Return ``True`` if *agent_id* is permitted *capability*.

        The check considers the agent's trust level, custom grants/
        denials, and the team policy.
        """
        record = self._records.get(agent_id)
        if record is None or record.revoked:
            return False
        return capability in record.effective_capabilities()

    async def require_capability(
        self,
        agent_id: str,
        capability: str,
    ) -> None:
        """Assert that *agent_id* has *capability*; raise otherwise."""
        allowed = await self.check_capability(agent_id, capability)
        if not allowed:
            level = self.get_trust_level(agent_id)
            raise TrustViolation(agent_id, capability, level)

    # ===================================================================
    # Trust Negotiation
    # ===================================================================

    async def negotiate(
        self,
        from_agent: str,
        to_agent: str,
        requested_capabilities: Optional[List[str]] = None,
    ) -> TrustNegotiationResult:
        """Negotiate trust between two agents.

        The *from_agent* requests that *to_agent* be granted certain
        capabilities.  The outcome is bounded by the team policy's
        ``max_negotiation_elevation``.

        Parameters
        ----------
        from_agent:
            Agent initiating the negotiation (must be ≥ TEAM).
        to_agent:
            Agent whose trust may be elevated.
        requested_capabilities:
            Specific capabilities requested.  ``None`` means "all
            capabilities appropriate for the negotiated level".

        Returns
        -------
        TrustNegotiationResult
        """
        initiator = self._records.get(from_agent)
        target = self._records.get(to_agent)

        # Validate initiator
        if initiator is None or initiator.revoked:
            return TrustNegotiationResult(
                success=False,
                from_agent=from_agent,
                to_agent=to_agent,
                granted_level=TrustLevel.UNTRUSTED,
                reason="Initiator is unregistered or revoked.",
            )

        if initiator.trust_level < TrustLevel.TEAM:
            return TrustNegotiationResult(
                success=False,
                from_agent=from_agent,
                to_agent=to_agent,
                granted_level=TrustLevel.UNTRUSTED,
                reason="Initiator trust level too low for negotiation.",
            )

        # Auto-register target if unknown
        if target is None:
            target = self.register_agent(to_agent)

        # Determine ceiling
        ceiling = self._policy.max_negotiation_elevation
        if initiator.trust_level < ceiling:
            ceiling = initiator.trust_level

        # Resolve granted capabilities
        all_caps = set(_DEFAULT_CAPABILITIES.get(ceiling, frozenset()))
        if requested_capabilities:
            requested_set = set(requested_capabilities)
            granted = requested_set & all_caps
            denied = requested_set - all_caps
        else:
            granted = all_caps
            denied = set()

        # Remove any caps that require human approval
        needs_human = granted & set(self._policy.human_approval_required)
        if needs_human:
            denied |= needs_human
            granted -= needs_human

        # Apply
        target.trust_level = ceiling
        target.custom_grants |= granted
        target.last_activity = time.time()
        target.negotiation_history.append({
            "from": from_agent,
            "granted_level": ceiling.name,
            "granted_caps": sorted(granted),
            "denied_caps": sorted(denied),
            "timestamp": time.time(),
        })

        result = TrustNegotiationResult(
            success=True,
            from_agent=from_agent,
            to_agent=to_agent,
            granted_level=ceiling,
            granted_capabilities=granted,
            denied_capabilities=denied,
            reason="Negotiation succeeded.",
        )

        self._audit(
            "negotiate",
            from_agent=from_agent,
            to_agent=to_agent,
            result=result.to_dict(),
        )
        return result

    # ===================================================================
    # HMAC Signing & Verification
    # ===================================================================

    async def sign_handoff(self, packet: Any) -> Any:
        """Sign a :class:`HandoffPacket` with HMAC-SHA256.

        The ``trust_signature`` field is overwritten with the computed
        signature.  The method returns the same (mutated) packet.

        Parameters
        ----------
        packet:
            A :class:`~orchestra.teams.team.HandoffPacket` instance.
        """
        payload = self._handoff_signing_payload(packet)
        signature = self._compute_hmac(payload)
        packet.trust_signature = signature

        self._audit(
            "sign_handoff",
            from_agent=packet.from_agent,
            to_agent=packet.to_agent,
            task_id=packet.task_id,
        )
        return packet

    async def verify_handoff(self, packet: Any) -> bool:
        """Verify that a :class:`HandoffPacket`'s HMAC signature is valid.

        Returns ``True`` if the signature matches, ``False`` otherwise.
        Also checks that the sending agent is not revoked and that the
        packet has not expired.
        """
        # Verify sender is registered and not revoked
        sender = self._records.get(packet.from_agent)
        if sender is None or sender.revoked:
            log.warning(
                "Handoff verification failed: sender %s unknown/revoked",
                packet.from_agent,
            )
            return False

        # Check packet age
        age = time.time() - packet.timestamp
        if age > self._policy.handoff_expiry_seconds:
            log.warning(
                "Handoff packet expired (age=%.1fs, max=%.1fs)",
                age,
                self._policy.handoff_expiry_seconds,
            )
            return False

        # Verify HMAC
        payload = self._handoff_signing_payload(packet)
        expected = self._compute_hmac(payload)
        valid = hmac.compare_digest(expected, packet.trust_signature)

        self._audit(
            "verify_handoff",
            from_agent=packet.from_agent,
            to_agent=packet.to_agent,
            valid=valid,
        )
        if not valid:
            log.warning(
                "HMAC verification FAILED for handoff %s → %s",
                packet.from_agent,
                packet.to_agent,
            )
        return valid

    # ===================================================================
    # Revocation
    # ===================================================================

    async def revoke(self, agent_id: str) -> None:
        """Revoke trust for *agent_id*.

        The agent's record is kept for audit purposes but marked as
        revoked.  All subsequent capability checks will fail.
        """
        record = self._records.get(agent_id)
        if record is not None:
            record.revoked = True
            record.trust_level = TrustLevel.UNTRUSTED
            self._audit("revoke", agent_id=agent_id)
            log.info("Revoked trust for agent %s", agent_id)

    async def reinstate(
        self,
        agent_id: str,
        trust_level: TrustLevel = TrustLevel.TEAM,
    ) -> None:
        """Reinstate a previously revoked agent at *trust_level*."""
        record = self._records.get(agent_id)
        if record is not None:
            record.revoked = False
            record.trust_level = trust_level
            record.last_activity = time.time()
            self._audit(
                "reinstate",
                agent_id=agent_id,
                level=trust_level.name,
            )

    # ===================================================================
    # Trust Matrix
    # ===================================================================

    def get_trust_matrix(self) -> Dict[str, dict]:
        """Return a full agent × agent trust grid.

        The outer key is the agent_id.  The value is a dict containing
        the agent's trust record plus a ``can_interact_with`` mapping
        listing the trust relationship with every other registered
        agent.
        """
        matrix: Dict[str, dict] = {}
        agents = list(self._records.values())
        for rec in agents:
            interactions: Dict[str, str] = {}
            for other in agents:
                if other.agent_id == rec.agent_id:
                    continue
                # Interaction is allowed if both are ≥ EXTERNAL and
                # either same org or cross-org is enabled
                same_org = rec.org_id == other.org_id
                cross_ok = self._policy.allow_cross_org
                if same_org or cross_ok:
                    interactions[other.agent_id] = "allowed"
                else:
                    interactions[other.agent_id] = "blocked"
            matrix[rec.agent_id] = {
                **rec.to_dict(),
                "can_interact_with": interactions,
            }
        return matrix

    # ===================================================================
    # Audit
    # ===================================================================

    def get_audit_log(self, limit: int = 100) -> List[dict]:
        """Return the most recent audit entries."""
        return self._audit_log[-limit:]

    def clear_audit_log(self) -> None:
        """Clear the audit log."""
        self._audit_log.clear()

    @property
    def policy(self) -> TrustPolicy:
        """Current trust policy."""
        return self._policy

    @policy.setter
    def policy(self, value: TrustPolicy) -> None:
        self._policy = value
        self._audit("policy_change", policy=value.to_dict())

    # ===================================================================
    # Internal helpers
    # ===================================================================

    def _compute_hmac(self, payload: str) -> str:
        """Compute HMAC-SHA256 over *payload* using the shared secret."""
        return hmac.new(
            key=self._secret_key.encode("utf-8"),
            msg=payload.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _handoff_signing_payload(packet: Any) -> str:
        """Build the canonical string to be HMAC-signed.

        We sign: from_agent + to_agent + task_id + completed_work +
        remaining_work + sorted(artifacts) + timestamp.
        """
        parts = [
            packet.from_agent,
            packet.to_agent,
            packet.task_id,
            packet.completed_work,
            packet.remaining_work,
            json.dumps(sorted(packet.artifacts), sort_keys=True),
            str(packet.timestamp),
        ]
        return "|".join(parts)

    def _audit(self, action: str, **kwargs: Any) -> None:
        """Append an entry to the internal audit log."""
        entry = {"action": action, "timestamp": time.time(), **kwargs}
        self._audit_log.append(entry)
        if len(self._audit_log) > 10_000:
            self._audit_log = self._audit_log[-5_000:]
