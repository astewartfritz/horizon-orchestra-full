from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.llm.base import LLM, Message


@dataclass
class PromptTemplates:
    query: str = """You are a skill query generator. Given a task and the skill library stats, produce a concise search query to find the most relevant skill.

Task: {task_instruction}
Library stats: {library_stats}

Output ONLY a single line with the search query."""

    rerank: str = """You are a skill selector. Given a task and a list of candidate skills, choose the single best skill to condition on.

Task: {task_instruction}
Candidate skills:
{candidates}

Respond with the ID of the best skill. Output ONLY the number."""

    act: str = """You are acting in an environment with a strategy. Use the skill to guide your actions.

Task: {task_instruction}
Skill strategy: {skill_body}

Current observation:
{observation}

Available actions:
{actions}

History (last {history_len} steps):
{history}

Respond with ONE action from the available actions list. Output ONLY the action exactly as shown."""

    distill: str = """You are a skill distiller. Given a completed trajectory, produce a reusable skill strategy.

Task: {task_instruction}

Trajectory summary:
{trajectory_summary}

Final reward: {final_reward}
Success: {success}

Write a concise natural-language skill strategy (2-5 sentences) that captures the essential method used. Output ONLY the strategy text."""


@dataclass
class PolicyOutput:
    content: str
    logprobs: dict[str, float] | None = None
    mode: str = ""


class MetaPolicy:
    def __init__(self, llm: LLM, templates: PromptTemplates | None = None):
        self.llm = llm
        self.templates = templates or PromptTemplates()

    async def query(self, task_instruction: str, library_stats: str) -> PolicyOutput:
        prompt = self.templates.query.format(task_instruction=task_instruction, library_stats=library_stats)
        resp = await self.llm.chat(messages=[Message(role="user", content=prompt)])
        return PolicyOutput(content=(resp.content or "").strip(), mode="query")

    async def rerank(self, task_instruction: str, candidates: list[tuple[float, Any]]) -> PolicyOutput:
        lines = []
        for i, (score, skill) in enumerate(candidates):
            lines.append(f"[{skill.id}] score={score:.3f} | {skill.body[:150]}")
        candidates_text = "\n".join(lines)
        prompt = self.templates.rerank.format(task_instruction=task_instruction, candidates=candidates_text)
        resp = await self.llm.chat(messages=[Message(role="user", content=prompt)])
        return PolicyOutput(content=(resp.content or "").strip(), mode="rerank")

    async def act(self, task_instruction: str, skill_body: str, observation: str, actions: list[str], history: list[str]) -> PolicyOutput:
        prompt = self.templates.act.format(
            task_instruction=task_instruction, skill_body=skill_body,
            observation=observation, actions="\n".join(f"- {a}" for a in actions),
            history_len=len(history), history="\n".join(history[-5:]) if history else "(none)",
        )
        resp = await self.llm.chat(messages=[Message(role="user", content=prompt)])
        return PolicyOutput(content=(resp.content or "").strip(), mode="act")

    async def distill(self, task_instruction: str, trajectory_summary: str, final_reward: float, success: bool) -> PolicyOutput:
        prompt = self.templates.distill.format(
            task_instruction=task_instruction, trajectory_summary=trajectory_summary,
            final_reward=final_reward, success=success,
        )
        resp = await self.llm.chat(messages=[Message(role="user", content=prompt)])
        return PolicyOutput(content=(resp.content or "").strip(), mode="distill")
