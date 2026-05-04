"""
orchestra/token_streaming.py
------------------------------
Streaming token output — SSE chunked responses and WebSocket frames
for real-time UI rendering. Every character appears as the model
generates it, like a typing animation.
"""
from __future__ import annotations

__all__ = [
    "StreamingConfig",
    "TokenStreamer",
    "StreamChunk",
    "BufferedStreamer",
]

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

logger = logging.getLogger("orchestra.token_streaming")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StreamingConfig:
    """Configuration for streaming output."""

    enable_sse: bool = True
    enable_websocket: bool = True
    heartbeat_interval: float = 15.0  # seconds between heartbeat chunks
    buffer_size: int = 1               # flush every N tokens (1 = real-time)


@dataclass
class StreamChunk:
    """A single streaming chunk from the model or agent loop."""

    type: str  # "token" | "tool_call_start" | "tool_call_delta" | "tool_call_complete" | "finish" | "heartbeat" | "error"
    content: str = ""
    tool_call: dict | None = None
    finish_reason: str = ""
    sequence: int = 0

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "content": self.content,
            "tool_call": self.tool_call,
            "finish_reason": self.finish_reason,
            "sequence": self.sequence,
        }

    def to_sse(self) -> str:
        """Format as a Server-Sent Events data line."""
        return f"data: {json.dumps(self.to_dict())}\n\n"


# ---------------------------------------------------------------------------
# TokenStreamer
# ---------------------------------------------------------------------------

class TokenStreamer:
    """
    Wraps an OpenAI-compatible streaming completion and yields StreamChunks.

    Handles:
    - Token content deltas
    - Partial tool call JSON assembly
    - Heartbeat injection on silence
    - SSE and WebSocket output adapters
    """

    def __init__(self, config: StreamingConfig | None = None) -> None:
        self._config = config or StreamingConfig()

    async def stream_completion(
        self,
        client: Any,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream a completion from an OpenAI-compatible client.

        Yields ``StreamChunk`` objects for every token, tool call chunk,
        finish event, and heartbeat.
        """
        create_kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "stream": True,
            **kwargs,
        }
        if tools:
            create_kwargs["tools"] = tools

        sequence = 0
        last_data_time = time.time()
        heartbeat_interval = self._config.heartbeat_interval

        # Accumulator for in-flight tool calls keyed by index
        tool_call_accumulators: dict[int, dict] = {}

        try:
            stream = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.chat.completions.create(**create_kwargs),
            )
        except Exception as exc:
            logger.exception("stream_completion: error creating stream model=%s", model_id)
            yield StreamChunk(type="error", content=str(exc), sequence=sequence)
            return

        # Iterate over streaming chunks
        # We wrap the sync iterator in an async generator via run_in_executor
        chunk_queue: asyncio.Queue[Any] = asyncio.Queue()
        done_sentinel = object()

        def _fill_queue() -> None:
            try:
                for chunk in stream:
                    chunk_queue.put_nowait(chunk)
            except Exception as exc:
                chunk_queue.put_nowait(exc)
            finally:
                chunk_queue.put_nowait(done_sentinel)

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _fill_queue)

        while True:
            # Check heartbeat timeout while waiting
            try:
                raw_chunk = await asyncio.wait_for(
                    chunk_queue.get(), timeout=heartbeat_interval
                )
            except asyncio.TimeoutError:
                # No data for heartbeat_interval — emit heartbeat
                yield StreamChunk(
                    type="heartbeat",
                    content="",
                    sequence=sequence,
                )
                sequence += 1
                continue

            if raw_chunk is done_sentinel:
                break

            if isinstance(raw_chunk, Exception):
                logger.error("stream_completion: stream error: %s", raw_chunk)
                yield StreamChunk(
                    type="error",
                    content=str(raw_chunk),
                    sequence=sequence,
                )
                sequence += 1
                break

            last_data_time = time.time()
            delta = None
            finish_reason = ""

            # Extract delta from the chunk
            try:
                choice = raw_chunk.choices[0] if raw_chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta
                finish_reason = choice.finish_reason or ""
            except (AttributeError, IndexError):
                continue

            if delta is None:
                continue

            # --- Token content ---
            token_content = getattr(delta, "content", None) or ""
            if token_content:
                yield StreamChunk(
                    type="token",
                    content=token_content,
                    sequence=sequence,
                )
                sequence += 1

            # --- Tool call deltas ---
            tool_calls_delta = getattr(delta, "tool_calls", None) or []
            for tc_delta in tool_calls_delta:
                idx = tc_delta.index if hasattr(tc_delta, "index") else 0

                if idx not in tool_call_accumulators:
                    # New tool call starting
                    tool_call_accumulators[idx] = {
                        "id": getattr(tc_delta, "id", "") or "",
                        "type": getattr(tc_delta, "type", "function") or "function",
                        "function": {
                            "name": "",
                            "arguments": "",
                        },
                    }
                    fn = getattr(tc_delta, "function", None)
                    if fn:
                        tool_call_accumulators[idx]["function"]["name"] = (
                            getattr(fn, "name", "") or ""
                        )
                    yield StreamChunk(
                        type="tool_call_start",
                        tool_call={
                            "index": idx,
                            "id": tool_call_accumulators[idx]["id"],
                            "name": tool_call_accumulators[idx]["function"]["name"],
                        },
                        sequence=sequence,
                    )
                    sequence += 1
                else:
                    # Accumulate arguments delta
                    fn = getattr(tc_delta, "function", None)
                    if fn:
                        args_delta = getattr(fn, "arguments", "") or ""
                        tool_call_accumulators[idx]["function"]["arguments"] += args_delta
                        if args_delta:
                            yield StreamChunk(
                                type="tool_call_delta",
                                content=args_delta,
                                tool_call={"index": idx},
                                sequence=sequence,
                            )
                            sequence += 1

            # --- Finish reason ---
            if finish_reason:
                # Flush any complete tool calls
                for idx, tc in tool_call_accumulators.items():
                    assembled = self._assemble_tool_call(
                        [tc]  # already accumulated into single dict
                    )
                    yield StreamChunk(
                        type="tool_call_complete",
                        tool_call=assembled,
                        sequence=sequence,
                    )
                    sequence += 1
                tool_call_accumulators.clear()

                yield StreamChunk(
                    type="finish",
                    finish_reason=finish_reason,
                    sequence=sequence,
                )
                sequence += 1

    async def stream_to_sse(
        self,
        completion_stream: AsyncGenerator[StreamChunk, None],
    ) -> AsyncGenerator[str, None]:
        """Convert a StreamChunk async generator to SSE-formatted strings.

        Each yielded string is a complete SSE event ready to send over HTTP.
        """
        async for chunk in completion_stream:
            yield chunk.to_sse()

    async def stream_to_websocket(
        self,
        completion_stream: AsyncGenerator[StreamChunk, None],
        websocket: Any,
    ) -> None:
        """Send StreamChunks over a WebSocket connection.

        ``websocket`` must have an async ``send`` or ``send_text`` method.
        """
        async for chunk in completion_stream:
            payload = json.dumps(chunk.to_dict())
            try:
                if hasattr(websocket, "send_text"):
                    await websocket.send_text(payload)
                elif hasattr(websocket, "send"):
                    await websocket.send(payload)
                else:
                    logger.warning(
                        "stream_to_websocket: websocket object has no send method"
                    )
            except Exception as exc:
                logger.error("stream_to_websocket: send error: %s", exc)
                break

    @staticmethod
    def _assemble_tool_call(deltas: list[dict]) -> dict:
        """Assemble a complete tool call from accumulated delta dicts.

        Each delta is expected to have the shape accumulated by
        ``stream_completion``: ``{id, type, function: {name, arguments}}``.
        """
        if not deltas:
            return {}

        # We accumulate into a single dict, so just return the first (complete) one
        tc = deltas[0]
        fn = tc.get("function", {})
        args_str = fn.get("arguments", "")

        # Try to parse arguments JSON
        args: dict = {}
        if args_str:
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                # Return raw string if not valid JSON yet
                args = {"_raw": args_str}

        return {
            "id": tc.get("id", ""),
            "type": tc.get("type", "function"),
            "function": {
                "name": fn.get("name", ""),
                "arguments": args,
            },
        }


# ---------------------------------------------------------------------------
# BufferedStreamer
# ---------------------------------------------------------------------------

class BufferedStreamer:
    """
    Wraps an agent's event stream and produces StreamChunks for the UI.

    For each agent event type:
    - ``ToolCallEvent``     → tool_call_start chunk
    - ``ToolResultEvent``   → tool_call_complete chunk
    - ``ThinkingEvent``     → token chunk (if enabled)
    - ``FinalAnswerEvent``  → word-by-word token chunks (typewriter effect)
    - silence               → heartbeat chunks
    """

    def __init__(self, config: StreamingConfig | None = None) -> None:
        self._config = config or StreamingConfig()

    async def stream_agent_response(
        self,
        agent: Any,
        task: str,
        context: str = "",
    ) -> AsyncGenerator[StreamChunk, None]:
        """Wrap ``agent.stream(task)`` and yield StreamChunks.

        The agent must expose an async generator ``stream(task: str)``.
        Each event should have a ``type`` attribute.  Recognised types:
        - ``"tool_call"`` / ``"tool_call_start"``
        - ``"tool_result"`` / ``"tool_call_complete"``
        - ``"thinking"``
        - ``"final"`` / ``"final_answer"``
        Any other type emits a generic token chunk.
        """
        sequence = 0
        heartbeat_interval = self._config.heartbeat_interval

        async def _next_with_heartbeat(
            gen: AsyncGenerator,
        ) -> tuple[Any | None, bool]:
            """Get next item with heartbeat timeout. Returns (item, is_heartbeat)."""
            try:
                item = await asyncio.wait_for(gen.__anext__(), timeout=heartbeat_interval)
                return item, False
            except asyncio.TimeoutError:
                return None, True
            except StopAsyncIteration:
                return None, False  # exhausted

        agent_gen = agent.stream(task) if not context else agent.stream(task, context=context)

        while True:
            item, is_heartbeat = await _next_with_heartbeat(agent_gen)

            if is_heartbeat:
                yield StreamChunk(type="heartbeat", sequence=sequence)
                sequence += 1
                continue

            if item is None:
                # Generator exhausted
                break

            # Normalise to dict
            if hasattr(item, "to_dict"):
                event = item.to_dict()
            elif isinstance(item, dict):
                event = item
            else:
                event = {"type": "token", "content": str(item)}

            event_type: str = str(event.get("type", "token")).lower()

            # --- Tool call start ---
            if event_type in ("tool_call", "tool_call_start"):
                tool_call_data = {
                    "name": event.get("tool_name", event.get("name", "")),
                    "arguments": event.get("arguments", event.get("args", {})),
                    "id": event.get("tool_call_id", event.get("id", "")),
                }
                yield StreamChunk(
                    type="tool_call_start",
                    content=f"Calling tool: {tool_call_data['name']}",
                    tool_call=tool_call_data,
                    sequence=sequence,
                )
                sequence += 1

            # --- Tool result ---
            elif event_type in ("tool_result", "tool_call_complete", "tool_result_event"):
                tool_call_data = {
                    "id": event.get("tool_call_id", event.get("id", "")),
                    "name": event.get("tool_name", event.get("name", "")),
                    "result": event.get("result", event.get("content", "")),
                }
                yield StreamChunk(
                    type="tool_call_complete",
                    content="",
                    tool_call=tool_call_data,
                    sequence=sequence,
                )
                sequence += 1

            # --- Thinking / reasoning ---
            elif event_type == "thinking":
                thinking_text = event.get("content", event.get("thinking", ""))
                if thinking_text:
                    yield StreamChunk(
                        type="token",
                        content=thinking_text,
                        sequence=sequence,
                    )
                    sequence += 1

            # --- Final answer — typewriter effect ---
            elif event_type in ("final", "final_answer", "answer"):
                final_content: str = str(event.get("content", event.get("result", "")))
                # Split into words and stream with brief pauses for typewriter effect
                words = final_content.split(" ")
                for i, word in enumerate(words):
                    token = word if i == 0 else f" {word}"
                    yield StreamChunk(
                        type="token",
                        content=token,
                        sequence=sequence,
                    )
                    sequence += 1
                    # Brief yield to allow other coroutines to run
                    await asyncio.sleep(0)

                # Emit finish
                yield StreamChunk(
                    type="finish",
                    finish_reason="stop",
                    sequence=sequence,
                )
                sequence += 1

            # --- Generic / unknown event ---
            else:
                content = event.get("content", event.get("text", ""))
                if content:
                    yield StreamChunk(
                        type="token",
                        content=str(content),
                        sequence=sequence,
                    )
                    sequence += 1
