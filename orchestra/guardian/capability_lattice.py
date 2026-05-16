"""Capability Lattice — Formal partial-ordering of agent capabilities.

Implements a mathematical lattice over a fixed set of capabilities.
Higher capabilities *imply* lower ones (e.g. ``TOOL_DELETE`` implies
``TOOL_WRITE`` which implies ``TOOL_READ``).  The lattice can be
queried, granted, revoked, and compared in constant time per
capability because the implication closure is pre-computed at
module load.

Key guarantees:
    * Default-deny: an agent has **no** capabilities until explicitly granted.
    * Implied capabilities are expanded automatically upon grant.
    * Revocation removes the *exact* capability and any that depend on it.
    * Thread-safe for concurrent reads; writes are protected by an
      asyncio lock.
    * Standard profiles for common agent archetypes.

Beyond NemoClaw: NemoClaw grants static, flat capabilities. This system
models a *lattice* with a true partial order, dynamic grant/revoke,
profile diffing, and full audit hooks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, FrozenSet, Optional, Set

__all__ = [
    "Capability",
    "CapabilityGrant",
    "CapabilityLattice",
    "IMPLICATION_EDGES",
]

log = logging.getLogger("orchestra.guardian.capability_lattice")


# ---------------------------------------------------------------------------
# Capability enum
# ---------------------------------------------------------------------------

class Capability(str, Enum):
    """Every discrete capability an agent can possess.

    Organised by domain.  String values use dotted notation so they
    serialise cleanly to YAML / JSON.
    """

    # Network
    NETWORK_OUTBOUND = "network.outbound"
    NETWORK_INFERENCE = "network.inference"
    NETWORK_ENTERPRISE = "network.enterprise"

    # Filesystem
    FS_READ_WORKSPACE = "fs.read.workspace"
    FS_WRITE_WORKSPACE = "fs.write.workspace"
    FS_READ_SYSTEM = "fs.read.system"

    # Tools
    TOOL_READ = "tool.read"
    TOOL_WRITE = "tool.write"
    TOOL_DELETE = "tool.delete"
    TOOL_EXECUTE_CODE = "tool.execute.code"
    TOOL_DEPLOY = "tool.deploy"

    # Memory
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_DELETE = "memory.delete"

    # Models
    MODEL_FAST = "model.fast"
    MODEL_STANDARD = "model.standard"
    MODEL_LARGE = "model.large"
    MODEL_MULTIMODAL = "model.multimodal"

    # Cross-agent
    AGENT_SPAWN = "agent.spawn"
    AGENT_HANDOFF = "agent.handoff"
    AGENT_BROADCAST = "agent.broadcast"

    # Enterprise connectors
    CONNECTOR_SALESFORCE = "connector.salesforce"
    CONNECTOR_GOOGLE = "connector.google"
    CONNECTOR_MICROSOFT = "connector.microsoft"
    CONNECTOR_META = "connector.meta"
    CONNECTOR_AMAZON = "connector.amazon"


# ---------------------------------------------------------------------------
# Implication edges  (higher -> lower)
# ---------------------------------------------------------------------------

# Each entry ``A -> B`` means "granting A automatically grants B".
IMPLICATION_EDGES: list[tuple[Capability, Capability]] = [
    # Tool hierarchy: DELETE -> WRITE -> READ
    (Capability.TOOL_DELETE, Capability.TOOL_WRITE),
    (Capability.TOOL_WRITE, Capability.TOOL_READ),

    # Filesystem hierarchy: WRITE -> READ
    (Capability.FS_WRITE_WORKSPACE, Capability.FS_READ_WORKSPACE),
    (Capability.FS_READ_SYSTEM, Capability.FS_READ_WORKSPACE),

    # Memory hierarchy: DELETE -> WRITE -> READ
    (Capability.MEMORY_DELETE, Capability.MEMORY_WRITE),
    (Capability.MEMORY_WRITE, Capability.MEMORY_READ),

    # Model hierarchy: LARGE -> STANDARD -> FAST
    (Capability.MODEL_LARGE, Capability.MODEL_STANDARD),
    (Capability.MODEL_STANDARD, Capability.MODEL_FAST),
    (Capability.MODEL_MULTIMODAL, Capability.MODEL_FAST),

    # Network hierarchy: ENTERPRISE -> OUTBOUND -> INFERENCE
    (Capability.NETWORK_ENTERPRISE, Capability.NETWORK_OUTBOUND),
    (Capability.NETWORK_OUTBOUND, Capability.NETWORK_INFERENCE),

    # Agent hierarchy: BROADCAST -> HANDOFF, SPAWN -> HANDOFF
    (Capability.AGENT_BROADCAST, Capability.AGENT_HANDOFF),
    (Capability.AGENT_SPAWN, Capability.AGENT_HANDOFF),

    # Deploy implies execute + write + outbound
    (Capability.TOOL_DEPLOY, Capability.TOOL_EXECUTE_CODE),
    (Capability.TOOL_DEPLOY, Capability.TOOL_WRITE),
    (Capability.TOOL_DEPLOY, Capability.NETWORK_OUTBOUND),
]


# ---------------------------------------------------------------------------
# Pre-compute transitive closure
# ---------------------------------------------------------------------------

def _transitive_closure(
    edges: list[tuple[Capability, Capability]],
) -> dict[Capability, frozenset[Capability]]:
    """Return a mapping ``cap -> {all capabilities implied by cap}`` (incl. self)."""
    children: dict[Capability, set[Capability]] = {c: set() for c in Capability}
    for parent, child in edges:
        children[parent].add(child)

    # BFS per node
    closure: dict[Capability, frozenset[Capability]] = {}
    for cap in Capability:
        visited: set[Capability] = {cap}
        queue = list(children[cap])
        while queue:
            cur = queue.pop()
            if cur in visited:
                continue
            visited.add(cur)
            queue.extend(children[cur])
        closure[cap] = frozenset(visited)

    return closure


_IMPLIED: dict[Capability, frozenset[Capability]] = _transitive_closure(IMPLICATION_EDGES)


def _reverse_dependents() -> dict[Capability, frozenset[Capability]]:
    """Return a mapping ``cap -> {all capabilities that imply cap}``."""
    deps: dict[Capability, set[Capability]] = {c: set() for c in Capability}
    for cap, implied in _IMPLIED.items():
        for imp in implied:
            if imp != cap:
                deps[imp].add(cap)
    return {c: frozenset(s) for c, s in deps.items()}


_DEPENDENTS: dict[Capability, frozenset[Capability]] = _reverse_dependents()


# ---------------------------------------------------------------------------
# CapabilityGrant — audit record
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    """Immutable record of a single capability grant."""

    capability: Capability
    granted_by: str
    granted_at: float
    reason: str = ""


# ---------------------------------------------------------------------------
# CapabilityLattice
# ---------------------------------------------------------------------------

class CapabilityLattice:
    """Formal lattice ordering of agent capabilities.

    Higher capabilities imply lower ones.  Granting ``TOOL_DELETE``
    automatically grants ``TOOL_WRITE`` and ``TOOL_READ``.

    Capabilities can be dynamically revoked.  Revoking a *lower*
    capability also revokes every *higher* capability that depends
    on it (maintaining lattice consistency).

    Parameters
    ----------
    on_change : callable, optional
        ``async (agent_id, cap, action)`` called after every grant/revoke.
    """

    def __init__(
        self,
        *,
        on_change: Optional[Callable[..., Any]] = None,
    ) -> None:
        # agent_id -> {Capability -> CapabilityGrant}
        self._grants: dict[str, dict[Capability, CapabilityGrant]] = {}
        self._lock = asyncio.Lock()
        self._on_change = on_change
        self._history: list[dict[str, Any]] = []

    # -- query --------------------------------------------------------------

    def has(self, agent_id: str, capability: Capability) -> bool:
        """Return ``True`` if *agent_id* has *capability* (directly or implied)."""
        effective = self.get_effective(agent_id)
        return capability in effective

    def get_direct(self, agent_id: str) -> set[Capability]:
        """Return capabilities explicitly granted (not implied)."""
        grants = self._grants.get(agent_id)
        if not grants:
            return set()
        return set(grants.keys())

    def get_effective(self, agent_id: str) -> set[Capability]:
        """Return all capabilities including those implied by the lattice."""
        direct = self.get_direct(agent_id)
        effective: set[Capability] = set()
        for cap in direct:
            effective |= _IMPLIED[cap]
        return effective

    def get_all(self, agent_id: str) -> set[Capability]:
        """Alias for :meth:`get_effective`."""
        return self.get_effective(agent_id)

    def get_grants(self, agent_id: str) -> list[CapabilityGrant]:
        """Return all :class:`CapabilityGrant` records for *agent_id*."""
        grants = self._grants.get(agent_id)
        if not grants:
            return []
        return list(grants.values())

    # -- mutate -------------------------------------------------------------

    async def grant(
        self,
        agent_id: str,
        capability: Capability,
        granted_by: str = "system",
        reason: str = "",
    ) -> set[Capability]:
        """Grant *capability* to *agent_id*.

        Returns the set of *newly* granted capabilities (including implied).
        """
        async with self._lock:
            if agent_id not in self._grants:
                self._grants[agent_id] = {}

            before = self.get_effective(agent_id)
            grant_record = CapabilityGrant(
                capability=capability,
                granted_by=granted_by,
                granted_at=time.time(),
                reason=reason,
            )
            self._grants[agent_id][capability] = grant_record
            after = self.get_effective(agent_id)
            newly = after - before

            self._history.append({
                "action": "grant",
                "agent_id": agent_id,
                "capability": capability.value,
                "granted_by": granted_by,
                "reason": reason,
                "timestamp": grant_record.granted_at,
                "newly_effective": [c.value for c in newly],
            })

            log.info(
                "Granted %s to %s (implied +%d)",
                capability.value, agent_id, len(newly) - 1 if capability in newly else len(newly),
            )

        if self._on_change and newly:
            try:
                await self._on_change(agent_id, capability, "grant")
            except Exception:
                log.exception("on_change callback failed")

        return newly

    async def revoke(
        self,
        agent_id: str,
        capability: Capability,
        reason: str = "",
    ) -> set[Capability]:
        """Revoke *capability* and any higher capabilities that depend on it.

        Returns the set of capabilities that were actually removed.
        """
        async with self._lock:
            grants = self._grants.get(agent_id)
            if not grants:
                return set()

            before = self.get_effective(agent_id)

            # Remove the capability itself
            removed_direct: set[Capability] = set()
            if capability in grants:
                del grants[capability]
                removed_direct.add(capability)

            # Remove any higher-level capability that depends on this one
            dependents = _DEPENDENTS.get(capability, frozenset())
            for dep in dependents:
                if dep in grants:
                    del grants[dep]
                    removed_direct.add(dep)

            after = self.get_effective(agent_id)
            actually_lost = before - after

            self._history.append({
                "action": "revoke",
                "agent_id": agent_id,
                "capability": capability.value,
                "reason": reason,
                "timestamp": time.time(),
                "removed_effective": [c.value for c in actually_lost],
            })

            log.info(
                "Revoked %s from %s (effective -%d)",
                capability.value, agent_id, len(actually_lost),
            )

        if self._on_change and actually_lost:
            try:
                await self._on_change(agent_id, capability, "revoke")
            except Exception:
                log.exception("on_change callback failed")

        return actually_lost

    async def grant_profile(
        self,
        agent_id: str,
        profile: set[Capability],
        granted_by: str = "system",
        reason: str = "",
    ) -> set[Capability]:
        """Grant an entire profile at once.  Returns newly effective."""
        all_new: set[Capability] = set()
        for cap in profile:
            newly = await self.grant(agent_id, cap, granted_by=granted_by, reason=reason)
            all_new |= newly
        return all_new

    async def revoke_all(self, agent_id: str, reason: str = "") -> set[Capability]:
        """Remove every capability from *agent_id*.  Returns removed set."""
        async with self._lock:
            grants = self._grants.get(agent_id)
            if not grants:
                return set()
            before = self.get_effective(agent_id)
            grants.clear()
            self._history.append({
                "action": "revoke_all",
                "agent_id": agent_id,
                "reason": reason,
                "timestamp": time.time(),
                "removed_effective": [c.value for c in before],
            })
            return before

    # -- comparison ---------------------------------------------------------

    def diff(self, agent_a: str, agent_b: str) -> dict[str, set[Capability]]:
        """Return what each agent has that the other doesn't.

        Returns ``{"only_a": {...}, "only_b": {...}, "common": {...}}``.
        """
        eff_a = self.get_effective(agent_a)
        eff_b = self.get_effective(agent_b)
        return {
            "only_a": eff_a - eff_b,
            "only_b": eff_b - eff_a,
            "common": eff_a & eff_b,
        }

    def get_matrix(self) -> dict[str, dict[str, bool]]:
        """Return full capability grid: ``{agent_id: {cap_value: bool}}``."""
        matrix: dict[str, dict[str, bool]] = {}
        for agent_id in self._grants:
            effective = self.get_effective(agent_id)
            matrix[agent_id] = {c.value: c in effective for c in Capability}
        return matrix

    # -- lattice introspection ----------------------------------------------

    @staticmethod
    def get_implied(capability: Capability) -> frozenset[Capability]:
        """Return all capabilities implied by *capability* (incl. self)."""
        return _IMPLIED[capability]

    @staticmethod
    def get_dependents(capability: Capability) -> frozenset[Capability]:
        """Return all capabilities that *depend* on (imply) *capability*."""
        return _DEPENDENTS.get(capability, frozenset())

    @staticmethod
    def is_implied_by(lower: Capability, higher: Capability) -> bool:
        """Return ``True`` if *higher* implies *lower* in the lattice."""
        return lower in _IMPLIED[higher]

    def get_history(
        self,
        agent_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return grant/revoke history, optionally filtered by agent."""
        history = self._history
        if agent_id:
            history = [h for h in history if h["agent_id"] == agent_id]
        return history[-limit:]

    # -- standard profiles --------------------------------------------------

    @staticmethod
    def standard_agent() -> set[Capability]:
        """Basic agent profile: read + inference + fast models."""
        return {
            Capability.FS_READ_WORKSPACE,
            Capability.TOOL_READ,
            Capability.MEMORY_READ,
            Capability.NETWORK_INFERENCE,
            Capability.MODEL_FAST,
        }

    @staticmethod
    def enterprise_agent() -> set[Capability]:
        """Enterprise agent: standard + write + enterprise network + connectors."""
        return {
            Capability.FS_READ_WORKSPACE,
            Capability.FS_WRITE_WORKSPACE,
            Capability.TOOL_READ,
            Capability.TOOL_WRITE,
            Capability.MEMORY_READ,
            Capability.MEMORY_WRITE,
            Capability.NETWORK_INFERENCE,
            Capability.NETWORK_ENTERPRISE,
            Capability.MODEL_STANDARD,
            Capability.MODEL_MULTIMODAL,
            Capability.CONNECTOR_SALESFORCE,
            Capability.CONNECTOR_GOOGLE,
            Capability.CONNECTOR_MICROSOFT,
        }

    @staticmethod
    def coordinator_agent() -> set[Capability]:
        """Coordinator: enterprise + spawn + handoff + large models."""
        return {
            Capability.FS_READ_WORKSPACE,
            Capability.FS_WRITE_WORKSPACE,
            Capability.TOOL_READ,
            Capability.TOOL_WRITE,
            Capability.TOOL_EXECUTE_CODE,
            Capability.MEMORY_READ,
            Capability.MEMORY_WRITE,
            Capability.NETWORK_INFERENCE,
            Capability.NETWORK_ENTERPRISE,
            Capability.MODEL_LARGE,
            Capability.MODEL_MULTIMODAL,
            Capability.AGENT_SPAWN,
            Capability.AGENT_HANDOFF,
            Capability.AGENT_BROADCAST,
            Capability.CONNECTOR_SALESFORCE,
            Capability.CONNECTOR_GOOGLE,
            Capability.CONNECTOR_MICROSOFT,
        }

    @staticmethod
    def external_agent() -> set[Capability]:
        """Minimal profile for cross-org / external agents."""
        return {
            Capability.FS_READ_WORKSPACE,
            Capability.TOOL_READ,
            Capability.MEMORY_READ,
            Capability.NETWORK_INFERENCE,
            Capability.MODEL_FAST,
        }

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise the full lattice state."""
        out: dict[str, Any] = {}
        for agent_id, grants in self._grants.items():
            out[agent_id] = {
                "direct": [g.capability.value for g in grants.values()],
                "effective": [c.value for c in self.get_effective(agent_id)],
                "grants": [
                    {
                        "capability": g.capability.value,
                        "granted_by": g.granted_by,
                        "granted_at": g.granted_at,
                        "reason": g.reason,
                    }
                    for g in grants.values()
                ],
            }
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityLattice":
        """Restore lattice from serialised state."""
        lattice = cls()
        cap_lookup = {c.value: c for c in Capability}
        for agent_id, info in data.items():
            lattice._grants[agent_id] = {}
            for g in info.get("grants", []):
                cap = cap_lookup.get(g["capability"])
                if cap is None:
                    log.warning("Unknown capability %s — skipping", g["capability"])
                    continue
                lattice._grants[agent_id][cap] = CapabilityGrant(
                    capability=cap,
                    granted_by=g.get("granted_by", "restored"),
                    granted_at=g.get("granted_at", 0.0),
                    reason=g.get("reason", ""),
                )
        return lattice

    def __repr__(self) -> str:
        agents = len(self._grants)
        total_grants = sum(len(g) for g in self._grants.values())
        return f"<CapabilityLattice agents={agents} grants={total_grants}>"
