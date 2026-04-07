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
from .perplexity import PerplexitySearch

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


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

SYSTEM_TEMPLATE = """\
You are Horizon Orchestra, an autonomous AI agent powered by Kimi K2.5.

You have access to tools for web search, code execution, file I/O,
browser automation, and persistent memory.  Use them iteratively to
complete the user's task.  You can call up to {max_iter} tools in
sequence.

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

        # -- build system prompt with memory context -------------------------
        memory_block = await self.memory.get_context_block(
            query=task,
            limit=self.config.memory_context_limit,
        )
        system_prompt = SYSTEM_TEMPLATE.format(
            max_iter=self.config.max_iterations,
            memory_block=memory_block or "(No prior memories for this user.)",
        )

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
