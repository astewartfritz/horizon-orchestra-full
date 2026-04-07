"""
stream_healer.py — Heals broken streaming responses for Horizon Orchestra.

When an SSE stream breaks mid-response, :class:`StreamHealer` buffers
received chunks, detects the break type, reconstructs partial state,
resumes transparently, and deduplicates overlap — the user sees
continuous output with no visible gap.

Also handles JSON truncation repair, tool-call truncation, repetition
loop detection, and abrupt cut detection.
"""
from __future__ import annotations

__all__ = [
    "BreakType",
    "StreamState",
    "StreamHealer",
]

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Break type classification
# ---------------------------------------------------------------------------

class BreakType(str, Enum):
    """Types of stream interruption."""
    SSE_DISCONNECT = "SSE_DISCONNECT"
    JSON_TRUNCATION = "JSON_TRUNCATION"
    TIMEOUT = "TIMEOUT"
    REPETITION_LOOP = "REPETITION_LOOP"
    ABRUPT_CUT = "ABRUPT_CUT"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Stream state
# ---------------------------------------------------------------------------

@dataclass
class StreamState:
    """Tracks the state of an active or interrupted stream.

    Attributes:
        chunks: Ordered list of received text chunks.
        event_ids: SSE event IDs received (for resumption).
        total_chars: Total characters received.
        last_chunk_time: Monotonic time of last chunk.
        break_type: Detected break type, if any.
        is_complete: Whether the stream terminated normally.
    """
    chunks: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    total_chars: int = 0
    last_chunk_time: float = 0.0
    break_type: Optional[BreakType] = None
    is_complete: bool = False


# ---------------------------------------------------------------------------
# StreamHealer
# ---------------------------------------------------------------------------

class StreamHealer:
    """Heals broken streaming responses transparently.

    Provides methods to:
    - Resume SSE disconnects from the last event ID.
    - Repair truncated JSON (incomplete objects/arrays/strings).
    - Repair truncated tool calls.
    - Deduplicate overlap between original and resumed streams.
    - Detect repetition loops and abrupt cuts.

    Example::

        healer = StreamHealer()
        # Repair truncated JSON
        repaired = healer.heal_json_truncation('{"name": "test", "items": [1, 2')
        assert repaired == {"name": "test", "items": [1, 2]}
    """

    def __init__(
        self,
        loop_window: int = 100,
        loop_threshold: float = 0.6,
        silence_timeout_ms: float = 10000.0,
    ) -> None:
        self._loop_window = loop_window  # characters to check for loops
        self._loop_threshold = loop_threshold  # ratio to trigger loop detection
        self._silence_timeout = silence_timeout_ms

    # ------------------------------------------------------------------
    # SSE disconnect healing
    # ------------------------------------------------------------------

    async def heal_sse_disconnect(
        self,
        buffer: list[str],
        last_event_id: Optional[str],
        resume_fn: Any = None,
    ) -> AsyncGenerator[str, None]:
        """Resume a broken SSE stream from *last_event_id*.

        Yields previously buffered chunks, then (if *resume_fn* is
        provided) resumes the stream and deduplicates the overlap.

        Args:
            buffer: Already-received text chunks.
            last_event_id: The SSE ``id`` of the last complete event.
            resume_fn: Async callable ``(last_event_id) → AsyncGenerator[str]``
                       that reconnects and yields new chunks.
        """
        accumulated = "".join(buffer)
        if not resume_fn:
            yield accumulated
            return

        # Resume from where we left off
        overlap_resolved = False
        async for chunk in resume_fn(last_event_id):
            if not overlap_resolved:
                # Try to find overlap with end of accumulated
                deduped = self.deduplicate_overlap(accumulated, chunk)
                if deduped != chunk:
                    overlap_resolved = True
                    new_part = deduped
                    if new_part:
                        yield new_part
                    continue
                else:
                    overlap_resolved = True
            yield chunk

    # ------------------------------------------------------------------
    # JSON truncation healing
    # ------------------------------------------------------------------

    def heal_json_truncation(self, partial: str) -> Any:
        """Repair truncated JSON and return the parsed result.

        Handles incomplete objects, arrays, strings, and trailing commas.
        Returns the best-effort parsed result.

        Args:
            partial: An incomplete JSON string.

        Returns:
            Parsed Python object (dict, list, str, etc.).

        Raises:
            ValueError: If the input cannot be repaired.
        """
        if not partial or not partial.strip():
            raise ValueError("Empty input")

        text = partial.strip()

        # First try parsing as-is
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 1: Close open structures
        repaired = self._close_json_structures(text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Strip trailing partial value + close
        repaired = self._strip_trailing_partial(text)
        repaired = self._close_json_structures(repaired)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Strategy 3: Aggressive — find the last valid prefix
        for i in range(len(text), 0, -1):
            candidate = self._close_json_structures(text[:i])
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        raise ValueError(f"Cannot repair JSON: {text[:100]}...")

    # ------------------------------------------------------------------
    # Tool call truncation healing
    # ------------------------------------------------------------------

    def heal_tool_call_truncation(self, partial: dict[str, Any]) -> dict[str, Any]:
        """Repair a truncated tool call dict.

        Ensures the tool call has at least ``name`` and ``arguments``
        keys.  If ``arguments`` is a truncated JSON string, attempts
        to repair it.

        Args:
            partial: A partially received tool-call dictionary.

        Returns:
            A repaired tool-call dictionary.
        """
        result = dict(partial)

        # Ensure required fields
        if "name" not in result:
            result["name"] = "unknown_tool"
        if "id" not in result:
            result["id"] = "call_truncated"
        if "type" not in result:
            result["type"] = "function"

        # Repair arguments
        args = result.get("arguments", "{}")
        if isinstance(args, str):
            try:
                parsed = self.heal_json_truncation(args)
                result["arguments"] = json.dumps(parsed) if isinstance(parsed, (dict, list)) else args
            except (ValueError, json.JSONDecodeError):
                result["arguments"] = "{}"
        elif args is None:
            result["arguments"] = "{}"

        return result

    # ------------------------------------------------------------------
    # Resume after timeout
    # ------------------------------------------------------------------

    async def resume_after_timeout(
        self,
        partial_response: str,
        original_request: dict[str, Any],
        call_fn: Any = None,
    ) -> AsyncGenerator[str, None]:
        """Resume generation after a timeout.

        Yields the continuation from where the partial response left off.

        Args:
            partial_response: Text received before the timeout.
            original_request: The original request dict.
            call_fn: Async callable ``(messages) → AsyncGenerator[str]``
                     that re-issues the request.
        """
        if not call_fn:
            yield partial_response
            return

        last_sentence = self._find_last_coherent_sentence(partial_response)
        continuation_prompt = f"Continue from exactly where this was cut off: ...{last_sentence}"

        messages = list(original_request.get("messages", []))
        messages.append({"role": "assistant", "content": partial_response})
        messages.append({"role": "user", "content": continuation_prompt})

        async for chunk in call_fn(messages):
            deduped = self.deduplicate_overlap(partial_response, chunk)
            yield deduped

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def deduplicate_overlap(self, chunk1: str, chunk2: str) -> str:
        """Remove overlapping text between the end of *chunk1* and
        the start of *chunk2*.

        Uses a sliding-window approach: finds the longest suffix of
        *chunk1* that matches a prefix of *chunk2*, then returns
        only the non-overlapping portion of *chunk2*.

        Args:
            chunk1: The first (earlier) text.
            chunk2: The second (later) text.

        Returns:
            The portion of *chunk2* that does not overlap with *chunk1*.
        """
        if not chunk1 or not chunk2:
            return chunk2

        # Check up to the last N characters of chunk1 for overlap
        max_overlap = min(len(chunk1), len(chunk2), 500)

        best_overlap = 0
        for length in range(1, max_overlap + 1):
            suffix = chunk1[-length:]
            if chunk2.startswith(suffix):
                best_overlap = length

        if best_overlap > 0:
            return chunk2[best_overlap:]
        return chunk2

    # ------------------------------------------------------------------
    # Sentinel detection
    # ------------------------------------------------------------------

    def detect_repetition_loop(self, text: str) -> bool:
        """Detect if the model is stuck in a repetition loop.

        Checks the last ``loop_window`` characters for repeated
        patterns (n-grams of sizes 10–50 chars).

        Returns:
            ``True`` if a repetition loop is detected.
        """
        if len(text) < self._loop_window:
            return False

        window = text[-self._loop_window:]

        # Check for repeated n-grams of various sizes
        for ngram_size in (10, 15, 20, 30, 50):
            if ngram_size > len(window) // 2:
                continue
            # Count how many non-overlapping occurrences of each ngram
            for start in range(0, len(window) - ngram_size, ngram_size):
                ngram = window[start:start + ngram_size]
                if not ngram.strip():
                    continue
                count = window.count(ngram)
                ratio = (count * ngram_size) / len(window)
                if count >= 3 and ratio >= self._loop_threshold:
                    logger.warning(
                        "Repetition loop detected: '%s...' repeated %d times",
                        ngram[:30], count,
                    )
                    return True

        return False

    def detect_abrupt_cut(self, text: str) -> bool:
        """Detect if the text was cut off mid-sentence or mid-word.

        Returns:
            ``True`` if the text appears to be abruptly truncated.
        """
        if not text or not text.strip():
            return True

        stripped = text.rstrip()

        # Ends mid-word (no space/punctuation at end)
        if stripped and stripped[-1].isalpha() and len(stripped) > 20:
            # Check if the last "word" looks incomplete
            last_space = stripped.rfind(" ")
            if last_space > 0:
                last_word = stripped[last_space + 1:]
                # Very short trailing word after substantial text is suspicious
                # but not necessarily truncated. Check for other signals.
                if len(last_word) <= 2 and not last_word.lower() in {"a", "i", "is", "it", "be", "to", "in", "on", "of"}:
                    return True

        # Ends mid-code-block
        if stripped.count("```") % 2 != 0:
            return True

        # Ends mid-JSON
        opens = stripped.count("{") + stripped.count("[")
        closes = stripped.count("}") + stripped.count("]")
        if opens > closes + 1:
            return True

        # Ends mid-string (unclosed quote)
        in_string = False
        escaped = False
        for ch in stripped:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
        if in_string:
            return True

        return False

    def detect_end_of_thought(self, text: str) -> bool:
        """Detect if the text represents a complete thought vs abrupt cut.

        Returns ``True`` if the text appears to be a complete response.
        """
        if not text or not text.strip():
            return False

        stripped = text.rstrip()
        # Complete sentence endings
        if stripped[-1] in ".!?:;)]\u201d":
            return True
        # Markdown code block properly closed
        if stripped.endswith("```"):
            return stripped.count("```") % 2 == 0
        # Ends with a list item that looks complete
        if re.search(r"\n[-*]\s+.{10,}[.!?]$", stripped):
            return True

        return False

    # ------------------------------------------------------------------
    # JSON repair helpers
    # ------------------------------------------------------------------

    def _close_json_structures(self, text: str) -> str:
        """Append closing brackets/braces to balance the JSON."""
        # Remove trailing comma (invalid in JSON)
        text = re.sub(r",\s*$", "", text)

        # Track open structures
        stack: list[str] = []
        in_string = False
        escaped = False

        for ch in text:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                if in_string:
                    escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ("{", "["):
                stack.append(ch)
            elif ch == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
            elif ch == "]":
                if stack and stack[-1] == "[":
                    stack.pop()

        # Close unclosed string
        if in_string:
            text += '"'

        # Close open structures in reverse
        for opener in reversed(stack):
            if opener == "{":
                text += "}"
            elif opener == "[":
                text += "]"

        return text

    def _strip_trailing_partial(self, text: str) -> str:
        """Strip a trailing partial value (incomplete key, string, number)."""
        # Remove trailing partial key-value: ,"key":
        text = re.sub(r',\s*"[^"]*"\s*:\s*$', "", text)
        # Remove trailing partial string value: ,"key": "val
        text = re.sub(r',\s*"[^"]*"\s*:\s*"[^"]*$', "", text)
        # Remove trailing partial number: ,"key": 12
        text = re.sub(r',\s*"[^"]*"\s*:\s*\d+\.?\d*$', "", text)
        # Remove trailing comma
        text = re.sub(r",\s*$", "", text)
        return text

    def _find_last_coherent_sentence(self, text: str) -> str:
        """Find the last complete sentence in *text*."""
        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text)
        # Return the last few complete sentences for context
        complete = [s for s in sentences if s and s.strip()[-1:] in ".!?"]
        if complete:
            return complete[-1]
        # Fallback: last 200 chars
        return text[-200:] if len(text) > 200 else text
