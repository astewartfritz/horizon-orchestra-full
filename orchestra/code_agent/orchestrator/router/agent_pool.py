from __future__ import annotations

from orchestra.code_agent.orchestrator.router.models import (
    AgentClass, AgentSpec, ModelLane, RouterConfig, MODEL_LANE_MAP,
)

LANE_ROLES: dict[ModelLane, str] = {
    ModelLane.MASTER_PLANNER_7B: "Plan and decompose tasks into actionable steps",
    ModelLane.CODER_7B: "Write and debug code in any language",
    ModelLane.REASONER_7B: "Logical reasoning and problem decomposition",
    ModelLane.SUMMARIZER_3B: "Condense long text into concise summaries",
    ModelLane.SCRATCH_3B: "Quick drafts, notes, and exploration",
    ModelLane.VALIDATOR_7B: "Check outputs for correctness and completeness",
    ModelLane.SEARCHER_3B: "Find relevant information and context",
    ModelLane.EXTRACTOR_3B: "Extract structured data from unstructured text",
    ModelLane.FALLBACK_3B: "General purpose fallback for any task",
}

LANE_INSTRUCTIONS: dict[ModelLane, str] = {
    ModelLane.CODER_7B: "\nReturn working code with no placeholders.",
    ModelLane.VALIDATOR_7B: "\nCheck for correctness, edge cases, and bugs. List any issues found.",
    ModelLane.SUMMARIZER_3B: "\nBe concise. Focus on key points only.",
}


class AgentPool:
    def __init__(self, config: RouterConfig | None = None):
        self.config = config or RouterConfig()
        self._specs: dict[ModelLane, AgentSpec] = {}

    def register(self, lane: ModelLane, spec: AgentSpec) -> None:
        self._specs[lane] = spec

    def get(self, lane: ModelLane) -> AgentSpec:
        if lane in self._specs:
            return self._specs[lane]
        model = self.config.model_lanes.get(lane, MODEL_LANE_MAP.get(lane, "qwen2.5:1.5b"))
        return AgentSpec(
            agent_class=AgentClass.CODER,
            model=model,
            role_description=LANE_ROLES.get(lane, "General purpose agent"),
        )

    def select_model(self, lane: ModelLane) -> str:
        return self.get(lane).model

    def list_agents(self) -> list[AgentSpec]:
        return list(self._specs.values())

    def build_prompt_from_lane(
        self,
        lane: ModelLane,
        goal: str,
        context: str | None = None,
        history: list | None = None,
    ) -> str:
        role = LANE_ROLES.get(lane, "General purpose agent")
        parts = [f"You are a {role}."]
        if context:
            parts.append(f"\nContext:\n{context}")
        if history:
            parts.append(f"\nPrevious work:\n{self._format_history(history)}")
        parts.append(f"\nTask: {goal}")
        instruction = LANE_INSTRUCTIONS.get(lane, "")
        if instruction:
            parts.append(instruction)
        return "\n".join(parts)

    @staticmethod
    def _format_history(history: list) -> str:
        lines = []
        for h in history[-5:]:
            lane = getattr(h, "lane", "unknown")
            status = getattr(h, "status", "?")
            output = getattr(h, "output", "")
            preview = (output[:200] + "...") if output and len(output) > 200 else (output or "")
            lines.append(f"[{lane}] ({status}): {preview}")
        return "\n".join(lines)
