from __future__ import annotations

import uuid
import time
import re
import json
import os
import asyncio
from enum import Enum
from typing import Any, Callable
from dataclasses import dataclass, field


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    WAITING_HUMAN = "waiting_human"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class DAGResult:
    step_id: str = ""
    step_type: str = ""
    step_name: str = ""
    status: StepStatus = StepStatus.PENDING
    output: str = ""
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: float = 0.0
    child_results: list[DAGResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == StepStatus.COMPLETED


@dataclass
class WorkflowContext:
    workflow_id: str = ""
    workflow_name: str = ""
    vars: dict[str, Any] = field(default_factory=dict)
    results: dict[str, DAGResult] = field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.PENDING
    error: str = ""
    current_step_id: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    total_duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    _handoff_events: dict[str, asyncio.Event] = field(default_factory=dict)

    def get_step_output(self, step_id: str, field_path: str = "") -> str:
        result = self.results.get(step_id)
        if not result:
            return ""
        output = result.output
        if not field_path:
            return output
        try:
            data = json.loads(output)
            parts = field_path.split(".")
            for p in parts:
                if isinstance(data, dict):
                    data = data.get(p, "")
                elif isinstance(data, list):
                    try:
                        data = data[int(p)]
                    except (ValueError, IndexError):
                        return ""
                else:
                    return str(data)
            return str(data) if not isinstance(data, (dict, list)) else json.dumps(data)
        except (json.JSONDecodeError, ValueError):
            return ""

    def resolve_variables(self, text: str) -> str:
        def replacer(m):
            expr = m.group(1).strip()
            if expr.startswith("vars."):
                key = expr[5:]
                return str(self.vars.get(key, ""))
            if expr.startswith("steps."):
                parts = expr.split(".")
                step_id = parts[1] if len(parts) > 1 else ""
                field_path = ".".join(parts[2:]) if len(parts) > 2 else ""
                if field_path == "output":
                    field_path = ""
                elif field_path.startswith("output."):
                    field_path = field_path[7:]
                return self.get_step_output(step_id, field_path)
            if expr.startswith("env."):
                return os.environ.get(expr[4:], "")
            if expr.startswith("result."):
                return self.get_step_output(self.current_step_id, expr[7:])
            return expr
        return re.sub(r'\$\{\{(.+?)\}\}', replacer, text)

    def resolve_in_dict(self, d: dict) -> dict:
        result = {}
        for k, v in d.items():
            if isinstance(v, str):
                result[k] = self.resolve_variables(v)
            elif isinstance(v, dict):
                result[k] = self.resolve_in_dict(v)
            elif isinstance(v, list):
                result[k] = [
                    self.resolve_in_dict(i) if isinstance(i, dict) else
                    self.resolve_variables(i) if isinstance(i, str) else i
                    for i in v
                ]
            else:
                result[k] = v
        return result


@dataclass
class BaseStep:
    id: str = ""
    name: str = ""
    step_type: str = "base"
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    max_retries: int = 0
    timeout: float = 300.0
    condition: str = ""
    on_failure: str = "fail"
    metadata: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"step_{uuid.uuid4().hex[:8]}"

    def all_child_steps(self) -> list[BaseStep]:
        return []


@dataclass
class AgentStep(BaseStep):
    step_type: str = "agent"
    prompt: str = ""
    agent_config: dict[str, Any] = field(default_factory=dict)
    output_key: str = ""


@dataclass
class ToolStep(BaseStep):
    step_type: str = "tool"
    tool_name: str = ""
    tool_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransformStep(BaseStep):
    step_type: str = "transform"
    expression: str = ""
    output_template: str = ""


@dataclass
class ParallelStep(BaseStep):
    step_type: str = "parallel"
    branches: list[list[BaseStep]] = field(default_factory=list)
    max_concurrency: int = 5
    aggregator: str = "join"
    aggregator_expression: str = ""

    def all_child_steps(self) -> list[BaseStep]:
        children = []
        for branch in self.branches:
            for step in branch:
                children.append(step)
                children.extend(step.all_child_steps())
        return children


@dataclass
class ConditionStep(BaseStep):
    step_type: str = "condition"
    condition_expression: str = ""
    if_steps: list[BaseStep] = field(default_factory=list)
    else_steps: list[BaseStep] = field(default_factory=list)

    def all_child_steps(self) -> list[BaseStep]:
        children = []
        for step in self.if_steps + self.else_steps:
            children.append(step)
            children.extend(step.all_child_steps())
        return children


@dataclass
class SwitchStep(BaseStep):
    step_type: str = "switch"
    switch_expression: str = ""
    cases: dict[str, list[BaseStep]] = field(default_factory=dict)
    default_steps: list[BaseStep] = field(default_factory=list)

    def all_child_steps(self) -> list[BaseStep]:
        children = []
        for case_steps in self.cases.values():
            for step in case_steps:
                children.append(step)
                children.extend(step.all_child_steps())
        for step in self.default_steps:
            children.append(step)
            children.extend(step.all_child_steps())
        return children


@dataclass
class LoopStep(BaseStep):
    step_type: str = "loop"
    loop_body: list[BaseStep] = field(default_factory=list)
    while_condition: str = ""
    for_items: str = ""
    max_iterations: int = 10
    item_variable: str = "item"

    def all_child_steps(self) -> list[BaseStep]:
        children = []
        for step in self.loop_body:
            children.append(step)
            children.extend(step.all_child_steps())
        return children


@dataclass
class HumanHandoffStep(BaseStep):
    step_type: str = "human_handoff"
    message: str = ""
    prompt: str = ""
    timeout: float = 3600.0
    channel: str = ""
    response: str = ""


@dataclass
class SubWorkflowStep(BaseStep):
    step_type: str = "subworkflow"
    workflow_name: str = ""
    workflow_vars: dict[str, Any] = field(default_factory=dict)


@dataclass
class DAGWorkflow:
    id: str = ""
    name: str = ""
    description: str = ""
    version: str = "1.0"
    steps: list[BaseStep] = field(default_factory=list)
    vars: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = f"wf_{uuid.uuid4().hex[:12]}"

    def add_step(self, step: BaseStep):
        self.steps.append(step)
        return step.id

    def get_step(self, step_id: str) -> BaseStep | None:
        for step in self.steps:
            if step.id == step_id:
                return step
            child = self._find_in_children(step, step_id)
            if child:
                return child
        return None

    def _find_in_children(self, step: BaseStep, step_id: str) -> BaseStep | None:
        for child in step.all_child_steps():
            if child.id == step_id:
                return child
            grandchild = self._find_in_children(child, step_id)
            if grandchild:
                return grandchild
        return None

    def all_steps_flat(self) -> list[BaseStep]:
        flat = []
        for step in self.steps:
            flat.append(step)
            flat.extend(step.all_child_steps())
        return flat

    def get_dependency_ids(self, step: BaseStep) -> set[str]:
        deps = set(step.depends_on)
        if isinstance(step, ConditionStep):
            for s in step.if_steps + step.else_steps:
                deps.update(s.depends_on)
        elif isinstance(step, ParallelStep):
            for branch in step.branches:
                for s in branch:
                    deps.update(s.depends_on)
        elif isinstance(step, SwitchStep):
            for case_steps in step.cases.values():
                for s in case_steps:
                    deps.update(s.depends_on)
            for s in step.default_steps:
                deps.update(s.depends_on)
        elif isinstance(step, LoopStep):
            for s in step.loop_body:
                deps.update(s.depends_on)
        return deps
