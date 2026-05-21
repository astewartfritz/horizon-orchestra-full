from __future__ import annotations

from orchestra.code_agent.orchestrator.router.models import (
    ModelLane, RouterConfig,
)


class AgentRouter:
    """Non-LLM router that picks the correct model lane for a task type.

    This is the AGENT_ROUTER from the state diagram — it runs in microseconds
    with no LLM call. It:

    1. Receives a task_type and context dict from the EnqueueSteps stage
    2. Calls choose_model_lane() to select the optimal ModelLane
    3. Returns the lane + resolved model name for the ExecuteStep stage
    """

    def __init__(self, config: RouterConfig | None = None):
        self.config = config or RouterConfig()

    def route(
        self,
        task_type: str,
        context: dict | None = None,
    ) -> tuple[ModelLane, str]:
        lane = self._choose_lane(task_type, context or {})
        model = self.config.model_lanes.get(lane, lane.value)
        return lane, model

    def _choose_lane(self, task_type: str, context: dict) -> ModelLane:
        task_type = task_type.lower().strip()
        input_length = context.get("input_length", 0) or 0
        if task_type in ("summary", "summarize") or (input_length > 4000 and task_type != "plan"):
            return ModelLane.SUMMARIZER_3B
        if task_type == "plan":
            return ModelLane.MASTER_PLANNER_7B
        if task_type == "code":
            return ModelLane.CODER_7B
        if task_type == "reasoning":
            return ModelLane.REASONER_7B
        if task_type == "scratch":
            return ModelLane.SCRATCH_3B
        if task_type == "validate":
            return ModelLane.VALIDATOR_7B
        if task_type == "search":
            return ModelLane.SEARCHER_3B
        if task_type == "extract":
            return ModelLane.EXTRACTOR_3B
        return ModelLane.FALLBACK_3B

    def list_lanes(self) -> list[dict[str, str]]:
        return [
            {"task_type": "plan", "lane": ModelLane.MASTER_PLANNER_7B.value, "model": self.config.model_lanes[ModelLane.MASTER_PLANNER_7B]},
            {"task_type": "code", "lane": ModelLane.CODER_7B.value, "model": self.config.model_lanes[ModelLane.CODER_7B]},
            {"task_type": "reasoning", "lane": ModelLane.REASONER_7B.value, "model": self.config.model_lanes[ModelLane.REASONER_7B]},
            {"task_type": "summary", "lane": ModelLane.SUMMARIZER_3B.value, "model": self.config.model_lanes[ModelLane.SUMMARIZER_3B]},
            {"task_type": "scratch", "lane": ModelLane.SCRATCH_3B.value, "model": self.config.model_lanes[ModelLane.SCRATCH_3B]},
            {"task_type": "validate", "lane": ModelLane.VALIDATOR_7B.value, "model": self.config.model_lanes[ModelLane.VALIDATOR_7B]},
            {"task_type": "search", "lane": ModelLane.SEARCHER_3B.value, "model": self.config.model_lanes[ModelLane.SEARCHER_3B]},
            {"task_type": "extract", "lane": ModelLane.EXTRACTOR_3B.value, "model": self.config.model_lanes[ModelLane.EXTRACTOR_3B]},
            {"task_type": "fallback", "lane": ModelLane.FALLBACK_3B.value, "model": self.config.model_lanes[ModelLane.FALLBACK_3B]},
        ]

    @staticmethod
    def choose_model_lane(task_type: str, context: dict | None = None) -> ModelLane:
        from orchestra.code_agent.orchestrator.router.models import choose_model_lane as _cml
        return _cml(task_type, context)
