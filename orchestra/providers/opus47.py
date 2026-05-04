"""Horizon Orchestra — Claude Opus 4.7 Provider.

Provides direct integration with Anthropic's Claude Opus 4.7 via the
Messages API using ``httpx`` for async HTTP requests.  This provider is
designed to work without the ``anthropic`` SDK installed, relying solely
on ``httpx`` for transport.

Key capabilities:

1. **Extended Thinking** — effort-tiered reasoning (low/medium/high/xhigh)
   with configurable thinking budgets per effort level.
2. **Vision** — multimodal image understanding with base64-encoded images;
   max resolution 2576px on the long edge.
3. **Agentic Loop** — iterative tool-calling loop with token-budget
   tracking, automatic tool-result feeding, and cost accounting.
4. **Task Budgets** — beta feature for capping total task cost via the
   ``task-budgets-2026-03-13`` beta header.
5. **Premium Pricing** — automatic pricing tier upgrade for requests
   exceeding 200k input tokens.

Model:

* ``claude-opus-4-7`` — 1M context, 128K max output, $5/$25 per MTok
  (premium: $10/$37.50 for >200k context).
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    HAS_HTTPX = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    anthropic = None  # type: ignore[assignment]
    HAS_ANTHROPIC = False

__all__ = [
    "Opus47Provider",
    "Opus47Response",
    "AgenticResult",
    "MODEL_ID",
    "CONTEXT_WINDOW",
    "MAX_OUTPUT_TOKENS",
    "PRICING",
    "PREMIUM_PRICING",
    "EFFORT_LEVELS",
    "BETA_HEADERS",
]

log = logging.getLogger("orchestra.providers.opus47")

# ---------------------------------------------------------------------------
# Constants & Config
# ---------------------------------------------------------------------------

MODEL_ID: str = "claude-opus-4-7"
CONTEXT_WINDOW: int = 1_000_000
MAX_OUTPUT_TOKENS: int = 128_000
PRICING: Dict[str, float] = {"input": 5.0, "output": 25.0}
PREMIUM_PRICING: Dict[str, float] = {"input": 10.0, "output": 37.50}
EFFORT_LEVELS: List[str] = ["low", "medium", "high", "xhigh"]
BETA_HEADERS: Dict[str, str] = {"task_budgets": "task-budgets-2026-03-13"}

#: Anthropic Messages API version.
_API_VERSION: str = "2023-06-01"

#: Thinking budget ceilings per effort level (tokens).
_THINKING_BUDGETS: Dict[str, int] = {
    "low": 2_048,
    "medium": 8_192,
    "high": 32_768,
    "xhigh": 65_536,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Opus47Response:
    """Response from an Opus 4.7 API call.

    Attributes:
        content: Final text content from the model.
        thinking: Condensed thinking summary (None if thinking was disabled).
        tool_calls: List of tool-use blocks returned by the model.
        model: Canonical model ID used for the request.
        usage: Token usage breakdown with ``input_tokens``,
            ``output_tokens``, and ``thinking_tokens`` keys.
        stop_reason: API stop reason (``"end_turn"``, ``"tool_use"``,
            ``"max_tokens"``, ``"stop_sequence"``).
        effort_used: Effort level that was applied for this request.
        budget_remaining: Remaining task budget tokens (None if task
            budgets were not enabled).
    """

    content: str
    thinking: Optional[str]
    tool_calls: List[dict]
    model: str
    usage: dict
    stop_reason: str
    effort_used: str
    budget_remaining: Optional[int]


@dataclass
class AgenticResult:
    """Result from an agentic tool-calling loop.

    Attributes:
        final_response: The model's final text output after completing
            the agentic loop.
        iterations: Number of iterations completed.
        tool_calls_made: Ordered list of all tool calls across iterations.
        total_tokens: Aggregated token usage with ``input_tokens``,
            ``output_tokens``, and ``thinking_tokens`` keys.
        budget_used: Total thinking budget tokens consumed.
        budget_remaining: Remaining thinking budget tokens.
        thinking_trace: Ordered list of thinking summaries from each
            iteration.
        cost: Estimated cost breakdown with ``input_cost``,
            ``output_cost``, and ``total_cost`` keys.
    """

    final_response: str
    iterations: int
    tool_calls_made: List[dict]
    total_tokens: dict
    budget_used: int
    budget_remaining: int
    thinking_trace: List[str]
    cost: dict


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class Opus47Provider:
    """Anthropic Claude Opus 4.7 provider using raw HTTP via httpx.

    This provider communicates directly with the Anthropic Messages API
    without requiring the ``anthropic`` Python SDK.  It uses ``httpx``
    for all async HTTP requests.

    Usage::

        provider = Opus47Provider()
        resp = await provider.chat(
            messages=[{"role": "user", "content": "Hello, Opus 4.7!"}],
            system="You are a helpful assistant.",
        )
        print(resp.content)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.anthropic.com",
        effort: str = "xhigh",
        task_budget: Optional[int] = None,
    ) -> None:
        self.api_key: str = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url: str = base_url.rstrip("/")
        self.effort: str = effort
        self.task_budget: Optional[int] = task_budget
        self.client: Optional[Any] = None  # Lazy-initialised httpx.AsyncClient

    # -- HTTP helpers -------------------------------------------------------

    def _ensure_httpx(self) -> None:
        """Raise a clear error if httpx is not installed."""
        if not HAS_HTTPX:
            raise ImportError(
                "httpx is required for the Opus 4.7 provider. "
                "Install with: pip install httpx"
            )

    def _get_client(self) -> Any:
        """Lazy-initialise and return the httpx.AsyncClient.

        Returns:
            An ``httpx.AsyncClient`` instance configured with a 120-second
            timeout.
        """
        self._ensure_httpx()
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self.client

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers for the Anthropic Messages API.

        Returns:
            Dict of headers including authentication, API version,
            content type, and optional beta headers.
        """
        headers: Dict[str, str] = {
            "x-api-key": self.api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        if self.task_budget is not None:
            headers["anthropic-beta"] = BETA_HEADERS["task_budgets"]
        return headers

    def _get_thinking_budget(self, effort: str) -> int:
        """Return the thinking token budget for the given effort level.

        Args:
            effort: One of ``"low"``, ``"medium"``, ``"high"``, or
                ``"xhigh"``.

        Returns:
            Token budget ceiling for the thinking phase.

        Raises:
            ValueError: If the effort level is not recognised.
        """
        effort = effort.lower()
        if effort not in _THINKING_BUDGETS:
            raise ValueError(
                f"Unknown effort level '{effort}'. "
                f"Choose from: {', '.join(EFFORT_LEVELS)}"
            )
        return _THINKING_BUDGETS[effort]

    # -- Core chat method ---------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
        effort: Optional[str] = None,
        task_budget: Optional[int] = None,
        max_tokens: int = 8192,
        thinking: bool = True,
    ) -> Opus47Response:
        """Send a chat completion request to the Opus 4.7 Messages API.

        Builds the full request payload, including optional extended
        thinking configuration and task-budget beta headers, and sends
        it via ``httpx.AsyncClient``.

        Args:
            messages: Conversation messages in Anthropic format
                (list of ``{"role": ..., "content": ...}`` dicts).
            system: Optional system prompt.
            tools: Optional list of tool definitions in Anthropic format.
            effort: Thinking effort level override (default uses
                ``self.effort``).
            task_budget: Per-request task budget override (default uses
                ``self.task_budget``).
            max_tokens: Maximum output tokens for the response.
            thinking: Whether to enable extended thinking.

        Returns:
            :class:`Opus47Response` with the parsed API response.

        Raises:
            ImportError: If httpx is not installed.
            RuntimeError: If the API returns a non-2xx status code.
        """
        self._ensure_httpx()
        client = self._get_client()
        effective_effort: str = effort or self.effort
        effective_budget: Optional[int] = task_budget if task_budget is not None else self.task_budget

        # Build request payload
        payload: Dict[str, Any] = {
            "model": MODEL_ID,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        if system:
            payload["system"] = system

        if tools:
            payload["tools"] = tools

        if thinking:
            thinking_budget = self._get_thinking_budget(effective_effort)
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }
            # Temperature must be 1.0 when extended thinking is active
            payload["temperature"] = 1.0

        if effective_budget is not None:
            payload["task_budget"] = effective_budget

        # Build headers (with beta if task_budget active)
        headers = self._build_headers()
        if effective_budget is not None and "anthropic-beta" not in headers:
            headers["anthropic-beta"] = BETA_HEADERS["task_budgets"]

        url = f"{self.base_url}/v1/messages"

        log.debug(
            "chat(): model=%s effort=%s thinking=%s max_tokens=%d",
            MODEL_ID, effective_effort, thinking, max_tokens,
        )

        try:
            response = await client.post(url, headers=headers, json=payload)
        except Exception as exc:
            log.error("chat(): HTTP request failed: %s", exc)
            raise RuntimeError(f"Opus 4.7 API request failed: {exc}") from exc

        if response.status_code >= 400:
            error_body = response.text
            log.error(
                "chat(): API error status=%d body=%s",
                response.status_code, error_body[:500],
            )
            raise RuntimeError(
                f"Opus 4.7 API returned {response.status_code}: {error_body[:500]}"
            )

        data: Dict[str, Any] = response.json()
        return self._parse_response(data, effective_effort)

    # -- Vision method ------------------------------------------------------

    async def chat_with_vision(
        self,
        messages: List[Dict[str, Any]],
        images: List[bytes],
        system: str = "",
        max_tokens: int = 4096,
    ) -> Opus47Response:
        """Send a multimodal chat request with base64-encoded images.

        Each image is encoded as a base64 ``image/png`` content block
        and prepended to the last user message.  Images are resized by
        the API to fit within a 2576px long-edge bounding box.

        Args:
            messages: Conversation messages in Anthropic format.
            images: List of raw image bytes (JPEG, PNG, GIF, or WebP).
            system: Optional system prompt.
            max_tokens: Maximum output tokens for the response.

        Returns:
            :class:`Opus47Response` with the parsed API response.

        Raises:
            ImportError: If httpx is not installed.
            RuntimeError: If the API returns a non-2xx status code.
        """
        self._ensure_httpx()
        client = self._get_client()

        # Build image content blocks
        image_blocks: List[Dict[str, Any]] = []
        for img_bytes in images:
            b64_data = base64.b64encode(img_bytes).decode("utf-8")
            # Detect MIME type from magic bytes
            mime_type = _detect_image_mime(img_bytes)
            image_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": b64_data,
                },
            })

        # Clone messages and inject images into the last user message
        augmented_messages: List[Dict[str, Any]] = []
        for msg in messages:
            augmented_messages.append(dict(msg))

        # Find the last user message and convert its content to a list
        for i in range(len(augmented_messages) - 1, -1, -1):
            if augmented_messages[i].get("role") == "user":
                original_content = augmented_messages[i].get("content", "")
                content_blocks: List[Dict[str, Any]] = list(image_blocks)
                if isinstance(original_content, str):
                    content_blocks.append({"type": "text", "text": original_content})
                elif isinstance(original_content, list):
                    content_blocks.extend(original_content)
                augmented_messages[i]["content"] = content_blocks
                break

        payload: Dict[str, Any] = {
            "model": MODEL_ID,
            "max_tokens": max_tokens,
            "messages": augmented_messages,
        }

        if system:
            payload["system"] = system

        headers = self._build_headers()
        url = f"{self.base_url}/v1/messages"

        log.debug(
            "chat_with_vision(): model=%s images=%d max_tokens=%d",
            MODEL_ID, len(images), max_tokens,
        )

        try:
            response = await client.post(url, headers=headers, json=payload)
        except Exception as exc:
            log.error("chat_with_vision(): HTTP request failed: %s", exc)
            raise RuntimeError(
                f"Opus 4.7 vision API request failed: {exc}"
            ) from exc

        if response.status_code >= 400:
            error_body = response.text
            log.error(
                "chat_with_vision(): API error status=%d body=%s",
                response.status_code, error_body[:500],
            )
            raise RuntimeError(
                f"Opus 4.7 API returned {response.status_code}: {error_body[:500]}"
            )

        data: Dict[str, Any] = response.json()
        return self._parse_response(data, self.effort)

    # -- Agentic loop -------------------------------------------------------

    async def agentic_loop(
        self,
        task: str,
        tools: List[Dict[str, Any]],
        system: str = "",
        budget_tokens: int = 50_000,
        max_iterations: int = 20,
    ) -> AgenticResult:
        """Run an iterative tool-calling agentic loop.

        The loop sends the task to the model with the provided tools,
        then iteratively feeds tool results back until the model signals
        completion (``end_turn``), the thinking budget is exhausted, or
        the maximum number of iterations is reached.

        Tool execution is the caller's responsibility: this method
        generates placeholder results for tool calls.  Override or
        wrap this method to inject real tool execution.

        Args:
            task: The user task to accomplish.
            tools: List of tool definitions in Anthropic format.
            system: Optional system prompt.
            budget_tokens: Total thinking token budget for the loop.
            max_iterations: Maximum number of loop iterations.

        Returns:
            :class:`AgenticResult` with the full execution trace.

        Raises:
            ImportError: If httpx is not installed.
            RuntimeError: If an API call fails.
        """
        self._ensure_httpx()

        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": task},
        ]

        all_tool_calls: List[dict] = []
        thinking_trace: List[str] = []
        total_input_tokens: int = 0
        total_output_tokens: int = 0
        total_thinking_tokens: int = 0
        budget_used: int = 0
        iterations: int = 0
        final_response: str = ""

        log.info(
            "agentic_loop(): starting task=%s budget=%d max_iter=%d",
            task[:80], budget_tokens, max_iterations,
        )

        for iteration in range(max_iterations):
            iterations = iteration + 1

            # Calculate remaining budget for thinking
            remaining = max(0, budget_tokens - budget_used)
            if remaining == 0:
                log.info(
                    "agentic_loop(): budget exhausted at iteration %d",
                    iterations,
                )
                break

            # Determine effort based on remaining budget
            if remaining >= _THINKING_BUDGETS["xhigh"]:
                iter_effort = "xhigh"
            elif remaining >= _THINKING_BUDGETS["high"]:
                iter_effort = "high"
            elif remaining >= _THINKING_BUDGETS["medium"]:
                iter_effort = "medium"
            else:
                iter_effort = "low"

            # Send request
            response = await self.chat(
                messages=messages,
                system=system,
                tools=tools,
                effort=iter_effort,
                max_tokens=MAX_OUTPUT_TOKENS,
                thinking=True,
            )

            # Track token usage
            iter_input = response.usage.get("input_tokens", 0)
            iter_output = response.usage.get("output_tokens", 0)
            iter_thinking = response.usage.get("thinking_tokens", 0)
            total_input_tokens += iter_input
            total_output_tokens += iter_output
            total_thinking_tokens += iter_thinking
            budget_used += iter_thinking

            if response.thinking:
                thinking_trace.append(response.thinking)

            log.debug(
                "agentic_loop(): iteration=%d stop_reason=%s tool_calls=%d "
                "thinking_tokens=%d budget_used=%d/%d",
                iterations, response.stop_reason, len(response.tool_calls),
                iter_thinking, budget_used, budget_tokens,
            )

            # If the model finished without tool calls, we are done
            if response.stop_reason == "end_turn" and not response.tool_calls:
                final_response = response.content
                break

            # If the model made tool calls, process them
            if response.tool_calls:
                all_tool_calls.extend(response.tool_calls)

                # Append the assistant's response (with tool_use blocks) to messages
                assistant_content: List[Dict[str, Any]] = []
                if response.content:
                    assistant_content.append({
                        "type": "text",
                        "text": response.content,
                    })
                for tc in response.tool_calls:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"tool_{iterations}_{len(all_tool_calls)}"),
                        "name": tc.get("name", "unknown"),
                        "input": tc.get("input", {}),
                    })

                messages.append({"role": "assistant", "content": assistant_content})

                # Build tool_result blocks for each tool call
                tool_results: List[Dict[str, Any]] = []
                for tc in response.tool_calls:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.get("id", f"tool_{iterations}_{len(all_tool_calls)}"),
                        "content": json.dumps({
                            "status": "pending",
                            "message": (
                                f"Tool '{tc.get('name', 'unknown')}' called. "
                                "Override agentic_loop() to provide real tool execution."
                            ),
                        }),
                    })
                messages.append({"role": "user", "content": tool_results})
            else:
                # No tool calls and stop_reason is not end_turn (e.g., max_tokens)
                final_response = response.content
                break

        # If we exhausted iterations without an end_turn, use the last content
        if not final_response and iterations > 0:
            final_response = response.content  # type: ignore[possibly-undefined]

        cost = self.estimate_cost(total_input_tokens, total_output_tokens)

        result = AgenticResult(
            final_response=final_response,
            iterations=iterations,
            tool_calls_made=all_tool_calls,
            total_tokens={
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "thinking_tokens": total_thinking_tokens,
            },
            budget_used=budget_used,
            budget_remaining=max(0, budget_tokens - budget_used),
            thinking_trace=thinking_trace,
            cost=cost,
        )

        log.info(
            "agentic_loop(): completed iterations=%d tool_calls=%d "
            "budget_used=%d/%d total_cost=$%.4f",
            iterations, len(all_tool_calls), budget_used, budget_tokens,
            cost["total_cost"],
        )

        return result

    # -- Cost estimation ----------------------------------------------------

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> Dict[str, float]:
        """Estimate the USD cost for a request.

        Applies premium pricing automatically when ``input_tokens``
        exceeds 200,000 (the premium context threshold).

        Args:
            input_tokens: Number of prompt / context tokens.
            output_tokens: Number of generated completion tokens.

        Returns:
            Dict with ``input_cost``, ``output_cost``, and
            ``total_cost`` keys, each rounded to 4 decimal places.
        """
        if input_tokens > 200_000:
            pricing = PREMIUM_PRICING
        else:
            pricing = PRICING

        input_cost = round((input_tokens / 1_000_000) * pricing["input"], 4)
        output_cost = round((output_tokens / 1_000_000) * pricing["output"], 4)
        total_cost = round(input_cost + output_cost, 4)

        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
        }

    # -- Tool definitions ---------------------------------------------------

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for the Opus 4.7 provider capabilities.

        Provides three tools that expose the provider's main methods:

        * ``opus47_chat`` — standard chat with optional thinking.
        * ``opus47_vision`` — multimodal chat with image inputs.
        * ``opus47_agentic`` — iterative agentic tool-calling loop.

        Returns:
            List of Anthropic-format tool definition dicts.
        """
        return [
            {
                "name": "opus47_chat",
                "description": (
                    "Send a chat message to Claude Opus 4.7 with optional "
                    "extended thinking. Supports effort levels: low, medium, "
                    "high, xhigh."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "messages": {
                            "type": "array",
                            "description": "Conversation messages in Anthropic format.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "role": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                                "required": ["role", "content"],
                            },
                        },
                        "system": {
                            "type": "string",
                            "description": "Optional system prompt.",
                        },
                        "effort": {
                            "type": "string",
                            "description": "Thinking effort level.",
                            "enum": EFFORT_LEVELS,
                        },
                        "max_tokens": {
                            "type": "integer",
                            "description": "Maximum output tokens.",
                            "default": 8192,
                        },
                        "thinking": {
                            "type": "boolean",
                            "description": "Enable extended thinking.",
                            "default": True,
                        },
                    },
                    "required": ["messages"],
                },
            },
            {
                "name": "opus47_vision",
                "description": (
                    "Send a multimodal chat request to Claude Opus 4.7 "
                    "with base64-encoded images. Max resolution: 2576px "
                    "long edge."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "messages": {
                            "type": "array",
                            "description": "Conversation messages in Anthropic format.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "role": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                                "required": ["role", "content"],
                            },
                        },
                        "images_base64": {
                            "type": "array",
                            "description": "Base64-encoded image strings.",
                            "items": {"type": "string"},
                        },
                        "system": {
                            "type": "string",
                            "description": "Optional system prompt.",
                        },
                        "max_tokens": {
                            "type": "integer",
                            "description": "Maximum output tokens.",
                            "default": 4096,
                        },
                    },
                    "required": ["messages", "images_base64"],
                },
            },
            {
                "name": "opus47_agentic",
                "description": (
                    "Run an iterative agentic tool-calling loop with "
                    "Claude Opus 4.7. Tracks token budget and returns "
                    "full execution trace."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The task to accomplish.",
                        },
                        "tools": {
                            "type": "array",
                            "description": "Tool definitions in Anthropic format.",
                            "items": {"type": "object"},
                        },
                        "system": {
                            "type": "string",
                            "description": "Optional system prompt.",
                        },
                        "budget_tokens": {
                            "type": "integer",
                            "description": "Total thinking token budget.",
                            "default": 50000,
                        },
                        "max_iterations": {
                            "type": "integer",
                            "description": "Maximum loop iterations.",
                            "default": 20,
                        },
                    },
                    "required": ["task", "tools"],
                },
            },
        ]

    # -- Response parsing ---------------------------------------------------

    def _parse_response(
        self,
        data: Dict[str, Any],
        effort_used: str,
    ) -> Opus47Response:
        """Parse an Anthropic Messages API response into an Opus47Response.

        Extracts text content, thinking blocks, tool-use blocks, and
        usage information from the raw JSON response.

        Args:
            data: Raw JSON response dict from the API.
            effort_used: The effort level that was applied.

        Returns:
            Parsed :class:`Opus47Response`.
        """
        content_blocks: List[Dict[str, Any]] = data.get("content", [])
        text_parts: List[str] = []
        thinking_parts: List[str] = []
        tool_calls: List[dict] = []

        for block in content_blocks:
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "thinking":
                thinking_parts.append(block.get("thinking", ""))
            elif block_type == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": block.get("input", {}),
                })

        usage_data = data.get("usage", {})
        usage: Dict[str, int] = {
            "input_tokens": usage_data.get("input_tokens", 0),
            "output_tokens": usage_data.get("output_tokens", 0),
            "thinking_tokens": usage_data.get("cache_creation_input_tokens", 0),
        }

        return Opus47Response(
            content="\n".join(text_parts) if text_parts else "",
            thinking="\n".join(thinking_parts) if thinking_parts else None,
            tool_calls=tool_calls,
            model=data.get("model", MODEL_ID),
            usage=usage,
            stop_reason=data.get("stop_reason", ""),
            effort_used=effort_used,
            budget_remaining=data.get("budget_remaining"),
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _detect_image_mime(data: bytes) -> str:
    """Detect the MIME type of an image from its magic bytes.

    Supports JPEG, PNG, GIF, and WebP.  Falls back to ``image/png``
    if the format is not recognised.

    Args:
        data: Raw image bytes.

    Returns:
        MIME type string.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"
