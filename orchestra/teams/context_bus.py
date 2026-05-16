"""Horizon Orchestra — Context Bus for Inter-Agent Communication.

The :class:`ContextBus` provides a thread-safe publish/subscribe bus,
direct agent-to-agent messaging, and a shared-state key-value store.
All delivery is backed by :mod:`asyncio` primitives (``Queue`` and
``Event``) so the bus works without any external message broker.

Topics are hierarchically namespaced:

- ``task.<task_id>.result``  — Result payload for a finished task.
- ``task.<task_id>.status``  — Status transitions (queued → active → done).
- ``agent.<agent_id>.status`` — Agent heartbeat / status changes.
- ``team.broadcast``         — Fan-out messages to every agent.
- ``context.<key>``          — Shared-state change notifications.

Example usage::

    bus = ContextBus(capacity=5000)
    await bus.subscribe("task.*", callback=on_task_event, agent_id="coordinator")
    mid = await bus.publish("task.42.result", {"answer": "42"}, from_agent="analyst")
    await bus.send(to_agent="writer", payload={"draft": "…"}, from_agent="analyst")
    msgs = await bus.receive("writer", timeout=5)
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Deque, Dict, List, Optional, Set

__all__ = [
    "ContextBus",
    "ContextMessage",
    "Subscription",
    "BusStats",
]

log = logging.getLogger("orchestra.teams.context_bus")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ContextMessage:
    """Single message flowing through the bus."""

    message_id: str
    topic: str
    payload: Any
    from_agent: str
    timestamp: float
    ttl_seconds: float = 3600.0
    is_direct: bool = False
    to_agent: Optional[str] = None

    # ── helpers ────────────────────────────────────────────────────────────
    @property
    def is_expired(self) -> bool:
        """Return ``True`` when the message's TTL has elapsed."""
        return (time.time() - self.timestamp) > self.ttl_seconds

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "message_id": self.message_id,
            "topic": self.topic,
            "payload": self.payload,
            "from_agent": self.from_agent,
            "timestamp": self.timestamp,
            "ttl_seconds": self.ttl_seconds,
            "is_direct": self.is_direct,
            "to_agent": self.to_agent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContextMessage":
        """Deserialise from a dictionary."""
        return cls(**data)

    def __repr__(self) -> str:  # pragma: no cover
        direction = f" → {self.to_agent}" if self.to_agent else ""
        return (
            f"<ContextMessage {self.message_id[:8]} "
            f"topic={self.topic!r} from={self.from_agent}{direction}>"
        )


@dataclass
class Subscription:
    """A single topic subscription held by an agent."""

    subscription_id: str
    topic_pattern: str
    callback: Callable[[ContextMessage], Awaitable[None]]
    agent_id: str
    created_at: float = field(default_factory=time.time)

    def matches(self, topic: str) -> bool:
        """Check if *topic* matches this subscription's glob pattern."""
        return fnmatch.fnmatch(topic, self.topic_pattern)


@dataclass
class BusStats:
    """Snapshot of bus statistics."""

    total_published: int = 0
    total_delivered: int = 0
    total_direct_messages: int = 0
    active_subscriptions: int = 0
    topic_count: int = 0
    shared_state_keys: int = 0
    agents_registered: int = 0
    bus_uptime_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Return stats as a plain dictionary."""
        return {
            "total_published": self.total_published,
            "total_delivered": self.total_delivered,
            "total_direct_messages": self.total_direct_messages,
            "active_subscriptions": self.active_subscriptions,
            "topic_count": self.topic_count,
            "shared_state_keys": self.shared_state_keys,
            "agents_registered": self.agents_registered,
            "bus_uptime_seconds": self.bus_uptime_seconds,
        }


# ---------------------------------------------------------------------------
# ContextBus
# ---------------------------------------------------------------------------

class ContextBus:
    """Thread-safe publish/subscribe bus for inter-agent communication.

    The bus maintains a ring buffer (``deque``) per topic for history,
    fan-out delivery to matching subscribers, direct agent-to-agent
    message queues, and a shared key-value store for team-wide state.

    All operations are ``async`` and safe to call concurrently from
    multiple agents running in the same event loop.

    Parameters
    ----------
    capacity:
        Maximum number of messages retained in each per-topic ring
        buffer.  Older messages are evicted when the buffer is full.
    default_ttl_seconds:
        Default time-to-live for published messages.
    """

    def __init__(
        self,
        capacity: int = 10_000,
        default_ttl_seconds: float = 3600.0,
    ) -> None:
        # Configuration
        self._capacity = capacity
        self._default_ttl = default_ttl_seconds

        # Topic history ring buffers
        self._topic_buffers: Dict[str, Deque[ContextMessage]] = defaultdict(
            lambda: deque(maxlen=self._capacity)
        )

        # Subscriptions keyed by subscription_id
        self._subscriptions: Dict[str, Subscription] = {}
        # Quick lookup: topic → list of subscription_ids (rebuilt on change)
        self._topic_subs: Dict[str, List[str]] = defaultdict(list)

        # Direct message queues per agent_id
        self._dm_queues: Dict[str, asyncio.Queue[ContextMessage]] = {}
        self._dm_events: Dict[str, asyncio.Event] = {}

        # Shared state (KV store)
        self._shared_state: Dict[str, Any] = {}
        self._shared_state_meta: Dict[str, dict] = {}

        # Stats
        self._total_published: int = 0
        self._total_delivered: int = 0
        self._total_direct: int = 0
        self._start_time: float = time.time()

        # Lock for shared-state writes
        self._state_lock = asyncio.Lock()
        # Lock for subscription mutations
        self._sub_lock = asyncio.Lock()

        log.debug("ContextBus initialised (capacity=%d)", capacity)

    # ===================================================================
    # Publish / Subscribe
    # ===================================================================

    async def publish(
        self,
        topic: str,
        payload: Any,
        from_agent: str,
        ttl_seconds: Optional[float] = None,
    ) -> str:
        """Publish a message to *topic*.

        All subscriptions whose pattern matches *topic* will have their
        callback invoked asynchronously.  The message is also appended
        to the topic's ring buffer for later retrieval.

        Parameters
        ----------
        topic:
            Hierarchical topic string, e.g. ``"task.42.result"``.
        payload:
            Arbitrary data (should be JSON-serialisable).
        from_agent:
            ID of the publishing agent.
        ttl_seconds:
            Override the bus default TTL for this message.

        Returns
        -------
        str
            The unique ``message_id``.
        """
        msg = ContextMessage(
            message_id=uuid.uuid4().hex,
            topic=topic,
            payload=payload,
            from_agent=from_agent,
            timestamp=time.time(),
            ttl_seconds=ttl_seconds or self._default_ttl,
        )

        # Store in ring buffer
        self._topic_buffers[topic].append(msg)
        self._total_published += 1

        # Fan-out to matching subscriptions
        delivered = await self._fan_out(msg)
        self._total_delivered += delivered

        log.debug(
            "Published %s to topic=%r → %d deliveries",
            msg.message_id[:8],
            topic,
            delivered,
        )
        return msg.message_id

    async def subscribe(
        self,
        topic: str,
        callback: Callable[[ContextMessage], Awaitable[None]],
        agent_id: str,
    ) -> str:
        """Subscribe *agent_id* to messages matching *topic* (glob).

        Parameters
        ----------
        topic:
            Glob pattern, e.g. ``"task.*"`` or ``"agent.coder.status"``.
        callback:
            Async callable invoked for each matching message.
        agent_id:
            Subscribing agent's identifier.

        Returns
        -------
        str
            The ``subscription_id`` needed for :meth:`unsubscribe`.
        """
        sub = Subscription(
            subscription_id=uuid.uuid4().hex,
            topic_pattern=topic,
            callback=callback,
            agent_id=agent_id,
        )
        async with self._sub_lock:
            self._subscriptions[sub.subscription_id] = sub
            self._rebuild_topic_index()

        self._ensure_dm_queue(agent_id)
        log.debug(
            "Agent %s subscribed to %r (sub=%s)",
            agent_id,
            topic,
            sub.subscription_id[:8],
        )
        return sub.subscription_id

    async def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription by its ID.

        No-op if the subscription does not exist.
        """
        async with self._sub_lock:
            if subscription_id in self._subscriptions:
                del self._subscriptions[subscription_id]
                self._rebuild_topic_index()
                log.debug("Unsubscribed %s", subscription_id[:8])

    # ===================================================================
    # Direct Messaging
    # ===================================================================

    async def send(
        self,
        to_agent: str,
        payload: Any,
        from_agent: str,
        ttl_seconds: Optional[float] = None,
    ) -> str:
        """Send a direct message from one agent to another.

        The message is placed in the recipient's ``asyncio.Queue`` and
        the corresponding ``asyncio.Event`` is set so that a blocking
        :meth:`receive` call wakes up immediately.

        Returns
        -------
        str
            The ``message_id``.
        """
        msg = ContextMessage(
            message_id=uuid.uuid4().hex,
            topic=f"dm.{from_agent}.{to_agent}",
            payload=payload,
            from_agent=from_agent,
            timestamp=time.time(),
            ttl_seconds=ttl_seconds or self._default_ttl,
            is_direct=True,
            to_agent=to_agent,
        )

        self._ensure_dm_queue(to_agent)
        await self._dm_queues[to_agent].put(msg)
        self._dm_events[to_agent].set()
        self._total_direct += 1

        log.debug(
            "DM %s → %s (%s)",
            from_agent,
            to_agent,
            msg.message_id[:8],
        )
        return msg.message_id

    async def receive(
        self,
        agent_id: str,
        timeout: float = 30.0,
    ) -> List[ContextMessage]:
        """Receive all pending direct messages for *agent_id*.

        Blocks up to *timeout* seconds waiting for at least one message.
        Returns an empty list on timeout.

        Parameters
        ----------
        agent_id:
            The receiving agent's identifier.
        timeout:
            Maximum seconds to wait.

        Returns
        -------
        list[ContextMessage]
            All messages currently queued for the agent.
        """
        self._ensure_dm_queue(agent_id)
        event = self._dm_events[agent_id]
        queue = self._dm_queues[agent_id]

        # Wait for at least one message (or timeout)
        if queue.empty():
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return []

        # Drain the queue
        messages: List[ContextMessage] = []
        while not queue.empty():
            try:
                msg = queue.get_nowait()
                if not msg.is_expired:
                    messages.append(msg)
            except asyncio.QueueEmpty:
                break

        # Reset the event if queue is now empty
        if queue.empty():
            event.clear()

        return messages

    # ===================================================================
    # Shared State (Key-Value)
    # ===================================================================

    async def set_shared(
        self,
        key: str,
        value: Any,
        from_agent: str,
    ) -> None:
        """Set a shared key-value pair visible to all agents.

        Also publishes a notification on topic ``context.<key>`` so
        subscribers are alerted to the change.

        Parameters
        ----------
        key:
            State key (e.g. ``"current_plan"``, ``"iteration_count"``).
        value:
            Any JSON-serialisable value.
        from_agent:
            Agent performing the write.
        """
        async with self._state_lock:
            self._shared_state[key] = value
            self._shared_state_meta[key] = {
                "updated_by": from_agent,
                "updated_at": time.time(),
            }

        # Notify subscribers of the state change
        await self.publish(
            topic=f"context.{key}",
            payload={"key": key, "value": value},
            from_agent=from_agent,
        )
        log.debug("Shared state set: %s (by %s)", key, from_agent)

    async def get_shared(self, key: str) -> Any:
        """Read a shared-state value.

        Returns ``None`` if the key has not been set.
        """
        return self._shared_state.get(key)

    async def list_shared_keys(self) -> List[str]:
        """Return all keys currently in the shared state store."""
        return list(self._shared_state.keys())

    async def get_shared_meta(self, key: str) -> Optional[dict]:
        """Return metadata (writer, timestamp) for a shared-state key."""
        return self._shared_state_meta.get(key)

    async def delete_shared(self, key: str, from_agent: str) -> bool:
        """Remove a shared-state key.  Returns ``True`` if the key existed."""
        async with self._state_lock:
            existed = key in self._shared_state
            self._shared_state.pop(key, None)
            self._shared_state_meta.pop(key, None)
        if existed:
            await self.publish(
                topic=f"context.{key}.deleted",
                payload={"key": key},
                from_agent=from_agent,
            )
        return existed

    # ===================================================================
    # History
    # ===================================================================

    async def get_topic_history(
        self,
        topic: str,
        limit: int = 100,
    ) -> List[ContextMessage]:
        """Return the most recent messages for a specific topic.

        Only non-expired messages are returned, up to *limit*.
        """
        buf = self._topic_buffers.get(topic, deque())
        now = time.time()
        result: List[ContextMessage] = []
        for msg in reversed(buf):
            if (now - msg.timestamp) <= msg.ttl_seconds:
                result.append(msg)
                if len(result) >= limit:
                    break
        result.reverse()
        return result

    async def get_all_topics(self) -> List[str]:
        """Return a sorted list of all topics that have at least one message."""
        return sorted(self._topic_buffers.keys())

    async def clear_topic(self, topic: str) -> int:
        """Remove all messages from a topic buffer.  Returns count removed."""
        buf = self._topic_buffers.pop(topic, deque())
        return len(buf)

    # ===================================================================
    # Stats
    # ===================================================================

    def get_stats(self) -> BusStats:
        """Return a snapshot of bus-wide statistics."""
        return BusStats(
            total_published=self._total_published,
            total_delivered=self._total_delivered,
            total_direct_messages=self._total_direct,
            active_subscriptions=len(self._subscriptions),
            topic_count=len(self._topic_buffers),
            shared_state_keys=len(self._shared_state),
            agents_registered=len(self._dm_queues),
            bus_uptime_seconds=time.time() - self._start_time,
        )

    # ===================================================================
    # Agent Registration helpers
    # ===================================================================

    def register_agent(self, agent_id: str) -> None:
        """Pre-register an agent so its DM queue is ready."""
        self._ensure_dm_queue(agent_id)

    def deregister_agent(self, agent_id: str) -> None:
        """Remove an agent's DM queue and all its subscriptions."""
        self._dm_queues.pop(agent_id, None)
        self._dm_events.pop(agent_id, None)
        # Remove subscriptions belonging to this agent
        to_remove = [
            sid for sid, sub in self._subscriptions.items()
            if sub.agent_id == agent_id
        ]
        for sid in to_remove:
            del self._subscriptions[sid]
        if to_remove:
            self._rebuild_topic_index()

    # ===================================================================
    # Lifecycle
    # ===================================================================

    async def shutdown(self) -> None:
        """Gracefully shut down the bus.

        Drains remaining queues and clears state.
        """
        log.info(
            "ContextBus shutting down — %d msgs published, %d delivered",
            self._total_published,
            self._total_delivered,
        )
        self._subscriptions.clear()
        self._topic_subs.clear()
        self._topic_buffers.clear()
        self._dm_queues.clear()
        self._dm_events.clear()
        self._shared_state.clear()
        self._shared_state_meta.clear()

    def __repr__(self) -> str:  # pragma: no cover
        stats = self.get_stats()
        return (
            f"<ContextBus subs={stats.active_subscriptions} "
            f"topics={stats.topic_count} "
            f"published={stats.total_published} "
            f"agents={stats.agents_registered}>"
        )

    # ===================================================================
    # Internal helpers
    # ===================================================================

    def _ensure_dm_queue(self, agent_id: str) -> None:
        """Lazily create a DM queue + event for an agent."""
        if agent_id not in self._dm_queues:
            self._dm_queues[agent_id] = asyncio.Queue()
            self._dm_events[agent_id] = asyncio.Event()

    def _rebuild_topic_index(self) -> None:
        """Rebuild the topic → subscription_ids index.

        Called after any subscription add/remove while holding
        ``_sub_lock``.  We keep a flat index for O(1) exact-match and
        fall back to glob matching for wildcard patterns.
        """
        self._topic_subs.clear()
        for sid, sub in self._subscriptions.items():
            self._topic_subs[sub.topic_pattern].append(sid)

    async def _fan_out(self, msg: ContextMessage) -> int:
        """Deliver *msg* to all matching subscriptions.

        Returns the number of successful deliveries.
        """
        delivered = 0
        for sid, sub in list(self._subscriptions.items()):
            if sub.matches(msg.topic):
                try:
                    await sub.callback(msg)
                    delivered += 1
                except Exception:
                    log.exception(
                        "Subscriber %s callback failed for %s",
                        sid[:8],
                        msg.message_id[:8],
                    )
        return delivered

    async def _purge_expired(self) -> int:
        """Remove expired messages from all topic buffers.

        Returns the total number of messages purged.  This is intended
        to be called periodically (e.g. from a background task).
        """
        total_purged = 0
        now = time.time()
        for topic, buf in list(self._topic_buffers.items()):
            before = len(buf)
            self._topic_buffers[topic] = deque(
                (m for m in buf if (now - m.timestamp) <= m.ttl_seconds),
                maxlen=self._capacity,
            )
            after = len(self._topic_buffers[topic])
            total_purged += before - after
            # Remove empty buffers
            if after == 0:
                del self._topic_buffers[topic]
        if total_purged:
            log.debug("Purged %d expired messages", total_purged)
        return total_purged
