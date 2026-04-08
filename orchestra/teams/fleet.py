"""Horizon Orchestra — OrchestraFleet: Multi-Team Fleet Orchestration.

The :class:`OrchestraFleet` manages N :class:`OrchestraTeam` instances
running simultaneously as a coordinated fleet.  Where a single team has
specialist agents, the fleet has specialist *teams*, each handling a
domain (sales, engineering, research, enterprise integrations).

Supporting classes
------------------
- :class:`FleetConfig` — Fleet-wide configuration.
- :class:`FleetBus` — Extends :class:`ContextBus` to fleet scale with
  team-namespace isolation.
- :class:`FleetCircuitBreaker` — Trips when > threshold% of teams fail
  simultaneously.
- :class:`FleetMemory` — Shared memory across all teams with priority
  access control.

Example::

    fleet = OrchestraFleet(FleetConfig(name="horizon-fleet", max_teams=10))
    await fleet.add_team(sales_team)
    await fleet.add_team(engineering_team)
    await fleet.start()
    result = await fleet.run("Summarise this quarter's sales and build a dashboard")
    await fleet.shutdown()
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Awaitable, Deque, Dict, List, Optional, Set, Tuple

try:
    from .context_bus import ContextBus, ContextMessage
except ImportError:  # pragma: no cover
    ContextBus = object  # type: ignore[assignment,misc]
    ContextMessage = object  # type: ignore[assignment,misc]

try:
    from .team import OrchestraTeam, TeamConfig, Specialist, TeamTask
except ImportError:  # pragma: no cover
    OrchestraTeam = object  # type: ignore[assignment,misc]
    TeamConfig = object  # type: ignore[assignment,misc]
    Specialist = object  # type: ignore[assignment,misc]
    TeamTask = object  # type: ignore[assignment,misc]

__all__ = [
    "OrchestraFleet",
    "FleetConfig",
    "FleetBus",
    "FleetCircuitBreaker",
    "FleetMemory",
]

log = logging.getLogger("orchestra.teams.fleet")


# ==========================================================================
# Configuration
# ==========================================================================

@dataclass
class FleetConfig:
    """Configuration for an :class:`OrchestraFleet`.

    Attributes
    ----------
    name:
        Human-readable fleet name used for logging and namespacing.
    max_teams:
        Maximum number of teams the fleet can manage simultaneously.
    max_total_specialists:
        Hard cap on the total number of specialists across all teams.
    enable_cross_team_routing:
        When ``True``, tasks can be routed to any team regardless of
        the originating domain.
    enable_shared_memory:
        Enable :class:`FleetMemory` for cross-team knowledge sharing.
    circuit_breaker_threshold:
        Trip the fleet-level circuit breaker if more than this fraction
        of teams are in a failing state (0.0–1.0).
    load_balance_strategy:
        Routing strategy: ``"least_loaded"`` | ``"round_robin"`` |
        ``"capability_match"``.
    fleet_heartbeat_interval:
        Seconds between fleet-wide heartbeat checks.
    """

    name: str = "horizon-fleet"
    max_teams: int = 20
    max_total_specialists: int = 200
    enable_cross_team_routing: bool = True
    enable_shared_memory: bool = True
    circuit_breaker_threshold: float = 0.5
    load_balance_strategy: str = "least_loaded"
    fleet_heartbeat_interval: float = 30.0

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "name": self.name,
            "max_teams": self.max_teams,
            "max_total_specialists": self.max_total_specialists,
            "enable_cross_team_routing": self.enable_cross_team_routing,
            "enable_shared_memory": self.enable_shared_memory,
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "load_balance_strategy": self.load_balance_strategy,
            "fleet_heartbeat_interval": self.fleet_heartbeat_interval,
        }


# ==========================================================================
# FleetBus — fleet-scale ContextBus with namespace isolation
# ==========================================================================

class FleetBus(ContextBus):
    """Extends :class:`ContextBus` to fleet scale with team-namespace isolation.

    Every topic published through a team is automatically prefixed with
    the team's namespace (``fleet.<team_id>.<original_topic>``).
    Cross-team messages use the ``fleet.cross.<from_team>.<to_team>``
    namespace.  Fleet-wide broadcasts go to ``fleet.broadcast.*``.

    Parameters
    ----------
    fleet_name:
        Name of the owning fleet (used in topic prefixes).
    capacity:
        Per-topic ring buffer capacity.
    default_ttl_seconds:
        Default message TTL.
    """

    def __init__(
        self,
        fleet_name: str = "horizon-fleet",
        capacity: int = 50_000,
        default_ttl_seconds: float = 3600.0,
    ) -> None:
        super().__init__(capacity=capacity, default_ttl_seconds=default_ttl_seconds)
        self._fleet_name = fleet_name
        self._team_namespaces: Dict[str, str] = {}  # team_id → namespace prefix
        self._namespace_lock = asyncio.Lock()
        log.debug("FleetBus initialised for fleet %r", fleet_name)

    # -- Namespace management ------------------------------------------------

    async def register_team_namespace(self, team_id: str) -> str:
        """Register a team and return its namespace prefix.

        Parameters
        ----------
        team_id:
            The unique team identifier.

        Returns
        -------
        str
            The namespace prefix, e.g. ``"fleet.my-fleet.team-abc"``.
        """
        async with self._namespace_lock:
            if team_id not in self._team_namespaces:
                namespace = f"fleet.{self._fleet_name}.{team_id}"
                self._team_namespaces[team_id] = namespace
                log.debug("Registered namespace %r for team %s", namespace, team_id)
            return self._team_namespaces[team_id]

    async def deregister_team_namespace(self, team_id: str) -> None:
        """Remove a team's namespace.  Outstanding messages remain in buffers."""
        async with self._namespace_lock:
            self._team_namespaces.pop(team_id, None)

    def get_namespace(self, team_id: str) -> Optional[str]:
        """Return the namespace for a team, or ``None`` if unregistered."""
        return self._team_namespaces.get(team_id)

    # -- Namespaced publish / subscribe --------------------------------------

    async def publish_team(
        self,
        team_id: str,
        topic: str,
        payload: Any,
        from_agent: str,
        ttl_seconds: Optional[float] = None,
    ) -> str:
        """Publish a message under a team's namespace.

        The final topic becomes ``<namespace>.<topic>``.

        Returns
        -------
        str
            The ``message_id``.
        """
        ns = self._team_namespaces.get(team_id, f"fleet.{self._fleet_name}.{team_id}")
        namespaced_topic = f"{ns}.{topic}"
        return await self.publish(namespaced_topic, payload, from_agent, ttl_seconds)

    async def subscribe_team(
        self,
        team_id: str,
        topic_pattern: str,
        callback: Callable[[ContextMessage], Awaitable[None]],
        agent_id: str,
    ) -> str:
        """Subscribe to topics within a team's namespace.

        The pattern is prefixed with the team namespace so that only
        messages in that team's scope are delivered.

        Returns
        -------
        str
            The ``subscription_id``.
        """
        ns = self._team_namespaces.get(team_id, f"fleet.{self._fleet_name}.{team_id}")
        namespaced_pattern = f"{ns}.{topic_pattern}"
        return await self.subscribe(namespaced_pattern, callback, agent_id)

    # -- Cross-team messaging ------------------------------------------------

    async def publish_cross_team(
        self,
        from_team: str,
        to_team: str,
        payload: Any,
        from_agent: str,
        ttl_seconds: Optional[float] = None,
    ) -> str:
        """Publish a cross-team message.

        Topic: ``fleet.cross.<from_team>.<to_team>``.

        Returns
        -------
        str
            The ``message_id``.
        """
        topic = f"fleet.cross.{from_team}.{to_team}"
        return await self.publish(topic, payload, from_agent, ttl_seconds)

    async def subscribe_cross_team(
        self,
        team_id: str,
        callback: Callable[[ContextMessage], Awaitable[None]],
        agent_id: str,
    ) -> str:
        """Subscribe to all incoming cross-team messages for *team_id*.

        Pattern: ``fleet.cross.*.<team_id>``.
        """
        pattern = f"fleet.cross.*.{team_id}"
        return await self.subscribe(pattern, callback, agent_id)

    # -- Fleet broadcast -----------------------------------------------------

    async def broadcast_fleet(
        self,
        payload: Any,
        from_agent: str,
        ttl_seconds: Optional[float] = None,
    ) -> str:
        """Broadcast a message to the entire fleet.

        Topic: ``fleet.broadcast``.
        """
        return await self.publish("fleet.broadcast", payload, from_agent, ttl_seconds)

    # -- Introspection -------------------------------------------------------

    def list_team_namespaces(self) -> Dict[str, str]:
        """Return a copy of team_id → namespace mapping."""
        return dict(self._team_namespaces)


# ==========================================================================
# FleetCircuitBreaker
# ==========================================================================

@dataclass
class _TeamHealthRecord:
    """Internal health tracking for a single team."""

    team_id: str
    consecutive_failures: int = 0
    last_success: float = field(default_factory=time.time)
    last_failure: float = 0.0
    is_healthy: bool = True
    total_tasks: int = 0
    total_failures: int = 0


class FleetCircuitBreaker:
    """Fleet-level circuit breaker that trips when too many teams fail.

    The breaker transitions between three states:

    - **closed** (normal) — all tasks are accepted and executed.
    - **open** (tripped) — new tasks are queued, not executed.  A
      cooldown timer runs; after it expires the breaker moves to
      *half-open*.
    - **half-open** — a limited number of probe tasks are accepted.
      If they succeed the breaker closes; if they fail it opens again.

    Parameters
    ----------
    threshold:
        Fraction of teams that must be failing to trip the breaker
        (0.0–1.0).
    cooldown_seconds:
        How long the breaker stays open before moving to half-open.
    max_consecutive_failures:
        Number of consecutive failures for a single team before it
        is marked unhealthy.
    """

    def __init__(
        self,
        threshold: float = 0.5,
        cooldown_seconds: float = 60.0,
        max_consecutive_failures: int = 3,
    ) -> None:
        self._threshold = max(0.0, min(1.0, threshold))
        self._cooldown = cooldown_seconds
        self._max_failures = max_consecutive_failures

        self._records: Dict[str, _TeamHealthRecord] = {}
        self._state: str = "closed"  # closed | open | half_open
        self._opened_at: float = 0.0
        self._probe_count: int = 0
        self._max_probes: int = 3

        self._lock = asyncio.Lock()
        log.debug(
            "FleetCircuitBreaker initialised (threshold=%.0f%%, cooldown=%.0fs)",
            self._threshold * 100,
            self._cooldown,
        )

    # -- Registration --------------------------------------------------------

    def register_team(self, team_id: str) -> None:
        """Register a team for health tracking."""
        if team_id not in self._records:
            self._records[team_id] = _TeamHealthRecord(team_id=team_id)

    def deregister_team(self, team_id: str) -> None:
        """Remove a team from health tracking."""
        self._records.pop(team_id, None)

    # -- Reporting -----------------------------------------------------------

    async def report_success(self, team_id: str) -> None:
        """Report a successful task execution by *team_id*."""
        async with self._lock:
            rec = self._records.get(team_id)
            if rec is None:
                return
            rec.consecutive_failures = 0
            rec.last_success = time.time()
            rec.is_healthy = True
            rec.total_tasks += 1

            # Half-open → closed transition
            if self._state == "half_open":
                self._probe_count += 1
                if self._probe_count >= self._max_probes:
                    self._state = "closed"
                    self._probe_count = 0
                    log.info("Fleet circuit breaker CLOSED after successful probes")

    async def report_failure(self, team_id: str) -> None:
        """Report a failed task execution by *team_id*."""
        async with self._lock:
            rec = self._records.get(team_id)
            if rec is None:
                return
            rec.consecutive_failures += 1
            rec.last_failure = time.time()
            rec.total_tasks += 1
            rec.total_failures += 1

            if rec.consecutive_failures >= self._max_failures:
                rec.is_healthy = False
                log.warning(
                    "Team %s marked unhealthy (%d consecutive failures)",
                    team_id,
                    rec.consecutive_failures,
                )

            # Check if we need to trip the breaker
            await self._evaluate_state()

    # -- State queries -------------------------------------------------------

    @property
    def state(self) -> str:
        """Current breaker state: ``"closed"`` | ``"open"`` | ``"half_open"``."""
        return self._state

    @property
    def is_open(self) -> bool:
        """Return ``True`` if the breaker is tripped (open)."""
        return self._state == "open"

    @property
    def is_closed(self) -> bool:
        """Return ``True`` if the breaker is in normal (closed) state."""
        return self._state == "closed"

    async def allow_request(self) -> bool:
        """Return ``True`` if a new task should be allowed through.

        In *closed* state, always returns ``True``.
        In *open* state, checks if cooldown has elapsed and
        transitions to *half_open* if so.
        In *half_open*, allows a limited number of probe requests.
        """
        async with self._lock:
            if self._state == "closed":
                return True

            if self._state == "open":
                elapsed = time.time() - self._opened_at
                if elapsed >= self._cooldown:
                    self._state = "half_open"
                    self._probe_count = 0
                    log.info("Fleet circuit breaker → HALF_OPEN (cooldown elapsed)")
                    return True
                return False

            # half_open: allow limited probes
            if self._probe_count < self._max_probes:
                return True
            return False

    def get_health_summary(self) -> Dict[str, Any]:
        """Return a summary of fleet health."""
        total = len(self._records)
        unhealthy = sum(1 for r in self._records.values() if not r.is_healthy)
        return {
            "state": self._state,
            "total_teams": total,
            "healthy_teams": total - unhealthy,
            "unhealthy_teams": unhealthy,
            "failure_ratio": unhealthy / total if total > 0 else 0.0,
            "threshold": self._threshold,
            "teams": {
                tid: {
                    "is_healthy": rec.is_healthy,
                    "consecutive_failures": rec.consecutive_failures,
                    "total_tasks": rec.total_tasks,
                    "total_failures": rec.total_failures,
                    "success_rate": (
                        (rec.total_tasks - rec.total_failures) / rec.total_tasks
                        if rec.total_tasks > 0
                        else 1.0
                    ),
                }
                for tid, rec in self._records.items()
            },
        }

    # -- Internal ------------------------------------------------------------

    async def _evaluate_state(self) -> None:
        """Evaluate whether the breaker should trip or close.

        Must be called while holding ``_lock``.
        """
        total = len(self._records)
        if total == 0:
            return

        unhealthy = sum(1 for r in self._records.values() if not r.is_healthy)
        ratio = unhealthy / total

        if self._state == "closed" and ratio >= self._threshold:
            self._state = "open"
            self._opened_at = time.time()
            log.warning(
                "Fleet circuit breaker TRIPPED: %.0f%% teams unhealthy "
                "(threshold=%.0f%%)",
                ratio * 100,
                self._threshold * 100,
            )
        elif self._state == "half_open" and ratio >= self._threshold:
            self._state = "open"
            self._opened_at = time.time()
            self._probe_count = 0
            log.warning("Fleet circuit breaker re-opened during half_open")


# ==========================================================================
# FleetMemory — shared memory across all teams
# ==========================================================================

@dataclass
class _MemoryEntry:
    """Single entry in fleet-wide shared memory."""

    key: str
    value: Any
    team_id: str
    agent_id: str
    priority: int  # lower = higher priority
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    ttl_seconds: float = 86400.0  # 24h default

    @property
    def is_expired(self) -> bool:
        """Return ``True`` if the entry has exceeded its TTL."""
        return (time.time() - self.updated_at) > self.ttl_seconds


class FleetMemory:
    """Shared memory across all teams in the fleet.

    Provides a priority-aware key-value store that all teams can read
    from and write to.  Higher-priority teams can overwrite lower-priority
    entries, and the access-control layer prevents unauthorised writes.

    Parameters
    ----------
    fleet_name:
        Name of the owning fleet.
    max_entries:
        Maximum number of entries before eviction (LRU by access time).
    default_ttl_seconds:
        Default time-to-live for new entries.
    """

    def __init__(
        self,
        fleet_name: str = "horizon-fleet",
        max_entries: int = 100_000,
        default_ttl_seconds: float = 86400.0,
    ) -> None:
        self._fleet_name = fleet_name
        self._max_entries = max_entries
        self._default_ttl = default_ttl_seconds

        self._store: Dict[str, _MemoryEntry] = {}
        self._team_priority: Dict[str, int] = {}  # team_id → priority (lower = higher)
        self._access_log: Deque[dict] = deque(maxlen=10_000)
        self._lock = asyncio.Lock()
        log.debug("FleetMemory initialised for fleet %r", fleet_name)

    # -- Team priority -------------------------------------------------------

    def set_team_priority(self, team_id: str, priority: int = 5) -> None:
        """Set the access priority for a team.

        Lower values = higher priority.  A team with priority 1 can
        overwrite entries written by a team with priority 5, but not
        vice versa.
        """
        self._team_priority[team_id] = priority
        log.debug("Team %s priority set to %d", team_id, priority)

    def get_team_priority(self, team_id: str) -> int:
        """Return the priority for *team_id* (default 5)."""
        return self._team_priority.get(team_id, 5)

    # -- Read / Write --------------------------------------------------------

    async def store(
        self,
        key: str,
        value: Any,
        team_id: str,
        agent_id: str = "unknown",
        priority: Optional[int] = None,
        ttl_seconds: Optional[float] = None,
    ) -> bool:
        """Store a value in fleet memory.

        If the key already exists and was written by a higher-priority
        team, the write is denied and ``False`` is returned.

        Parameters
        ----------
        key:
            Memory key.
        value:
            Arbitrary value (should be JSON-serialisable).
        team_id:
            Writing team's identifier.
        agent_id:
            Writing agent's identifier.
        priority:
            Override priority (defaults to the team's registered priority).
        ttl_seconds:
            Override TTL for this entry.

        Returns
        -------
        bool
            ``True`` if the write succeeded, ``False`` if blocked.
        """
        effective_priority = priority if priority is not None else self.get_team_priority(team_id)
        async with self._lock:
            existing = self._store.get(key)
            if existing is not None:
                # Higher-priority (lower number) entries cannot be overwritten
                # by lower-priority writers
                if existing.priority < effective_priority:
                    log.debug(
                        "FleetMemory write denied: key=%r (existing priority=%d, "
                        "writer priority=%d)",
                        key,
                        existing.priority,
                        effective_priority,
                    )
                    self._log_access("write_denied", key, team_id, agent_id)
                    return False

            entry = _MemoryEntry(
                key=key,
                value=value,
                team_id=team_id,
                agent_id=agent_id,
                priority=effective_priority,
                ttl_seconds=ttl_seconds or self._default_ttl,
            )
            if existing is not None:
                entry.created_at = existing.created_at
            self._store[key] = entry
            self._log_access("write", key, team_id, agent_id)

            # Evict if over capacity
            if len(self._store) > self._max_entries:
                await self._evict_lru()

        return True

    async def retrieve(
        self,
        key: str,
        team_id: str = "unknown",
        agent_id: str = "unknown",
    ) -> Any:
        """Retrieve a value from fleet memory.

        Returns ``None`` if the key does not exist or has expired.

        Parameters
        ----------
        key:
            Memory key.
        team_id:
            Reading team's identifier (for logging).
        agent_id:
            Reading agent's identifier (for logging).
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._store[key]
                return None
            entry.access_count += 1
            entry.updated_at = time.time()
            self._log_access("read", key, team_id, agent_id)
            return entry.value

    async def delete(self, key: str, team_id: str, agent_id: str = "unknown") -> bool:
        """Delete a key from fleet memory.

        Respects priority: a lower-priority team cannot delete a
        higher-priority entry.

        Returns
        -------
        bool
            ``True`` if the key was deleted.
        """
        effective_priority = self.get_team_priority(team_id)
        async with self._lock:
            existing = self._store.get(key)
            if existing is None:
                return False
            if existing.priority < effective_priority:
                log.debug("FleetMemory delete denied for key=%r", key)
                return False
            del self._store[key]
            self._log_access("delete", key, team_id, agent_id)
            return True

    async def search(
        self,
        prefix: str = "",
        team_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict]:
        """Search fleet memory by key prefix and optional team filter.

        Returns
        -------
        list[dict]
            List of entry summaries (key, value, team_id, priority).
        """
        results: List[dict] = []
        now = time.time()
        for key, entry in list(self._store.items()):
            if entry.is_expired:
                continue
            if prefix and not key.startswith(prefix):
                continue
            if team_id and entry.team_id != team_id:
                continue
            results.append({
                "key": entry.key,
                "value": entry.value,
                "team_id": entry.team_id,
                "agent_id": entry.agent_id,
                "priority": entry.priority,
                "access_count": entry.access_count,
                "age_seconds": now - entry.created_at,
            })
            if len(results) >= limit:
                break
        return results

    async def list_keys(self, prefix: str = "") -> List[str]:
        """Return all non-expired keys, optionally filtered by prefix."""
        return [
            key for key, entry in self._store.items()
            if not entry.is_expired and (not prefix or key.startswith(prefix))
        ]

    def get_stats(self) -> dict:
        """Return fleet memory statistics."""
        now = time.time()
        active = sum(1 for e in self._store.values() if not e.is_expired)
        return {
            "fleet_name": self._fleet_name,
            "total_entries": len(self._store),
            "active_entries": active,
            "expired_entries": len(self._store) - active,
            "max_entries": self._max_entries,
            "teams_with_entries": len(set(e.team_id for e in self._store.values())),
            "total_access_log": len(self._access_log),
        }

    async def clear(self) -> int:
        """Remove all entries from fleet memory.  Returns count removed."""
        async with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    # -- Internal ------------------------------------------------------------

    def _log_access(self, action: str, key: str, team_id: str, agent_id: str) -> None:
        """Append to the bounded access log."""
        self._access_log.append({
            "action": action,
            "key": key,
            "team_id": team_id,
            "agent_id": agent_id,
            "timestamp": time.time(),
        })

    async def _evict_lru(self) -> None:
        """Evict the least-recently-used entries until under capacity.

        Must be called while holding ``_lock``.
        """
        if len(self._store) <= self._max_entries:
            return
        # Sort by last access time (updated_at), evict oldest
        sorted_keys = sorted(
            self._store.keys(),
            key=lambda k: self._store[k].updated_at,
        )
        evict_count = len(self._store) - self._max_entries
        for key in sorted_keys[:evict_count]:
            del self._store[key]
        log.debug("FleetMemory evicted %d LRU entries", evict_count)


# ==========================================================================
# OrchestraFleet
# ==========================================================================

class OrchestraFleet:
    """N OrchestraTeams running as a coordinated fleet.

    The Fleet is one abstraction above a Team.  Where a Team has
    specialist agents, the Fleet has specialist Teams.  Each team
    handles a domain (sales, engineering, research, enterprise
    connections).

    **Global task routing** — incoming tasks are analysed and routed
    to the team best equipped to handle them.  If the primary team
    is overloaded, tasks are routed to secondary teams or queued.

    **Cross-team communication** — teams can delegate subtasks to
    each other via the :class:`FleetBus` (extends :class:`ContextBus`
    to fleet scale).

    **Fleet-level circuit breaker** — if more than ``threshold%`` of
    teams are failing or overloaded, the fleet enters degraded mode
    and queues new tasks instead of executing them.

    Parameters
    ----------
    config:
        Fleet configuration.  Defaults to :class:`FleetConfig()`.
    """

    def __init__(self, config: Optional[FleetConfig] = None) -> None:
        self.config = config or FleetConfig()

        # Team registry: team_id → OrchestraTeam
        self._teams: Dict[str, OrchestraTeam] = {}
        self._team_metadata: Dict[str, dict] = {}  # team_id → metadata

        # Fleet infrastructure
        self._bus = FleetBus(fleet_name=self.config.name)
        self._circuit_breaker = FleetCircuitBreaker(
            threshold=self.config.circuit_breaker_threshold,
        )
        self._memory: Optional[FleetMemory] = None
        if self.config.enable_shared_memory:
            self._memory = FleetMemory(fleet_name=self.config.name)

        # Round-robin index for load balancing
        self._rr_index: int = 0

        # Task tracking
        self._pending_tasks: Deque[dict] = deque()  # queued when circuit open
        self._task_history: Deque[dict] = deque(maxlen=10_000)

        # Fleet lifecycle
        self._started: bool = False
        self._heartbeat_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

        # Concurrency lock for team mutations
        self._team_lock = asyncio.Lock()

        log.info("OrchestraFleet %r initialised (max_teams=%d)", self.config.name, self.config.max_teams)

    # ==================================================================
    # Properties
    # ==================================================================

    @property
    def bus(self) -> FleetBus:
        """The fleet's communication bus."""
        return self._bus

    @property
    def memory(self) -> Optional[FleetMemory]:
        """The fleet's shared memory (``None`` if disabled)."""
        return self._memory

    @property
    def circuit_breaker(self) -> FleetCircuitBreaker:
        """The fleet-level circuit breaker."""
        return self._circuit_breaker

    # ==================================================================
    # Team management
    # ==================================================================

    async def add_team(self, team: Any) -> str:
        """Add an :class:`OrchestraTeam` to the fleet.

        Parameters
        ----------
        team:
            The team instance to add.

        Returns
        -------
        str
            The generated ``team_id``.

        Raises
        ------
        RuntimeError
            If the fleet is at capacity.
        """
        async with self._team_lock:
            if len(self._teams) >= self.config.max_teams:
                raise RuntimeError(
                    f"Fleet {self.config.name!r} is at max capacity "
                    f"({self.config.max_teams} teams)"
                )

            team_id = f"team-{uuid.uuid4().hex[:12]}"

            # Extract team config if available
            team_name = "unknown"
            team_capabilities: List[str] = []
            try:
                if hasattr(team, "_config"):
                    team_name = getattr(team._config, "name", "unknown")
                elif hasattr(team, "config"):
                    team_name = getattr(team.config, "name", "unknown")
            except Exception:
                pass

            self._teams[team_id] = team
            self._team_metadata[team_id] = {
                "team_id": team_id,
                "team_name": team_name,
                "added_at": time.time(),
                "status": "active",
                "tasks_completed": 0,
                "tasks_failed": 0,
                "capabilities": team_capabilities,
            }

            # Register in fleet subsystems
            await self._bus.register_team_namespace(team_id)
            self._circuit_breaker.register_team(team_id)
            if self._memory is not None:
                self._memory.set_team_priority(team_id)

            log.info("Added team %s (%s) to fleet %r", team_id, team_name, self.config.name)
            return team_id

    async def remove_team(self, team_id: str) -> None:
        """Remove a team from the fleet.

        Parameters
        ----------
        team_id:
            The team to remove.

        Raises
        ------
        KeyError
            If *team_id* is not in the fleet.
        """
        async with self._team_lock:
            if team_id not in self._teams:
                raise KeyError(f"Team {team_id!r} not found in fleet")

            del self._teams[team_id]
            self._team_metadata.pop(team_id, None)
            await self._bus.deregister_team_namespace(team_id)
            self._circuit_breaker.deregister_team(team_id)
            log.info("Removed team %s from fleet %r", team_id, self.config.name)

    async def get_team(self, team_id: str) -> Any:
        """Return the :class:`OrchestraTeam` for *team_id*, or ``None``."""
        return self._teams.get(team_id)

    def list_teams(self) -> List[dict]:
        """Return a summary of all teams in the fleet."""
        summaries: List[dict] = []
        for tid, meta in self._team_metadata.items():
            summary = dict(meta)
            team = self._teams.get(tid)
            if team is not None:
                try:
                    specialist_count = len(getattr(team, "_specialists", {}))
                except Exception:
                    specialist_count = 0
                summary["specialist_count"] = specialist_count
            summaries.append(summary)
        return summaries

    # ==================================================================
    # Fleet execution
    # ==================================================================

    async def run(self, task: str, context: Optional[dict] = None) -> str:
        """Run a task through the fleet.

        The task is routed to the best-matching team.  If the fleet's
        circuit breaker is open, the task is queued for later execution.

        Parameters
        ----------
        task:
            Natural-language task description.
        context:
            Optional additional context.

        Returns
        -------
        str
            The result from the executing team.
        """
        task_id = f"fleet-task-{uuid.uuid4().hex[:12]}"
        log.info("Fleet %r received task %s: %s", self.config.name, task_id, task[:80])

        # Check circuit breaker
        if self._circuit_breaker.is_open:
            allowed = await self._circuit_breaker.allow_request()
            if not allowed:
                self._pending_tasks.append({
                    "task_id": task_id,
                    "task": task,
                    "context": context,
                    "queued_at": time.time(),
                })
                log.warning("Fleet circuit breaker is open — task %s queued", task_id)
                return f"[Fleet degraded] Task {task_id} queued — fleet is in degraded mode."

        # Route to best team
        target_team_id, target_team = await self._route_to_team(task, context)

        if target_team is None:
            log.error("No team available in fleet %r for task %s", self.config.name, task_id)
            return f"[Fleet error] No team available to handle task: {task[:100]}"

        # Execute on the target team
        try:
            result = await self._execute_on_team(target_team_id, target_team, task, context)
            await self._circuit_breaker.report_success(target_team_id)
            meta = self._team_metadata.get(target_team_id, {})
            meta["tasks_completed"] = meta.get("tasks_completed", 0) + 1
            self._task_history.append({
                "task_id": task_id,
                "team_id": target_team_id,
                "status": "completed",
                "timestamp": time.time(),
            })
            return result
        except Exception as exc:
            await self._circuit_breaker.report_failure(target_team_id)
            meta = self._team_metadata.get(target_team_id, {})
            meta["tasks_failed"] = meta.get("tasks_failed", 0) + 1
            self._task_history.append({
                "task_id": task_id,
                "team_id": target_team_id,
                "status": "failed",
                "error": str(exc),
                "timestamp": time.time(),
            })
            log.exception("Task %s failed on team %s", task_id, target_team_id)
            return f"[Fleet error] Task failed: {exc}"

    async def stream(self, task: str) -> AsyncGenerator[str, None]:
        """Stream results from a fleet task execution.

        Routes the task to the best team and yields chunks as they
        arrive.  Falls back to non-streaming if the target team does
        not support streaming.

        Parameters
        ----------
        task:
            Natural-language task description.

        Yields
        ------
        str
            Result chunks.
        """
        target_team_id, target_team = await self._route_to_team(task)

        if target_team is None:
            yield "[Fleet error] No team available."
            return

        # Try streaming
        if hasattr(target_team, "stream"):
            try:
                async for chunk in target_team.stream(task):
                    yield chunk
                await self._circuit_breaker.report_success(target_team_id)
                return
            except Exception as exc:
                await self._circuit_breaker.report_failure(target_team_id)
                yield f"[Fleet error] Streaming failed: {exc}"
                return

        # Fallback to run
        try:
            result = await self._execute_on_team(target_team_id, target_team, task)
            yield result
        except Exception as exc:
            yield f"[Fleet error] {exc}"

    async def route_to_team(self, task: str) -> Any:
        """Intelligent routing — returns the best-fit team for a task.

        Parameters
        ----------
        task:
            Natural-language task description.

        Returns
        -------
        OrchestraTeam
            The selected team, or ``None``.
        """
        _, team = await self._route_to_team(task)
        return team

    async def broadcast_to_all(self, message: str) -> dict:
        """Send a broadcast message to all teams via the fleet bus.

        Parameters
        ----------
        message:
            The message payload.

        Returns
        -------
        dict
            Map of team_id → delivery status.
        """
        results: Dict[str, str] = {}
        await self._bus.broadcast_fleet(
            payload={"message": message, "timestamp": time.time()},
            from_agent="fleet-coordinator",
        )
        for team_id in self._teams:
            results[team_id] = "delivered"
        log.info("Broadcast sent to %d teams", len(results))
        return results

    # ==================================================================
    # Cross-team operations
    # ==================================================================

    async def delegate(
        self,
        from_team: str,
        to_team: str,
        task: str,
        context: dict,
    ) -> str:
        """Delegate a task from one team to another.

        Parameters
        ----------
        from_team:
            Source team ID.
        to_team:
            Destination team ID.
        task:
            Task description.
        context:
            Task context.

        Returns
        -------
        str
            The result from the destination team.

        Raises
        ------
        KeyError
            If either team is not found.
        RuntimeError
            If cross-team routing is disabled.
        """
        if not self.config.enable_cross_team_routing:
            raise RuntimeError("Cross-team routing is disabled in fleet config")

        if from_team not in self._teams:
            raise KeyError(f"Source team {from_team!r} not found")
        if to_team not in self._teams:
            raise KeyError(f"Destination team {to_team!r} not found")

        target = self._teams[to_team]
        log.info("Cross-team delegation: %s → %s: %s", from_team, to_team, task[:60])

        # Publish cross-team event
        await self._bus.publish_cross_team(
            from_team=from_team,
            to_team=to_team,
            payload={"task": task, "context": context},
            from_agent="fleet-coordinator",
        )

        # Execute on target
        return await self._execute_on_team(to_team, target, task, context)

    async def merge_results(self, team_results: Dict[str, str]) -> str:
        """Synthesise results from multiple teams into a unified answer.

        Parameters
        ----------
        team_results:
            Map of team_id → result string.

        Returns
        -------
        str
            Merged / synthesised result.
        """
        if not team_results:
            return "[Fleet] No results to merge."

        if len(team_results) == 1:
            return next(iter(team_results.values()))

        # Build a structured synthesis
        sections: List[str] = []
        for team_id, result in team_results.items():
            meta = self._team_metadata.get(team_id, {})
            team_name = meta.get("team_name", team_id)
            sections.append(f"## {team_name}\n{result}")

        merged = "# Fleet Synthesis\n\n" + "\n\n---\n\n".join(sections)

        # Store in fleet memory if available
        if self._memory is not None:
            merge_key = f"merge-{uuid.uuid4().hex[:8]}"
            await self._memory.store(
                key=merge_key,
                value=merged,
                team_id="fleet-coordinator",
                agent_id="fleet-coordinator",
                priority=1,
            )

        return merged

    # ==================================================================
    # Fleet-level circuit breaker (delegating to FleetCircuitBreaker)
    # ==================================================================

    def circuit_open(self) -> bool:
        """Return ``True`` if the fleet circuit breaker is tripped."""
        return self._circuit_breaker.is_open

    def get_fleet_load(self) -> Dict[str, float]:
        """Return per-team utilisation as a fraction 0.0–1.0.

        Utilisation is estimated from the team's specialist occupancy.
        """
        loads: Dict[str, float] = {}
        for team_id, team in self._teams.items():
            try:
                specialists = getattr(team, "_specialists", {})
                if not specialists:
                    loads[team_id] = 0.0
                    continue
                busy = sum(
                    1 for s in specialists.values()
                    if getattr(s, "status", "idle") != "idle"
                )
                loads[team_id] = busy / len(specialists)
            except Exception:
                loads[team_id] = 0.0
        return loads

    # ==================================================================
    # Status
    # ==================================================================

    def get_fleet_status(self) -> dict:
        """Return comprehensive fleet status."""
        loads = self.get_fleet_load()
        total_specialists = 0
        for team in self._teams.values():
            try:
                total_specialists += len(getattr(team, "_specialists", {}))
            except Exception:
                pass

        return {
            "fleet_name": self.config.name,
            "started": self._started,
            "total_teams": len(self._teams),
            "total_specialists": total_specialists,
            "circuit_breaker": self._circuit_breaker.get_health_summary(),
            "pending_tasks": len(self._pending_tasks),
            "load_balance_strategy": self.config.load_balance_strategy,
            "team_loads": loads,
            "teams": self.list_teams(),
            "memory_stats": self._memory.get_stats() if self._memory else None,
            "bus_stats": self._bus.get_stats().to_dict(),
        }

    async def health_check(self) -> dict:
        """Run a health check across all teams.

        Returns
        -------
        dict
            Per-team health status plus fleet-level summary.
        """
        results: Dict[str, Any] = {}
        for team_id, team in self._teams.items():
            try:
                if hasattr(team, "health_check"):
                    team_health = await team.health_check()
                else:
                    team_health = {"status": "ok", "note": "no health_check method"}
                results[team_id] = {
                    "status": "healthy",
                    "details": team_health,
                }
            except Exception as exc:
                results[team_id] = {
                    "status": "unhealthy",
                    "error": str(exc),
                }

        healthy_count = sum(1 for v in results.values() if v["status"] == "healthy")
        return {
            "fleet": self.config.name,
            "overall": "healthy" if healthy_count == len(results) else "degraded",
            "healthy_teams": healthy_count,
            "total_teams": len(results),
            "teams": results,
        }

    # ==================================================================
    # Lifecycle
    # ==================================================================

    async def start(self) -> None:
        """Start the fleet and begin heartbeat monitoring.

        Idempotent — calling multiple times has no additional effect.
        """
        if self._started:
            return
        self._started = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        log.info("OrchestraFleet %r started (%d teams)", self.config.name, len(self._teams))

    async def shutdown(self) -> None:
        """Gracefully shut down the fleet.

        Cancels the heartbeat loop, shuts down the bus, and drains
        any pending tasks.
        """
        self._started = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        await self._bus.shutdown()
        log.info(
            "OrchestraFleet %r shut down (%d pending tasks drained)",
            self.config.name,
            len(self._pending_tasks),
        )
        self._pending_tasks.clear()

    # ==================================================================
    # Internal helpers
    # ==================================================================

    async def _route_to_team(
        self,
        task: str,
        context: Optional[dict] = None,
    ) -> Tuple[str, Any]:
        """Select the best team for a task using the configured strategy.

        Returns
        -------
        tuple[str, Any]
            (team_id, team) — team is ``None`` if no teams are available.
        """
        if not self._teams:
            return ("", None)

        strategy = self.config.load_balance_strategy
        team_ids = list(self._teams.keys())

        if strategy == "round_robin":
            return self._route_round_robin(team_ids)

        if strategy == "capability_match":
            return self._route_capability_match(task, team_ids)

        # Default: least_loaded
        return self._route_least_loaded(team_ids)

    def _route_round_robin(self, team_ids: List[str]) -> Tuple[str, Any]:
        """Simple round-robin selection."""
        idx = self._rr_index % len(team_ids)
        self._rr_index += 1
        tid = team_ids[idx]
        return (tid, self._teams[tid])

    def _route_least_loaded(self, team_ids: List[str]) -> Tuple[str, Any]:
        """Route to the team with the lowest current load."""
        loads = self.get_fleet_load()
        best_tid = min(team_ids, key=lambda t: loads.get(t, 0.0))
        return (best_tid, self._teams[best_tid])

    def _route_capability_match(
        self,
        task: str,
        team_ids: List[str],
    ) -> Tuple[str, Any]:
        """Route based on capability overlap with the task.

        Falls back to least-loaded if no capability information is
        available.
        """
        task_lower = task.lower()
        best_score = -1
        best_tid = team_ids[0]

        for tid in team_ids:
            meta = self._team_metadata.get(tid, {})
            caps = meta.get("capabilities", [])
            score = sum(1 for cap in caps if cap.lower() in task_lower)
            if score > best_score:
                best_score = score
                best_tid = tid

        # If no matches, fall back to least-loaded
        if best_score <= 0:
            return self._route_least_loaded(team_ids)

        return (best_tid, self._teams[best_tid])

    async def _execute_on_team(
        self,
        team_id: str,
        team: Any,
        task: str,
        context: Optional[dict] = None,
    ) -> str:
        """Execute a task on a specific team.

        Tries ``team.run(task, context)`` first, then ``team.run(task)``.
        """
        if hasattr(team, "run"):
            try:
                if context:
                    return await team.run(task, context=context)
                return await team.run(task)
            except TypeError:
                # run() may not accept context kwarg
                return await team.run(task)
        return f"[Fleet] Team {team_id} does not support run()"

    async def _heartbeat_loop(self) -> None:
        """Background loop that periodically checks fleet health."""
        while self._started:
            try:
                await asyncio.sleep(self.config.fleet_heartbeat_interval)
                if not self._started:
                    break
                # Check health
                health = await self.health_check()
                unhealthy = health["total_teams"] - health["healthy_teams"]
                if unhealthy > 0:
                    log.warning(
                        "Fleet heartbeat: %d/%d teams unhealthy",
                        unhealthy,
                        health["total_teams"],
                    )

                # Try to drain pending tasks if circuit is closed
                if self._circuit_breaker.is_closed and self._pending_tasks:
                    await self._drain_pending_tasks()

            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Fleet heartbeat error")

    async def _drain_pending_tasks(self) -> None:
        """Attempt to execute queued tasks that were held during circuit-open."""
        drained = 0
        while self._pending_tasks:
            allowed = await self._circuit_breaker.allow_request()
            if not allowed:
                break
            item = self._pending_tasks.popleft()
            task_str = item.get("task", "")
            ctx = item.get("context")
            try:
                await self.run(task_str, context=ctx)
                drained += 1
            except Exception:
                log.exception("Failed to drain pending task")
                break
        if drained:
            log.info("Drained %d pending tasks", drained)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<OrchestraFleet {self.config.name!r} "
            f"teams={len(self._teams)} "
            f"started={self._started}>"
        )
