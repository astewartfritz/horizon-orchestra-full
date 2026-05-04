"""
recovery_graph.py — Directed Acyclic Graph of recovery strategies.

Given an error, the :class:`RecoveryGraph` traverses its DAG to find
the optimal recovery path — choosing success-rate-weighted edges so
that the highest-probability path is tried first.

The graph is backed by an adjacency list. Real-time empirical success
rates update edge weights via :meth:`update_empirical`.
``topological_sort()`` validates acyclicity. ``visualize()`` emits
DOT notation for Graphviz debugging.
"""
from __future__ import annotations

__all__ = [
    "RecoveryNode",
    "RecoveryEdge",
    "RecoveryPath",
    "RecoveryResult",
    "RecoveryGraph",
]

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .error_taxonomy import ERROR_REGISTRY, ErrorSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RecoveryNode:
    """A single node in the recovery DAG.

    Attributes:
        node_id: Unique identifier (e.g. ``"cache_hit"``).
        action: Human-readable description of the recovery action.
        condition: Optional callable ``(context) → bool`` gating entry.
        cost_ms: Estimated latency cost in milliseconds.
        success_rate: Empirical success rate (0.0–1.0), updated in real-time.
        total_attempts: Number of times this node has been executed.
        total_successes: Number of successful executions.
    """
    node_id: str
    action: str
    condition: Optional[Callable[..., bool]] = None
    cost_ms: float = 100.0
    success_rate: float = 0.5
    total_attempts: int = 0
    total_successes: int = 0


@dataclass
class RecoveryEdge:
    """Directed edge from one recovery node to another.

    Attributes:
        source: Node ID of the source.
        target: Node ID of the target.
        edge_type: ``"on_success"`` or ``"on_failure"``.
        weight: Traversal weight (lower = preferred). Derived from
                1 − target node success_rate so that high-success
                nodes are preferred.
    """
    source: str
    target: str
    edge_type: str  # "on_success" | "on_failure"
    weight: float = 0.5


@dataclass
class RecoveryPath:
    """An ordered sequence of nodes to try for a given error."""
    error_code: str
    nodes: list[str]
    estimated_cost_ms: float = 0.0
    estimated_success_rate: float = 0.0


@dataclass
class RecoveryResult:
    """Outcome of executing a recovery path."""
    error_code: str
    succeeded: bool
    node_used: str
    attempts: int
    total_latency_ms: float
    path_traversed: list[str] = field(default_factory=list)
    data: Any = None


# ---------------------------------------------------------------------------
# Pre-built strategy node definitions
# ---------------------------------------------------------------------------

_DEFAULT_NODES: list[RecoveryNode] = [
    RecoveryNode("cache_hit", "Check local cache for identical request", cost_ms=5, success_rate=0.30),
    RecoveryNode("retry_same", "Retry the same provider/model with backoff", cost_ms=500, success_rate=0.60),
    RecoveryNode("model_downgrade", "Try a cheaper/simpler model variant", cost_ms=200, success_rate=0.70),
    RecoveryNode("provider_failover", "Switch to secondary provider", cost_ms=150, success_rate=0.80),
    RecoveryNode("context_truncation", "Truncate context to fit limits", cost_ms=50, success_rate=0.85),
    RecoveryNode("split_request", "Break large request into smaller chunks", cost_ms=300, success_rate=0.65),
    RecoveryNode("async_queue", "Queue request and resume when provider recovers", cost_ms=5000, success_rate=0.90),
    RecoveryNode("partial_result", "Return partial result with continuation marker", cost_ms=10, success_rate=0.95),
    RecoveryNode("graceful_degrade", "Return structured degradation response", cost_ms=5, success_rate=0.99),
    RecoveryNode("emergency_cache", "Return most recent similar cached response", cost_ms=20, success_rate=0.40),
    RecoveryNode("key_rotation", "Rotate to alternate API key", cost_ms=50, success_rate=0.75),
    RecoveryNode("sanitize_input", "Clean / sanitize the input and retry", cost_ms=30, success_rate=0.60),
    RecoveryNode("rebuild_context", "Rebuild context from conversation history", cost_ms=200, success_rate=0.70),
    RecoveryNode("respawn_sandbox", "Restart execution sandbox", cost_ms=2000, success_rate=0.80),
    RecoveryNode("noop_terminal", "Terminal node — no further recovery", cost_ms=0, success_rate=0.0),
]


# ---------------------------------------------------------------------------
# Error → entry-node mapping
# ---------------------------------------------------------------------------

def _default_error_entry_map() -> dict[str, str]:
    """Map each error code to its best entry node in the DAG."""
    m: dict[str, str] = {}
    for code, spec in ERROR_REGISTRY.items():
        strategy = spec.recovery_strategy
        # Direct mapping from recovery_strategy to node_id
        node_map: dict[str, str] = {
            "exponential_backoff": "retry_same",
            "provider_failover": "provider_failover",
            "model_downgrade": "model_downgrade",
            "truncate_context": "context_truncation",
            "cache_lookup": "cache_hit",
            "graceful_degrade": "graceful_degrade",
            "retry_same": "retry_same",
            "async_queue": "async_queue",
        }
        m[code] = node_map.get(strategy, "retry_same")
    return m


# ---------------------------------------------------------------------------
# Pre-built DAG edges
# ---------------------------------------------------------------------------

def _default_edges() -> list[RecoveryEdge]:
    """Build the default recovery DAG edges.

    The graph encodes: on failure of one strategy, try the next.
    On success, proceed to terminal.
    """
    edges: list[RecoveryEdge] = []

    def _add(src: str, on_fail: str, on_success: str = "noop_terminal") -> None:
        edges.append(RecoveryEdge(src, on_success, "on_success"))
        edges.append(RecoveryEdge(src, on_fail, "on_failure"))

    # Primary chain: cache → retry → failover → downgrade → split → queue → partial → degrade
    _add("cache_hit", on_fail="retry_same")
    _add("retry_same", on_fail="provider_failover")
    _add("provider_failover", on_fail="model_downgrade")
    _add("model_downgrade", on_fail="split_request")
    _add("split_request", on_fail="async_queue")
    _add("async_queue", on_fail="partial_result")
    _add("partial_result", on_fail="graceful_degrade")
    _add("graceful_degrade", on_fail="noop_terminal")

    # Alternate paths
    _add("context_truncation", on_fail="retry_same")
    _add("emergency_cache", on_fail="graceful_degrade")
    _add("key_rotation", on_fail="provider_failover")
    _add("sanitize_input", on_fail="retry_same")
    _add("rebuild_context", on_fail="context_truncation")
    _add("respawn_sandbox", on_fail="graceful_degrade")

    return edges


# ---------------------------------------------------------------------------
# RecoveryGraph
# ---------------------------------------------------------------------------

class RecoveryGraph:
    """A directed acyclic graph of recovery strategies.

    The graph is stored as an adjacency list mapping each node to its
    outgoing edges.  Traversal follows success-rate-weighted paths:
    among the ``on_failure`` edges of a node, the target with the
    highest current ``success_rate`` is preferred.

    Example::

        graph = RecoveryGraph()
        path = graph.traverse("MODEL_RATE_LIMIT_SOFT")
        print(path.nodes)  # ['retry_same', 'provider_failover', 'model_downgrade', ...]
    """

    def __init__(
        self,
        nodes: Optional[list[RecoveryNode]] = None,
        edges: Optional[list[RecoveryEdge]] = None,
        error_entry_map: Optional[dict[str, str]] = None,
    ) -> None:
        self._nodes: dict[str, RecoveryNode] = {}
        self._adj: dict[str, list[RecoveryEdge]] = defaultdict(list)
        self._error_entry: dict[str, str] = error_entry_map or _default_error_entry_map()

        for node in (nodes or _DEFAULT_NODES):
            self.add_node(node)
        for edge in (edges or _default_edges()):
            self.add_edge(edge)

    # -- graph construction -----------------------------------------------

    def add_node(self, node: RecoveryNode) -> None:
        """Add or replace a node in the graph."""
        self._nodes[node.node_id] = node

    def add_edge(self, edge: RecoveryEdge) -> None:
        """Add an edge. Both source and target must exist as nodes."""
        self._adj[edge.source].append(edge)

    def set_entry(self, error_code: str, node_id: str) -> None:
        """Set the entry node for a given error code."""
        self._error_entry[error_code] = node_id

    # -- traversal --------------------------------------------------------

    def traverse(self, error_code: str) -> RecoveryPath:
        """Traverse the DAG from the entry node for *error_code*.

        Follows ``on_failure`` edges, preferring targets with the
        highest empirical success rate.  Stops at terminal or when
        all reachable nodes are visited (no cycles due to visited set).

        Returns a :class:`RecoveryPath` with the ordered list of nodes.
        """
        entry = self._error_entry.get(error_code, "retry_same")
        if entry not in self._nodes:
            entry = "retry_same"

        path_nodes: list[str] = []
        visited: set[str] = set()
        current: Optional[str] = entry
        total_cost = 0.0
        combined_success = 1.0

        while current and current not in visited:
            node = self._nodes.get(current)
            if not node or current == "noop_terminal":
                break

            visited.add(current)
            path_nodes.append(current)
            total_cost += node.cost_ms
            # Combined P(at least one succeeds) via complementary probability
            combined_success = 1.0 - (1.0 - combined_success) * (1.0 - node.success_rate)

            # Follow on_failure edge (since we're building the fallback chain)
            failure_edges = [
                e for e in self._adj.get(current, [])
                if e.edge_type == "on_failure" and e.target not in visited
            ]
            if not failure_edges:
                break

            # Pick the target with highest success_rate
            best_edge = max(
                failure_edges,
                key=lambda e: self._nodes[e.target].success_rate if e.target in self._nodes else 0.0,
            )
            current = best_edge.target

        return RecoveryPath(
            error_code=error_code,
            nodes=path_nodes,
            estimated_cost_ms=total_cost,
            estimated_success_rate=round(combined_success, 4),
        )

    async def execute(
        self,
        path: RecoveryPath,
        context: dict[str, Any],
    ) -> RecoveryResult:
        """Execute a recovery path node-by-node.

        For each node, checks the node's ``condition`` (if any),
        then invokes the action handler registered in *context*
        under ``context["handlers"][node_id]``.

        The first node whose handler returns a truthy result
        causes the traversal to stop with ``succeeded=True``.

        Args:
            path: The recovery path from :meth:`traverse`.
            context: Runtime context including ``handlers`` dict
                     mapping node IDs to async callables.

        Returns:
            A :class:`RecoveryResult`.
        """
        handlers = context.get("handlers", {})
        traversed: list[str] = []
        t0 = time.monotonic()

        for node_id in path.nodes:
            node = self._nodes.get(node_id)
            if not node:
                continue

            traversed.append(node_id)

            # Check condition gate
            if node.condition is not None:
                try:
                    if not node.condition(context):
                        logger.debug("Node %s condition not met — skipping", node_id)
                        continue
                except Exception:
                    continue

            handler = handlers.get(node_id)
            if handler is None:
                logger.debug("No handler for node %s — skipping", node_id)
                continue

            try:
                result = await handler(context)
                self.update_empirical(node_id, succeeded=True, latency_ms=(time.monotonic() - t0) * 1000)
                return RecoveryResult(
                    error_code=path.error_code,
                    succeeded=True,
                    node_used=node_id,
                    attempts=len(traversed),
                    total_latency_ms=(time.monotonic() - t0) * 1000,
                    path_traversed=traversed,
                    data=result,
                )
            except Exception as exc:
                logger.warning("Recovery node %s failed: %s", node_id, exc)
                self.update_empirical(node_id, succeeded=False, latency_ms=(time.monotonic() - t0) * 1000)

        return RecoveryResult(
            error_code=path.error_code,
            succeeded=False,
            node_used=traversed[-1] if traversed else "",
            attempts=len(traversed),
            total_latency_ms=(time.monotonic() - t0) * 1000,
            path_traversed=traversed,
        )

    # -- empirical updates ------------------------------------------------

    def update_empirical(
        self,
        node_id: str,
        succeeded: bool,
        latency_ms: float,
    ) -> None:
        """Update the success rate of *node_id* with a new observation.

        Uses an exponential moving average so recent observations are
        weighted more heavily.
        """
        node = self._nodes.get(node_id)
        if not node:
            return

        node.total_attempts += 1
        if succeeded:
            node.total_successes += 1

        # EMA with α = 0.1
        alpha = 0.1
        observation = 1.0 if succeeded else 0.0
        node.success_rate = (1.0 - alpha) * node.success_rate + alpha * observation

        # Update cost estimate
        node.cost_ms = (1.0 - alpha) * node.cost_ms + alpha * latency_ms

    # -- topological sort -------------------------------------------------

    def topological_sort(self) -> list[str]:
        """Return nodes in topological order. Raises if a cycle is detected.

        Uses Kahn's algorithm (BFS with in-degree tracking).
        """
        in_degree: dict[str, int] = {nid: 0 for nid in self._nodes}
        for edges in self._adj.values():
            for edge in edges:
                if edge.target in in_degree:
                    in_degree[edge.target] += 1

        queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
        result: list[str] = []

        while queue:
            nid = queue.popleft()
            result.append(nid)
            for edge in self._adj.get(nid, []):
                if edge.target in in_degree:
                    in_degree[edge.target] -= 1
                    if in_degree[edge.target] == 0:
                        queue.append(edge.target)

        if len(result) != len(self._nodes):
            visited_set = set(result)
            cycle_nodes = [n for n in self._nodes if n not in visited_set]
            raise ValueError(f"Cycle detected involving nodes: {cycle_nodes}")

        return result

    # -- visualization ----------------------------------------------------

    def visualize(self) -> str:
        """Return a DOT-format string for Graphviz.

        Nodes show ``node_id`` and current ``success_rate``.
        Edges are styled solid (on_success, green) or dashed (on_failure, red).
        """
        lines: list[str] = ["digraph RecoveryGraph {", "  rankdir=LR;", "  node [shape=box, style=rounded];"]

        for nid, node in self._nodes.items():
            label = f"{nid}\\nsr={node.success_rate:.2f} cost={node.cost_ms:.0f}ms"
            color = "green" if node.success_rate >= 0.7 else ("orange" if node.success_rate >= 0.4 else "red")
            lines.append(f'  "{nid}" [label="{label}", color="{color}"];')

        for source, edges in self._adj.items():
            for edge in edges:
                style = "solid" if edge.edge_type == "on_success" else "dashed"
                color = "green" if edge.edge_type == "on_success" else "red"
                lines.append(f'  "{source}" -> "{edge.target}" [style={style}, color={color}, label="{edge.edge_type}"];')

        lines.append("}")
        return "\n".join(lines)

    # -- introspection ----------------------------------------------------

    @property
    def node_ids(self) -> list[str]:
        """All registered node IDs."""
        return list(self._nodes.keys())

    @property
    def edge_count(self) -> int:
        """Total number of edges."""
        return sum(len(edges) for edges in self._adj.values())

    def get_node(self, node_id: str) -> Optional[RecoveryNode]:
        """Return the node with *node_id*, or ``None``."""
        return self._nodes.get(node_id)

    def get_edges(self, node_id: str) -> list[RecoveryEdge]:
        """Return outgoing edges from *node_id*."""
        return list(self._adj.get(node_id, []))
