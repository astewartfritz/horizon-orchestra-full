"""Architecture C — Native Agent Swarm.

The model itself decides when to spawn sub-agents, what they specialise
in, and when to merge results.  Supports both Kimi K2.5 and Gemma 4 as
coordinator/agent backbones with memory-aware context injection at every
level.

Gemma 4 additions:
- Coordinator and agents can use any Gemma 4 variant (31B, 26B MoE,
  E4B, E2B) alongside Kimi K2.5.
- Cost-optimised routing: use Gemma 4 26B MoE for fast parallel agents,
  Gemma 4 31B for complex reasoning tasks.
- Thinking mode enabled for coordinator when using a supported model.

The coordinator has three swarm-specific tools on top of the standard
tool surface:

* ``spawn_agent``  — create a sub-agent with a specific task and model
* ``collect_results`` — gather outputs from spawned agents
* ``delegate`` — synchronous one-shot delegation to a specialist model

Usage::

    from orchestra.arch_c import SwarmAgent, SwarmConfig
    config = SwarmConfig(coordinator_model="gemma-4-31b", default_agent_model="gemma-4-26b-moe")
    agent = SwarmAgent(config=config, user_id="ashton")
    result = await agent.run("Research and build a comparison dashboard")
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
from .security import SecurityMiddleware, standard_policy, strict_policy
from .domain_router import DomainRouter
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
    enable_security: bool = True
    security_policy: str = "standard"
    enable_domain_routing: bool = False
    enable_skills: bool = True
    enable_citations: bool = False


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SWARM_SYSTEM = """\
You are Horizon Orchestra operating in Agent Swarm mode (Architecture C),
powered by {model_display}.

You are an autonomous coordinator that can:
1. Analyse complex tasks and decompose them into parallel subtasks.
2. Spawn specialised sub-agents to handle each subtask.
3. Delegate one-off questions to specialist models.
4. Collect and merge results from sub-agents.
5. Search and store persistent user memory.
{thinking_block}
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
- Use gemma-4-26b-moe for fast parallel agents that still reason well.
- Use gemma-4-31b or kimi-k2.5 for coding, reasoning, and complex tasks.
- Use gemma-4-e4b for lightweight tasks (summaries, classification, extraction).
- Use claude-opus-4.6 for complex reasoning, coding, and safety-critical tasks (1M context, adaptive thinking).
- Use claude-sonnet-4.6 for balanced agents — near-Opus quality at 5x lower cost.
- Use claude-haiku-4.5 for high-throughput lightweight tasks ($1/$5 per 1M tokens).
- Search memory first when the task might relate to prior context.
- When all sub-agents complete, synthesise a final answer yourself.
"""

# Model display name mapping
MODEL_DISPLAY = {
    "kimi-k2.5": "Kimi K2.5",
    "gemma-4-31b": "Gemma 4 31B Dense",
    "gemma-4-26b-moe": "Gemma 4 26B MoE",
    "gemma-4-e4b": "Gemma 4 E4B",
    "gemma-4-e2b": "Gemma 4 E2B",
    "claude-opus-4.6": "Claude Opus 4.6",
    "claude-opus-4.6-native": "Claude Opus 4.6",
    "claude-opus-4.6-openrouter": "Claude Opus 4.6",
    "claude-sonnet-4.6": "Claude Sonnet 4.6",
    "claude-sonnet-4.6-openrouter": "Claude Sonnet 4.6",
    "claude-haiku-4.5": "Claude Haiku 4.5",
    "claude-haiku-4.5-openrouter": "Claude Haiku 4.5",
}


# ---------------------------------------------------------------------------
# Swarm agent
# ---------------------------------------------------------------------------

class SwarmAgent:
    """Architecture C: native swarm with memory-aware context injection."""

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

        # -- security -------------------------------------------------------
        self.security: SecurityMiddleware | None = None
        if self.config.enable_security:
            from .security import (
                SecurityMiddleware, standard_policy, strict_policy,
                permissive_policy, safety_critical_policy,
            )
            policy_map = {
                "strict": strict_policy,
                "standard": standard_policy,
                "permissive": permissive_policy,
                "safety_critical": safety_critical_policy,
            }
            policy_factory = policy_map.get(self.config.security_policy, standard_policy)
            self.security = SecurityMiddleware(policy=policy_factory())

        # -- domain router --------------------------------------------------
        self.domain_router: DomainRouter | None = None
        if self.config.enable_domain_routing:
            self.domain_router = DomainRouter(router=self.router)

        # -- skills ---------------------------------------------------------
        self.skill_activator: Any = None
        try:
            from .skills import SkillRegistry, SkillActivator
            registry = SkillRegistry.default()
            self.skill_activator = SkillActivator(registry, auto_activate=self.config.enable_skills)
        except Exception:
            pass

        # -- citation tracker -----------------------------------------------
        self.citation_tracker: Any = None
        if self.config.enable_citations:
            try:
                from .citation import CitationTracker
                self.citation_tracker = CitationTracker()
            except Exception:
                pass

        # -- session --------------------------------------------------------
        self.session = SessionContext(
            session_id=str(uuid.uuid4())[:8],
            user_id=self.config.user_id,
        )

        # -- swarm state ----------------------------------------------------
        self._active_agents: dict[str, asyncio.Task] = {}
        self._agent_results: dict[str, dict[str, Any]] = {}
        self._stats = {"tasks": 0, "agents_spawned": 0, "tool_calls": 0}

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
        """Run the swarm coordinator, yielding events."""
        self._stats["tasks"] += 1
        self.session.add_turn("user", task)
        t0 = time.monotonic()

        # -- build tools (standard + swarm + memory) -------------------------
        tools = create_default_tools(self.router)
        register_memory_tools(tools, self.memory)
        self._register_swarm_tools(tools)

        # -- activate skills for this task ----------------------------------
        skill_prompt_addition = ""
        if self.skill_activator:
            try:
                matches, skill_prompt_addition = self.skill_activator.activate_for_task(task)
                if matches and self.config.verbose:
                    log.info("[C] Skills activated: %s", [m.skill.name for m in matches])
            except Exception:
                pass

        # -- build system prompt with memory ---------------------------------
        memory_block = await self.memory.get_context_block(
            query=task, limit=self.config.memory_context_limit,
        )
        model_list = self._model_list_string()

        # Thinking block for Gemma 4 models
        thinking_block = ""
        try:
            coord_cfg = self.router.get_config(self.config.coordinator_model)
            if coord_cfg.supports_thinking:
                thinking_block = (
                    "\nYou have thinking/reasoning mode enabled.  For complex "
                    "decomposition, reason step-by-step internally before "
                    "spawning agents.  Plan your swarm strategy carefully.\n"
                )
        except KeyError:
            pass

        model_display = MODEL_DISPLAY.get(
            self.config.coordinator_model, self.config.coordinator_model
        )
        system_prompt = SWARM_SYSTEM.format(
            model_display=model_display,
            thinking_block=thinking_block,
            model_list=model_list,
            memory_block=memory_block or "(No prior memories.)",
        ) + skill_prompt_addition

        # -- run coordinator loop --------------------------------------------
        agent_config = AgentConfig(
            model=self.config.coordinator_model,
            max_iterations=self.config.max_coordinator_iterations,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system_prompt=system_prompt,
            security=self.security,
            citation_tracker=self.citation_tracker,
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
        """Run a sub-agent with its own AgentLoop."""
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

        config = AgentConfig(
            model=model,
            max_iterations=self.config.max_agent_iterations,
            max_tokens=8192,
            system_prompt=(
                f"You are sub-agent '{agent_id}' in Horizon Orchestra swarm.\n"
                f"Complete your task and save output to: {output_path}\n\n"
                f"{memory_block}"
            ),
            security=self.security,  # propagate security to sub-agents
            citation_tracker=self.citation_tracker if self.config.enable_citations else None,
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
        base = {
            "architecture": "C",
            "coordinator_model": self.config.coordinator_model,
            **self._stats,
            "session_id": self.session.session_id,
            "security_enabled": self.security is not None,
        }
        if self.security:
            base["security_stats"] = self.security.stats
        return base


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
