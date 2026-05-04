"""Horizon Orchestra — Multi-Agent Communication.

Message bus, shared blackboard, and handoff protocol for coordinating
multiple agents.  This is the kernel-level communication layer that
Architecture C's swarm builds on.

Patterns:
1. **Message Bus** — async pub/sub for agent-to-agent messages
2. **Blackboard** — shared key-value state that all agents can read/write
3. **Handoff** — structured task transfer between agents with context

Usage::

    from orchestra.multiagent import MessageBus, Blackboard, HandoffProtocol

    bus = MessageBus()
    bus.subscribe("research_done", callback)
    await bus.publish("research_done", {"findings": "..."})

    board = Blackboard()
    await board.write("research_results", data)
    data = await board.read("research_results")
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

__all__ = [
    "Message",
    "MessageBus",
    "Blackboard",
    "HandoffProtocol",
    "HandoffRequest",
    "AgentIdentity",
]

log = logging.getLogger("orchestra.multiagent")


# ---------------------------------------------------------------------------
# Agent identity
# ---------------------------------------------------------------------------

@dataclass
class AgentIdentity:
    """Identity of an agent in the multi-agent system."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    role: str = ""                       # planner, researcher, coder, reviewer, etc.
    model: str = "kimi-k2.5"
    capabilities: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Message bus (pub/sub)
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A message on the bus."""
    topic: str
    payload: dict[str, Any]
    sender: str = ""                     # agent ID
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    reply_to: str = ""                   # message ID this replies to


MessageHandler = Callable[[Message], Awaitable[None]]


class MessageBus:
    """Async pub/sub message bus for agent-to-agent communication.

    Agents subscribe to topics and receive messages asynchronously.
    Supports request/reply patterns via ``reply_to``.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[MessageHandler]] = {}
        self._history: list[Message] = []
        self._pending_replies: dict[str, asyncio.Future] = {}
        self._max_history = 1000

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        """Subscribe to a topic."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(handler)
        log.debug("Subscribed to topic: %s", topic)

    def unsubscribe(self, topic: str, handler: MessageHandler) -> None:
        if topic in self._subscribers:
            self._subscribers[topic] = [h for h in self._subscribers[topic] if h != handler]

    async def publish(self, topic: str, payload: dict[str, Any], sender: str = "", reply_to: str = "") -> Message:
        """Publish a message to a topic."""
        msg = Message(
            topic=topic, payload=payload,
            sender=sender, reply_to=reply_to,
        )
        self._history.append(msg)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Notify subscribers
        handlers = self._subscribers.get(topic, []) + self._subscribers.get("*", [])
        for handler in handlers:
            try:
                await handler(msg)
            except Exception as exc:
                log.error("Message handler error on topic %s: %s", topic, exc)

        # Resolve pending reply futures
        if reply_to and reply_to in self._pending_replies:
            self._pending_replies[reply_to].set_result(msg)

        return msg

    async def request(self, topic: str, payload: dict[str, Any], sender: str = "", timeout: float = 60.0) -> Message | None:
        """Publish a message and wait for a reply."""
        msg = await self.publish(topic, payload, sender=sender)
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_replies[msg.id] = future

        try:
            reply = await asyncio.wait_for(future, timeout=timeout)
            return reply
        except asyncio.TimeoutError:
            log.warning("Request timeout on topic %s (msg %s)", topic, msg.id)
            return None
        finally:
            self._pending_replies.pop(msg.id, None)

    def get_history(self, topic: str = "", limit: int = 50) -> list[dict[str, Any]]:
        msgs = self._history
        if topic:
            msgs = [m for m in msgs if m.topic == topic]
        return [
            {"id": m.id, "topic": m.topic, "sender": m.sender, "payload": m.payload, "ts": m.timestamp}
            for m in msgs[-limit:]
        ]


# ---------------------------------------------------------------------------
# Blackboard (shared state)
# ---------------------------------------------------------------------------

class Blackboard:
    """Shared key-value state accessible by all agents.

    Supports versioning — every write creates a new version.
    Agents can watch keys for changes.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._versions: dict[str, int] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._watchers: dict[str, list[Callable]] = {}
        self._lock = asyncio.Lock()

    async def write(self, key: str, value: Any, author: str = "") -> int:
        """Write a value. Returns the new version number."""
        async with self._lock:
            self._data[key] = value
            version = self._versions.get(key, 0) + 1
            self._versions[key] = version

            # Track history
            if key not in self._history:
                self._history[key] = []
            self._history[key].append({
                "version": version, "value": value,
                "author": author, "ts": time.time(),
            })

        # Notify watchers
        for watcher in self._watchers.get(key, []):
            try:
                await watcher(key, value, version)
            except Exception as exc:
                log.error("Blackboard watcher error on %s: %s", key, exc)

        return version

    async def read(self, key: str, default: Any = None) -> Any:
        """Read the current value."""
        return self._data.get(key, default)

    async def read_version(self, key: str) -> int:
        return self._versions.get(key, 0)

    async def read_history(self, key: str, limit: int = 10) -> list[dict[str, Any]]:
        return self._history.get(key, [])[-limit:]

    def watch(self, key: str, callback: Callable) -> None:
        """Register a callback for changes to a key."""
        if key not in self._watchers:
            self._watchers[key] = []
        self._watchers[key].append(callback)

    async def keys(self) -> list[str]:
        return list(self._data.keys())

    async def snapshot(self) -> dict[str, Any]:
        """Full snapshot of the blackboard state."""
        return {
            "keys": list(self._data.keys()),
            "versions": dict(self._versions),
            "data": {k: str(v)[:200] for k, v in self._data.items()},
        }


# ---------------------------------------------------------------------------
# Handoff protocol
# ---------------------------------------------------------------------------

@dataclass
class HandoffRequest:
    """A structured task handoff between agents."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    from_agent: AgentIdentity = field(default_factory=AgentIdentity)
    to_agent: AgentIdentity = field(default_factory=AgentIdentity)
    task: str = ""
    context: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)   # file paths, data refs
    priority: str = "medium"
    status: str = "pending"        # pending, accepted, completed, rejected
    result: str = ""
    created_at: float = field(default_factory=time.time)


class HandoffProtocol:
    """Manages task handoffs between agents.

    An agent completes part of a task and hands off to a specialist:
    1. Create a HandoffRequest with context + artifacts
    2. Target agent accepts and executes
    3. Result flows back to the originator
    """

    def __init__(self, bus: MessageBus | None = None, board: Blackboard | None = None) -> None:
        self.bus = bus or MessageBus()
        self.board = board or Blackboard()
        self._handoffs: dict[str, HandoffRequest] = {}

    async def initiate(
        self,
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
        task: str,
        context: str = "",
        artifacts: dict[str, str] | None = None,
        priority: str = "medium",
    ) -> HandoffRequest:
        """Initiate a handoff from one agent to another."""
        handoff = HandoffRequest(
            from_agent=from_agent,
            to_agent=to_agent,
            task=task,
            context=context,
            artifacts=artifacts or {},
            priority=priority,
        )
        self._handoffs[handoff.id] = handoff

        # Publish on the bus
        await self.bus.publish(
            topic=f"handoff.{to_agent.role}",
            payload={
                "handoff_id": handoff.id,
                "task": task,
                "from": from_agent.name,
                "priority": priority,
            },
            sender=from_agent.id,
        )

        # Write to blackboard
        await self.board.write(
            f"handoff:{handoff.id}",
            {"task": task, "status": "pending", "from": from_agent.name, "to": to_agent.name},
            author=from_agent.id,
        )

        log.info("Handoff %s: %s → %s: %s", handoff.id, from_agent.name, to_agent.name, task[:60])
        return handoff

    async def accept(self, handoff_id: str) -> HandoffRequest | None:
        """Mark a handoff as accepted."""
        h = self._handoffs.get(handoff_id)
        if not h:
            return None
        h.status = "accepted"
        await self.board.write(f"handoff:{handoff_id}", {"status": "accepted"}, author=h.to_agent.id)
        return h

    async def complete(self, handoff_id: str, result: str) -> HandoffRequest | None:
        """Mark a handoff as completed with results."""
        h = self._handoffs.get(handoff_id)
        if not h:
            return None
        h.status = "completed"
        h.result = result

        await self.board.write(
            f"handoff:{handoff_id}",
            {"status": "completed", "result": result[:2000]},
            author=h.to_agent.id,
        )

        # Notify the originator
        await self.bus.publish(
            topic=f"handoff_complete.{h.from_agent.role}",
            payload={"handoff_id": handoff_id, "result": result[:500]},
            sender=h.to_agent.id,
        )

        return h

    def get(self, handoff_id: str) -> HandoffRequest | None:
        return self._handoffs.get(handoff_id)

    def list_handoffs(self, status: str = "") -> list[dict[str, Any]]:
        handoffs = list(self._handoffs.values())
        if status:
            handoffs = [h for h in handoffs if h.status == status]
        return [
            {
                "id": h.id, "task": h.task[:80],
                "from": h.from_agent.name, "to": h.to_agent.name,
                "status": h.status, "priority": h.priority,
            }
            for h in handoffs
        ]
