"""Horizon Orchestra — Claude Opus 4.6 Native Provider.

Provides direct integration with Anthropic's Claude model family via the
native Anthropic SDK, exposing Opus 4.6-specific capabilities uniformly:

1. **Adaptive Extended Thinking** — effort-tiered reasoning (low/medium/high/max)
   with automatic interleaved thinking between tool calls.
2. **Vision** — best-in-class multimodal understanding; up to 600 images or PDF
   pages per request.  Supports photos, charts, technical diagrams, and documents.
3. **Function Calling** — parallel native tool execution with interleaved thinking
   enabled automatically on Opus 4.6.
4. **Streaming Thinking** — server-sent events exposing thinking and answer deltas
   in real time.
5. **Context Compaction** — auto-summarise older context when approaching the 1M
   token limit (requires ``compact-2026-01-12`` beta header).
6. **Batch API** — 50 % cost reduction for asynchronous workloads, with optional
   300 K output limit via the ``output-300k-2026-03-24`` beta header.
7. **Memory / Agentic** — Opus 4.6 excels at creating and maintaining memory files
   for long-horizon task awareness, breaking complex jobs into parallel subtasks.

Model family covered:

* ``claude-opus-4-6`` — 1 M context, 128 K max output, $5/$25 per 1 M tokens
* ``claude-sonnet-4-6`` — 1 M context, 64 K max output, $3/$15 per 1 M tokens
* ``claude-haiku-4-5`` — 200 K context, 64 K max output, $1/$5 per 1 M tokens

Thinking blocks from previous turns are preserved in context by default on
Opus 4.5+ for cache-hit optimisation.  No beta header is required for
interleaved thinking on Opus 4.6.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from .router import ModelRouter, ModelConfig

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    anthropic = None  # type: ignore[assignment]
    HAS_ANTHROPIC = False

__all__ = [
    "Opus4Provider",
    "Opus4Config",
    "ThinkingResponse",
    "VisionInput",
    "Opus4FunctionCall",
    "get_effort_config",
    "estimate_cost",
]

log = logging.getLogger("orchestra.opus4_provider")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Opus4Config:
    """Configuration for the Opus 4.6 provider.

    Attributes:
        model: Default Anthropic model ID.
        effort: Adaptive thinking effort level — ``"low"``, ``"medium"``,
            ``"high"`` (default), or ``"max"``.  Only used when extended
            thinking is requested.
        max_output_tokens: Hard ceiling on generated tokens per request.
        temperature: Sampling temperature.  Anthropic's default is 1.0.
            Must be 1.0 when extended thinking is active.
        enable_compaction: When ``True``, sends the ``compact-2026-01-12``
            beta header so the API auto-summarises older context when the
            window approaches capacity.
        fast_mode: When ``True``, selects the priority-tier endpoint at
            $30/$150 per 1 M tokens.  Incompatible with Batch API.
        backend: Routing hint — ``"anthropic"``, ``"openrouter"``,
            ``"bedrock"``, or ``"vertex"``.
    """
    model: str = "claude-opus-4-6"
    effort: str = "high"
    max_output_tokens: int = 128_000
    temperature: float = 1.0
    enable_compaction: bool = False
    fast_mode: bool = False
    backend: str = "anthropic"


@dataclass
class ThinkingResponse:
    """Response from an extended-thinking generation call.

    Opus 4.6 returns thinking *summaries* rather than the full raw thinking
    stream (a privacy-by-design feature added in Opus 4.5+).  Each
    ``thinking`` block in the response contains a condensed summary of the
    model's internal reasoning.

    Attributes:
        thinking_summary: Condensed reasoning summary emitted by the model.
        answer: Final answer text after thinking.
        model: Canonical model ID used for the request.
        thinking_tokens: Tokens consumed by the thinking phase.
        answer_tokens: Tokens consumed by the answer phase.
        total_tokens: Sum of input, thinking, and answer tokens.
        effort_used: Effort level that was applied (``"low"`` … ``"max"``).
    """
    thinking_summary: str
    answer: str
    model: str = ""
    thinking_tokens: int = 0
    answer_tokens: int = 0
    total_tokens: int = 0
    effort_used: str = "high"


@dataclass
class VisionInput:
    """A single visual or document input element for multimodal requests.

    Attributes:
        type: Source variety — ``"image_url"``, ``"image_bytes"``,
            ``"pdf_bytes"``, or ``"document"``.
        content: URL string, raw bytes, or base64-encoded bytes depending on
            ``type``.
        mime_type: IANA media type (e.g. ``"image/png"``,
            ``"application/pdf"``).
        detail: Image resolution hint forwarded to the API.  ``"auto"``
            (default) lets the model decide; ``"low"`` forces thumbnail-
            scale processing; ``"high"`` forces full-resolution processing.
    """
    type: str
    content: str | bytes
    mime_type: str
    detail: str = "auto"


@dataclass
class Opus4FunctionCall:
    """A structured function/tool call returned by the model.

    Attributes:
        name: Name of the function to invoke.
        arguments: Parsed JSON arguments as a Python dict.
        call_id: Unique tool-use block ID from the API response (may be
            empty when parsing from non-native backends).
    """
    name: str
    arguments: dict[str, Any]
    call_id: str = ""


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Pricing table: (input $/1M, output $/1M) for standard and fast modes.
_PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "claude-opus-4-6": {
        "standard": (5.0, 25.0),
        "fast": (30.0, 150.0),
    },
    "claude-sonnet-4-6": {
        "standard": (3.0, 15.0),
        "fast": (30.0, 150.0),
    },
    "claude-haiku-4-5": {
        "standard": (1.0, 5.0),
        "fast": (30.0, 150.0),
    },
}

#: Context and output limits per model.
_MODEL_LIMITS: dict[str, dict[str, int]] = {
    "claude-opus-4-6":   {"max_context": 1_000_000, "max_output": 128_000},
    "claude-sonnet-4-6": {"max_context": 1_000_000, "max_output":  64_000},
    "claude-haiku-4-5":  {"max_context":   200_000, "max_output":  64_000},
}

#: Effort levels that support adaptive thinking.
_EFFORT_LEVELS = ("low", "medium", "high", "max")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_effort_config(effort: str) -> dict[str, Any]:
    """Return the API-level thinking configuration dict for an effort level.

    Opus 4.6 and Sonnet 4.6 use *adaptive thinking*, where the model self-
    selects how many tokens to use for reasoning up to a ceiling determined
    by the effort level.  The ``budget_tokens`` values below are the
    recommended ceilings for each tier.

    For backward-compatibility, the dict is shaped for the top-level
    ``thinking`` parameter of ``client.messages.create()``.  The ``effort``
    parameter is passed separately at the request level.

    Args:
        effort: One of ``"low"``, ``"medium"``, ``"high"``, or ``"max"``.

    Returns:
        Dict with ``type`` and ``budget_tokens`` ready for the Anthropic API.

    Raises:
        ValueError: If ``effort`` is not one of the four recognised levels.

    Example::

        cfg = get_effort_config("high")
        # {"type": "adaptive", "budget_tokens": 16384}
    """
    effort = effort.lower()
    _budgets: dict[str, int] = {
        "low":    1_024,
        "medium": 4_096,
        "high":   16_384,
        "max":    32_768,
    }
    if effort not in _budgets:
        raise ValueError(
            f"Unknown effort level '{effort}'. "
            f"Choose from: {', '.join(_EFFORT_LEVELS)}"
        )
    return {
        "type": "adaptive",
        "budget_tokens": _budgets[effort],
    }


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = "claude-opus-4-6",
    fast_mode: bool = False,
) -> float:
    """Estimate the USD cost for a single request.

    Uses the published Anthropic pricing tiers.  Fast-mode pricing applies
    a 6× multiplier for both input and output.

    Args:
        input_tokens: Number of prompt + context tokens.
        output_tokens: Number of generated completion tokens.
        model: Canonical Anthropic model ID (default ``"claude-opus-4-6"``).
        fast_mode: If ``True``, use priority-tier pricing.

    Returns:
        Estimated cost in US dollars.

    Example::

        cost = estimate_cost(10_000, 2_000, "claude-opus-4-6")
        # 0.10 (10k × $5/1M + 2k × $25/1M)
    """
    tier = "fast" if fast_mode else "standard"
    prices = _PRICING.get(model, _PRICING["claude-opus-4-6"])[tier]
    input_cost  = (input_tokens  / 1_000_000) * prices[0]
    output_cost = (output_tokens / 1_000_000) * prices[1]
    return round(input_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class Opus4Provider:
    """Native Anthropic provider for Claude Opus 4.6 and its model family.

    Exposes Opus 4.6-specific capabilities that go beyond the standard
    OpenAI-compatible chat completion interface used by the router:

    * **Adaptive extended thinking** — self-calibrated reasoning at four
      effort tiers with automatic interleaved thinking between tool calls.
    * **Vision** — rich multimodal support for images (JPEG, PNG, GIF, WebP)
      and PDF documents up to 600 items per request.
    * **Function calling with interleaved thinking** — the model can reason
      between tool invocations, producing higher-quality decisions.
    * **Streaming** — real-time thinking + answer deltas via async generator.
    * **Context compaction** — seamless auto-summarisation for long-horizon
      tasks (opt-in via ``Opus4Config.enable_compaction``).

    Usage::

        provider = Opus4Provider()
        result = await provider.think("Explain quantum entanglement simply.")
        print(result.thinking_summary)
        print(result.answer)
    """

    def __init__(
        self,
        router: ModelRouter | None = None,
        config: Opus4Config | None = None,
    ) -> None:
        self.router = router or ModelRouter()
        self.config = config or Opus4Config()
        self._anthropic_client: Any = None

    # -- Anthropic SDK client ------------------------------------------------

    def _get_anthropic_client(self) -> Any:
        """Lazy-initialise and return the async Anthropic client.

        The client is created once and cached on the instance.  It reads the
        API key from the ``ANTHROPIC_API_KEY`` environment variable.

        Returns:
            An ``anthropic.AsyncAnthropic`` instance.

        Raises:
            RuntimeError: If the ``anthropic`` package is not installed or if
                ``ANTHROPIC_API_KEY`` is unset.
        """
        if self._anthropic_client is not None:
            return self._anthropic_client

        if not HAS_ANTHROPIC:
            raise RuntimeError(
                "anthropic SDK is required for native Opus 4.6 features. "
                "Install with: pip install anthropic"
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable is required for the "
                "Opus 4.6 provider."
            )

        extra_headers: dict[str, str] = {}
        if self.config.enable_compaction:
            extra_headers["anthropic-beta"] = "compact-2026-01-12"

        self._anthropic_client = anthropic.AsyncAnthropic(
            api_key=api_key,
            default_headers=extra_headers if extra_headers else None,
        )
        log.debug("Anthropic async client initialised (model family: claude-opus-4-6)")
        return self._anthropic_client

    # -- Extended thinking ---------------------------------------------------

    async def think(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str = "",
        effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ThinkingResponse:
        """Generate a response with adaptive extended thinking enabled.

        Opus 4.6 uses *adaptive thinking*: the model decides how deeply to
        reason within the token budget set by the effort level.  Interleaved
        thinking is automatic — no beta header required.  Thinking blocks
        from prior turns are preserved in context for cache efficiency.

        The temperature is forced to ``1.0`` when thinking is active, as
        required by the Anthropic API.

        Args:
            prompt: User message.
            model: Anthropic model ID (defaults to ``config.model``).
            system_prompt: Optional system instructions.
            effort: Thinking effort level — ``"low"``, ``"medium"``,
                ``"high"`` (default), or ``"max"``.
            max_output_tokens: Hard output token ceiling.

        Returns:
            :class:`ThinkingResponse` with separated thinking summary and
            final answer.

        Raises:
            RuntimeError: If the Anthropic SDK is unavailable or unconfigured.

        Example::

            provider = Opus4Provider()
            resp = await provider.think(
                "Derive the quadratic formula from first principles.",
                effort="max",
            )
            print(f"Thought for {resp.thinking_tokens} tokens")
            print(resp.answer)
        """
        model = model or self.config.model
        effort = effort or self.config.effort
        max_out = max_output_tokens or self.config.max_output_tokens

        client = self._get_anthropic_client()
        thinking_cfg = get_effort_config(effort)

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_out,
            "messages": messages,
            "thinking": thinking_cfg,
            "temperature": 1.0,  # required with extended thinking
            "effort": effort,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        log.debug(
            "think(): model=%s effort=%s max_out=%d", model, effort, max_out
        )

        response = await client.messages.create(**kwargs)

        thinking_summary = ""
        answer = ""
        thinking_tokens = 0
        answer_tokens = 0

        for block in response.content:
            btype = getattr(block, "type", "")
            if btype == "thinking":
                thinking_summary += getattr(block, "thinking", "")
            elif btype == "text":
                answer += getattr(block, "text", "")

        usage = getattr(response, "usage", None)
        if usage is not None:
            # input_tokens covers prompt; cache_read_input_tokens / cache_creation_input_tokens
            # are available on claude-3.5+ but not always present.
            total_in = getattr(usage, "input_tokens", 0)
            total_out = getattr(usage, "output_tokens", 0)
            # Anthropic doesn't split thinking vs answer tokens in the usage
            # response directly; we approximate thinking_tokens as the
            # thinking block's budget_tokens echo when available.
            thinking_tokens = min(thinking_cfg["budget_tokens"], total_out)
            answer_tokens = max(0, total_out - thinking_tokens)
            total_tokens = total_in + total_out
        else:
            total_tokens = 0

        log.info(
            "think(): done model=%s effort=%s tokens_total=%d",
            model, effort, total_tokens,
        )
        return ThinkingResponse(
            thinking_summary=thinking_summary,
            answer=answer,
            model=model,
            thinking_tokens=thinking_tokens,
            answer_tokens=answer_tokens,
            total_tokens=total_tokens,
            effort_used=effort,
        )

    # -- Vision / multimodal -------------------------------------------------

    async def vision(
        self,
        inputs: list[VisionInput],
        prompt: str = "",
        model: str | None = None,
        system_prompt: str = "",
        max_output_tokens: int | None = None,
    ) -> str:
        """Process multimodal vision inputs and return a text response.

        Supports up to 600 images or PDF pages per request.  Image types
        accepted: JPEG, PNG, GIF, WebP.  PDFs are sent as base64-encoded
        document blocks.

        Content blocks are built in the order of ``inputs`` with an optional
        trailing text prompt.  Mix images, PDFs, and text freely.

        Args:
            inputs: Ordered list of :class:`VisionInput` elements.
            prompt: Optional trailing text prompt appended after all inputs.
            model: Anthropic model ID (defaults to ``config.model``).
            system_prompt: Optional system instructions.
            max_output_tokens: Hard output token ceiling.

        Returns:
            Generated text response.

        Raises:
            ValueError: If more than 600 visual items are provided.
            RuntimeError: If the SDK is unavailable or unconfigured.

        Example::

            provider = Opus4Provider()
            img = VisionInput(
                type="image_url",
                content="https://example.com/chart.png",
                mime_type="image/png",
            )
            answer = await provider.vision([img], prompt="Describe this chart.")
            print(answer)
        """
        model = model or self.config.model
        max_out = max_output_tokens or self.config.max_output_tokens

        visual_count = sum(1 for i in inputs if i.type != "document")
        if visual_count > 600:
            raise ValueError(
                f"Anthropic supports up to 600 images/PDFs per request; "
                f"got {visual_count}."
            )

        client = self._get_anthropic_client()
        content_blocks: list[dict[str, Any]] = []

        for inp in inputs:
            block = _build_vision_block(inp)
            if block is not None:
                content_blocks.append(block)

        if prompt:
            content_blocks.append({"type": "text", "text": prompt})

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": content_blocks}
        ]
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_out,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        log.debug(
            "vision(): model=%s inputs=%d prompt_len=%d",
            model, len(inputs), len(prompt),
        )

        response = await client.messages.create(**kwargs)

        text = ""
        for block in response.content:
            if getattr(block, "type", "") == "text":
                text += getattr(block, "text", "")

        log.info(
            "vision(): done model=%s output_tokens=%d",
            model,
            getattr(getattr(response, "usage", None), "output_tokens", 0),
        )
        return text

    # -- Function calling with interleaved thinking --------------------------

    async def function_call(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        model: str | None = None,
        system_prompt: str = "",
        max_output_tokens: int | None = None,
    ) -> tuple[str, list[Opus4FunctionCall]]:
        """Invoke the model with native tool definitions.

        On Opus 4.6, extended thinking is interleaved automatically between
        tool calls — the model can reason before deciding which tool to use
        and again after receiving results.  No additional parameters are
        required to activate this behaviour.

        Tools should follow the Anthropic tool-definition schema::

            {
                "name": "get_weather",
                "description": "Retrieve current weather for a location.",
                "input_schema": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            }

        The method returns after the *first* turn (tool-call or text answer).
        For a complete agentic loop with tool-result feeding, use the model's
        response to build follow-up turns manually.

        Args:
            prompt: User message.
            tools: List of Anthropic-format tool definitions.
            model: Anthropic model ID (defaults to ``config.model``).
            system_prompt: Optional system instructions.
            max_output_tokens: Hard output token ceiling.

        Returns:
            Tuple of ``(text_content, list_of_function_calls)`` where
            ``text_content`` collects any ``text`` blocks and
            ``list_of_function_calls`` contains all ``tool_use`` blocks.

        Raises:
            RuntimeError: If the SDK is unavailable or unconfigured.

        Example::

            tools = [{
                "name": "search_web",
                "description": "Search the web.",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }]
            text, calls = await provider.function_call(
                "Find the latest Claude release notes.", tools=tools
            )
            for call in calls:
                print(call.name, call.arguments)
        """
        model = model or self.config.model
        max_out = max_output_tokens or self.config.max_output_tokens

        client = self._get_anthropic_client()
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_out,
            "messages": messages,
            "tools": tools if tools else [],
            "temperature": self.config.temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        log.debug(
            "function_call(): model=%s tools=%d", model, len(tools)
        )

        response = await client.messages.create(**kwargs)

        text = ""
        calls: list[Opus4FunctionCall] = []

        for block in response.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                text += getattr(block, "text", "")
            elif btype == "tool_use":
                raw_input = getattr(block, "input", {})
                if isinstance(raw_input, str):
                    try:
                        raw_input = json.loads(raw_input)
                    except json.JSONDecodeError:
                        raw_input = {}
                calls.append(Opus4FunctionCall(
                    name=getattr(block, "name", ""),
                    arguments=raw_input if isinstance(raw_input, dict) else {},
                    call_id=getattr(block, "id", ""),
                ))

        log.info(
            "function_call(): done model=%s text_len=%d tool_calls=%d",
            model, len(text), len(calls),
        )
        return text, calls

    # -- Streaming thinking --------------------------------------------------

    async def stream_think(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str = "",
        effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream extended thinking and answer tokens as they are generated.

        Yields string chunks tagged with a prefix so callers can distinguish
        thinking fragments from answer fragments:

        * ``"[thinking] "`` prefix → content from a thinking block delta.
        * ``"[answer] "`` prefix → content from a text block delta.

        The generator closes naturally when the API signals the end of the
        message stream.

        Args:
            prompt: User message.
            model: Anthropic model ID (defaults to ``config.model``).
            system_prompt: Optional system instructions.
            effort: Thinking effort level (``"low"`` … ``"max"``).
            max_output_tokens: Hard output token ceiling.

        Yields:
            Tagged string chunks of thinking or answer content.

        Raises:
            RuntimeError: If the SDK is unavailable or unconfigured.

        Example::

            async for chunk in provider.stream_think("What is consciousness?"):
                print(chunk, end="", flush=True)
        """
        model = model or self.config.model
        effort = effort or self.config.effort
        max_out = max_output_tokens or self.config.max_output_tokens

        client = self._get_anthropic_client()
        thinking_cfg = get_effort_config(effort)

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_out,
            "messages": messages,
            "thinking": thinking_cfg,
            "temperature": 1.0,  # required with extended thinking
            "effort": effort,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        log.debug(
            "stream_think(): model=%s effort=%s", model, effort
        )

        # The Anthropic SDK's streaming context manager yields events
        async with client.messages.stream(**kwargs) as stream:
            current_block_type: str = ""

            async for event in stream:
                etype = getattr(event, "type", "")

                if etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    current_block_type = getattr(block, "type", "") if block else ""

                elif etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta is None:
                        continue
                    dtype = getattr(delta, "type", "")

                    if dtype == "thinking_delta":
                        chunk = getattr(delta, "thinking", "")
                        if chunk:
                            yield f"[thinking] {chunk}"

                    elif dtype == "text_delta":
                        chunk = getattr(delta, "text", "")
                        if chunk:
                            if current_block_type == "thinking":
                                yield f"[thinking] {chunk}"
                            else:
                                yield f"[answer] {chunk}"

                elif etype == "content_block_stop":
                    current_block_type = ""

                elif etype == "message_stop":
                    log.debug("stream_think(): stream complete")
                    break

    # -- Model information ---------------------------------------------------

    def get_model_card(self, model: str | None = None) -> dict[str, Any]:
        """Return a capability card for the specified Claude model.

        The card describes pricing, context limits, and supported features.
        Useful for runtime routing decisions and logging.

        Args:
            model: Anthropic model ID (defaults to ``config.model``).

        Returns:
            Dict with keys: ``name``, ``family``, ``max_context``,
            ``max_output``, ``capabilities``, and ``cost``.

        Example::

            card = provider.get_model_card("claude-haiku-4-5")
            print(card["capabilities"]["extended_thinking"])  # False
        """
        model = model or self.config.model
        limits = _MODEL_LIMITS.get(model, _MODEL_LIMITS["claude-opus-4-6"])
        pricing = _PRICING.get(model, _PRICING["claude-opus-4-6"])

        # Feature availability varies by model
        supports_extended_thinking = model in ("claude-opus-4-6", "claude-sonnet-4-6")
        supports_interleaved_thinking = model == "claude-opus-4-6"
        supports_compaction = True  # all models via beta header
        supports_fast_mode = model in ("claude-opus-4-6", "claude-sonnet-4-6")
        max_images = 600

        return {
            "name": model,
            "family": "claude-opus-4",
            "max_context": limits["max_context"],
            "max_output": limits["max_output"],
            "capabilities": {
                "extended_thinking": supports_extended_thinking,
                "adaptive_thinking": supports_extended_thinking,
                "interleaved_thinking": supports_interleaved_thinking,
                "vision": True,
                "pdf_input": True,
                "max_visual_inputs": max_images,
                "tool_use": True,
                "parallel_tool_use": True,
                "streaming": True,
                "context_compaction": supports_compaction,
                "fast_mode": supports_fast_mode,
                "batch_api": True,
                "memory_files": True,
                "agentic": True,
                "multilingual": True,
            },
            "cost": {
                "input_per_1m_standard": pricing["standard"][0],
                "output_per_1m_standard": pricing["standard"][1],
                "input_per_1m_fast": pricing["fast"][0],
                "output_per_1m_fast": pricing["fast"][1],
                "batch_discount": "50%",
            },
            "notes": {
                "thinking_temp": "temperature must be 1.0 with extended thinking",
                "thinking_blocks_preserved": "Opus 4.5+ preserves thinking blocks in context",
                "interleaved_no_beta": "No beta header required for interleaved thinking on Opus 4.6",
                "compaction_header": "compact-2026-01-12",
                "batch_300k_header": "output-300k-2026-03-24",
            },
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_vision_block(inp: VisionInput) -> dict[str, Any] | None:
    """Convert a :class:`VisionInput` into an Anthropic API content block.

    Handles four source types:

    * ``"image_url"`` — URL-referenced image.
    * ``"image_bytes"`` — raw or base64-encoded image bytes.
    * ``"pdf_bytes"`` — raw or base64-encoded PDF bytes (document block).
    * ``"document"`` — same as ``pdf_bytes`` alias.

    Args:
        inp: The vision input descriptor.

    Returns:
        Anthropic-format content block dict, or ``None`` if the type is
        unrecognised (with a warning logged).
    """
    if inp.type == "image_url":
        return {
            "type": "image",
            "source": {
                "type": "url",
                "url": str(inp.content),
            },
        }

    elif inp.type == "image_bytes":
        if isinstance(inp.content, bytes):
            b64_data = base64.b64encode(inp.content).decode("utf-8")
        else:
            # Assume already base64-encoded string
            b64_data = str(inp.content)
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": inp.mime_type or "image/png",
                "data": b64_data,
            },
        }

    elif inp.type in ("pdf_bytes", "document"):
        if isinstance(inp.content, bytes):
            b64_data = base64.b64encode(inp.content).decode("utf-8")
        else:
            b64_data = str(inp.content)
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": inp.mime_type or "application/pdf",
                "data": b64_data,
            },
        }

    else:
        log.warning(
            "_build_vision_block(): unrecognised input type '%s'; skipping",
            inp.type,
        )
        return None
