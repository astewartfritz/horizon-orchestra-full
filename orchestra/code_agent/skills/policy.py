from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.llm.base import LLM, Message
from orchestra.code_agent.skills.models import Skill


@dataclass
class PolicyOutput:
    content: str
    logprobs: dict[str, float] | None = None
    mode: str = ""


QUERY_PROMPT = """You are a skill query generator. Given a task and skill library stats, produce a concise search query.

Task: {task_instruction}
Library stats: {library_stats}

Output ONLY a single line with the search query."""

RANK_PROMPT = """You are a skill selector. Given a task and candidate skills, choose the single best skill.

Task: {task_instruction}
Candidates:
{candidates}

Respond with the ID of the best skill. Output ONLY the number."""

ACT_PROMPT = """You are acting in an environment with a strategy.

Task: {task_instruction}
Skill strategy: {skill_body}

Observation:
{observation}

Available actions:
{actions}

History (last {history_len}):
{history}

Respond with ONE action from the list. Output ONLY the action."""

DISTILL_PROMPT = """You are a skill distiller. Produce a reusable skill strategy from a trajectory.

Task: {task_instruction}
Trajectory:
{trajectory_summary}
Final reward: {final_reward}
Success: {success}

Write a concise natural-language skill strategy (2-5 sentences). Output ONLY the strategy."""

SAFETY_PROMPT = """You are a safety filter. Check if this action is safe in the current context.

Action: {action}
Observation: {observation}

Respond with only: SAFE or BLOCKED. If blocked, give a brief reason."""


class SkillPolicy:
    def __init__(self, llm: LLM):
        self.llm = llm

    async def query(self, task_instruction: str, library_stats: str) -> PolicyOutput:
        resp = await self.llm.chat(messages=[Message(role="user", content=QUERY_PROMPT.format(task_instruction=task_instruction, library_stats=library_stats))])
        return PolicyOutput(content=(resp.content or "").strip(), mode="query")

    async def rank(self, task_instruction: str, candidates: list[tuple[float, Skill]]) -> PolicyOutput:
        lines = [f"[{s.id}] score={score:.3f} | {s.body[:150]}" for score, s in candidates]
        resp = await self.llm.chat(messages=[Message(role="user", content=RANK_PROMPT.format(task_instruction=task_instruction, candidates="\n".join(lines)))])
        return PolicyOutput(content=(resp.content or "").strip(), mode="rank")

    async def act(self, task_instruction: str, skill_body: str, observation: str, actions: list[str], history: list[str]) -> PolicyOutput:
        resp = await self.llm.chat(messages=[Message(role="user", content=ACT_PROMPT.format(task_instruction=task_instruction, skill_body=skill_body, observation=observation, actions="\n".join(f"- {a}" for a in actions), history_len=len(history), history="\n".join(history[-5:]) or "(none)"))])
        return PolicyOutput(content=(resp.content or "").strip(), mode="act")

    async def distill(self, task_instruction: str, trajectory_summary: str, final_reward: float, success: bool) -> PolicyOutput:
        resp = await self.llm.chat(messages=[Message(role="user", content=DISTILL_PROMPT.format(task_instruction=task_instruction, trajectory_summary=trajectory_summary, final_reward=final_reward, success=success))])
        return PolicyOutput(content=(resp.content or "").strip(), mode="distill")

    async def safety_check(self, action: str, observation: str) -> PolicyOutput:
        resp = await self.llm.chat(messages=[Message(role="user", content=SAFETY_PROMPT.format(action=action, observation=observation))])
        return PolicyOutput(content=(resp.content or "").strip(), mode="safety")
