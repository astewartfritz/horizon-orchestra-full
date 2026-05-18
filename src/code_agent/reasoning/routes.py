from __future__ import annotations

from fastapi import APIRouter, HTTPException

from code_agent.reasoning.engine import ReasoningEngine, ReasoningSession
from code_agent.reasoning.strategies import (
    get_strategy_prompt,
    COT_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    REFLECT_SYSTEM_PROMPT,
)

_STRATEGY_DESCRIPTIONS = {
    "cot": {
        "name": "Chain of Thought",
        "key": "cot",
        "description": "Step-by-step reasoning. Best for straightforward coding and analysis tasks.",
        "when_to_use": "Default for most tasks. Works well when the path forward is clear.",
    },
    "plan": {
        "name": "Plan and Execute",
        "key": "plan",
        "description": "Decompose complex tasks into a plan, then execute step by step.",
        "when_to_use": "Long, multi-step tasks with many sub-goals (>50 words in task description).",
    },
    "reflect": {
        "name": "Reflect on Error",
        "key": "reflect",
        "description": "Act → observe → reflect → adjust loop. Recovers from failures.",
        "when_to_use": "Debugging, error recovery, iterative refinement.",
    },
    "tot": {
        "name": "Tree of Thought",
        "key": "tot",
        "description": "Explore multiple reasoning branches and select the best path.",
        "when_to_use": "Open-ended problems where several approaches are plausible.",
    },
    "converse": {
        "name": "Conversational",
        "key": "converse",
        "description": "Natural conversation mode. No structured reasoning trace.",
        "when_to_use": "Greetings, clarifying questions, chit-chat.",
    },
    "auto": {
        "name": "Auto",
        "key": "auto",
        "description": "Automatically select the best strategy based on the task.",
        "when_to_use": "Default when you're unsure which strategy to use.",
    },
}


def _make_dummy_engine() -> ReasoningEngine:
    """Create a ReasoningEngine with a minimal stub LLM for strategy selection only."""
    from code_agent.llm.base import LLM, Message

    class _StubLLM(LLM):
        async def complete(self, messages, **_):  # type: ignore[override]
            return "[stub]"

        async def stream(self, messages, **_):  # type: ignore[override]
            yield "[stub]"

    from code_agent.config import ReasoningConfig
    return ReasoningEngine(_StubLLM(), ReasoningConfig(save_traces=False, show_thinking=False))


_engine: ReasoningEngine | None = None


def get_engine() -> ReasoningEngine:
    global _engine
    if _engine is None:
        _engine = _make_dummy_engine()
    return _engine


def register_reasoning_routes(app, prefix: str = "/api/reasoning"):
    router = APIRouter(prefix=prefix)

    @router.get("/strategies")
    async def list_strategies():
        return {
            "strategies": list(_STRATEGY_DESCRIPTIONS.values()),
            "count": len(_STRATEGY_DESCRIPTIONS),
        }

    @router.get("/strategies/{key}")
    async def get_strategy(key: str):
        s = _STRATEGY_DESCRIPTIONS.get(key)
        if not s:
            raise HTTPException(404, f"Unknown strategy: {key}")
        return {**s, "system_prompt": get_strategy_prompt(key)}

    @router.post("/select-strategy")
    async def select_strategy(body: dict):
        task = body.get("task", "")
        if not task:
            raise HTTPException(400, "task is required")
        engine = get_engine()
        selected = engine.select_strategy(task)
        meta = _STRATEGY_DESCRIPTIONS.get(selected, {})
        return {
            "task_preview": task[:100],
            "selected_strategy": selected,
            "strategy_name": meta.get("name", selected),
            "reason": meta.get("when_to_use", ""),
            "system_prompt": get_strategy_prompt(selected),
        }

    @router.post("/analyze")
    async def analyze_task(body: dict):
        task = body.get("task", "")
        if not task:
            raise HTTPException(400, "task is required")
        engine = get_engine()
        selected = engine.select_strategy(task)
        meta = _STRATEGY_DESCRIPTIONS.get(selected, {})

        word_count = len(task.split())
        has_error = any(kw in task.lower() for kw in ["error", "fix", "bug", "broken", "fail"])
        is_short = word_count <= 3
        is_long = word_count > 50

        return {
            "task": task,
            "word_count": word_count,
            "signals": {
                "is_conversational": engine._is_conversation(task),
                "has_error_keywords": has_error,
                "is_short_input": is_short,
                "is_long_task": is_long,
            },
            "recommended_strategy": selected,
            "strategy_name": meta.get("name", selected),
            "description": meta.get("description", ""),
        }

    @router.get("/traces")
    async def list_traces():
        engine = get_engine()
        traces = engine.list_traces()
        return {"traces": traces, "count": len(traces)}

    @router.get("/traces/{name}")
    async def get_trace(name: str):
        engine = get_engine()
        session = engine.load_trace(name)
        if not session:
            raise HTTPException(404, "Trace not found")
        return session.to_dict()

    @router.post("/session")
    async def start_session(body: dict):
        task = body.get("task", "")
        strategy = body.get("strategy", "auto")
        if not task:
            raise HTTPException(400, "task is required")
        engine = get_engine()
        resolved = engine.select_strategy(task) if strategy == "auto" else strategy
        if resolved not in _STRATEGY_DESCRIPTIONS:
            raise HTTPException(400, f"Unknown strategy: {strategy}")
        session = ReasoningSession(
            task=task,
            strategy=resolved,
        )
        from datetime import datetime
        session.created_at = datetime.utcnow().isoformat()
        return {
            "task": task,
            "strategy": resolved,
            "strategy_name": _STRATEGY_DESCRIPTIONS[resolved]["name"],
            "system_prompt": get_strategy_prompt(resolved),
            "created_at": session.created_at,
        }

    app.include_router(router)
