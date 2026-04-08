"""Horizon Orchestra — Multi-Orchestrator Team Engine.

The :class:`OrchestraTeam` is the top-level construct: a coordinator
backed by the Architecture E production stack decomposes a high-level
goal into subtasks, assigns each to the best-matching specialist,
manages dependencies, collects results, and synthesises the final
answer.

Data classes
------------
- :class:`TeamConfig` — Team-wide configuration.
- :class:`Specialist` — Descriptor for one specialist agent.
- :class:`TeamTask` — Unit of work routed to a specialist.
- :class:`HandoffPacket` — Structured payload passed between agents.

Example::

    config = TeamConfig(name="sales-team", coordinator_model="kimi-k2.5")
    team = OrchestraTeam(config)
    await team.add_specialist("prospector", capabilities=["salesforce", "linkedin"])
    await team.add_specialist("writer", capabilities=["email", "copywriting"])
    result = await team.run("Draft outreach for all high-value Salesforce leads")
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

from .context_bus import ContextBus, ContextMessage
from .team_memory import TeamMemory
from .inter_agent_trust import (
    InterAgentTrust,
    TrustLevel,
)

__all__ = [
    "OrchestraTeam",
    "TeamConfig",
    "Specialist",
    "TeamTask",
    "HandoffPacket",
]

log = logging.getLogger("orchestra.teams.team")


# ===========================================================================
# Configuration
# ===========================================================================

@dataclass
class TeamConfig:
    """Configuration for an :class:`OrchestraTeam`.

    Attributes
    ----------
    name:
        Human-readable team name (also used as a namespace).
    coordinator_model:
        LLM model used by the coordinator for planning and synthesis.
    max_specialists:
        Upper bound on team size.
    max_concurrent_tasks:
        How many tasks may run in parallel.
    handoff_timeout_seconds:
        Maximum wait for a handoff acknowledgement.
    enable_cross_org:
        Allow agents from different organisations.
    shared_memory:
        Whether the team memory is enabled.
    enable_trust_negotiation:
        Whether trust negotiation is enabled between agents.
    context_bus_capacity:
        Ring-buffer capacity of the :class:`ContextBus`.
    architecture:
        Default architecture letter for new specialists.
    """

    name: str = "horizon-team"
    coordinator_model: str = "kimi-k2.5"
    max_specialists: int = 10
    max_concurrent_tasks: int = 50
    handoff_timeout_seconds: float = 300.0
    enable_cross_org: bool = False
    shared_memory: bool = True
    enable_trust_negotiation: bool = True
    context_bus_capacity: int = 10_000
    architecture: str = "E"

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "name": self.name,
            "coordinator_model": self.coordinator_model,
            "max_specialists": self.max_specialists,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "handoff_timeout_seconds": self.handoff_timeout_seconds,
            "enable_cross_org": self.enable_cross_org,
            "shared_memory": self.shared_memory,
            "enable_trust_negotiation": self.enable_trust_negotiation,
            "context_bus_capacity": self.context_bus_capacity,
            "architecture": self.architecture,
        }


# ===========================================================================
# Specialist
# ===========================================================================

@dataclass
class Specialist:
    """Descriptor for a single specialist agent in the team.

    Attributes
    ----------
    agent_id:
        Unique identifier (auto-generated if omitted).
    name:
        Human-readable name, e.g. ``"salesforce-expert"``.
    capabilities:
        List of capability tags used for task routing.
    architecture:
        Architecture letter this specialist uses (A–E).
    model:
        LLM model identifier.
    connectors:
        External connectors this specialist has access to.
    trust_level:
        String trust level: ``"owner"`` | ``"team"`` | ``"external"``
        | ``"untrusted"``.
    status:
        Current operational status.
    org_id:
        Organisation this agent belongs to.
    current_task:
        The ``task_id`` currently being worked on, or ``None``.
    metadata:
        Arbitrary extra metadata (e.g. model parameters).
    """

    agent_id: str = ""
    name: str = ""
    capabilities: List[str] = field(default_factory=list)
    architecture: str = "A"
    model: str = "kimi-k2.5"
    connectors: List[str] = field(default_factory=list)
    trust_level: str = "team"
    status: str = "idle"
    org_id: str = "default"
    current_task: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.agent_id:
            self.agent_id = f"{self.name}-{uuid.uuid4().hex[:8]}"

    # ── helpers ────────────────────────────────────────────────────────────
    @property
    def is_available(self) -> bool:
        """Return ``True`` if the specialist can accept a new task."""
        return self.status == "idle"

    def has_capability(self, cap: str) -> bool:
        """Check whether this specialist advertises *cap*."""
        return cap.lower() in [c.lower() for c in self.capabilities]

    def capability_overlap(self, required: List[str]) -> int:
        """Count how many of *required* capabilities this specialist has."""
        lower_caps = {c.lower() for c in self.capabilities}
        return sum(1 for r in required if r.lower() in lower_caps)

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "capabilities": self.capabilities,
            "architecture": self.architecture,
            "model": self.model,
            "connectors": self.connectors,
            "trust_level": self.trust_level,
            "status": self.status,
            "org_id": self.org_id,
            "current_task": self.current_task,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Specialist {self.name!r} id={self.agent_id[:12]} "
            f"arch={self.architecture} status={self.status}>"
        )


# ===========================================================================
# TeamTask
# ===========================================================================

@dataclass
class TeamTask:
    """A unit of work assigned to a specialist.

    Attributes
    ----------
    task_id:
        Unique identifier.
    description:
        Human-readable description of the subtask.
    assigned_to:
        Agent ID of the specialist (or ``"coordinator"``).
    delegated_by:
        Agent ID of whoever created this task.
    status:
        One of ``"queued"`` | ``"active"`` | ``"blocked"``
        | ``"done"`` | ``"failed"``.
    dependencies:
        List of ``task_id`` values that must complete first.
    result:
        The output produced when the task completes.
    context:
        Shared data passed between agents for this task.
    created_at:
        Unix timestamp of creation.
    deadline:
        Optional Unix timestamp deadline.
    priority:
        Lower is higher priority (default 5).
    error:
        Error message if status is ``"failed"``.
    """

    task_id: str = ""
    description: str = ""
    assigned_to: str = "coordinator"
    delegated_by: str = "coordinator"
    status: str = "queued"
    dependencies: List[str] = field(default_factory=list)
    result: Any = None
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    deadline: Optional[float] = None
    priority: int = 5
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = f"task-{uuid.uuid4().hex[:12]}"

    # ── helpers ────────────────────────────────────────────────────────────
    @property
    def is_terminal(self) -> bool:
        """Return ``True`` if the task is in a final state."""
        return self.status in ("done", "failed")

    @property
    def is_blocked(self) -> bool:
        """Return ``True`` if the task has unresolved dependencies."""
        return self.status == "blocked"

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "assigned_to": self.assigned_to,
            "delegated_by": self.delegated_by,
            "status": self.status,
            "dependencies": self.dependencies,
            "result": self.result,
            "context": self.context,
            "created_at": self.created_at,
            "deadline": self.deadline,
            "priority": self.priority,
            "error": self.error,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TeamTask {self.task_id[:12]} status={self.status} "
            f"assigned_to={self.assigned_to}>"
        )


# ===========================================================================
# HandoffPacket
# ===========================================================================

@dataclass
class HandoffPacket:
    """Structured data passed when one agent hands off to another.

    Attributes
    ----------
    from_agent:
        Agent ID of the sender.
    to_agent:
        Agent ID of the receiver.
    task_id:
        The task being handed off.
    completed_work:
        Summary of what was done.
    remaining_work:
        Description of what still needs to be done.
    context:
        Arbitrary data the next agent needs.
    artifacts:
        File paths, URLs, or IDs produced by the sender.
    trust_signature:
        HMAC-SHA256 signature for verification.
    timestamp:
        Unix timestamp of handoff creation.
    """

    from_agent: str = ""
    to_agent: str = ""
    task_id: str = ""
    completed_work: str = ""
    remaining_work: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    trust_signature: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "task_id": self.task_id,
            "completed_work": self.completed_work,
            "remaining_work": self.remaining_work,
            "context": self.context,
            "artifacts": self.artifacts,
            "trust_signature": self.trust_signature,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HandoffPacket":
        """Deserialise from a dictionary."""
        return cls(**data)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<HandoffPacket {self.from_agent} → {self.to_agent} "
            f"task={self.task_id[:12]}>"
        )


# ===========================================================================
# OrchestraTeam
# ===========================================================================

class OrchestraTeam:
    """Multi-orchestrator team: coordinator + specialist fleet.

    The TeamCoordinator receives a high-level goal, decomposes it into
    subtasks, assigns each subtask to the best specialist, manages
    dependencies, collects results, and synthesises the final output.

    Parameters
    ----------
    config:
        Team configuration.  Pass a :class:`TeamConfig` or use the
        default.
    context_bus:
        Pre-configured :class:`ContextBus`.  Created automatically if
        ``None``.
    memory:
        Pre-configured :class:`TeamMemory`.  Created automatically if
        ``config.shared_memory`` is ``True``.
    trust:
        Pre-configured :class:`InterAgentTrust`.  Created automatically
        if ``config.enable_trust_negotiation`` is ``True``.

    Example::

        team = OrchestraTeam(TeamConfig(name="coding"))
        await team.add_specialist("architect", capabilities=["design"])
        await team.add_specialist("coder", capabilities=["python"])
        result = await team.run("Build a REST API with FastAPI")
    """

    def __init__(
        self,
        config: Optional[TeamConfig] = None,
        context_bus: Optional[ContextBus] = None,
        memory: Optional[TeamMemory] = None,
        trust: Optional[InterAgentTrust] = None,
    ) -> None:
        self._config = config or TeamConfig()

        # Core subsystems
        self._bus = context_bus or ContextBus(
            capacity=self._config.context_bus_capacity,
        )
        self._memory: Optional[TeamMemory] = memory
        if self._memory is None and self._config.shared_memory:
            self._memory = TeamMemory(team_id=self._config.name)

        self._trust: Optional[InterAgentTrust] = trust
        if self._trust is None and self._config.enable_trust_negotiation:
            self._trust = InterAgentTrust(team_org_id="default")

        # Specialist registry: agent_id → Specialist
        self._specialists: Dict[str, Specialist] = {}

        # Task registry: task_id → TeamTask
        self._tasks: Dict[str, TeamTask] = {}

        # Concurrency limiter
        self._semaphore = asyncio.Semaphore(
            self._config.max_concurrent_tasks,
        )

        # Coordinator agent ID
        self._coordinator_id = f"coordinator-{uuid.uuid4().hex[:8]}"

        # Register coordinator in trust system
        if self._trust is not None:
            self._trust.register_agent(
                self._coordinator_id,
                trust_level=TrustLevel.OWNER,
            )

        # Register coordinator on the bus
        self._bus.register_agent(self._coordinator_id)

        self._started_at = time.time()
        log.info(
            "OrchestraTeam %r initialised (arch=%s, model=%s)",
            self._config.name,
            self._config.architecture,
            self._config.coordinator_model,
        )

    # ── properties ─────────────────────────────────────────────────────────

    @property
    def config(self) -> TeamConfig:
        """Team configuration."""
        return self._config

    @property
    def specialists(self) -> List[Specialist]:
        """Snapshot of the current specialist list."""
        return list(self._specialists.values())

    @property
    def bus(self) -> ContextBus:
        """The team's :class:`ContextBus`."""
        return self._bus

    @property
    def memory(self) -> Optional[TeamMemory]:
        """The team's :class:`TeamMemory` (may be ``None``)."""
        return self._memory

    @property
    def trust(self) -> Optional[InterAgentTrust]:
        """The team's :class:`InterAgentTrust` (may be ``None``)."""
        return self._trust

    @property
    def coordinator_id(self) -> str:
        """Coordinator agent ID."""
        return self._coordinator_id

    # ===================================================================
    # Specialist Management
    # ===================================================================

    async def add_specialist(
        self,
        name: str,
        capabilities: Optional[List[str]] = None,
        arch: str = "A",
        model: str = "kimi-k2.5",
        connectors: Optional[List[str]] = None,
        trust_level: str = "team",
        org_id: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Specialist:
        """Add a specialist agent to the team.

        Parameters
        ----------
        name:
            Human-readable name (e.g. ``"salesforce-expert"``).
        capabilities:
            List of capability tags for routing.
        arch:
            Architecture letter (A–E).
        model:
            LLM model to use.
        connectors:
            List of connector names this specialist has.
        trust_level:
            Initial trust level string.
        org_id:
            Organisation the agent belongs to.
        metadata:
            Arbitrary extra metadata.

        Returns
        -------
        Specialist
            The newly created specialist.

        Raises
        ------
        RuntimeError
            If the team is already at ``max_specialists``.
        """
        if len(self._specialists) >= self._config.max_specialists:
            raise RuntimeError(
                f"Team {self._config.name!r} is at max capacity "
                f"({self._config.max_specialists} specialists)"
            )

        spec = Specialist(
            name=name,
            capabilities=capabilities or [],
            architecture=arch,
            model=model,
            connectors=connectors or [],
            trust_level=trust_level,
            org_id=org_id,
            metadata=metadata or {},
        )

        self._specialists[spec.agent_id] = spec

        # Register on bus and trust system
        self._bus.register_agent(spec.agent_id)
        if self._trust is not None:
            self._trust.register_agent(
                spec.agent_id,
                trust_level=TrustLevel.from_string(trust_level),
                org_id=org_id,
            )

        # Announce on the bus
        await self._bus.publish(
            topic=f"agent.{spec.agent_id}.joined",
            payload=spec.to_dict(),
            from_agent=self._coordinator_id,
        )

        log.info(
            "Added specialist %r (%s) to team %r",
            name,
            spec.agent_id[:12],
            self._config.name,
        )
        return spec

    async def remove_specialist(self, agent_id: str) -> None:
        """Remove a specialist from the team.

        Raises ``KeyError`` if the specialist does not exist.
        """
        spec = self._specialists.pop(agent_id, None)
        if spec is None:
            raise KeyError(f"Specialist {agent_id!r} not found")

        self._bus.deregister_agent(agent_id)
        if self._trust is not None:
            await self._trust.revoke(agent_id)

        await self._bus.publish(
            topic=f"agent.{agent_id}.removed",
            payload={"agent_id": agent_id, "name": spec.name},
            from_agent=self._coordinator_id,
        )
        log.info("Removed specialist %r from team %r", spec.name, self._config.name)

    # ===================================================================
    # Execution — run() pipeline
    # ===================================================================

    async def run(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        deadline: Optional[float] = None,
    ) -> str:
        """Execute a high-level goal through the full team pipeline.

        Pipeline:

        1. **Decompose** — break the goal into subtasks.
        2. **Route** — assign each subtask to the best specialist.
        3. **Execute** — run all tasks (respecting dependencies).
        4. **Collect** — gather results.
        5. **Synthesise** — produce the final answer.

        Parameters
        ----------
        goal:
            Natural-language description of the goal.
        context:
            Optional initial context dict shared with all tasks.
        deadline:
            Optional Unix timestamp deadline.

        Returns
        -------
        str
            The synthesised final answer.
        """
        context = context or {}
        run_id = uuid.uuid4().hex[:12]
        log.info("Team %r run started (run=%s): %s", self._config.name, run_id, goal[:120])

        # Publish run start on bus
        await self._bus.set_shared("current_goal", goal, self._coordinator_id)
        await self._bus.publish(
            topic="team.run.started",
            payload={"run_id": run_id, "goal": goal},
            from_agent=self._coordinator_id,
        )

        # Store goal in memory
        if self._memory is not None:
            await self._memory.store(
                content=f"Team goal: {goal}",
                agent_id=self._coordinator_id,
                tags=["goal", "run"],
                pinned=True,
            )

        # 1. Decompose
        tasks = await self.decompose_goal(goal, context=context, deadline=deadline)
        log.info("Decomposed into %d subtasks", len(tasks))

        # 2. Route each task to the best specialist
        for task in tasks:
            best = await self.route_task(task)
            task.assigned_to = best.agent_id
            best.status = "busy"
            best.current_task = task.task_id
            self._tasks[task.task_id] = task

        # 3. Execute (resolve dependency ordering)
        await self._execute_tasks(tasks)

        # 4. Collect results
        task_ids = [t.task_id for t in tasks]
        results = await self.collect_results(task_ids)

        # 5. Synthesise
        answer = await self.synthesize(results, goal=goal)

        # Publish run completion
        await self._bus.publish(
            topic="team.run.completed",
            payload={"run_id": run_id, "answer_preview": answer[:200]},
            from_agent=self._coordinator_id,
        )

        # Store result in memory
        if self._memory is not None:
            await self._memory.store(
                content=f"Result for '{goal[:80]}': {answer[:500]}",
                agent_id=self._coordinator_id,
                tags=["result", "run"],
            )

        log.info("Team %r run completed (run=%s)", self._config.name, run_id)
        return answer

    async def stream(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream incremental progress as the team works on *goal*.

        Yields status strings as each subtask starts, completes, or
        encounters an error.  The final yield is the synthesised answer.
        """
        context = context or {}
        yield f"[team:{self._config.name}] Decomposing goal…\n"

        tasks = await self.decompose_goal(goal, context=context)
        yield f"[team:{self._config.name}] Created {len(tasks)} subtasks\n"

        for task in tasks:
            best = await self.route_task(task)
            task.assigned_to = best.agent_id
            best.status = "busy"
            best.current_task = task.task_id
            self._tasks[task.task_id] = task
            yield (
                f"[{best.name}] Assigned: {task.description[:80]}\n"
            )

        await self._execute_tasks(tasks)

        for task in tasks:
            status = "OK" if task.status == "done" else task.status.upper()
            yield f"[{task.assigned_to[:16]}] {status}: {task.description[:60]}\n"

        results = await self.collect_results([t.task_id for t in tasks])
        answer = await self.synthesize(results, goal=goal)
        yield f"\n--- Final Answer ---\n{answer}\n"

    # ===================================================================
    # Task Management
    # ===================================================================

    async def assign_task(
        self,
        task: TeamTask,
        specialist_id: str,
    ) -> TeamTask:
        """Manually assign *task* to a specific specialist.

        Returns the updated :class:`TeamTask`.
        """
        spec = self._specialists.get(specialist_id)
        if spec is None:
            raise KeyError(f"Specialist {specialist_id!r} not found")

        task.assigned_to = specialist_id
        task.status = "queued"
        self._tasks[task.task_id] = task

        await self._bus.publish(
            topic=f"task.{task.task_id}.assigned",
            payload={"task_id": task.task_id, "specialist": specialist_id},
            from_agent=self._coordinator_id,
        )
        return task

    async def handoff(self, packet: HandoffPacket) -> bool:
        """Execute a handoff between two agents.

        If trust negotiation is enabled the packet is HMAC-signed and
        verified.  Returns ``True`` on success.
        """
        # Sign if trust is enabled
        if self._trust is not None:
            await self._trust.sign_handoff(packet)
            valid = await self._trust.verify_handoff(packet)
            if not valid:
                log.warning(
                    "Handoff %s → %s rejected (HMAC failure)",
                    packet.from_agent,
                    packet.to_agent,
                )
                return False

        # Deliver via bus DM
        await self._bus.send(
            to_agent=packet.to_agent,
            payload=packet.to_dict(),
            from_agent=packet.from_agent,
        )

        # Update specialist statuses
        from_spec = self._specialists.get(packet.from_agent)
        if from_spec:
            from_spec.status = "idle"
            from_spec.current_task = None

        to_spec = self._specialists.get(packet.to_agent)
        if to_spec:
            to_spec.status = "busy"
            to_spec.current_task = packet.task_id

        log.info(
            "Handoff %s → %s (task=%s)",
            packet.from_agent,
            packet.to_agent,
            packet.task_id[:12],
        )
        return True

    async def broadcast(
        self,
        message: Any,
        exclude: Optional[List[str]] = None,
    ) -> None:
        """Broadcast *message* to all specialists.

        Parameters
        ----------
        message:
            Arbitrary payload.
        exclude:
            List of agent IDs to skip.
        """
        exclude_set = set(exclude or [])
        for spec in self._specialists.values():
            if spec.agent_id not in exclude_set:
                await self._bus.send(
                    to_agent=spec.agent_id,
                    payload=message,
                    from_agent=self._coordinator_id,
                )

    # ===================================================================
    # Coordination
    # ===================================================================

    async def decompose_goal(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        deadline: Optional[float] = None,
    ) -> List[TeamTask]:
        """Decompose a high-level goal into subtasks.

        The coordinator analyses the goal and the available specialist
        capabilities to produce a list of :class:`TeamTask` objects
        with appropriate dependency ordering.

        In a production deployment this calls the coordinator LLM.
        The default implementation uses a heuristic decomposition:
        one task per specialist, plus a synthesis task.
        """
        context = context or {}
        tasks: List[TeamTask] = []

        # Heuristic: create one task per specialist
        available = [s for s in self._specialists.values() if s.is_available or True]
        if not available:
            # No specialists — create a single coordinator task
            task = TeamTask(
                description=goal,
                assigned_to=self._coordinator_id,
                delegated_by=self._coordinator_id,
                context=context,
                deadline=deadline,
            )
            return [task]

        # Create a subtask for each specialist based on capabilities
        for spec in available:
            cap_str = ", ".join(spec.capabilities) if spec.capabilities else spec.name
            task = TeamTask(
                description=(
                    f"[{spec.name}] Contribute to: {goal} "
                    f"(using {cap_str})"
                ),
                assigned_to=spec.agent_id,
                delegated_by=self._coordinator_id,
                context={**context, "specialist": spec.name},
                deadline=deadline,
                priority=5,
            )
            tasks.append(task)

        return tasks

    async def route_task(self, task: TeamTask) -> Specialist:
        """Find the best specialist for *task*.

        Routing heuristic:
        1. If already assigned, return that specialist.
        2. Score each idle specialist by capability overlap with the
           task description keywords.
        3. Break ties by preferring specialists with fewer active tasks.

        Returns
        -------
        Specialist
            The best-matching specialist.

        Raises
        ------
        RuntimeError
            If no specialists are registered.
        """
        if not self._specialists:
            raise RuntimeError("No specialists registered")

        # If already assigned, honour it
        if task.assigned_to and task.assigned_to in self._specialists:
            return self._specialists[task.assigned_to]

        # Score each specialist
        desc_tokens = set(task.description.lower().split())
        scored: List[tuple[float, Specialist]] = []

        for spec in self._specialists.values():
            # Capability overlap
            cap_tokens = {c.lower() for c in spec.capabilities}
            overlap = len(desc_tokens & cap_tokens)

            # Name match bonus
            if spec.name.lower() in task.description.lower():
                overlap += 2

            # Availability bonus
            avail_bonus = 1.0 if spec.is_available else 0.0

            score = overlap + avail_bonus
            scored.append((score, spec))

        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]
        log.debug(
            "Routed task %s → %s (score=%.1f)",
            task.task_id[:8],
            best.name,
            scored[0][0],
        )
        return best

    async def collect_results(
        self,
        task_ids: List[str],
    ) -> Dict[str, Any]:
        """Collect results from completed tasks.

        Returns a dictionary mapping ``task_id`` → result.
        """
        results: Dict[str, Any] = {}
        for tid in task_ids:
            task = self._tasks.get(tid)
            if task is not None:
                results[tid] = {
                    "description": task.description,
                    "status": task.status,
                    "result": task.result,
                    "assigned_to": task.assigned_to,
                    "error": task.error,
                }
        return results

    async def synthesize(
        self,
        results: Dict[str, Any],
        goal: str = "",
    ) -> str:
        """Synthesise a final answer from all subtask results.

        In production this calls the coordinator LLM with all results
        as context.  The default implementation merges result strings.

        Parameters
        ----------
        results:
            Mapping of task_id → result dict.
        goal:
            The original goal (for context).

        Returns
        -------
        str
            The synthesised final answer.
        """
        parts: List[str] = []
        parts.append(f"# Team Result: {self._config.name}")
        if goal:
            parts.append(f"\n**Goal:** {goal}\n")

        parts.append(f"**Specialists involved:** {len(results)}\n")

        for tid, info in results.items():
            status = info.get("status", "unknown")
            desc = info.get("description", "")[:100]
            result = info.get("result")
            agent = info.get("assigned_to", "unknown")
            error = info.get("error")

            parts.append(f"## Task: {desc}")
            parts.append(f"- **Assigned to:** {agent}")
            parts.append(f"- **Status:** {status}")
            if result is not None:
                result_str = str(result)[:500]
                parts.append(f"- **Result:** {result_str}")
            if error:
                parts.append(f"- **Error:** {error}")
            parts.append("")

        return "\n".join(parts)

    # ===================================================================
    # Status
    # ===================================================================

    def get_team_status(self) -> dict:
        """Return a comprehensive status snapshot of the team."""
        active_tasks = sum(
            1 for t in self._tasks.values() if t.status == "active"
        )
        completed_tasks = sum(
            1 for t in self._tasks.values() if t.status == "done"
        )
        failed_tasks = sum(
            1 for t in self._tasks.values() if t.status == "failed"
        )
        idle_specialists = sum(
            1 for s in self._specialists.values() if s.is_available
        )

        return {
            "team_name": self._config.name,
            "coordinator_id": self._coordinator_id,
            "coordinator_model": self._config.coordinator_model,
            "architecture": self._config.architecture,
            "specialists_total": len(self._specialists),
            "specialists_idle": idle_specialists,
            "specialists_busy": len(self._specialists) - idle_specialists,
            "tasks_total": len(self._tasks),
            "tasks_active": active_tasks,
            "tasks_completed": completed_tasks,
            "tasks_failed": failed_tasks,
            "memory_enabled": self._memory is not None,
            "trust_enabled": self._trust is not None,
            "uptime_seconds": time.time() - self._started_at,
            "bus_stats": self._bus.get_stats().to_dict(),
        }

    def get_specialist(self, agent_id: str) -> Optional[Specialist]:
        """Look up a specialist by agent_id."""
        return self._specialists.get(agent_id)

    def list_specialists(self) -> List[Specialist]:
        """Return a copy of the specialists list."""
        return list(self._specialists.values())

    async def health_check(self) -> dict:
        """Run a basic health check on all team subsystems.

        Returns a dict with ``"healthy": True/False`` and per-component
        status.
        """
        health: Dict[str, Any] = {
            "team": self._config.name,
            "coordinator": True,
            "bus": True,
            "memory": None,
            "trust": None,
            "specialists": {},
        }

        # Bus check
        try:
            stats = self._bus.get_stats()
            health["bus"] = stats.bus_uptime_seconds > 0
        except Exception as exc:
            health["bus"] = False
            health["bus_error"] = str(exc)

        # Memory check
        if self._memory is not None:
            try:
                ms = self._memory.stats()
                health["memory"] = True
                health["memory_entries"] = ms.total_entries
            except Exception as exc:
                health["memory"] = False
                health["memory_error"] = str(exc)

        # Trust check
        if self._trust is not None:
            try:
                level = self._trust.get_trust_level(self._coordinator_id)
                health["trust"] = level == TrustLevel.OWNER
            except Exception as exc:
                health["trust"] = False
                health["trust_error"] = str(exc)

        # Specialist checks
        for spec in self._specialists.values():
            health["specialists"][spec.agent_id] = {
                "name": spec.name,
                "status": spec.status,
                "healthy": spec.status != "unavailable",
            }

        health["healthy"] = (
            health["coordinator"]
            and health["bus"]
            and health.get("memory") is not False
            and health.get("trust") is not False
        )
        return health

    # ===================================================================
    # Lifecycle
    # ===================================================================

    async def shutdown(self) -> None:
        """Gracefully shut down the team and all subsystems."""
        log.info("Shutting down team %r", self._config.name)
        await self._bus.shutdown()
        if self._memory is not None:
            await self._memory.shutdown()
        self._specialists.clear()
        self._tasks.clear()

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<OrchestraTeam {self._config.name!r} "
            f"specialists={len(self._specialists)} "
            f"tasks={len(self._tasks)}>"
        )

    # ===================================================================
    # Internal helpers
    # ===================================================================

    async def _execute_tasks(self, tasks: List[TeamTask]) -> None:
        """Execute tasks respecting dependency order.

        Tasks without dependencies run in parallel.  Tasks with
        dependencies wait until all predecessors are done.
        """
        # Build dependency graph
        pending = {t.task_id: t for t in tasks}
        completed_ids: Set[str] = set()

        max_iterations = len(tasks) + 5  # safety guard
        iteration = 0

        while pending and iteration < max_iterations:
            iteration += 1
            # Find tasks whose dependencies are all satisfied
            ready = [
                t for t in pending.values()
                if all(d in completed_ids for d in t.dependencies)
            ]

            if not ready:
                # All remaining tasks are blocked — mark them failed
                for t in pending.values():
                    t.status = "failed"
                    t.error = "Deadlocked: unresolvable dependencies"
                break

            # Execute ready tasks concurrently
            coros = [self._execute_single(t) for t in ready]
            await asyncio.gather(*coros, return_exceptions=True)

            for t in ready:
                completed_ids.add(t.task_id)
                del pending[t.task_id]

    async def _execute_single(self, task: TeamTask) -> None:
        """Execute a single task.

        In production this dispatches to the specialist's agent loop.
        The default implementation simulates execution by marking the
        task as done and producing a placeholder result.
        """
        async with self._semaphore:
            task.status = "active"
            await self._bus.publish(
                topic=f"task.{task.task_id}.status",
                payload={"status": "active"},
                from_agent=self._coordinator_id,
            )

            try:
                # Simulated execution — in production this calls the
                # specialist's AgentLoop.run()
                spec = self._specialists.get(task.assigned_to)
                specialist_name = spec.name if spec else task.assigned_to

                task.result = (
                    f"[{specialist_name}] Completed: "
                    f"{task.description[:120]}"
                )
                task.status = "done"

                # Free the specialist
                if spec:
                    spec.status = "idle"
                    spec.current_task = None

                # Store in memory
                if self._memory is not None:
                    await self._memory.store(
                        content=f"Task result ({specialist_name}): {task.result}",
                        agent_id=task.assigned_to,
                        tags=["task-result"],
                    )

            except Exception as exc:
                task.status = "failed"
                task.error = str(exc)
                log.exception(
                    "Task %s failed: %s",
                    task.task_id[:12],
                    exc,
                )

            await self._bus.publish(
                topic=f"task.{task.task_id}.status",
                payload={"status": task.status, "result": task.result},
                from_agent=self._coordinator_id,
            )
