from code_agent.workflow_v2.models import (
    BaseStep, AgentStep, ToolStep, TransformStep,
    ParallelStep, ConditionStep, SwitchStep, LoopStep,
    HumanHandoffStep, SubWorkflowStep,
    DAGWorkflow,
)

STEP_TYPE_MAP = {
    "agent": AgentStep,
    "tool": ToolStep,
    "transform": TransformStep,
    "parallel": ParallelStep,
    "condition": ConditionStep,
    "switch": SwitchStep,
    "loop": LoopStep,
    "human_handoff": HumanHandoffStep,
    "subworkflow": SubWorkflowStep,
}


def _parse_step(data: dict) -> BaseStep:
    step_type = data.get("type", "agent")
    data = {k: v for k, v in data.items() if k != "type"}
    cls = STEP_TYPE_MAP.get(step_type)
    if not cls:
        cls = AgentStep

    if cls == ParallelStep:
        branches_data = data.pop("branches", [])
        step = cls(**data)
        step.branches = [[_parse_step(s) for s in branch] for branch in branches_data]
        return step
    elif cls == ConditionStep:
        if_data = data.pop("if", [])
        else_data = data.pop("else", [])
        step = cls(**data)
        step.if_steps = [_parse_step(s) for s in if_data]
        step.else_steps = [_parse_step(s) for s in else_data]
        return step
    elif cls == SwitchStep:
        cases_data = data.pop("cases", {})
        default_data = data.pop("default", [])
        step = cls(**data)
        step.cases = {k: [_parse_step(s) for s in v] for k, v in cases_data.items()}
        step.default_steps = [_parse_step(s) for s in default_data]
        return step
    elif cls == LoopStep:
        body_data = data.pop("body", [])
        step = cls(**data)
        step.loop_body = [_parse_step(s) for s in body_data]
        return step
    else:
        return cls(**data)


def parse_workflow(data: dict) -> DAGWorkflow:
    steps_data = data.pop("steps", [])
    wf = DAGWorkflow(**data)
    for step_data in steps_data:
        step = _parse_step(step_data)
        wf.add_step(step)
    return wf


def parse_workflow_yaml(yaml_text: str) -> DAGWorkflow:
    import yaml
    data = yaml.safe_load(yaml_text)
    return parse_workflow(data)


def parse_workflow_json(json_text: str) -> DAGWorkflow:
    import json
    data = json.loads(json_text)
    return parse_workflow(data)


def workflow_to_dict(wf: DAGWorkflow) -> dict:
    def step_to_dict(step: BaseStep) -> dict:
        d = {
            "id": step.id,
            "name": step.name,
            "type": step.step_type,
            "depends_on": list(step.depends_on),
            "status": step.status.value,
            "max_retries": step.max_retries,
            "timeout": step.timeout,
            "condition": step.condition,
            "on_failure": step.on_failure,
            "description": step.description,
            "metadata": dict(step.metadata),
        }
        if isinstance(step, AgentStep):
            d["prompt"] = step.prompt
            d["output_key"] = step.output_key
        elif isinstance(step, ToolStep):
            d["tool_name"] = step.tool_name
            d["tool_params"] = dict(step.tool_params)
        elif isinstance(step, TransformStep):
            d["expression"] = step.expression
            d["output_template"] = step.output_template
        elif isinstance(step, ParallelStep):
            d["branches"] = [[step_to_dict(s) for s in b] for b in step.branches]
            d["max_concurrency"] = step.max_concurrency
            d["aggregator"] = step.aggregator
        elif isinstance(step, ConditionStep):
            d["condition_expression"] = step.condition_expression
            d["if"] = [step_to_dict(s) for s in step.if_steps]
            d["else"] = [step_to_dict(s) for s in step.else_steps]
        elif isinstance(step, SwitchStep):
            d["switch_expression"] = step.switch_expression
            d["cases"] = {k: [step_to_dict(s) for s in v] for k, v in step.cases.items()}
            d["default"] = [step_to_dict(s) for s in step.default_steps]
        elif isinstance(step, LoopStep):
            d["body"] = [step_to_dict(s) for s in step.loop_body]
            d["while_condition"] = step.while_condition
            d["for_items"] = step.for_items
            d["max_iterations"] = step.max_iterations
        elif isinstance(step, HumanHandoffStep):
            d["message"] = step.message
            d["prompt"] = step.prompt
            d["timeout"] = step.timeout
            d["channel"] = step.channel
        elif isinstance(step, SubWorkflowStep):
            d["workflow_name"] = step.workflow_name
            d["workflow_vars"] = dict(step.workflow_vars)
        return d

    return {
        "id": wf.id,
        "name": wf.name,
        "description": wf.description,
        "version": wf.version,
        "vars": dict(wf.vars),
        "tags": list(wf.tags),
        "steps": [step_to_dict(s) for s in wf.steps],
    }
