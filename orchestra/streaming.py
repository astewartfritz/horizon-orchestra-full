"""Horizon Orchestra — Streaming Protocol.

Server-Sent Events (SSE) and WebSocket streaming for real-time UI.
Converts AgentEvents into wire-format JSON frames that frontends
can consume.

Usage::

    # SSE endpoint (FastAPI)
    @app.get("/v1/stream")
    async def stream(task: str):
        return StreamingResponse(sse_stream(agent, task), media_type="text/event-stream")

    # WebSocket
    @app.websocket("/v1/ws")
    async def ws(websocket: WebSocket):
        await ws_stream(agent, websocket)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from .agent_loop import (
    AgentEvent,
    ToolCallEvent,
    ToolResultEvent,
    ThinkingEvent,
    FinalAnswerEvent,
    ErrorEvent,
)

__all__ = [
    "StreamFrame",
    "event_to_frame",
    "sse_stream",
    "ws_stream",
    "format_sse",
]

log = logging.getLogger("orchestra.streaming")


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

@dataclass
class StreamFrame:
    """A single frame in the streaming protocol."""
    event_type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    sequence: int = 0

    def to_json(self) -> str:
        return json.dumps({
            "type": self.event_type,
            "data": self.data,
            "ts": self.timestamp,
            "seq": self.sequence,
        })

    def to_sse(self) -> str:
        """Format as Server-Sent Event."""
        return f"event: {self.event_type}\ndata: {self.to_json()}\n\n"


def event_to_frame(event: AgentEvent, seq: int = 0) -> StreamFrame:
    """Convert an AgentEvent to a StreamFrame."""
    if isinstance(event, ToolCallEvent):
        return StreamFrame(
            event_type="tool_call",
            data={
                "iteration": event.iteration,
                "tool": event.tool_name,
                "arguments": event.arguments,
                "tool_call_id": event.tool_call_id,
            },
            sequence=seq,
        )
    elif isinstance(event, ToolResultEvent):
        return StreamFrame(
            event_type="tool_result",
            data={
                "iteration": event.iteration,
                "tool": event.tool_name,
                "success": event.success,
                "duration": round(event.duration, 3),
                "result_preview": event.result[:200],
            },
            sequence=seq,
        )
    elif isinstance(event, ThinkingEvent):
        return StreamFrame(
            event_type="thinking",
            data={"iteration": event.iteration, "content": event.content[:500]},
            sequence=seq,
        )
    elif isinstance(event, FinalAnswerEvent):
        return StreamFrame(
            event_type="final_answer",
            data={
                "content": event.content,
                "total_iterations": event.total_iterations,
                "total_tool_calls": event.total_tool_calls,
            },
            sequence=seq,
        )
    elif isinstance(event, ErrorEvent):
        return StreamFrame(
            event_type="error",
            data={
                "message": event.message,
                "iteration": event.iteration,
                "recoverable": event.recoverable,
            },
            sequence=seq,
        )
    else:
        return StreamFrame(
            event_type="unknown",
            data={"event": str(event)},
            sequence=seq,
        )


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------

async def sse_stream(
    agent: Any,
    task: str,
    context: str = "",
) -> AsyncGenerator[str, None]:
    """Yield Server-Sent Events from an agent execution.

    Use with FastAPI's StreamingResponse:
        return StreamingResponse(sse_stream(agent, task), media_type="text/event-stream")
    """
    seq = 0

    # Send initial "start" event
    start_frame = StreamFrame(
        event_type="start",
        data={"task": task[:200], "model": getattr(agent, "config", {})},
        sequence=seq,
    )
    yield start_frame.to_sse()
    seq += 1

    # Stream agent events
    async for event in agent.stream(task, context):
        frame = event_to_frame(event, seq)
        yield frame.to_sse()
        seq += 1

    # Send "done" event
    done_frame = StreamFrame(
        event_type="done",
        data={"total_frames": seq, "stats": getattr(agent, "stats", {})},
        sequence=seq,
    )
    yield done_frame.to_sse()


def format_sse(event_type: str, data: dict[str, Any]) -> str:
    """Format a raw SSE string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# WebSocket streaming
# ---------------------------------------------------------------------------

async def ws_stream(
    agent: Any,
    websocket: Any,
    task: str | None = None,
    context: str = "",
) -> None:
    """Stream agent events over a WebSocket connection.

    If *task* is None, reads the task from the first WebSocket message.
    """
    if task is None:
        msg = await websocket.receive_json()
        task = msg.get("task", "")
        context = msg.get("context", "")

    seq = 0

    # Start event
    await websocket.send_json({
        "type": "start", "data": {"task": task[:200]}, "seq": seq,
    })
    seq += 1

    # Stream
    async for event in agent.stream(task, context):
        frame = event_to_frame(event, seq)
        await websocket.send_json(json.loads(frame.to_json()))
        seq += 1

    # Done
    await websocket.send_json({
        "type": "done", "data": {"total_frames": seq}, "seq": seq,
    })
