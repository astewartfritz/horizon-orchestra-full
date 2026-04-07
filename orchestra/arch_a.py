"""Architecture A — Monolithic Orchestrator.

Single backbone agent loop with full tool surface and persistent memory.
The simplest architecture: one model, one loop, up to 300 sequential tool
calls.  Memory is injected into the system prompt and tools are available
for the agent to search/store memories mid-execution.

Supports both Kimi K2.5 and Gemma 4 as the backbone model.  When Gemma 4
is selected, thinking mode and multimodal capabilities are automatically
enabled based on the model variant.

Usage::

    from orchestra.arch_a import MonolithicAgent
    agent = MonolithicAgent(user_id="ashton")
    result = await agent.run("Build a REST API for task management")

    # With Gemma 4:
    from orchestra.arch_a import MonolithicConfig
    config = MonolithicConfig(model="gemma-4-31b", user_id="ashton")
    agent = MonolithicAgent(config=config)
    result = await agent.run("Analyse this codebase and refactor")
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
try:
    from .skills import SkillRegistry, SkillActivator
except ImportError:
    pass
try:
    from .citation import CitationTracker, CitationMiddleware
except ImportError:
    pass
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
from .perplexity import PerplexitySearch
from .security import SecurityMiddleware, standard_policy, strict_policy, safety_critical_policy
from .domain_router import DomainRouter, TaskClassification, DomainRoute

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
    enable_security: bool = True             # enable security middleware
    security_policy: str = "standard"        # "strict", "standard", "permissive", "safety_critical"
    enable_domain_routing: bool = False      # auto-route tasks to optimal model
    enable_skills: bool = True               # auto-activate skills based on task
    enable_citations: bool = False           # enforce citation grounding (adds latency)
    skill_dirs: list[str] = field(default_factory=list)  # extra skill directories


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

SYSTEM_TEMPLATE = """\
You are Horizon Orchestra, an autonomous AI agent powered by {model_display}.

You have access to tools for web search, code execution, file I/O,
browser automation, and persistent memory.  Use them iteratively to
complete the user's task.  You can call up to {max_iter} tools in
sequence.
{thinking_block}
{memory_block}

Rules:
- Break complex tasks into steps.  Use tools at each step.
- Search memory first when the task might relate to prior context.
- Store durable facts about the user when you learn them.
- When finished, respond with your complete final answer.
- Cite sources when using web search results.
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


def _model_display_name(model: str) -> str:
    """Resolve a human-readable model name."""
    return MODEL_DISPLAY.get(model, model)


def _thinking_block(model: str, router: ModelRouter) -> str:
    """Build thinking-mode instructions if the model supports it."""
    try:
        cfg = router.get_config(model)
    except KeyError:
        return ""
    if not cfg.supports_thinking:
        return ""
    if cfg.supports_thinking and model.startswith("claude-"):
        return (
            "\nYou have adaptive thinking enabled.  For complex tasks, "
            "you will automatically engage extended reasoning.  Use your "
            "interleaved thinking to reason between tool calls — analyse "
            "results before deciding your next action.  For safety-critical "
            "tasks, think at maximum effort before acting.\n"
        )
    return (
        "\nYou have thinking/reasoning mode enabled.  For complex tasks, "
        "reason step-by-step internally before acting.  Use your extended "
        "reasoning budget for multi-step planning, code analysis, and "
        "mathematical problem solving.\n"
    )


# ---------------------------------------------------------------------------
# Monolithic agent
# ---------------------------------------------------------------------------

class MonolithicAgent:
    """Architecture A: single model loop with tools + memory.

    This is the recommended starting point.  It leverages Kimi K2.5's
    stability across 200-300 sequential tool calls to handle complex
    tasks without needing multi-model routing or parallel sub-agents.
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

        # -- memory ---------------------------------------------------------
        db_path = self.config.memory_db or None
        self.memory_store = MemoryStore(db_path=db_path)
        self.memory = MemoryManager(
            store=self.memory_store,
            user_id=self.config.user_id,
        )
        register_memory_tools(self.tools, self.memory)

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

        # -- session tracking -----------------------------------------------
        self.session = SessionContext(
            session_id=str(uuid.uuid4())[:8],
            user_id=self.config.user_id,
        )
        self._total_tool_calls = 0
        self._total_tasks = 0

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
        2. Run AgentLoop with all tools (including memory tools)
        3. Track session turns
        4. Auto-extract durable facts when done
        """
        self._total_tasks += 1
        self.session.add_turn("user", task)
        t0 = time.monotonic()

        # -- activate skills for this task ----------------------------------
        skill_prompt_addition = ""
        if self.skill_activator:
            try:
                matches, skill_prompt_addition = self.skill_activator.activate_for_task(task)
                if matches and self.config.verbose:
                    log.info("[A] Skills activated: %s", [m.skill.name for m in matches])
            except Exception:
                pass

        # -- build system prompt with memory context -------------------------
        memory_block = await self.memory.get_context_block(
            query=task,
            limit=self.config.memory_context_limit,
        )
        system_prompt = SYSTEM_TEMPLATE.format(
            max_iter=self.config.max_iterations,
            model_display=_model_display_name(self.config.model),
            thinking_block=_thinking_block(self.config.model, self.router),
            memory_block=memory_block or "(No prior memories for this user.)",
        ) + skill_prompt_addition

        # -- run agent loop --------------------------------------------------
        agent_config = AgentConfig(
            model=self.config.model,
            max_iterations=self.config.max_iterations,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system_prompt=system_prompt,
            security=self.security,
            usage_tracker=self.config.usage_tracker if hasattr(self.config, 'usage_tracker') else None,
            citation_tracker=self.citation_tracker,
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
        base = {
            "architecture": "A",
            "model": self.config.model,
            "total_tasks": self._total_tasks,
            "total_tool_calls": self._total_tool_calls,
            "session_id": self.session.session_id,
            "session_turns": len(self.session.turns),
            "tools_available": self.tools.names,
            "security_enabled": self.security is not None,
            "skills_enabled": self.skill_activator is not None,
            "citations_enabled": self.citation_tracker is not None,
        }
        if self.security:
            base["security_stats"] = self.security.stats
        return base


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
