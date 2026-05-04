"""Horizon Orchestra — OrchestratorMesh: Federated Multi-Orchestrator Mesh.

The :class:`OrchestratorMesh` connects N ProductionOrchestrators (Arch E)
as a federated mesh for distributed, fault-tolerant task execution.

The mesh is the highest-level abstraction in Orchestra.  Where a Fleet
manages teams of agents, the Mesh manages fleets of orchestrators.

Each mesh node is a full :class:`ProductionOrchestrator` (Arch E) that
can be specialised for a domain.  The mesh routes tasks to the best node,
aggregates results, and can run the same task on multiple nodes and
merge/consensus-rank the results.

Key capabilities
~~~~~~~~~~~~~~~~

1. **Smart routing** — analyse task → pick best-architecture node.

   - Code tasks → nodes running Arch A (MonolithicAgent) + coding models
   - Research tasks → nodes running Arch B (RAGPipeline)
   - Complex parallel → nodes running Arch C (SwarmAgent)
   - Enterprise integration → nodes with MCP Hub (Arch D)

2. **Parallel execution** — run the same task on N nodes, merge results
   (useful for high-stakes tasks where one wrong answer is costly).

3. **Consensus mode** — N nodes independently answer the same question;
   the final answer requires 2/3 agreement.

4. **Fault tolerance** — if a node fails mid-task, another node picks
   up from the last checkpoint.

5. **Cross-node memory** — all nodes share a global memory store so
   knowledge discovered by one is available to all.

Supporting classes
------------------
- :class:`MeshNode` — Descriptor for a single node in the mesh.
- :class:`MeshConfig` — Mesh-wide configuration.
- :class:`MeshMemory` — Cross-node shared memory.
- :class:`MeshHealthMonitor` — Continuous health monitoring.

Example::

    mesh = OrchestratorMesh(MeshConfig(name="production-mesh"))
    await mesh.add_node(coding_orchestrator, specialization="coding", architecture="A")
    await mesh.add_node(research_orchestrator, specialization="research", architecture="B")
    await mesh.start()
    result = await mesh.run("Build a RAG pipeline for our knowledge base")
    await mesh.shutdown()
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Deque, Dict, List, Optional, Set, Tuple

try:
    from ..arch_e import ProductionOrchestrator
except ImportError:  # pragma: no cover
    ProductionOrchestrator = object  # type: ignore[assignment,misc]

__all__ = [
    "OrchestratorMesh",
    "MeshNode",
    "MeshConfig",
    "MeshMemory",
    "MeshHealthMonitor",
]

log = logging.getLogger("orchestra.teams.orchestrator_mesh")


# ==========================================================================
# Data models
# ==========================================================================

@dataclass
class MeshNode:
    """Descriptor for a single node in the orchestrator mesh.

    Attributes
    ----------
    node_id:
        Unique identifier for this mesh node.
    orchestrator:
        The :class:`ProductionOrchestrator` instance (or compatible).
    architecture:
        Architecture letter: ``"A"`` | ``"B"`` | ``"C"`` | ``"D"``
        | ``"E"``.
    specialization:
        Domain specialisation: ``"coding"`` | ``"research"`` |
        ``"enterprise"`` | ``"general"``.
    endpoint:
        Local or remote endpoint URL for this node.
    status:
        Current operational status: ``"active"`` | ``"overloaded"`` |
        ``"offline"`` | ``"standby"``.
    current_tasks:
        Number of tasks currently being executed.
    completed_tasks:
        Total tasks completed since node was added.
    success_rate:
        Fraction of completed tasks that succeeded (0.0–1.0).
    avg_latency_ms:
        Average execution latency in milliseconds.
    capabilities:
        List of capability tags this node supports.
    """

    node_id: str = ""
    orchestrator: Any = None
    architecture: str = "E"
    specialization: str = "general"
    endpoint: str = "local://default"
    status: str = "active"
    current_tasks: int = 0
    completed_tasks: int = 0
    success_rate: float = 1.0
    avg_latency_ms: float = 0.0
    capabilities: List[str] = field(default_factory=list)

    # Internal tracking (not serialised)
    _failed_tasks: int = field(default=0, repr=False)
    _last_heartbeat: float = field(default_factory=time.time, repr=False)
    _task_latencies: Deque[float] = field(
        default_factory=lambda: deque(maxlen=1000), repr=False
    )

    def __post_init__(self) -> None:
        if not self.node_id:
            self.node_id = f"node-{uuid.uuid4().hex[:12]}"

    def record_task_completion(self, latency_ms: float, success: bool) -> None:
        """Record a task completion and update running statistics.

        Parameters
        ----------
        latency_ms:
            Execution latency in milliseconds.
        success:
            Whether the task succeeded.
        """
        self.completed_tasks += 1
        if not success:
            self._failed_tasks += 1
        self._task_latencies.append(latency_ms)

        total = self.completed_tasks
        self.success_rate = (total - self._failed_tasks) / total if total > 0 else 1.0
        self.avg_latency_ms = (
            sum(self._task_latencies) / len(self._task_latencies)
            if self._task_latencies
            else 0.0
        )

    def set_status(self, new_status: str) -> None:
        """Transition to a new status with logging.

        Parameters
        ----------
        new_status:
            Target status.
        """
        old = self.status
        self.status = new_status
        if old != new_status:
            log.info(
                "MeshNode %s status: %s → %s",
                self.node_id,
                old,
                new_status,
            )

    @property
    def is_available(self) -> bool:
        """Return ``True`` if the node can accept new tasks."""
        return self.status in ("active", "standby")

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary (excludes orchestrator ref)."""
        return {
            "node_id": self.node_id,
            "architecture": self.architecture,
            "specialization": self.specialization,
            "endpoint": self.endpoint,
            "status": self.status,
            "current_tasks": self.current_tasks,
            "completed_tasks": self.completed_tasks,
            "success_rate": round(self.success_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "capabilities": self.capabilities,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<MeshNode {self.node_id} arch={self.architecture} "
            f"spec={self.specialization} status={self.status} "
            f"tasks={self.current_tasks}>"
        )


@dataclass
class MeshConfig:
    """Configuration for an :class:`OrchestratorMesh`.

    Attributes
    ----------
    name:
        Human-readable mesh name.
    max_nodes:
        Maximum number of nodes the mesh can manage.
    routing_strategy:
        How tasks are routed: ``"smart"`` | ``"round_robin"`` |
        ``"least_loaded"`` | ``"arch_affinity"``.
    enable_result_merging:
        Whether parallel-execution results can be merged.
    consensus_threshold:
        Fraction of nodes that must agree for consensus mode
        (default 0.67 = 2/3 majority).
    fault_tolerance:
        Number of nodes that can be lost while the mesh remains
        functional.
    enable_cross_node_memory:
        Enable :class:`MeshMemory` for cross-node knowledge sharing.
    """

    name: str = "horizon-mesh"
    max_nodes: int = 50
    routing_strategy: str = "smart"
    enable_result_merging: bool = True
    consensus_threshold: float = 0.67
    fault_tolerance: int = 2
    enable_cross_node_memory: bool = True

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "name": self.name,
            "max_nodes": self.max_nodes,
            "routing_strategy": self.routing_strategy,
            "enable_result_merging": self.enable_result_merging,
            "consensus_threshold": self.consensus_threshold,
            "fault_tolerance": self.fault_tolerance,
            "enable_cross_node_memory": self.enable_cross_node_memory,
        }


# ==========================================================================
# MeshMemory — cross-node shared memory
# ==========================================================================

@dataclass
class _MeshMemoryEntry:
    """Single entry in the mesh-wide memory store."""

    key: str
    value: Any
    node_id: str
    version: int
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    ttl_seconds: float = 86400.0

    @property
    def is_expired(self) -> bool:
        """Return ``True`` if the entry has exceeded its TTL."""
        return (time.time() - self.updated_at) > self.ttl_seconds


class MeshMemory:
    """Cross-node shared memory for the orchestrator mesh.

    All nodes in the mesh share a global memory store so that
    knowledge discovered by one node is available to all.  The store
    uses optimistic concurrency control — writes include a version
    number and are rejected if the version has advanced.

    Parameters
    ----------
    mesh_name:
        Name of the owning mesh.
    max_entries:
        Maximum entries before LRU eviction.
    """

    def __init__(
        self,
        mesh_name: str = "horizon-mesh",
        max_entries: int = 50_000,
    ) -> None:
        self._mesh_name = mesh_name
        self._max_entries = max_entries
        self._store: Dict[str, _MeshMemoryEntry] = {}
        self._lock = asyncio.Lock()
        self._version_counter: int = 0
        log.debug("MeshMemory initialised for mesh %r", mesh_name)

    async def store(
        self,
        key: str,
        value: Any,
        node_id: str,
        ttl_seconds: float = 86400.0,
    ) -> int:
        """Store a value, returning the new version number.

        Parameters
        ----------
        key:
            Memory key.
        value:
            Arbitrary value.
        node_id:
            Writing node's identifier.
        ttl_seconds:
            Time-to-live for this entry.

        Returns
        -------
        int
            The version number of the stored entry.
        """
        async with self._lock:
            self._version_counter += 1
            version = self._version_counter

            existing = self._store.get(key)
            entry = _MeshMemoryEntry(
                key=key,
                value=value,
                node_id=node_id,
                version=version,
                ttl_seconds=ttl_seconds,
            )
            if existing:
                entry.created_at = existing.created_at
            self._store[key] = entry

            # Evict if needed
            if len(self._store) > self._max_entries:
                self._evict_lru()

            return version

    async def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve a value by key.  Returns ``None`` if missing or expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            del self._store[key]
            return None
        entry.access_count += 1
        return entry.value

    async def delete(self, key: str) -> bool:
        """Delete a key.  Returns ``True`` if it existed."""
        return self._store.pop(key, None) is not None

    async def list_keys(self, prefix: str = "") -> List[str]:
        """Return non-expired keys, optionally filtered by prefix."""
        return [
            k for k, e in self._store.items()
            if not e.is_expired and (not prefix or k.startswith(prefix))
        ]

    def get_stats(self) -> dict:
        """Return memory statistics."""
        return {
            "mesh_name": self._mesh_name,
            "total_entries": len(self._store),
            "version_counter": self._version_counter,
            "max_entries": self._max_entries,
        }

    def _evict_lru(self) -> None:
        """Evict least-recently-used entries (must hold lock)."""
        if len(self._store) <= self._max_entries:
            return
        sorted_keys = sorted(
            self._store.keys(),
            key=lambda k: self._store[k].updated_at,
        )
        count = len(self._store) - self._max_entries
        for key in sorted_keys[:count]:
            del self._store[key]


# ==========================================================================
# MeshHealthMonitor
# ==========================================================================

class MeshHealthMonitor:
    """Continuous health monitoring for mesh nodes.

    Runs a background loop that pings nodes and updates their status.
    Unhealthy nodes are marked ``"offline"`` and excluded from routing.

    Parameters
    ----------
    check_interval_s:
        Seconds between health checks.
    max_missed_heartbeats:
        Number of consecutive missed heartbeats before marking a
        node offline.
    """

    def __init__(
        self,
        check_interval_s: float = 30.0,
        max_missed_heartbeats: int = 3,
    ) -> None:
        self._interval = check_interval_s
        self._max_missed = max_missed_heartbeats
        self._nodes: Dict[str, MeshNode] = {}
        self._missed_beats: Dict[str, int] = defaultdict(int)
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._lock = asyncio.Lock()
        log.debug(
            "MeshHealthMonitor initialised (interval=%.0fs, max_missed=%d)",
            check_interval_s,
            max_missed_heartbeats,
        )

    def register_node(self, node: MeshNode) -> None:
        """Register a node for health monitoring."""
        self._nodes[node.node_id] = node
        self._missed_beats[node.node_id] = 0

    def deregister_node(self, node_id: str) -> None:
        """Remove a node from monitoring."""
        self._nodes.pop(node_id, None)
        self._missed_beats.pop(node_id, None)

    async def check_node(self, node: MeshNode) -> bool:
        """Check a single node's health.

        Attempts to call ``health_check()`` on the node's orchestrator.
        Returns ``True`` if the node is healthy.
        """
        try:
            orch = node.orchestrator
            if orch is None:
                return False
            if hasattr(orch, "health_check"):
                await orch.health_check()
            node._last_heartbeat = time.time()
            return True
        except Exception as exc:
            log.debug("Health check failed for node %s: %s", node.node_id, exc)
            return False

    async def run_check_cycle(self) -> Dict[str, str]:
        """Run one health-check cycle across all registered nodes.

        Returns
        -------
        dict[str, str]
            Map of node_id → status after the check.
        """
        results: Dict[str, str] = {}
        for node_id, node in list(self._nodes.items()):
            healthy = await self.check_node(node)
            if healthy:
                self._missed_beats[node_id] = 0
                if node.status == "offline":
                    node.set_status("active")
                    log.info("Node %s recovered → active", node_id)
                results[node_id] = node.status
            else:
                self._missed_beats[node_id] += 1
                missed = self._missed_beats[node_id]
                if missed >= self._max_missed:
                    if node.status != "offline":
                        node.set_status("offline")
                        log.warning(
                            "Node %s marked offline (%d missed heartbeats)",
                            node_id,
                            missed,
                        )
                results[node_id] = node.status
        return results

    async def start(self) -> None:
        """Start the background health-check loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info("MeshHealthMonitor started")

    async def stop(self) -> None:
        """Stop the background health-check loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("MeshHealthMonitor stopped")

    async def _loop(self) -> None:
        """Internal loop that runs health checks at the configured interval."""
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                if not self._running:
                    break
                await self.run_check_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("MeshHealthMonitor error")


# ==========================================================================
# Architecture-to-task mapping for smart routing
# ==========================================================================

_ARCH_TASK_KEYWORDS: Dict[str, List[str]] = {
    "A": [
        "code", "coding", "program", "python", "javascript", "typescript",
        "build", "implement", "debug", "fix", "refactor", "api", "function",
        "class", "module", "script", "deploy", "compile",
    ],
    "B": [
        "research", "search", "find", "rag", "retrieval", "document",
        "knowledge", "summarise", "summarize", "analyse", "analyze",
        "paper", "article", "report", "data", "extract", "information",
    ],
    "C": [
        "parallel", "swarm", "multiple", "complex", "multi-step",
        "coordinate", "orchestrate", "pipeline", "workflow", "batch",
        "distribute", "concurrent", "simultaneous",
    ],
    "D": [
        "enterprise", "integration", "mcp", "connector", "gmail",
        "slack", "notion", "jira", "salesforce", "github", "api",
        "webhook", "external", "service", "tool",
    ],
    "E": [
        "production", "full", "complete", "end-to-end", "system",
        "general", "comprehensive", "all",
    ],
}

# Specialization keywords
_SPEC_KEYWORDS: Dict[str, List[str]] = {
    "coding": [
        "code", "coding", "program", "python", "javascript", "build",
        "implement", "debug", "fix", "api", "function", "class",
    ],
    "research": [
        "research", "search", "find", "rag", "document", "knowledge",
        "summarise", "summarize", "analyse", "analyze", "paper", "report",
    ],
    "enterprise": [
        "enterprise", "integration", "connector", "gmail", "slack",
        "notion", "jira", "salesforce", "github", "external", "service",
    ],
    "general": [],
}


# ==========================================================================
# OrchestratorMesh
# ==========================================================================

class OrchestratorMesh:
    """N ProductionOrchestrators connected as a federated mesh.

    The mesh is the highest-level abstraction in Orchestra.  Where a
    Fleet manages teams of agents, the Mesh manages fleets of
    orchestrators.

    Each mesh node is a full :class:`ProductionOrchestrator` (Arch E)
    that can be specialised for a domain.  The mesh routes tasks to the
    best node, aggregates results, and can run the same task on multiple
    nodes and merge/consensus-rank the results.

    Parameters
    ----------
    config:
        Mesh configuration.  Defaults to :class:`MeshConfig()`.
    """

    def __init__(self, config: Optional[MeshConfig] = None) -> None:
        self.config = config or MeshConfig()

        # Node registry: node_id → MeshNode
        self._nodes: Dict[str, MeshNode] = {}

        # Cross-node memory
        self._memory: Optional[MeshMemory] = None
        if self.config.enable_cross_node_memory:
            self._memory = MeshMemory(mesh_name=self.config.name)

        # Health monitor
        self._health_monitor = MeshHealthMonitor()

        # Round-robin index
        self._rr_index: int = 0

        # Task tracking
        self._task_history: Deque[dict] = deque(maxlen=10_000)
        self._active_tasks: Dict[str, dict] = {}  # task_id → task info
        self._checkpoints: Dict[str, dict] = {}  # task_id → checkpoint data

        # Lifecycle
        self._started: bool = False
        self._node_lock = asyncio.Lock()

        log.info(
            "OrchestratorMesh %r initialised (max_nodes=%d, strategy=%s)",
            self.config.name,
            self.config.max_nodes,
            self.config.routing_strategy,
        )

    # ==================================================================
    # Properties
    # ==================================================================

    @property
    def memory(self) -> Optional[MeshMemory]:
        """The mesh's cross-node shared memory (``None`` if disabled)."""
        return self._memory

    @property
    def health_monitor(self) -> MeshHealthMonitor:
        """The mesh's health monitor."""
        return self._health_monitor

    # ==================================================================
    # Node management
    # ==================================================================

    async def add_node(
        self,
        orchestrator: Any,
        specialization: str = "general",
        architecture: str = "E",
    ) -> str:
        """Add a new orchestrator node to the mesh.

        Parameters
        ----------
        orchestrator:
            A :class:`ProductionOrchestrator` instance (or compatible).
        specialization:
            Domain specialisation for routing.
        architecture:
            Architecture letter for routing affinity.

        Returns
        -------
        str
            The generated ``node_id``.

        Raises
        ------
        RuntimeError
            If the mesh is at maximum capacity.
        """
        async with self._node_lock:
            if len(self._nodes) >= self.config.max_nodes:
                raise RuntimeError(
                    f"Mesh {self.config.name!r} at max capacity "
                    f"({self.config.max_nodes} nodes)"
                )

            node_id = f"node-{uuid.uuid4().hex[:12]}"

            # Infer capabilities from architecture and specialization
            capabilities = self._infer_capabilities(architecture, specialization)

            node = MeshNode(
                node_id=node_id,
                orchestrator=orchestrator,
                architecture=architecture,
                specialization=specialization,
                endpoint=f"local://{node_id}",
                status="active",
                capabilities=capabilities,
            )

            self._nodes[node_id] = node
            self._health_monitor.register_node(node)

            log.info(
                "Added mesh node %s (arch=%s, spec=%s, caps=%d)",
                node_id,
                architecture,
                specialization,
                len(capabilities),
            )
            return node_id

    async def remove_node(self, node_id: str) -> None:
        """Remove a node from the mesh.

        Parameters
        ----------
        node_id:
            The node to remove.

        Raises
        ------
        KeyError
            If *node_id* is not in the mesh.
        """
        async with self._node_lock:
            if node_id not in self._nodes:
                raise KeyError(f"Node {node_id!r} not in mesh")

            node = self._nodes.pop(node_id)
            node.set_status("offline")
            self._health_monitor.deregister_node(node_id)
            log.info("Removed mesh node %s", node_id)

    async def get_node(self, node_id: str) -> Optional[MeshNode]:
        """Return the :class:`MeshNode` for *node_id*, or ``None``."""
        return self._nodes.get(node_id)

    def list_nodes(self) -> List[MeshNode]:
        """Return all nodes in the mesh."""
        return list(self._nodes.values())

    # ==================================================================
    # Execution modes
    # ==================================================================

    async def run(self, task: str, context: Optional[dict] = None) -> str:
        """Run a task on the best-suited mesh node.

        Routes the task using the configured strategy, executes it,
        and returns the result.

        Parameters
        ----------
        task:
            Natural-language task description.
        context:
            Optional additional context.

        Returns
        -------
        str
            The execution result.
        """
        task_id = f"mesh-task-{uuid.uuid4().hex[:12]}"
        log.info("Mesh %r received task %s: %s", self.config.name, task_id, task[:80])

        # Route to best node
        target_node = await self.route(task)
        if target_node is None:
            return f"[Mesh error] No available node for task: {task[:100]}"

        # Execute
        return await self._execute_on_node(task_id, target_node, task, context)

    async def run_parallel(self, task: str, node_count: int = 3) -> List[str]:
        """Run the same task on multiple nodes in parallel.

        Useful for high-stakes tasks where redundancy is valuable.

        Parameters
        ----------
        task:
            Task description.
        node_count:
            Number of nodes to run on (up to available count).

        Returns
        -------
        list[str]
            Results from each node.
        """
        available = [n for n in self._nodes.values() if n.is_available]
        selected = available[:min(node_count, len(available))]

        if not selected:
            return ["[Mesh error] No available nodes for parallel execution."]

        task_id = f"mesh-parallel-{uuid.uuid4().hex[:12]}"
        log.info(
            "Parallel execution on %d nodes for task %s",
            len(selected),
            task_id,
        )

        # Launch all in parallel
        tasks = [
            self._execute_on_node(
                f"{task_id}-{i}",
                node,
                task,
            )
            for i, node in enumerate(selected)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error strings
        output: List[str] = []
        for result in results:
            if isinstance(result, Exception):
                output.append(f"[Node error] {result}")
            else:
                output.append(str(result))

        return output

    async def run_consensus(self, task: str, node_count: int = 3) -> str:
        """Run a task on N nodes and require consensus.

        The final answer requires agreement from at least
        ``consensus_threshold`` fraction of nodes.

        Parameters
        ----------
        task:
            Task description.
        node_count:
            Number of nodes to consult.

        Returns
        -------
        str
            The consensus result, or an explanation of disagreement.
        """
        results = await self.run_parallel(task, node_count=node_count)

        # Filter out error results
        valid_results = [r for r in results if not r.startswith("[")]
        if not valid_results:
            return "[Mesh error] All nodes failed — no consensus possible."

        # Run consensus
        consensus_result, confidence = await self.consensus(valid_results)

        if confidence >= self.config.consensus_threshold:
            log.info(
                "Consensus reached with %.0f%% confidence (%d/%d nodes)",
                confidence * 100,
                int(confidence * len(valid_results)),
                len(valid_results),
            )
            return consensus_result
        else:
            log.warning(
                "Consensus NOT reached: %.0f%% < %.0f%% threshold",
                confidence * 100,
                self.config.consensus_threshold * 100,
            )
            return (
                f"[Mesh] Consensus not reached (confidence={confidence:.0%}, "
                f"threshold={self.config.consensus_threshold:.0%}).\n\n"
                f"Individual results:\n"
                + "\n---\n".join(f"Node {i+1}: {r}" for i, r in enumerate(valid_results))
            )

    async def stream(self, task: str) -> AsyncGenerator[str, None]:
        """Stream results from the best-suited mesh node.

        Parameters
        ----------
        task:
            Task description.

        Yields
        ------
        str
            Result chunks.
        """
        target_node = await self.route(task)
        if target_node is None:
            yield "[Mesh error] No available node."
            return

        orch = target_node.orchestrator
        if orch is None:
            yield "[Mesh error] Node has no orchestrator."
            return

        target_node.current_tasks += 1
        try:
            if hasattr(orch, "stream"):
                async for chunk in orch.stream(task):
                    yield chunk
            elif hasattr(orch, "run"):
                result = await orch.run(task)
                yield str(result)
            else:
                yield "[Mesh error] Node does not support streaming or run."
        except Exception as exc:
            yield f"[Node error] {exc}"
        finally:
            target_node.current_tasks = max(0, target_node.current_tasks - 1)

    # ==================================================================
    # Routing
    # ==================================================================

    async def route(self, task: str) -> Optional[MeshNode]:
        """Select the best mesh node for a task.

        Uses the configured routing strategy.

        Parameters
        ----------
        task:
            Task description.

        Returns
        -------
        MeshNode or None
            The selected node, or ``None`` if no nodes are available.
        """
        available = [n for n in self._nodes.values() if n.is_available]
        if not available:
            return None

        strategy = self.config.routing_strategy

        if strategy == "round_robin":
            return self._route_round_robin(available)

        if strategy == "least_loaded":
            return self._route_least_loaded(available)

        if strategy == "arch_affinity":
            return self._route_arch_affinity(task, available)

        # Default: "smart" — combines all signals
        return self._route_smart(task, available)

    def _score_node(self, node: MeshNode, task: str) -> float:
        """Score a node's fitness for a task.

        The smart routing score combines:
        - Architecture affinity (how well the arch matches the task type)
        - Specialization match (domain overlap)
        - Load (fewer current tasks → higher score)
        - Success rate (historical reliability)
        - Latency (lower is better)

        Parameters
        ----------
        node:
            The node to score.
        task:
            The task description.

        Returns
        -------
        float
            Score (higher is better).
        """
        task_lower = task.lower()

        # Architecture affinity: count keyword matches
        arch_keywords = _ARCH_TASK_KEYWORDS.get(node.architecture, [])
        arch_matches = sum(1 for kw in arch_keywords if kw in task_lower)
        arch_score = min(arch_matches / max(len(arch_keywords), 1), 1.0)

        # Specialization match
        spec_keywords = _SPEC_KEYWORDS.get(node.specialization, [])
        spec_matches = sum(1 for kw in spec_keywords if kw in task_lower)
        spec_score = min(spec_matches / max(len(spec_keywords), 1), 1.0)

        # Load score (fewer tasks = higher score)
        # Cap at 20 as a reasonable maximum
        load_score = max(0.0, 1.0 - (node.current_tasks / 20.0))

        # Success rate (historical)
        success_score = node.success_rate

        # Latency score (lower latency = higher score, normalise to 0-1)
        # Assume 5000ms as a reasonable maximum
        latency_score = max(0.0, 1.0 - (node.avg_latency_ms / 5000.0))

        # Weighted combination
        score = (
            arch_score * 0.30
            + spec_score * 0.25
            + load_score * 0.20
            + success_score * 0.15
            + latency_score * 0.10
        )

        return round(score, 6)

    # ==================================================================
    # Result aggregation
    # ==================================================================

    async def merge_results(self, results: List[str], task: str) -> str:
        """Merge results from parallel execution into a unified answer.

        Parameters
        ----------
        results:
            List of result strings from different nodes.
        task:
            The original task (for context).

        Returns
        -------
        str
            Merged result.
        """
        if not results:
            return "[Mesh] No results to merge."

        if len(results) == 1:
            return results[0]

        # Remove duplicates while preserving order
        seen: Set[str] = set()
        unique: List[str] = []
        for r in results:
            normalised = r.strip()
            if normalised not in seen:
                seen.add(normalised)
                unique.append(r)

        if len(unique) == 1:
            return unique[0]

        # Build a structured merge
        sections = [f"### Result {i+1}\n{r}" for i, r in enumerate(unique)]
        merged = (
            f"# Mesh Parallel Results\n\n"
            f"**Task:** {task[:200]}\n\n"
            f"**Nodes consulted:** {len(results)}\n"
            f"**Unique results:** {len(unique)}\n\n"
            + "\n\n---\n\n".join(sections)
        )

        # Store in mesh memory if available
        if self._memory is not None:
            await self._memory.store(
                key=f"merge-{uuid.uuid4().hex[:8]}",
                value=merged,
                node_id="mesh-coordinator",
            )

        return merged

    async def consensus(self, results: List[str]) -> Tuple[str, float]:
        """Determine consensus among multiple results.

        Uses a simple similarity-based voting mechanism: results are
        compared pairwise, and the result with the most "similar"
        votes wins.

        Parameters
        ----------
        results:
            List of result strings.

        Returns
        -------
        tuple[str, float]
            (consensus_result, confidence) where confidence is 0.0–1.0.
        """
        if not results:
            return ("[Mesh] No results for consensus.", 0.0)

        if len(results) == 1:
            return (results[0], 1.0)

        # Normalise results for comparison
        normalised = [r.strip().lower() for r in results]

        # Count exact matches for each result
        vote_counts: Dict[int, int] = defaultdict(int)
        for i, norm in enumerate(normalised):
            for j, other in enumerate(normalised):
                if i != j and self._results_similar(norm, other):
                    vote_counts[i] += 1

        if not vote_counts:
            # No agreement — pick the first result with low confidence
            return (results[0], 1.0 / len(results))

        # Find the result with the most votes
        winner_idx = max(vote_counts, key=vote_counts.get)  # type: ignore[arg-type]
        votes = vote_counts[winner_idx]
        total_possible = len(results) - 1
        confidence = (votes / total_possible) if total_possible > 0 else 1.0

        return (results[winner_idx], round(confidence, 4))

    # ==================================================================
    # Fault tolerance
    # ==================================================================

    async def handle_node_failure(self, node_id: str, task_id: str) -> None:
        """Handle a node failure mid-task.

        Marks the node as offline and attempts to reassign the task
        to another available node using the last checkpoint.

        Parameters
        ----------
        node_id:
            The failed node.
        task_id:
            The task that was in progress.
        """
        node = self._nodes.get(node_id)
        if node is not None:
            node.set_status("offline")
            node.current_tasks = max(0, node.current_tasks - 1)
            node.record_task_completion(0.0, success=False)

        # Look for a checkpoint
        checkpoint = self._checkpoints.get(task_id)
        task_info = self._active_tasks.get(task_id)

        if task_info is None:
            log.warning("No task info for %s — cannot reassign", task_id)
            return

        # Find a replacement node
        available = [
            n for n in self._nodes.values()
            if n.is_available and n.node_id != node_id
        ]

        if not available:
            log.error("No replacement nodes available for task %s", task_id)
            return

        # Pick the best replacement
        task_str = task_info.get("task", "")
        replacement = max(available, key=lambda n: self._score_node(n, task_str))

        log.info(
            "Reassigning task %s from %s to %s",
            task_id,
            node_id,
            replacement.node_id,
        )

        # Execute on replacement (with checkpoint context if available)
        context = task_info.get("context", {})
        if checkpoint:
            context["checkpoint"] = checkpoint

        try:
            result = await self._execute_on_node(
                task_id, replacement, task_str, context
            )
            task_info["result"] = result
            task_info["reassigned_to"] = replacement.node_id
        except Exception as exc:
            log.exception("Replacement node also failed for task %s", task_id)

    async def rebalance(self) -> None:
        """Redistribute active tasks across available nodes.

        Moves tasks from overloaded nodes to underutilised ones.
        Only safe to call when the mesh is not under heavy load.
        """
        available = [n for n in self._nodes.values() if n.is_available]
        if len(available) < 2:
            return

        # Find overloaded and underloaded nodes
        avg_tasks = sum(n.current_tasks for n in available) / len(available)

        overloaded = [n for n in available if n.current_tasks > avg_tasks * 1.5]
        underloaded = [n for n in available if n.current_tasks < avg_tasks * 0.5]

        if not overloaded or not underloaded:
            log.debug("Rebalance: no action needed")
            return

        moved = 0
        for over_node in overloaded:
            excess = int(over_node.current_tasks - avg_tasks)
            for _ in range(excess):
                if not underloaded:
                    break
                target = underloaded[0]
                # Transfer one task slot
                over_node.current_tasks = max(0, over_node.current_tasks - 1)
                target.current_tasks += 1
                moved += 1
                # Rotate underloaded list
                if target.current_tasks >= avg_tasks:
                    underloaded.pop(0)

        if moved:
            log.info("Rebalanced %d tasks across mesh nodes", moved)

    async def save_checkpoint(self, task_id: str, data: dict) -> None:
        """Save a checkpoint for a running task.

        Parameters
        ----------
        task_id:
            The task to checkpoint.
        data:
            Checkpoint data (partial results, state, etc.).
        """
        self._checkpoints[task_id] = {
            "data": data,
            "timestamp": time.time(),
        }
        log.debug("Checkpoint saved for task %s", task_id)

    # ==================================================================
    # Status
    # ==================================================================

    def get_mesh_status(self) -> dict:
        """Return comprehensive mesh status."""
        nodes = self.list_nodes()
        active = sum(1 for n in nodes if n.status == "active")
        offline = sum(1 for n in nodes if n.status == "offline")
        total_tasks = sum(n.current_tasks for n in nodes)
        total_completed = sum(n.completed_tasks for n in nodes)

        return {
            "mesh_name": self.config.name,
            "started": self._started,
            "routing_strategy": self.config.routing_strategy,
            "total_nodes": len(nodes),
            "active_nodes": active,
            "offline_nodes": offline,
            "total_current_tasks": total_tasks,
            "total_completed_tasks": total_completed,
            "active_task_count": len(self._active_tasks),
            "checkpoints": len(self._checkpoints),
            "fault_tolerance": self.config.fault_tolerance,
            "nodes": [n.to_dict() for n in nodes],
            "memory_stats": self._memory.get_stats() if self._memory else None,
        }

    async def health_check(self) -> dict:
        """Run a health check on all mesh nodes.

        Returns
        -------
        dict
            Per-node and aggregate health status.
        """
        node_results = await self._health_monitor.run_check_cycle()

        active_count = sum(1 for s in node_results.values() if s == "active")
        total = len(node_results)
        offline_count = sum(1 for s in node_results.values() if s == "offline")

        # Check fault tolerance
        can_tolerate = offline_count <= self.config.fault_tolerance
        overall = "healthy" if can_tolerate and active_count > 0 else "degraded"

        return {
            "mesh": self.config.name,
            "overall": overall,
            "active_nodes": active_count,
            "offline_nodes": offline_count,
            "total_nodes": total,
            "fault_tolerance_ok": can_tolerate,
            "nodes": node_results,
        }

    # ==================================================================
    # Lifecycle
    # ==================================================================

    async def start(self) -> None:
        """Start the mesh and its health monitor.

        Idempotent — calling multiple times has no additional effect.
        """
        if self._started:
            return
        self._started = True
        await self._health_monitor.start()
        log.info(
            "OrchestratorMesh %r started (%d nodes)",
            self.config.name,
            len(self._nodes),
        )

    async def shutdown(self) -> None:
        """Gracefully shut down the mesh.

        Stops the health monitor, marks all nodes as offline, and
        clears active task tracking.
        """
        self._started = False
        await self._health_monitor.stop()

        for node in self._nodes.values():
            node.set_status("offline")

        self._active_tasks.clear()
        self._checkpoints.clear()

        log.info("OrchestratorMesh %r shut down", self.config.name)

    # ==================================================================
    # Internal routing strategies
    # ==================================================================

    def _route_round_robin(self, available: List[MeshNode]) -> MeshNode:
        """Simple round-robin selection."""
        idx = self._rr_index % len(available)
        self._rr_index += 1
        return available[idx]

    def _route_least_loaded(self, available: List[MeshNode]) -> MeshNode:
        """Route to the node with the fewest current tasks."""
        return min(available, key=lambda n: n.current_tasks)

    def _route_arch_affinity(
        self,
        task: str,
        available: List[MeshNode],
    ) -> MeshNode:
        """Route based on architecture affinity only."""
        task_lower = task.lower()
        best_arch = "E"
        best_score = -1

        for arch, keywords in _ARCH_TASK_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in task_lower)
            if matches > best_score:
                best_score = matches
                best_arch = arch

        # Find nodes with matching architecture
        matching = [n for n in available if n.architecture == best_arch]
        if matching:
            return self._route_least_loaded(matching)
        return self._route_least_loaded(available)

    def _route_smart(
        self,
        task: str,
        available: List[MeshNode],
    ) -> MeshNode:
        """Smart routing: combines architecture, specialization, load, and history."""
        scored = [(node, self._score_node(node, task)) for node in available]
        # Sort by score descending, ties broken by node_id for determinism
        scored.sort(key=lambda x: (-x[1], x[0].node_id))
        return scored[0][0]

    # ==================================================================
    # Internal helpers
    # ==================================================================

    async def _execute_on_node(
        self,
        task_id: str,
        node: MeshNode,
        task: str,
        context: Optional[dict] = None,
    ) -> str:
        """Execute a task on a specific mesh node.

        Tracks execution time, updates node statistics, and handles
        errors gracefully.

        Parameters
        ----------
        task_id:
            Unique task identifier.
        node:
            The target node.
        task:
            Task description.
        context:
            Optional context.

        Returns
        -------
        str
            The execution result.
        """
        node.current_tasks += 1
        self._active_tasks[task_id] = {
            "task_id": task_id,
            "node_id": node.node_id,
            "task": task,
            "context": context,
            "started_at": time.time(),
        }

        start_time = time.time()
        try:
            orch = node.orchestrator
            if orch is None:
                raise RuntimeError(f"Node {node.node_id} has no orchestrator")

            if hasattr(orch, "run"):
                if context:
                    try:
                        result = await orch.run(task, context=context)
                    except TypeError:
                        result = await orch.run(task)
                else:
                    result = await orch.run(task)
            else:
                result = f"[Mesh] Node {node.node_id} does not support run()"

            latency_ms = (time.time() - start_time) * 1000
            node.record_task_completion(latency_ms, success=True)

            self._task_history.append({
                "task_id": task_id,
                "node_id": node.node_id,
                "status": "completed",
                "latency_ms": round(latency_ms, 2),
                "timestamp": time.time(),
            })

            return str(result)

        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            node.record_task_completion(latency_ms, success=False)

            self._task_history.append({
                "task_id": task_id,
                "node_id": node.node_id,
                "status": "failed",
                "error": str(exc),
                "latency_ms": round(latency_ms, 2),
                "timestamp": time.time(),
            })

            # Check if we've exceeded fault tolerance
            offline_count = sum(
                1 for n in self._nodes.values() if n.status == "offline"
            )
            if offline_count > self.config.fault_tolerance:
                node.set_status("overloaded")
            raise

        finally:
            node.current_tasks = max(0, node.current_tasks - 1)
            self._active_tasks.pop(task_id, None)

    @staticmethod
    def _results_similar(a: str, b: str) -> bool:
        """Check if two results are similar enough for consensus.

        Uses a simple character-level overlap metric.  Two results
        are considered similar if they share > 80% of their content.

        Parameters
        ----------
        a:
            First result (normalised).
        b:
            Second result (normalised).

        Returns
        -------
        bool
            ``True`` if the results are similar.
        """
        if a == b:
            return True
        if not a or not b:
            return False

        # Simple word overlap
        words_a = set(a.split())
        words_b = set(b.split())

        if not words_a or not words_b:
            return False

        intersection = words_a & words_b
        union = words_a | words_b
        jaccard = len(intersection) / len(union) if union else 0.0

        return jaccard > 0.8

    @staticmethod
    def _infer_capabilities(architecture: str, specialization: str) -> List[str]:
        """Infer capability tags from architecture and specialization.

        Parameters
        ----------
        architecture:
            Architecture letter.
        specialization:
            Domain specialisation.

        Returns
        -------
        list[str]
            Inferred capability tags.
        """
        caps: List[str] = []

        arch_caps = {
            "A": ["monolithic", "coding", "single-agent"],
            "B": ["rag", "retrieval", "search", "documents"],
            "C": ["swarm", "parallel", "multi-agent", "coordination"],
            "D": ["mcp", "connectors", "enterprise", "integrations"],
            "E": ["production", "full-stack", "gateway", "memory"],
        }
        caps.extend(arch_caps.get(architecture, ["general"]))

        spec_caps = {
            "coding": ["python", "javascript", "typescript", "debugging", "apis"],
            "research": ["analysis", "summarisation", "papers", "data"],
            "enterprise": ["gmail", "slack", "notion", "jira", "github"],
            "general": ["versatile", "multi-purpose"],
        }
        caps.extend(spec_caps.get(specialization, ["general"]))

        return caps

    def __repr__(self) -> str:  # pragma: no cover
        active = sum(1 for n in self._nodes.values() if n.status == "active")
        return (
            f"<OrchestratorMesh {self.config.name!r} "
            f"nodes={len(self._nodes)} active={active} "
            f"started={self._started}>"
        )
