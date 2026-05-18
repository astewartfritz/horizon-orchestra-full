import asyncio
import time
import logging
from typing import Callable

from code_agent.agentmesh.protocol import MeshMessage, MessageType
from code_agent.agentmesh.registry import AgentInfo, AgentType, AgentStatus

logger = logging.getLogger(__name__)


class AgentNode:
    def __init__(self, info: AgentInfo, agent=None, llm_model: str = ""):
        self.info = info
        self._agent = agent
        self._handlers: dict[MessageType, list[Callable]] = {}
        self._running = False
        self._heartbeat_task: asyncio.Task | None = None
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._message_callback: Callable | None = None
        self._llm_function = None

    @property
    def id(self) -> str:
        return self.info.id

    @property
    def agent(self):
        return self._agent

    @agent.setter
    def agent(self, value):
        self._agent = value

    def set_llm_function(self, fn: Callable):
        self._llm_function = fn

    def on_message(self, msg_type: MessageType, handler: Callable):
        self._handlers.setdefault(msg_type, []).append(handler)

    def set_message_callback(self, cb: Callable):
        self._message_callback = cb

    def is_available(self) -> bool:
        return self.info.is_available()

    async def handle_message(self, message: MeshMessage) -> MeshMessage | None:
        self.info.last_heartbeat = time.time()
        handlers = self._handlers.get(message.message_type, [])
        for handler in handlers:
            result = handler(self, message)
            if asyncio.iscoroutine(result):
                result = await result
            if result is not None:
                return result
        result = await self._default_handler(message)
        return result

    async def _default_handler(self, message: MeshMessage) -> MeshMessage | None:
        if message.message_type == MessageType.HEARTBEAT:
            return MeshMessage(
                sender_id=self.id,
                target_id=message.sender_id,
                message_type=MessageType.HEARTBEAT,
                content="alive",
                parent_id=message.id,
                trace_id=message.trace_id,
            )
        if message.message_type in (MessageType.REQUEST, MessageType.DELEGATE):
            response = await self._process_request(message.content, message.metadata)
            return MeshMessage(
                sender_id=self.id,
                target_id=message.sender_id,
                message_type=MessageType.RESPONSE,
                content=response,
                parent_id=message.id,
                trace_id=message.trace_id,
            )
        return None

    async def _process_request(self, content: str, metadata: dict) -> str:
        if self._llm_function:
            try:
                result = self._llm_function(content, metadata)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except Exception as e:
                return f"Error: {e}"
        if self._agent and hasattr(self._agent, "run"):
            try:
                return await self._agent.run(content)
            except Exception as e:
                return f"Agent error: {e}"
        return f"[{self.info.name}] received: {content}"

    def enqueue_message(self, message: MeshMessage):
        self._message_queue.put_nowait(message)

    async def process_queue(self):
        while self._running:
            try:
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                response = await self.handle_message(message)
                if response and self._message_callback:
                    await self._message_callback(response)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"AgentNode[{self.id}] queue error: {e}")

    async def start(self, registry=None):
        self._running = True
        if registry:
            self.info.status = AgentStatus.ONLINE
            registry.register(self.info)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(registry))
        asyncio.create_task(self.process_queue())

    async def stop(self, registry=None):
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if registry:
            self.info.status = AgentStatus.OFFLINE
            registry.heartbeat(self.id, AgentStatus.OFFLINE)

    async def _heartbeat_loop(self, registry=None):
        while self._running:
            await asyncio.sleep(15)
            if registry:
                registry.heartbeat(self.id, self.info.status)

    def to_info(self) -> AgentInfo:
        return self.info
