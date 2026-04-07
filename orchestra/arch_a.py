"""Architecture A — Monolithic Orchestrator.

Single Kimi K2.5 agent loop with full tool surface and persistent memory.
The simplest architecture: one model, one loop, up to 300 sequential tool
calls.  Memory is injected into the system prompt and tools are available
for the agent to search/store memories mid-execution.

Usage::

    from orchestra.arch_a import MonolithicAgent
    agent = MonolithicAgent(user_id="ashton")
    result = await agent.run("Build a REST API for task management")
    print(result)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from .router import ModelRouter, ModelConfig
from .agent_loop import (
    AgentLoop,
    AgentConfig,
    AgentEvent,
    FinalAnswerEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolRegistry,
    create_default_tools,
)
from .memory import (
    MemoryStore,
    MemoryManager,
    SessionContext,
    register_memory_tools,
)
from .skills.base import SkillRegistry
from .perplexity import PerplexitySearch

# ---------------------------------------------------------------------------
# Optional module imports — guarded so the file loads even if modules are
# absent (e.g. during isolated unit tests or partial installs).
# ---------------------------------------------------------------------------

try:
    from .adaptive_context import (
        AdaptiveContext,
        AdaptiveContextConfig,
        TokenCounter,
        PriorityMessage,
    )
    _HAS_ADAPTIVE_CONTEXT = True
except ImportError:  # pragma: no cover
    AdaptiveContext = None  # type: ignore[assignment,misc]
    AdaptiveContextConfig = None  # type: ignore[assignment,misc]
    TokenCounter = None  # type: ignore[assignment,misc]
    PriorityMessage = None  # type: ignore[assignment,misc]
    _HAS_ADAPTIVE_CONTEXT = False

try:
    from .long_horizon import (
        LongHorizonRunner,
        LongHorizonConfig,
        LongHorizonResult,
        CheckpointStore,
        ProgressTracker,
    )
    _HAS_LONG_HORIZON = True
except ImportError:  # pragma: no cover
    LongHorizonRunner = None  # type: ignore[assignment,misc]
    LongHorizonConfig = None  # type: ignore[assignment,misc]
    LongHorizonResult = None  # type: ignore[assignment,misc]
    CheckpointStore = None  # type: ignore[assignment,misc]
    ProgressTracker = None  # type: ignore[assignment,misc]
    _HAS_LONG_HORIZON = False

try:
    from .token_streaming import (
        TokenStreamer,
        StreamingConfig,
        StreamChunk,
        BufferedStreamer,
    )
    _HAS_TOKEN_STREAMING = True
except ImportError:  # pragma: no cover
    TokenStreamer = None  # type: ignore[assignment,misc]
    StreamingConfig = None  # type: ignore[assignment,misc]
    StreamChunk = None  # type: ignore[assignment,misc]
    BufferedStreamer = None  # type: ignore[assignment,misc]
    _HAS_TOKEN_STREAMING = False

__all__ = ["MonolithicAgent", "MonolithicConfig"]

log = logging.getLogger("orchestra.arch_a")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class MonolithicConfig:
    """Tuning knobs for Architecture A."""
    model: str = "kimi-k2.5"
    max_iterations: int = 300
    max_tokens: int = 16384
    temperature: float = 0.6
    user_id: str = "default"
    workspace_dir: str = "/tmp/horizon_workspace"
    memory_db: str = ""                      # empty → default ~/.horizon/memory.db
    auto_extract_memory: bool = True         # extract facts at end of session
    memory_context_limit: int = 15           # memories injected into system prompt
    verbose: bool = False

    # -- adaptive context ---------------------------------------------------
    enable_adaptive_context: bool = True
    adaptive_context_config: "AdaptiveContextConfig | None" = None

    # -- long horizon -------------------------------------------------------
    enable_long_horizon: bool = False
    long_horizon_config: "LongHorizonConfig | None" = None

    # -- token streaming ----------------------------------------------------
    enable_token_streaming: bool = True
    streaming_config: "StreamingConfig | None" = None


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

SYSTEM_TEMPLATE = """\
You are Horizon Orchestra, an autonomous AI agent powered by Kimi K2.5.

You have access to tools for web search, code execution, file I/O,
browser automation, persistent memory, and data science (profiling,
statistical testing, visualization, ML pipelines, SQL analytics,
data validation).  Use them iteratively to complete the user's task.
You can call up to {max_iter} tools in sequence.

{memory_block}

Rules:
- Break complex tasks into steps.  Use tools at each step.
- Search memory first when the task might relate to prior context.
- Store durable facts about the user when you learn them.
- When finished, respond with your complete final answer.
- Cite sources when using web search results.
"""


# ---------------------------------------------------------------------------
# Monolithic agent
# ---------------------------------------------------------------------------

class MonolithicAgent:
    """Architecture A: single model loop with tools + memory.

    This is the recommended starting point.  It leverages Kimi K2.5's
    stability across 200-300 sequential tool calls to handle complex
    tasks without needing multi-model routing or parallel sub-agents.

    New capabilities (additive, all opt-in via config):

    * **AdaptiveContext** — priority-based message management that auto-
      compresses when the context window reaches 80% capacity.
    * **LongHorizonRunner** — checkpoint/resume support for multi-hour
      tasks; activate via ``config.enable_long_horizon=True`` or the
      ``run_long_horizon()`` method.
    * **TokenStreamer** — SSE/WebSocket-ready streaming via ``stream_sse()``.
    """

    def __init__(
        self,
        config: MonolithicConfig | None = None,
        router: ModelRouter | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.config = config or MonolithicConfig()
        self.router = router or ModelRouter()

        # -- tool registry --------------------------------------------------
        self.tools = tools or create_default_tools(self.router)

        # -- data science skills --------------------------------------------
        self.skills = SkillRegistry.default()
        self.skills.register_tools(self.tools)

        # -- memory ---------------------------------------------------------
        db_path = self.config.memory_db or None
        self.memory_store = MemoryStore(db_path=db_path)
        self.memory = MemoryManager(
            store=self.memory_store,
            user_id=self.config.user_id,
        )
        register_memory_tools(self.tools, self.memory)

        # -- session tracking -----------------------------------------------
        self.session = SessionContext(
            session_id=str(uuid.uuid4())[:8],
            user_id=self.config.user_id,
        )
        self._total_tool_calls = 0
        self._total_tasks = 0

        # -- adaptive context -----------------------------------------------
        self.adaptive_context: "AdaptiveContext | None" = None
        if self.config.enable_adaptive_context and _HAS_ADAPTIVE_CONTEXT:
            ac_config = self.config.adaptive_context_config or AdaptiveContextConfig()
            self.adaptive_context = AdaptiveContext(
                config=ac_config,
                router=self.router,
            )
            log.debug("[A] AdaptiveContext enabled (max_tokens=%d)", ac_config.max_tokens)

        # -- token streamer -------------------------------------------------
        self.token_streamer: "TokenStreamer | None" = None
        if self.config.enable_token_streaming and _HAS_TOKEN_STREAMING:
            st_config = self.config.streaming_config or StreamingConfig()
            self.token_streamer = TokenStreamer(config=st_config)
            log.debug("[A] TokenStreamer enabled")

        # -- long horizon (lazy — instantiated on first use) ----------------
        self._long_horizon: "LongHorizonRunner | None" = None

    # -- internal helpers ---------------------------------------------------

    def _get_long_horizon_runner(self) -> "LongHorizonRunner":
        """Return (or lazily create) the LongHorizonRunner."""
        if not _HAS_LONG_HORIZON:
            raise RuntimeError(
                "long_horizon module is not available; "
                "ensure orchestra/long_horizon.py is present."
            )
        if self._long_horizon is None:
            lh_config = (
                self.config.long_horizon_config or LongHorizonConfig(
                    model=self.config.model,
                )
            )
            checkpoint_store = CheckpointStore()
            self._long_horizon = LongHorizonRunner(
                router=self.router,
                tools=list(self.tools),
                config=lh_config,
                checkpoint_store=checkpoint_store,
            )
            log.debug(
                "[A] LongHorizonRunner created (max_hours=%.1f)",
                lh_config.max_runtime_hours,
            )
        return self._long_horizon

    # -- public API ---------------------------------------------------------

    async def run(self, task: str, context: str = "") -> str:
        """Execute a task end-to-end, returning the final answer string."""
        result_parts: list[str] = []
        async for event in self.stream(task, context):
            if isinstance(event, FinalAnswerEvent):
                result_parts.append(event.content)
            elif isinstance(event, ErrorEvent) and not event.recoverable:
                result_parts.append(f"[ERROR] {event.message}")
        return "\n".join(result_parts)

    async def stream(self, task: str, context: str = "") -> AsyncGenerator[AgentEvent, None]:
        """Execute a task, yielding events as they occur.

        This is the core Architecture A loop:
        1. Build memory-enriched system prompt
        2. Optionally load system + user message into AdaptiveContext
        3. Run AgentLoop with all tools (including memory tools)
        4. Track session turns
        5. Auto-extract durable facts when done
        """
        self._total_tasks += 1
        self.session.add_turn("user", task)
        t0 = time.monotonic()

        # -- build system prompt with memory context -------------------------
        memory_block = await self.memory.get_context_block(
            query=task,
            limit=self.config.memory_context_limit,
        )
        system_prompt = SYSTEM_TEMPLATE.format(
            max_iter=self.config.max_iterations,
            memory_block=memory_block or "(No prior memories for this user.)",
        )

        # -- wire adaptive context ------------------------------------------
        if self.adaptive_context is not None:
            # Reset per-task context (system prompt is non-compressible)
            self.adaptive_context.add_message("system", system_prompt, priority=1)
            self.adaptive_context.add_message("user", task)
            # Run a compression pass so get_messages() is ready
            await self.adaptive_context.compress()
            log.debug("[A] AdaptiveContext messages ready")

        # -- run agent loop --------------------------------------------------
        agent_config = AgentConfig(
            model=self.config.model,
            max_iterations=self.config.max_iterations,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system_prompt=system_prompt,
        )
        agent = AgentLoop(
            router=self.router,
            tools=self.tools,
            config=agent_config,
        )

        final_content = ""
        tool_count = 0

        async for event in agent.run(task, context=context):
            if isinstance(event, ToolCallEvent):
                tool_count += 1
                if self.config.verbose:
                    log.info("[A] iter=%d tool=%s", event.iteration, event.tool_name)
            elif isinstance(event, FinalAnswerEvent):
                final_content = event.content
            yield event

        elapsed = time.monotonic() - t0
        self._total_tool_calls += tool_count

        # -- post-execution --------------------------------------------------
        if final_content:
            self.session.add_turn("assistant", final_content[:2000])

        # Save session
        await self.memory_store.save_session(self.session)

        # Auto-extract memories
        if self.config.auto_extract_memory and final_content:
            conversation_text = self.session.to_context_string(last_n=6)
            try:
                extracted = await self.memory.auto_extract(
                    conversation=conversation_text,
                    model=self.config.model,
                    router=self.router,
                )
                if extracted and self.config.verbose:
                    log.info("[A] Auto-extracted %d memories", len(extracted))
            except Exception as exc:
                log.debug("Memory extraction failed: %s", exc)

        log.info(
            "[A] Task complete: %d tools, %.1fs, model=%s",
            tool_count, elapsed, self.config.model,
        )

    async def run_long_horizon(
        self,
        task: str,
        user_id: str = "",
        resume_from: str = "",
    ) -> "LongHorizonResult":
        """Execute a long-horizon task with automatic checkpoint/resume.

        Uses LongHorizonRunner to break the task into steps, execute them
        sequentially, checkpoint periodically, and pause gracefully near
        runtime/Lambda limits.

        Args:
            task: The high-level task description.
            user_id: User identifier (defaults to config.user_id).
            resume_from: Task ID of a prior paused run to resume from.

        Returns:
            LongHorizonResult with status, result text, and progress info.

        Raises:
            RuntimeError: If the long_horizon module is unavailable.
        """
        runner = self._get_long_horizon_runner()
        uid = user_id or self.config.user_id
        log.info("[A] Starting long-horizon task user_id=%s resume=%s", uid, resume_from or "none")
        result = await runner.run(task=task, user_id=uid, resume_from=resume_from)
        log.info(
            "[A] Long-horizon complete: status=%s steps=%d/%d",
            result.status, result.steps_completed, result.total_steps,
        )
        return result

    async def stream_sse(
        self,
        task: str,
        context: str = "",
    ) -> AsyncGenerator["StreamChunk", None]:
        """Execute a task and yield SSE-ready StreamChunk objects.

        Wraps ``stream()`` with BufferedStreamer to produce typed chunks
        (token, tool_call_start, tool_call_complete, finish, heartbeat)
        suitable for Server-Sent Events or WebSocket delivery.

        Args:
            task: The user task to execute.
            context: Optional additional context string.

        Yields:
            StreamChunk objects. Call ``.to_sse()`` on each for raw SSE wire format.

        Raises:
            RuntimeError: If the token_streaming module is unavailable.
        """
        if not _HAS_TOKEN_STREAMING:
            raise RuntimeError(
                "token_streaming module is not available; "
                "ensure orchestra/token_streaming.py is present."
            )
        st_config = self.config.streaming_config or StreamingConfig()
        buffered = BufferedStreamer(config=st_config)
        log.debug("[A] stream_sse: starting buffered SSE stream")
        async for chunk in buffered.stream_agent_response(self, task, context=context):
            yield chunk

    # -- session helpers ----------------------------------------------------

    async def recall(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search memories related to a query."""
        results = await self.memory_store.search(
            self.config.user_id, query, limit=limit,
        )
        return [
            {
                "content": r.content,
                "category": r.category,
                "relevance": round(r.relevance_score, 3),
            }
            for r in results
        ]

    async def remember(self, fact: str, category: str = "fact") -> str:
        """Manually store a memory."""
        entry = await self.memory_store.store(
            self.config.user_id, fact, category=category, source="explicit",
        )
        return entry.id

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "architecture": "A",
            "model": self.config.model,
            "total_tasks": self._total_tasks,
            "total_tool_calls": self._total_tool_calls,
            "session_id": self.session.session_id,
            "session_turns": len(self.session.turns),
            "tools_available": self.tools.names,
            "adaptive_context_enabled": self.adaptive_context is not None,
            "token_streaming_enabled": self.token_streamer is not None,
            "long_horizon_enabled": self.config.enable_long_horizon,
        }


# ---------------------------------------------------------------------------
# Quick-run helper
# ---------------------------------------------------------------------------

async def run_monolithic(
    task: str,
    model: str = "kimi-k2.5",
    user_id: str = "default",
    verbose: bool = False,
) -> str:
    """One-liner to run a task through Architecture A."""
    config = MonolithicConfig(model=model, user_id=user_id, verbose=verbose)
    agent = MonolithicAgent(config=config)
    return await agent.run(task)
