import asyncio
import uuid
import time
import logging
from typing import Callable

from code_agent.agentmesh.protocol import MeshMessage, MessageType
from code_agent.agentmesh.registry import AgentRegistry, AgentStatus
from code_agent.agentmesh.node import AgentNode

logger = logging.getLogger(__name__)


class MeshRouter:
    def __init__(self, registry: AgentRegistry):
        self._registry = registry
        self._routes: list[tuple[str, str, Callable]] = []

    def add_route(self, source_pattern: str, target_capability: str, condition: Callable | None = None):
        self._routes.append((source_pattern, target_capability, condition))

    async def route(self, message: MeshMessage, nodes: dict[str, AgentNode]) -> list[AgentNode]:
        targets: list[AgentNode] = []

        if message.target_id and message.target_id in nodes:
            node = nodes[message.target_id]
            if node.is_available():
                return [node]
            return []

        if message.target_capability:
            agents = self._registry.discover_by_capability(message.target_capability)
            target_ids = {a.id for a in agents}
            targets = [nodes[a_id] for a_id in target_ids if a_id in nodes and nodes[a_id].is_available()]
            if targets:
                return targets

        connected_ids = set(nodes.keys()) & {a.id for a in self._registry.list_agents() if a.is_available()}
        return [nodes[a_id] for a_id in connected_ids if nodes[a_id].is_available()]


class MeshNetwork:
    def __init__(self, registry: AgentRegistry | None = None):
        self._registry = registry or AgentRegistry()
        self._nodes: dict[str, AgentNode] = {}
        self._router = MeshRouter(self._registry)
        self._trace_store: dict[str, list[MeshMessage]] = {}
        self._handler: Callable | None = None
        self._running = False
        self._broadcast_queue: asyncio.Queue = asyncio.Queue()

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    @property
    def router(self) -> MeshRouter:
        return self._router

    def register_node(self, node: AgentNode):
        self._nodes[node.id] = node
        if node.info.id not in self._registry.list_agents():
            self._registry.register(node.info)
        node.set_message_callback(self._on_node_response)

    async def _on_node_response(self, message: MeshMessage):
        self._trace(message)

    def unregister_node(self, node_id: str):
        self._nodes.pop(node_id, None)
        self._registry.unregister(node_id)

    def get_node(self, node_id: str) -> AgentNode | None:
        return self._nodes.get(node_id)

    def list_nodes(self) -> list[AgentNode]:
        return list(self._nodes.values())

    def set_global_handler(self, handler: Callable):
        self._handler = handler

    def _trace(self, message: MeshMessage):
        trace_id = message.trace_id or message.id
        self._trace_store.setdefault(trace_id, []).append(message)

    def get_trace(self, trace_id: str) -> list[MeshMessage]:
        return self._trace_store.get(trace_id, [])

    def get_all_traces(self) -> dict[str, list[MeshMessage]]:
        return dict(self._trace_store)

    async def send(self, message: MeshMessage) -> list[MeshMessage]:
        self._trace(message)
        if self._handler:
            await self._handler(message)
        targets = await self._router.route(message, self._nodes)
        if not targets:
            return []

        async def send_to(target: AgentNode) -> MeshMessage | None:
            msg = MeshMessage(
                id=uuid.uuid4().hex,
                sender_id=self._nodes.get(message.sender_id, object()).id if message.sender_id in self._nodes else message.sender_id,
                target_id=target.id,
                message_type=message.message_type,
                content=message.content,
                metadata=message.metadata,
                parent_id=message.id,
                trace_id=message.trace_id or message.id,
            )
            target.enqueue_message(msg)
            return msg

        results = await asyncio.gather(*[send_to(t) for t in targets], return_exceptions=True)
        responses = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"MeshNetwork send error: {r}")
            elif r is not None:
                responses.append(r)
        return responses

    async def broadcast(self, message: MeshMessage) -> list[MeshMessage]:
        message.message_type = MessageType.BROADCAST
        targets = [n for n in self._nodes.values() if n.is_available()]

        async def broadcast_to(target: AgentNode) -> MeshMessage | None:
            msg = MeshMessage(
                id=uuid.uuid4().hex,
                sender_id=message.sender_id,
                target_id=target.id,
                message_type=MessageType.BROADCAST,
                content=message.content,
                metadata=message.metadata,
                parent_id=message.id,
                trace_id=message.trace_id or message.id,
            )
            target.enqueue_message(msg)
            return msg

        results = await asyncio.gather(*[broadcast_to(t) for t in targets], return_exceptions=True)
        responses = [r for r in results if isinstance(r, MeshMessage)]
        return responses

    async def request(self, target_id: str, content: str, sender_id: str = "", metadata: dict | None = None) -> MeshMessage | None:
        msg = MeshMessage(
            sender_id=sender_id,
            target_id=target_id,
            message_type=MessageType.REQUEST,
            content=content,
            metadata=metadata or {},
        )
        self._trace(msg)
        target = self._nodes.get(target_id)
        if not target or not target.is_available():
            return None

        response_event = asyncio.Event()
        response_data = {"message": None}

        orig_callback = target._message_callback

        async def wait_for_response(response: MeshMessage):
            if response.parent_id == msg.id:
                response_data["message"] = response
                response_event.set()
                return True
            if orig_callback:
                await orig_callback(response)
            return False

        target.set_message_callback(wait_for_response)
        target.enqueue_message(msg)
        try:
            await asyncio.wait_for(response_event.wait(), timeout=30.0)
            result = response_data["message"]
            if result:
                self._trace(result)
            return result
        except asyncio.TimeoutError:
            return MeshMessage(
                sender_id=target_id,
                target_id=sender_id,
                message_type=MessageType.ERROR,
                content="timeout",
                parent_id=msg.id,
                trace_id=msg.trace_id,
            )
        finally:
            target.set_message_callback(orig_callback)

    async def request_by_capability(self, capability: str, content: str, sender_id: str = "") -> MeshMessage | None:
        agents = self._registry.discover_by_capability(capability)
        for agent_info in agents:
            if agent_info.id in self._nodes:
                result = await self.request(agent_info.id, content, sender_id)
                if result and result.message_type != MessageType.ERROR:
                    return result
        return None

    async def delegate(self, target_id: str, content: str, sender_id: str = "", metadata: dict | None = None) -> MeshMessage | None:
        msg = MeshMessage(
            sender_id=sender_id,
            target_id=target_id,
            message_type=MessageType.DELEGATE,
            content=content,
            metadata=metadata or {},
        )
        return await self.request(target_id, content, sender_id, metadata)

    async def start(self):
        self._running = True
        for node in self._nodes.values():
            if not node._running:
                await node.start(self._registry)

    async def stop(self):
        self._running = False
        for node in self._nodes.values():
            await node.stop(self._registry)

    async def health(self) -> dict:
        total = len(self._nodes)
        online = sum(1 for n in self._nodes.values() if n.info.status == AgentStatus.ONLINE)
        busy = sum(1 for n in self._nodes.values() if n.info.status == AgentStatus.BUSY)
        return {
            "total_nodes": total,
            "online": online,
            "busy": busy,
            "offline": total - online - busy,
            "registered_agents": len(self._registry.list_agents()),
            "traces": len(self._trace_store),
        }

