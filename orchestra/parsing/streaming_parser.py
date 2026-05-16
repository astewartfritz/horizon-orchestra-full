"""Real-time streaming parser for Horizon Orchestra.

Parses streaming LLM output in real time, emitting structured events the
instant each element completes — not when the entire stream finishes.
Detects tool calls, JSON objects, code blocks, thinking sections,
and repetition loops mid-stream.

Target: >100MB/s throughput.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, AsyncIterator

__all__ = [
    "StreamingParser",
    "ParsedEvent",
    "EventType",
    "ThinkingChunk",
    "AnswerChunk",
    "ToolCallDetected",
    "CodeBlockStart",
    "CodeBlockEnd",
    "JSONObjectComplete",
    "RepetitionDetected",
    "StreamComplete",
    "StreamAborted",
]


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType(Enum):
    """Types of events emitted by the streaming parser."""
    THINKING_CHUNK = auto()
    ANSWER_CHUNK = auto()
    TOOL_CALL_DETECTED = auto()
    CODE_BLOCK_START = auto()
    CODE_BLOCK_END = auto()
    JSON_OBJECT_COMPLETE = auto()
    REPETITION_DETECTED = auto()
    STREAM_COMPLETE = auto()
    STREAM_ABORTED = auto()


@dataclass
class ThinkingChunk:
    """A chunk of intermediate reasoning/thinking."""
    event_type: EventType = field(default=EventType.THINKING_CHUNK, init=False)
    content: str = ""
    token_count: int = 0
    timestamp: float = 0.0


@dataclass
class AnswerChunk:
    """A chunk of the final answer content."""
    event_type: EventType = field(default=EventType.ANSWER_CHUNK, init=False)
    content: str = ""
    token_count: int = 0
    timestamp: float = 0.0


@dataclass
class ToolCallDetected:
    """A complete tool call extracted from the stream."""
    event_type: EventType = field(default=EventType.TOOL_CALL_DETECTED, init=False)
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    timestamp: float = 0.0


@dataclass
class CodeBlockStart:
    """A code block has been opened."""
    event_type: EventType = field(default=EventType.CODE_BLOCK_START, init=False)
    language: str = ""
    timestamp: float = 0.0


@dataclass
class CodeBlockEnd:
    """A code block has been closed."""
    event_type: EventType = field(default=EventType.CODE_BLOCK_END, init=False)
    language: str = ""
    code: str = ""
    timestamp: float = 0.0


@dataclass
class JSONObjectComplete:
    """A complete JSON object/array has been detected in the stream."""
    event_type: EventType = field(default=EventType.JSON_OBJECT_COMPLETE, init=False)
    data: Any = None
    raw_text: str = ""
    timestamp: float = 0.0


@dataclass
class RepetitionDetected:
    """Repetition loop detected in the stream."""
    event_type: EventType = field(default=EventType.REPETITION_DETECTED, init=False)
    repeated_text: str = ""
    repeat_count: int = 0
    timestamp: float = 0.0


@dataclass
class StreamComplete:
    """Stream finished normally."""
    event_type: EventType = field(default=EventType.STREAM_COMPLETE, init=False)
    total_tokens: int = 0
    total_events: int = 0
    duration_ms: float = 0.0
    timestamp: float = 0.0


@dataclass
class StreamAborted:
    """Stream was aborted (repetition, error, etc.)."""
    event_type: EventType = field(default=EventType.STREAM_ABORTED, init=False)
    reason: str = ""
    timestamp: float = 0.0


# Union type for all events.
ParsedEvent = (
    ThinkingChunk | AnswerChunk | ToolCallDetected |
    CodeBlockStart | CodeBlockEnd | JSONObjectComplete |
    RepetitionDetected | StreamComplete | StreamAborted
)


# ---------------------------------------------------------------------------
# StreamingParser
# ---------------------------------------------------------------------------

class StreamingParser:
    """Real-time streaming LLM output parser.

    Emits structured :class:`ParsedEvent` objects the instant each element
    completes in the stream.  Detects:

      - Thinking vs answer sections
      - Tool calls (OpenAI function_call format, raw JSON, XML)
      - Code blocks (with language detection)
      - JSON objects (bracket-balanced)
      - Repetition loops (for early termination)
    """

    # Thinking section markers (common patterns).
    _THINK_OPEN = re.compile(r'<(?:think|thinking|thought|reasoning)>', re.IGNORECASE)
    _THINK_CLOSE = re.compile(r'</(?:think|thinking|thought|reasoning)>', re.IGNORECASE)

    # Tool call markers.
    _TOOL_CALL_START = re.compile(
        r'(?:"function_call"\s*:\s*\{|<tool_call>|<function_call>|"tool_calls"\s*:\s*\[)',
    )

    # Repetition detection window.
    _REP_WINDOW = 200  # chars
    _REP_THRESHOLD = 3  # repeats to trigger

    def __init__(
        self,
        *,
        max_repetitions: int = 3,
        thinking_markers: bool = True,
    ) -> None:
        """Create a streaming parser.

        Args:
            max_repetitions: How many repetitions to tolerate before emitting
                a :class:`RepetitionDetected` event.
            thinking_markers: If True, detect ``<think>...</think>`` sections.
        """
        self._max_reps = max_repetitions
        self._use_think_markers = thinking_markers

    async def parse(
        self,
        chunks: AsyncIterator[str],
    ) -> AsyncIterator[ParsedEvent]:
        """Parse a stream of text chunks into structured events.

        Yields :class:`ParsedEvent` instances as each element completes.
        """
        state = _ParserState(
            max_reps=self._max_reps,
            use_think_markers=self._use_think_markers,
        )
        t0 = time.monotonic()

        async for chunk in chunks:
            events = state.feed(chunk)
            for ev in events:
                yield ev

        # Flush remaining buffer.
        events = state.flush()
        for ev in events:
            yield ev

        duration = (time.monotonic() - t0) * 1000
        yield StreamComplete(
            total_tokens=state.token_count,
            total_events=state.event_count,
            duration_ms=duration,
            timestamp=time.monotonic(),
        )


# ---------------------------------------------------------------------------
# Internal parser state machine
# ---------------------------------------------------------------------------

class _ParserState:
    """Mutable parser state — processes incoming chunks and emits events."""

    def __init__(self, max_reps: int = 3, use_think_markers: bool = True) -> None:
        self.buffer = ""
        self.token_count = 0
        self.event_count = 0
        self.max_reps = max_reps
        self.use_think_markers = use_think_markers

        # Tracking state.
        self._in_thinking = False
        self._in_code_block = False
        self._code_language = ""
        self._code_content: list[str] = []
        self._json_depth = 0
        self._json_start = -1
        self._json_buffer = ""
        self._in_json_string = False
        self._json_escape = False

        # Repetition detection.
        self._recent_chunks: list[str] = []
        self._rep_buffer = ""

        # Tool call accumulator.
        self._tool_call_buffer = ""
        self._in_tool_call = False

    def feed(self, chunk: str) -> list[ParsedEvent]:
        """Process a chunk and return any completed events."""
        events: list[ParsedEvent] = []
        self.buffer += chunk
        self.token_count += max(1, len(chunk.split()))

        # Update repetition buffer.
        self._rep_buffer += chunk
        if len(self._rep_buffer) > self._REP_BUFFER_SIZE:
            self._rep_buffer = self._rep_buffer[-self._REP_BUFFER_SIZE:]

        # Check for repetition.
        rep_event = self._check_repetition(chunk)
        if rep_event:
            events.append(rep_event)

        # Process the buffer for events.
        events.extend(self._process_buffer())

        return events

    _REP_BUFFER_SIZE = 2000

    def flush(self) -> list[ParsedEvent]:
        """Flush remaining buffer content as events."""
        events: list[ParsedEvent] = []

        if self._in_code_block:
            events.append(CodeBlockEnd(
                language=self._code_language,
                code="".join(self._code_content),
                timestamp=time.monotonic(),
            ))
            self._in_code_block = False
            self.event_count += 1

        if self._json_depth > 0 and self._json_buffer:
            # Try to heal and emit incomplete JSON.
            from .json_healer import JSONHealer
            healer = JSONHealer()
            try:
                obj, _ = healer.heal(self._json_buffer)
                events.append(JSONObjectComplete(
                    data=obj,
                    raw_text=self._json_buffer,
                    timestamp=time.monotonic(),
                ))
                self.event_count += 1
            except Exception:
                                import logging as _log; _log.getLogger('parsing.streaming_parser').debug('Suppressed exception', exc_info=True)
            self._json_depth = 0
            self._json_buffer = ""

        if self._in_tool_call and self._tool_call_buffer:
            # Try to parse incomplete tool call.
            tc_event = self._try_parse_tool_call(self._tool_call_buffer)
            if tc_event:
                events.append(tc_event)
            self._in_tool_call = False
            self._tool_call_buffer = ""

        # Emit any remaining buffer as answer chunk.
        remaining = self.buffer.strip()
        if remaining:
            if self._in_thinking:
                events.append(ThinkingChunk(
                    content=remaining,
                    token_count=len(remaining.split()),
                    timestamp=time.monotonic(),
                ))
            else:
                events.append(AnswerChunk(
                    content=remaining,
                    token_count=len(remaining.split()),
                    timestamp=time.monotonic(),
                ))
            self.event_count += 1
            self.buffer = ""

        return events

    def _process_buffer(self) -> list[ParsedEvent]:
        """Process accumulated buffer and emit events for completed elements."""
        events: list[ParsedEvent] = []
        consumed = 0

        while consumed < len(self.buffer):
            remaining = self.buffer[consumed:]

            # --- Check for thinking markers ---
            if self.use_think_markers and not self._in_thinking:
                m = StreamingParser._THINK_OPEN.search(remaining)
                if m and m.start() == 0:
                    self._in_thinking = True
                    consumed += m.end()
                    continue

            if self.use_think_markers and self._in_thinking:
                m = StreamingParser._THINK_CLOSE.search(remaining)
                if m:
                    thinking_text = remaining[:m.start()]
                    if thinking_text.strip():
                        events.append(ThinkingChunk(
                            content=thinking_text,
                            token_count=len(thinking_text.split()),
                            timestamp=time.monotonic(),
                        ))
                        self.event_count += 1
                    self._in_thinking = False
                    consumed += m.end()
                    continue
                else:
                    # Still in thinking, wait for more data.
                    break

            # --- Check for code blocks ---
            if not self._in_code_block:
                code_start = remaining.find("```")
                if code_start == 0:
                    # Find end of language tag.
                    newline = remaining.find("\n", 3)
                    if newline > 0:
                        lang = remaining[3:newline].strip()
                        self._in_code_block = True
                        self._code_language = lang
                        self._code_content = []
                        events.append(CodeBlockStart(
                            language=lang,
                            timestamp=time.monotonic(),
                        ))
                        self.event_count += 1
                        consumed += newline + 1
                        continue
                    else:
                        break  # Wait for more data.

            if self._in_code_block:
                end = remaining.find("```")
                if end >= 0:
                    code = remaining[:end]
                    self._code_content.append(code)
                    events.append(CodeBlockEnd(
                        language=self._code_language,
                        code="".join(self._code_content),
                        timestamp=time.monotonic(),
                    ))
                    self.event_count += 1
                    self._in_code_block = False
                    consumed += end + 3
                    continue
                else:
                    self._code_content.append(remaining)
                    consumed = len(self.buffer)
                    break

            # --- Check for JSON objects ---
            if not self._in_json_string and remaining and remaining[0] in ('{', '['):
                end = self._find_json_end(remaining)
                if end > 0:
                    raw = remaining[:end]
                    try:
                        data = json.loads(raw)
                        # Check if this is a tool call.
                        if isinstance(data, dict) and any(k in data for k in ("name", "function_call", "tool_calls")):
                            tc = self._try_parse_tool_call(raw)
                            if tc:
                                events.append(tc)
                        else:
                            events.append(JSONObjectComplete(
                                data=data,
                                raw_text=raw,
                                timestamp=time.monotonic(),
                            ))
                            self.event_count += 1
                    except (json.JSONDecodeError, ValueError):
                        pass
                    consumed += end
                    continue
                else:
                    # Incomplete JSON — wait for more.
                    break

            # --- Check for tool call patterns ---
            tc_match = StreamingParser._TOOL_CALL_START.search(remaining)
            if tc_match and tc_match.start() < 10:
                # Emit any text before as answer chunk.
                if tc_match.start() > 0:
                    pre = remaining[:tc_match.start()]
                    events.append(AnswerChunk(
                        content=pre,
                        token_count=len(pre.split()),
                        timestamp=time.monotonic(),
                    ))
                    self.event_count += 1
                    consumed += tc_match.start()
                    continue

            # --- Default: emit as answer/thinking chunk ---
            # Find the next potential marker.
            next_marker = len(remaining)
            for marker in ("```", "<think", "</think", '{"', "[{", '"function_call"', '"tool_calls"'):
                idx = remaining.find(marker, 1)
                if 0 < idx < next_marker:
                    next_marker = idx

            text = remaining[:next_marker]
            if text.strip():
                if self._in_thinking:
                    events.append(ThinkingChunk(
                        content=text,
                        token_count=len(text.split()),
                        timestamp=time.monotonic(),
                    ))
                else:
                    events.append(AnswerChunk(
                        content=text,
                        token_count=len(text.split()),
                        timestamp=time.monotonic(),
                    ))
                self.event_count += 1

            consumed += next_marker
            if next_marker == len(remaining):
                break

        # Remove consumed content from buffer.
        self.buffer = self.buffer[consumed:]
        return events

    def _find_json_end(self, text: str) -> int:
        """Find the end of a balanced JSON object/array starting at position 0."""
        if not text or text[0] not in ('{', '['):
            return -1
        open_ch = text[0]
        close_ch = '}' if open_ch == '{' else ']'
        depth = 0
        in_str = False
        escape = False

        for i, ch in enumerate(text):
            if escape:
                escape = False
                continue
            if ch == '\\' and in_str:
                escape = True
                continue
            if ch == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return i + 1
        return -1  # Not balanced yet.

    def _try_parse_tool_call(self, raw: str) -> ToolCallDetected | None:
        """Try to parse a tool call from raw text."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            from .json_healer import JSONHealer
            healer = JSONHealer()
            try:
                data, _ = healer.heal(raw)
            except Exception:
                return None

        if not isinstance(data, dict):
            return None

        # OpenAI function_call format.
        fc = data.get("function_call")
        if isinstance(fc, dict):
            name = fc.get("name", "")
            args = fc.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    args = {}
            if name:
                self.event_count += 1
                return ToolCallDetected(
                    tool_name=name,
                    arguments=args if isinstance(args, dict) else {},
                    raw_text=raw,
                    timestamp=time.monotonic(),
                )

        # Direct name + arguments.
        name = data.get("name", data.get("tool", data.get("function", "")))
        args = data.get("arguments", data.get("args", data.get("parameters", {})))
        if name:
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    args = {}
            self.event_count += 1
            return ToolCallDetected(
                tool_name=name,
                arguments=args if isinstance(args, dict) else {},
                raw_text=raw,
                timestamp=time.monotonic(),
            )

        return None

    def _check_repetition(self, chunk: str) -> RepetitionDetected | None:
        """Check for repetition in the recent output."""
        buf = self._rep_buffer
        if len(buf) < 100:
            return None

        # Check for repeated phrases of various lengths.
        for phrase_len in (50, 30, 20):
            if len(buf) < phrase_len * 3:
                continue
            tail = buf[-phrase_len:]
            count = 0
            pos = 0
            while True:
                idx = buf.find(tail, pos)
                if idx == -1:
                    break
                count += 1
                pos = idx + 1
            if count >= self.max_reps:
                self.event_count += 1
                return RepetitionDetected(
                    repeated_text=tail[:50],
                    repeat_count=count,
                    timestamp=time.monotonic(),
                )

        return None
