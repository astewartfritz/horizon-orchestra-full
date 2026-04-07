"""Architecture C — Native Kimi K2.5 Agent Swarm.

The model itself decides when to spawn sub-agents, what they specialise
in, and when to merge results.  This leverages K2.5's built-in swarm
coordination (up to 100 parallel agents) with memory-aware context
injection at every level.

The coordinator has three swarm-specific tools on top of the standard
tool surface:

* ``spawn_agent``  — create a sub-agent with a specific task and model
* ``collect_results`` — gather outputs from spawned agents
* ``delegate`` — synchronous one-shot delegation to a specialist model

Memory is shared across all agents via the same MemoryStore, so
sub-agents can search for and store user context.

Usage::

    from orchestra.arch_c import SwarmAgent
    agent = SwarmAgent(user_id="ashton")
    result = await agent.run("Research Kimi K2.5 benchmarks and build a comparison dashboard")
    print(result)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

from .router import ModelRouter
from .agent_loop import (
    AgentLoop,
    AgentConfig,
    AgentEvent,
    FinalAnswerEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolSpec,
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

__all__ = ["SwarmAgent", "SwarmConfig"]

log = logging.getLogger("orchestra.arch_c")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SwarmConfig:
    """Tuning knobs for Architecture C."""
    coordinator_model: str = "kimi-k2.5"
    default_agent_model: str = "kimi-k2.5"
    max_coordinator_iterations: int = 300
    max_agent_iterations: int = 100
    max_parallel_agents: int = 100
    max_tokens: int = 16384
    temperature: float = 0.6
    user_id: str = "default"
    workspace_dir: str = "/tmp/horizon_workspace"
    memory_db: str = ""
    auto_extract_memory: bool = True
    memory_context_limit: int = 15
    verbose: bool = False

    # -- adaptive context ---------------------------------------------------
    enable_adaptive_context: bool = True
    adaptive_context_config: "AdaptiveContextConfig | None" = None

    # -- long horizon (coordinator only) ------------------------------------
    enable_long_horizon: bool = False
    long_horizon_config: "LongHorizonConfig | None" = None

    # -- token streaming ----------------------------------------------------
    enable_token_streaming: bool = True
    streaming_config: "StreamingConfig | None" = None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SWARM_SYSTEM = """\
You are Horizon Orchestra operating in Agent Swarm mode (Architecture C),
powered by Kimi K2.5.

You are an autonomous coordinator that can:
1. Analyse complex tasks and decompose them into parallel subtasks.
2. Spawn specialised sub-agents to handle each subtask.
3. Delegate one-off questions to specialist models.
4. Collect and merge results from sub-agents.
5. Search and store persistent user memory.

Swarm tools:
- spawn_agent: Create a sub-agent (runs in parallel).
- collect_results: Gather outputs from spawned agents.
- delegate: Synchronous call to a specialist model.

Standard tools: web_search, fetch_url, execute_code, file_read, file_write,
browser_action, memory_search, memory_store.

Available specialist models for delegation:
{model_list}

{memory_block}

Strategy:
- Maximise parallelism — spawn agents for independent subtasks.
- Use the cheapest model that fits each sub-agent's needs.
- Delegate to sonar-pro for web research, grok-3 for fast summaries.
- Keep kimi-k2.5 for coding, reasoning, and complex tasks.
- Search memory first when the task might relate to prior context.
- When all sub-agents complete, synthesise a final answer yourself.
"""


# ---------------------------------------------------------------------------
# Swarm agent
# ---------------------------------------------------------------------------

class SwarmAgent:
    """Architecture C: native swarm with memory-aware context injection.

    New capabilities (additive, all opt-in via config):

    * **AdaptiveContext** — priority-based message management for both the
      coordinator and each sub-agent (each gets its own context window).
    * **LongHorizonRunner** — wired into the coordinator for multi-hour
      tasks; activate via ``config.enable_long_horizon=True`` or
      ``run_long_horizon()``.
    * **TokenStreamer** — SSE/WebSocket-ready coordinator output via
      ``stream_sse()``.
    """

    def __init__(
        self,
        config: SwarmConfig | None = None,
        router: ModelRouter | None = None,
    ) -> None:
        self.config = config or SwarmConfig()
        self.router = router or ModelRouter()
        self.workspace = Path(self.config.workspace_dir)
        self.workspace.mkdir(parents=True, exist_ok=True)

        # -- memory ---------------------------------------------------------
        db_path = self.config.memory_db or None
        self.memory_store = MemoryStore(db_path=db_path)
        self.memory = MemoryManager(
            store=self.memory_store,
            user_id=self.config.user_id,
        )

        # -- session --------------------------------------------------------
        self.session = SessionContext(
            session_id=str(uuid.uuid4())[:8],
            user_id=self.config.user_id,
        )

        # -- swarm state ----------------------------------------------------
        self._active_agents: dict[str, asyncio.Task] = {}
        self._agent_results: dict[str, dict[str, Any]] = {}
        self._stats = {"tasks": 0, "agents_spawned": 0, "tool_calls": 0}

        # -- adaptive context (coordinator) ---------------------------------
        self.adaptive_context: "AdaptiveContext | None" = None
        if self.config.enable_adaptive_context and _HAS_ADAPTIVE_CONTEXT:
            ac_config = self.config.adaptive_context_config or AdaptiveContextConfig()
            self.adaptive_context = AdaptiveContext(
                config=ac_config,
                router=self.router,
            )
            log.debug(
                "[C] AdaptiveContext enabled for coordinator (max_tokens=%d)",
                ac_config.max_tokens,
            )

        # -- token streamer -------------------------------------------------
        self.token_streamer: "TokenStreamer | None" = None
        if self.config.enable_token_streaming and _HAS_TOKEN_STREAMING:
            st_config = self.config.streaming_config or StreamingConfig()
            self.token_streamer = TokenStreamer(config=st_config)
            log.debug("[C] TokenStreamer enabled")

        # -- long horizon runner (lazy — coordinator only) ------------------
        self._long_horizon: "LongHorizonRunner | None" = None

    # -- internal helpers ---------------------------------------------------

    def _get_long_horizon_runner(self) -> "LongHorizonRunner":
        """Return (or lazily create) the coordinator's LongHorizonRunner."""
        if not _HAS_LONG_HORIZON:
            raise RuntimeError(
                "long_horizon module is not available; "
                "ensure orchestra/long_horizon.py is present."
            )
        if self._long_horizon is None:
            lh_config = (
                self.config.long_horizon_config or LongHorizonConfig(
                    model=self.config.coordinator_model,
                )
            )
            checkpoint_store = CheckpointStore()
            # Build a minimal tool list for the runner (coordinator tools)
            coord_tools = create_default_tools(self.router)
            register_memory_tools(coord_tools, self.memory)
            self._long_horizon = LongHorizonRunner(
                router=self.router,
                tools=list(coord_tools),
                config=lh_config,
                checkpoint_store=checkpoint_store,
            )
            log.debug(
                "[C] LongHorizonRunner created for coordinator (max_hours=%.1f)",
                lh_config.max_runtime_hours,
            )
        return self._long_horizon

    def _make_sub_agent_adaptive_context(self) -> "AdaptiveContext | None":
        """Create a fresh AdaptiveContext for a sub-agent, if enabled."""
        if not (self.config.enable_adaptive_context and _HAS_ADAPTIVE_CONTEXT):
            return None
        ac_config = self.config.adaptive_context_config or AdaptiveContextConfig()
        return AdaptiveContext(config=ac_config, router=self.router)

    # -- public API ---------------------------------------------------------

    async def run(self, task: str, context: str = "") -> str:
        """Run a task through the swarm coordinator."""
        result_parts: list[str] = []
        async for event in self.stream(task, context):
            if isinstance(event, FinalAnswerEvent):
                result_parts.append(event.content)
            elif isinstance(event, ErrorEvent) and not event.recoverable:
                result_parts.append(f"[ERROR] {event.message}")
        return "\n".join(result_parts)

    async def stream(self, task: str, context: str = "") -> AsyncGenerator[AgentEvent, None]:
        """Run the swarm coordinator, yielding events.

        1. Build tools (standard + skills + swarm + memory)
        2. Build memory-enriched system prompt
        3. Optionally load into coordinator's AdaptiveContext
        4. Run coordinator AgentLoop
        5. Post-execution cleanup and memory extraction
        """
        self._stats["tasks"] += 1
        self.session.add_turn("user", task)
        t0 = time.monotonic()

        # -- build tools (standard + skills + swarm + memory) ----------------
        tools = create_default_tools(self.router)
        skills = SkillRegistry.default()
        skills.register_tools(tools)
        register_memory_tools(tools, self.memory)
        self._register_swarm_tools(tools)

        # -- build system prompt with memory ---------------------------------
        memory_block = await self.memory.get_context_block(
            query=task, limit=self.config.memory_context_limit,
        )
        model_list = self._model_list_string()
        system_prompt = SWARM_SYSTEM.format(
            model_list=model_list,
            memory_block=memory_block or "(No prior memories.)",
        )

        # -- wire adaptive context into coordinator -------------------------
        if self.adaptive_context is not None:
            self.adaptive_context.add_message("system", system_prompt, priority=1)
            self.adaptive_context.add_message("user", task)
            await self.adaptive_context.compress()
            log.debug("[C] Coordinator AdaptiveContext messages ready")

        # -- run coordinator loop --------------------------------------------
        agent_config = AgentConfig(
            model=self.config.coordinator_model,
            max_iterations=self.config.max_coordinator_iterations,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system_prompt=system_prompt,
        )
        coordinator = AgentLoop(
            router=self.router, tools=tools, config=agent_config,
        )

        final_content = ""
        async for event in coordinator.run(task, context=context):
            if isinstance(event, ToolCallEvent):
                self._stats["tool_calls"] += 1
                if self.config.verbose:
                    log.info("[C] iter=%d tool=%s", event.iteration, event.tool_name)
            elif isinstance(event, FinalAnswerEvent):
                final_content = event.content
            yield event

        elapsed = time.monotonic() - t0

        # -- post-execution --------------------------------------------------
        # Cancel any lingering agents
        for aid, atask in self._active_agents.items():
            if not atask.done():
                atask.cancel()
        self._active_agents.clear()

        if final_content:
            self.session.add_turn("assistant", final_content[:2000])
        await self.memory_store.save_session(self.session)

        if self.config.auto_extract_memory and final_content:
            try:
                await self.memory.auto_extract(
                    conversation=self.session.to_context_string(last_n=6),
                    model=self.config.coordinator_model,
                    router=self.router,
                )
            except Exception:
                pass

        log.info(
            "[C] Swarm complete: %d agents spawned, %d tool calls, %.1fs",
            self._stats["agents_spawned"], self._stats["tool_calls"], elapsed,
        )

    async def run_long_horizon(
        self,
        task: str,
        user_id: str = "",
        resume_from: str = "",
    ) -> "LongHorizonResult":
        """Execute a long-horizon task through the coordinator with checkpoint/resume.

        The coordinator's LongHorizonRunner handles multi-hour tasks by
        breaking them into steps, checkpointing periodically, and pausing
        gracefully near Lambda/runtime limits.  Sub-agents are short-lived
        and do not need their own long-horizon runner.

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
        log.info(
            "[C] Starting long-horizon coordinator task user_id=%s resume=%s",
            uid, resume_from or "none",
        )
        result = await runner.run(task=task, user_id=uid, resume_from=resume_from)
        log.info(
            "[C] Long-horizon complete: status=%s steps=%d/%d",
            result.status, result.steps_completed, result.total_steps,
        )
        return result

    async def stream_sse(
        self,
        task: str,
        context: str = "",
    ) -> AsyncGenerator["StreamChunk", None]:
        """Execute a swarm task and yield SSE-ready StreamChunk objects.

        Wraps the coordinator's ``stream()`` with BufferedStreamer to produce
        typed chunks (token, tool_call_start, tool_call_complete, finish,
        heartbeat) suitable for Server-Sent Events or WebSocket delivery.

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
        log.debug("[C] stream_sse: starting buffered SSE stream for coordinator")
        async for chunk in buffered.stream_agent_response(self, task, context=context):
            yield chunk

    # -- swarm tool implementations -----------------------------------------

    def _register_swarm_tools(self, registry: ToolRegistry) -> None:
        """Add spawn_agent, collect_results, delegate to the registry."""

        async def _spawn_agent(
            agent_id: str,
            task: str,
            model: str = "",
            tools: list[str] | None = None,
            priority: str = "medium",
        ) -> str:
            model = model or self.config.default_agent_model
            if len(self._active_agents) >= self.config.max_parallel_agents:
                return json.dumps({"error": "Max parallel agents reached"})

            atask = asyncio.create_task(
                self._run_sub_agent(agent_id, task, model, tools or [])
            )
            self._active_agents[agent_id] = atask
            self._stats["agents_spawned"] += 1

            return json.dumps({
                "status": "spawned",
                "agent_id": agent_id,
                "model": model,
                "tools": tools or [],
            })

        async def _collect_results(
            agent_ids: list[str],
            timeout: int = 300,
        ) -> str:
            results: dict[str, Any] = {}

            # Gather the requested agents
            tasks_to_wait = {
                aid: self._active_agents[aid]
                for aid in agent_ids
                if aid in self._active_agents
            }

            if tasks_to_wait:
                done, pending = await asyncio.wait(
                    tasks_to_wait.values(),
                    timeout=timeout,
                )
                # Cancel timed-out agents
                for p in pending:
                    p.cancel()

            for aid in agent_ids:
                if aid in self._agent_results:
                    results[aid] = self._agent_results[aid]
                elif aid in self._active_agents and self._active_agents[aid].done():
                    try:
                        results[aid] = self._active_agents[aid].result()
                    except Exception as exc:
                        results[aid] = {"status": "error", "error": str(exc)}
                else:
                    results[aid] = {"status": "pending_or_timed_out"}

            return json.dumps(results)

        async def _delegate(
            model: str,
            task: str,
            context: str = "",
        ) -> str:
            """Synchronous one-shot delegation to a specialist model."""
            try:
                client, model_id = self.router.get_client(model)
            except KeyError:
                return json.dumps({"error": f"Unknown model: {model}"})

            messages = [
                {"role": "system", "content": "Complete this task precisely and concisely."},
            ]
            if context:
                messages.append({"role": "user", "content": f"Context: {context}\n\nTask: {task}"})
            else:
                messages.append({"role": "user", "content": task})

            try:
                resp = await client.chat.completions.create(
                    model=model_id, messages=messages, max_tokens=8192,
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                return json.dumps({"error": str(exc)})

        # -- Register -------------------------------------------------------

        registry.register(
            name="spawn_agent",
            description=(
                "Spawn a sub-agent to handle a subtask in parallel. "
                "The agent runs independently and results are collected later."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Unique ID for this agent (e.g. 'research_1')",
                    },
                    "task": {
                        "type": "string",
                        "description": "What this agent should accomplish",
                    },
                    "model": {
                        "type": "string",
                        "description": "Which model to use (default: kimi-k2.5)",
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tool names this agent needs",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": ["agent_id", "task"],
            },
            handler=_spawn_agent,
        )

        registry.register(
            name="collect_results",
            description="Wait for and collect results from spawned sub-agents.",
            parameters={
                "type": "object",
                "properties": {
                    "agent_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs of agents to collect from",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max seconds to wait (default: 300)",
                    },
                },
                "required": ["agent_ids"],
            },
            handler=_collect_results,
        )

        registry.register(
            name="delegate",
            description=(
                "Synchronous delegation: send a task to a specialist model "
                "and wait for the result. Use for one-off queries."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Model name (e.g. 'sonar-pro', 'grok-3')",
                    },
                    "task": {
                        "type": "string",
                        "description": "The task to complete",
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context",
                    },
                },
                "required": ["model", "task"],
            },
            handler=_delegate,
        )

    # -- sub-agent execution ------------------------------------------------

    async def _run_sub_agent(
        self,
        agent_id: str,
        task: str,
        model: str,
        tool_names: list[str],
    ) -> dict[str, Any]:
        """Run a sub-agent with its own AgentLoop.

        Each sub-agent gets its own AdaptiveContext instance (if enabled)
        so its context window is managed independently from the coordinator.
        Sub-agents are short-lived and do not use LongHorizonRunner.
        """
        t0 = time.monotonic()

        # Build scoped tools for this agent
        base_tools = create_default_tools(self.router)
        register_memory_tools(base_tools, self.memory)

        if tool_names:
            tools = base_tools.subset(tool_names)
        else:
            tools = base_tools

        # Inject memory context for the sub-agent
        memory_block = await self.memory.get_context_block(query=task, limit=8)

        output_path = self.workspace / "agents" / agent_id / "output.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        sub_system_prompt = (
            f"You are sub-agent '{agent_id}' in Horizon Orchestra swarm.\n"
            f"Complete your task and save output to: {output_path}\n\n"
            f"{memory_block}"
        )

        # Each sub-agent gets its own AdaptiveContext if enabled
        sub_ac = self._make_sub_agent_adaptive_context()
        if sub_ac is not None:
            sub_ac.add_message("system", sub_system_prompt, priority=1)
            sub_ac.add_message("user", task)
            try:
                await sub_ac.compress()
            except Exception as exc:
                log.debug("[C] sub-agent %s adaptive_context compress failed: %s", agent_id, exc)

        config = AgentConfig(
            model=model,
            max_iterations=self.config.max_agent_iterations,
            max_tokens=8192,
            system_prompt=sub_system_prompt,
        )

        agent = AgentLoop(router=self.router, tools=tools, config=config)

        output = ""
        try:
            async for event in agent.run(task):
                if isinstance(event, FinalAnswerEvent):
                    output = event.content
                elif isinstance(event, ErrorEvent) and not event.recoverable:
                    result = {
                        "agent_id": agent_id, "status": "error",
                        "error": event.message, "model": model,
                        "duration": time.monotonic() - t0,
                    }
                    self._agent_results[agent_id] = result
                    return result
        except Exception as exc:
            result = {
                "agent_id": agent_id, "status": "error",
                "error": str(exc), "model": model,
                "duration": time.monotonic() - t0,
            }
            self._agent_results[agent_id] = result
            return result

        # Persist output
        try:
            output_path.write_text(output, encoding="utf-8")
        except OSError:
            pass

        result = {
            "agent_id": agent_id,
            "status": "complete",
            "output": output[:5000],  # truncate for coordinator context
            "output_file": str(output_path),
            "model": model,
            "duration": round(time.monotonic() - t0, 1),
        }
        self._agent_results[agent_id] = result
        log.info("[C] Sub-agent %s complete (%.1fs, %s)", agent_id, result["duration"], model)
        return result

    # -- helpers ------------------------------------------------------------

    def _model_list_string(self) -> str:
        lines = []
        for m in self.router.list_models():
            if m["available"]:
                lines.append(
                    f"- {m['name']}: {', '.join(m['strengths'])} "
                    f"(${m['cost_input']}/{m['cost_output']})"
                )
        return "\n".join(lines) or "- kimi-k2.5: reasoning, coding, agentic ($0.60/$2.50)"

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "architecture": "C",
            "coordinator_model": self.config.coordinator_model,
            **self._stats,
            "session_id": self.session.session_id,
            "adaptive_context_enabled": self.adaptive_context is not None,
            "token_streaming_enabled": self.token_streamer is not None,
            "long_horizon_enabled": self.config.enable_long_horizon,
        }


# ---------------------------------------------------------------------------
# Quick-run helper
# ---------------------------------------------------------------------------

async def run_swarm(
    task: str,
    model: str = "kimi-k2.5",
    user_id: str = "default",
    verbose: bool = False,
) -> str:
    """One-liner to run a task through Architecture C."""
    config = SwarmConfig(
        coordinator_model=model, user_id=user_id, verbose=verbose,
    )
    agent = SwarmAgent(config=config)
    return await agent.run(task)
