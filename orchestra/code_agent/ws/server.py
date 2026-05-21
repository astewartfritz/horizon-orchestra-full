from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


class WSEvent(Enum):
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    AGENT_THINKING = "agent_thinking"
    AGENT_MESSAGE = "agent_message"
    SESSION_EVENT = "session_event"
    COST_UPDATE = "cost_update"
    HEARTBEAT = "heartbeat"
    LOG = "log"


@dataclass
class WSMessage:
    event: str
    data: dict = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_json(self) -> str:
        return json.dumps({"event": self.event, "data": self.data, "timestamp": self.timestamp})


class WebSocketServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8500):
        self.host = host
        self.port = port
        self.clients: set[Any] = set()
        self._server: Any = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._handlers: dict[str, list[Callable]] = {}
        self._connected: set[str] = set()
        self.logger = logging.getLogger("ws")

    async def start(self):
        if not HAS_WEBSOCKETS:
            print("websockets not installed. Install with: pip install websockets")
            return

        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            ping_interval=30,
            ping_timeout=10,
        )
        print(f"WebSocket server running at ws://{self.host}:{self.port}")
        asyncio.create_task(self._broadcast_heartbeat())

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def broadcast(self, event: WSEvent, data: dict = None):
        msg = WSMessage(event=event.value, data=data or {})
        payload = msg.to_json()
        dead = set()
        for client in self.clients:
            try:
                await client.send(payload)
            except Exception:
                dead.add(client)
        self.clients -= dead

    async def send_to(self, client_id: str, event: WSEvent, data: dict = None):
        for client in self.clients:
            cid = getattr(client, "id", "")
            if cid == client_id:
                try:
                    await client.send(WSMessage(event=event.value, data=data or {}).to_json())
                except Exception:
                    pass

    def on(self, event: str, handler: Callable):
        self._handlers.setdefault(event, []).append(handler)

    async def _handle_client(self, websocket):
        client_id = f"client-{int(time.time() * 1000)}"
        self.clients.add(websocket)
        self._connected.add(client_id)
        self.logger.info(f"Client connected: {client_id}")

        try:
            await websocket.send(WSMessage(event=WSEvent.HEARTBEAT.value, data={"client_id": client_id}).to_json())

            async for message in websocket:
                try:
                    data = json.loads(message)
                    event = data.get("event", "")
                    payload = data.get("data", {})

                    if event == "ping":
                        await websocket.send(WSMessage(event="pong", data={"time": datetime.now().isoformat()}).to_json())

                    for handler in self._handlers.get(event, []):
                        if asyncio.iscoroutinefunction(handler):
                            await handler(payload)
                        else:
                            handler(payload)

                except json.JSONDecodeError:
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            self._connected.discard(client_id)
            self.logger.info(f"Client disconnected: {client_id}")

    async def _broadcast_heartbeat(self):
        while True:
            await asyncio.sleep(30)
            if self.clients:
                await self.broadcast(WSEvent.HEARTBEAT, {"time": datetime.now().isoformat(), "clients": len(self.clients)})

    @property
    def client_count(self) -> int:
        return len(self.clients)

    def summary_text(self) -> str:
        return (
            f"WebSocket Server\n"
            f"{'=' * 40}\n"
            f"Host:    {self.host}:{self.port}\n"
            f"Clients: {self.client_count}\n"
            f"Running: {self._server is not None and hasattr(self._server, 'is_serving')}"
        )
