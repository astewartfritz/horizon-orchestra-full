from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from code_agent.llm.base import LLM, Message


@dataclass
class ThinkingTrace:
    strategy: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    plan: str | None = None
    duration_ms: float = 0.0
    tokens_used: int = 0
    reflection: str | None = None

    def add_step(self, label: str, content: str) -> None:
        self.steps.append({"label": label, "content": content, "ts": time.time()})

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "steps": self.steps[-20:],
            "plan": self.plan,
            "duration_ms": round(self.duration_ms, 1),
            "tokens_used": self.tokens_used,
            "reflection": self.reflection,
        }


COT_SYSTEM_PROMPT = """You are an autonomous code agent. Respond naturally to conversation. For tasks: examine, plan, use tools, verify, summarize. For greetings or introductions: just reply conversationally.

When asked "what can you do" or about your capabilities, list the agentic AI tasks you can perform: scaffold projects (Rust, TypeScript, Mojo, Python, web apps), read and write files, search code, run bash commands, execute git operations, browse the web, run tools in Docker sandboxes, analyze code quality, generate tests, transform and refactor code, create and manage skills, answer questions using web search with citations, and build full-stack applications."""

PLAN_SYSTEM_PROMPT = """You are an autonomous code agent. Respond naturally to conversation. For tasks: plan, use tools, execute step by step. For simple questions: answer immediately. For greetings or introductions: reply conversationally."""

REFLECT_SYSTEM_PROMPT = """You are an autonomous code agent. Act, observe, reflect, adjust, repeat. Analyze errors, hypothesize the cause, try a different approach. After two failures, stop and summarize blockers. When successful, note what worked and save the pattern."""


def get_strategy_prompt(strategy: str) -> str:
    prompts = {
        "cot": COT_SYSTEM_PROMPT,
        "plan": PLAN_SYSTEM_PROMPT,
        "reflect": REFLECT_SYSTEM_PROMPT,
        "converse": COT_SYSTEM_PROMPT,
    }
    return prompts.get(strategy, COT_SYSTEM_PROMPT)


class ChainOfThought:
    """Step-by-step reasoning with explicit thinking steps."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.trace = ThinkingTrace(strategy="cot")

    async def reason(
        self, question: str, context: list[Message] | None = None
    ) -> str:
        start = time.time()
        messages = [
            Message(
                role="system",
                content="Think step by step. Show your reasoning clearly.",
            ),
            *([Message(role="user", content=q) for q in [question]]),
        ]
        if context:
            messages = context + messages[-1:]
        resp = await self.llm.chat(messages, tools=None, stream=True)
        self.trace.duration_ms = (time.time() - start) * 1000
        self.trace.add_step("reason", resp.content or "")
        return resp.content or ""


class PlanAndExecute:
    """Plan-first, then execute step by step."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.trace = ThinkingTrace(strategy="plan")

    async def reason(
        self, question: str, context: list[Message] | None = None
    ) -> str:
        messages = [
            Message(role="system", content=PLAN_SYSTEM_PROMPT),
        ]
        if context:
            messages.extend(context[-4:])  # last 4 turns of conversation
        messages.append(Message(role="user", content=question))
        resp = await self.llm.chat(messages, tools=None, stream=True)
        result = resp.content or ""
        self.trace.add_step("reason", result)
        return result

    async def create_plan(self, task: str) -> str:
        messages = [
            Message(
                role="system",
                content=PLAN_SYSTEM_PROMPT,
            ),
            Message(
                role="user",
                content=f"Create a detailed plan for: {task}",
            ),
        ]
        resp = await self.llm.chat(messages, tools=None)
        plan = resp.content or ""
        self.trace.plan = plan
        self.trace.add_step("plan", plan)
        return plan


class ReflectOnError:
    """Analyze failures and learn from mistakes."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.trace = ThinkingTrace(strategy="reflect")

    async def reflect(self, error: str, context: str = "") -> str:
        messages = [
            Message(
                role="system",
                content="Analyze this error and suggest a fix. Be specific.",
            ),
            Message(
                role="user",
                content=f"Context: {context}\nError: {error}\n\nWhat went wrong and how should I fix it?",
            ),
        ]
        resp = await self.llm.chat(messages, tools=None)
        reflection = resp.content or ""
        self.trace.reflection = reflection
        self.trace.add_step("reflect", reflection)
        return reflection


class TreeOfThought:
    """Explore multiple reasoning paths in parallel."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.trace = ThinkingTrace(strategy="tot")

    async def explore(
        self, question: str, branches: int = 3
    ) -> list[tuple[str, str]]:
        import asyncio

        async def _branch(b: int) -> tuple[str, str]:
            messages = [
                Message(
                    role="system",
                    content="Think step by step. Consider approach {b}.",
                ),
                Message(
                    role="user",
                    content=f"Solve this using approach #{b}: {question}",
                ),
            ]
            resp = await self.llm.chat(messages, tools=None)
            return (f"approach_{b}", resp.content or "")

        results = await asyncio.gather(*[_branch(b) for b in range(branches)])
        for name, content in results:
            self.trace.add_step(name, content)
        return results
