from __future__ import annotations

import json
import time
from typing import Any

from orchestra.code_agent.orchestrator.router.models import (
    ModelLane, RouterConfig, RouterPlan, TaskIntent, TaskStep,
)


class RouterPlanner:
    def __init__(
        self,
        config: RouterConfig | None = None,
        llm_call: callable | None = None,
    ):
        self.config = config or RouterConfig()
        self._llm_call = llm_call or self._default_llm_call

    async def create_plan(
        self,
        user_input: str,
        intent: TaskIntent | None = None,
        constraints: list[str] | None = None,
    ) -> RouterPlan:
        intent = intent or self._detect_intent(user_input)
        system = self._system_prompt()
        user = self._build_prompt(user_input, intent, constraints or [])
        response = await self._llm_call(system, user)
        plan = self._parse(response, intent, constraints or [])
        plan.raw_llm_output = response
        return plan

    def _system_prompt(self) -> str:
        return f"""You are a routing planner for a multi-agent LLM system.
Decompose user requests into steps and assign each step to an agent role.

Available agent roles: coder, reasoner, summarizer, validator, scratch, searcher, extractor.

Return ONLY valid JSON with a "steps" array. Each step: {{"step": int, "agent": str, "goal": str}}.
Maximum {self.config.max_steps} steps."""

    def _build_prompt(self, user_input: str, intent: TaskIntent, constraints: list[str]) -> str:
        parts = [f"User: {user_input}", f"Intent: {intent.value}"]
        if constraints:
            parts.append(f"Constraints: {', '.join(constraints)}")
        parts.append("Return plan JSON.")
        return "\n".join(parts)

    def _detect_intent(self, text: str) -> TaskIntent:
        t = text.lower()
        if any(k in t for k in ("write code", "implement", "function", "class", "bug", "fix", "refactor")):
            return TaskIntent.CODE
        if any(k in t for k in ("reason", "explain why", "analyze", "compare")):
            return TaskIntent.REASONING
        if any(k in t for k in ("summarize", "summarise", "tl;dr", "condense")):
            return TaskIntent.SUMMARY
        if any(k in t for k in ("search", "find", "look up", "research")):
            return TaskIntent.SEARCH
        if any(k in t for k in ("plan", "outline", "steps to", "strategy")):
            return TaskIntent.PLAN
        if any(k in t for k in ("validate", "verify", "check", "review")):
            return TaskIntent.VALIDATE
        if any(k in t for k in ("extract", "parse")):
            return TaskIntent.EXTRACT
        return TaskIntent.GENERAL

    def _parse(self, response: str, intent: TaskIntent, constraints: list[str]) -> RouterPlan:
        try:
            data = self._extract_json(response)
            steps = []
            for s in data.get("steps", []):
                agent_str = s.get("agent", "reasoner").lower().strip()
                steps.append(TaskStep(
                    step=s.get("step", len(steps) + 1),
                    lane=self._role_to_lane(agent_str),
                    goal=s.get("goal", "Process this step"),
                    agent_role=agent_str,
                ))
            if not steps:
                steps = self._fallback(intent)
            return RouterPlan(steps=steps, intent=intent, constraints=constraints)
        except (json.JSONDecodeError, KeyError, TypeError):
            return RouterPlan(steps=self._fallback(intent), intent=intent, constraints=constraints)

    def _role_to_lane(self, role: str) -> ModelLane:
        mapping = {
            "coder": ModelLane.CODER_7B,
            "reasoner": ModelLane.REASONER_7B,
            "summarizer": ModelLane.SUMMARIZER_3B,
            "validator": ModelLane.VALIDATOR_7B,
            "scratch": ModelLane.SCRATCH_3B,
            "searcher": ModelLane.SEARCHER_3B,
            "extractor": ModelLane.EXTRACTOR_3B,
            "planner": ModelLane.MASTER_PLANNER_7B,
        }
        return mapping.get(role, ModelLane.FALLBACK_3B)

    def _fallback(self, intent: TaskIntent) -> list[TaskStep]:
        mapping = {
            TaskIntent.CODE: [("coder", ModelLane.CODER_7B), ("validator", ModelLane.VALIDATOR_7B)],
            TaskIntent.REASONING: [("reasoner", ModelLane.REASONER_7B), ("validator", ModelLane.VALIDATOR_7B)],
            TaskIntent.SUMMARY: [("summarizer", ModelLane.SUMMARIZER_3B)],
            TaskIntent.SEARCH: [("searcher", ModelLane.SEARCHER_3B), ("extractor", ModelLane.EXTRACTOR_3B)],
            TaskIntent.PLAN: [("planner", ModelLane.MASTER_PLANNER_7B), ("reasoner", ModelLane.REASONER_7B)],
            TaskIntent.VALIDATE: [("validator", ModelLane.VALIDATOR_7B)],
            TaskIntent.EXTRACT: [("extractor", ModelLane.EXTRACTOR_3B)],
            TaskIntent.GENERAL: [("reasoner", ModelLane.REASONER_7B), ("summarizer", ModelLane.SUMMARIZER_3B)],
        }
        chain = mapping.get(intent, mapping[TaskIntent.GENERAL])
        return [
            TaskStep(step=i + 1, lane=lane, goal=f"Process using {role}", agent_role=role)
            for i, (role, lane) in enumerate(chain)
        ]

    async def replan(self, original: str, plan: RouterPlan, history: list, failed_step: int | None = None) -> RouterPlan:
        parts = [
            f"Original: {original}",
            f"Current plan: {json.dumps([{'step': s.step, 'agent': s.agent_role, 'goal': s.goal} for s in plan.steps])}",
        ]
        if failed_step is not None:
            parts.append(f"Step {failed_step} FAILED. Revise.")
        response = await self._llm_call(self._system_prompt(), "\n".join(parts))
        return self._parse(response, plan.intent, plan.constraints)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise json.JSONDecodeError("No JSON object found", text, 0)

    @staticmethod
    async def _default_llm_call(system: str, user: str) -> str:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "qwen2.5:7b",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3},
                },
            )
            data = resp.json()
            return data.get("message", {}).get("content", "")
