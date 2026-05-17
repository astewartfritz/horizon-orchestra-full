from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentClass(str, Enum):
    CODER = "coder"
    REASONER = "reasoner"
    SUMMARIZER = "summarizer"
    VALIDATOR = "validator"
    SCRATCH = "scratch"
    PLANNER = "planner"
    SEARCHER = "searcher"
    EXTRACTOR = "extractor"


@dataclass
class AgentSpec:
    agent_class: AgentClass
    model: str
    role_description: str
    temperature: float = 0.7
    max_tokens: int = 4096


class ModelLane(str, Enum):
    MASTER_PLANNER_7B = "master_planner_7b"
    CODER_7B = "coder_7b"
    REASONER_7B = "reasoner_7b"
    SUMMARIZER_3B = "summarizer_3b"
    SCRATCH_3B = "scratch_3b"
    VALIDATOR_7B = "validator_7b"
    SEARCHER_3B = "searcher_3b"
    EXTRACTOR_3B = "extractor_3b"
    FALLBACK_3B = "fallback_3b"


MODEL_LANE_MAP: dict[ModelLane, str] = {
    ModelLane.MASTER_PLANNER_7B: "qwen2.5:7b",
    ModelLane.CODER_7B: "qwen2.5-coder:7b",
    ModelLane.REASONER_7B: "deepseek-r1:8b",
    ModelLane.SUMMARIZER_3B: "qwen2.5:3b",
    ModelLane.SCRATCH_3B: "qwen2.5:1.5b",
    ModelLane.VALIDATOR_7B: "qwen2.5:7b",
    ModelLane.SEARCHER_3B: "qwen2.5:3b",
    ModelLane.EXTRACTOR_3B: "qwen2.5:3b",
    ModelLane.FALLBACK_3B: "qwen2.5:1.5b",
}


class TaskIntent(str, Enum):
    CODE = "code"
    REASONING = "reasoning"
    SUMMARY = "summary"
    SEARCH = "search"
    PLAN = "plan"
    VALIDATE = "validate"
    EXTRACT = "extract"
    GENERAL = "general"


class StepStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_REPLAN = "needs_replan"
    RETRY = "retry"


class TaskStatus(str, Enum):
    PENDING = "pending"
    INGESTED = "ingested"
    PLANNED = "planned"
    ENQUEUED = "enqueued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskStep:
    step: int
    lane: ModelLane
    goal: str
    agent_role: str = ""
    input_prompt: str = ""
    status: StepStatus = StepStatus.PENDING
    result: str | None = None
    error: str | None = None
    retries: int = 0
    max_retries: int = 2


@dataclass
class RouterPlan:
    steps: list[TaskStep] = field(default_factory=list)
    intent: TaskIntent = TaskIntent.GENERAL
    constraints: list[str] = field(default_factory=list)
    raw_llm_output: str = ""


@dataclass
class StepResult:
    step: int
    lane: ModelLane
    agent_role: str
    status: StepStatus
    output: str | None = None
    error: str | None = None


@dataclass
class TaskState:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_input: str = ""
    intent: TaskIntent = TaskIntent.GENERAL
    status: TaskStatus = TaskStatus.PENDING
    plan: RouterPlan | None = None
    history: list[StepResult] = field(default_factory=list)
    final_output: str | None = None
    current_step_index: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class RouterConfig:
    planner_model: str = "qwen2.5:7b"
    planner_temperature: float = 0.3
    planner_max_tokens: int = 2048
    max_steps: int = 5
    enable_replan: bool = True
    enable_fallback: bool = True
    model_lanes: dict[ModelLane, str] = field(default_factory=lambda: dict(MODEL_LANE_MAP))
    ollama_base_url: str = "http://localhost:11434"


def choose_model_lane(task_type: str, context: dict | None = None) -> ModelLane:
    context = context or {}
    if task_type == "plan":
        return ModelLane.MASTER_PLANNER_7B
    elif task_type == "code":
        return ModelLane.CODER_7B
    elif task_type == "reasoning":
        return ModelLane.REASONER_7B
    elif task_type == "summary" or (context.get("input_length", 0) or 0) > 4000:
        return ModelLane.SUMMARIZER_3B
    elif task_type == "scratch":
        return ModelLane.SCRATCH_3B
    elif task_type == "validate":
        return ModelLane.VALIDATOR_7B
    elif task_type == "search":
        return ModelLane.SEARCHER_3B
    elif task_type == "extract":
        return ModelLane.EXTRACTOR_3B
    else:
        return ModelLane.FALLBACK_3B
