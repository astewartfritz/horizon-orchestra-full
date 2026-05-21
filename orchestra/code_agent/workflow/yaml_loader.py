from __future__ import annotations

from pathlib import Path

from orchestra.code_agent.workflow.engine import Workflow, WorkflowStep


def load_workflow(path: str) -> Workflow:
    p = Path(path)
    text = p.read_text("utf-8")

    import yaml
    data = yaml.safe_load(text)

    workflow = Workflow(
        name=data.get("name", p.stem),
        description=data.get("description", ""),
        vars=data.get("vars", {}),
    )

    for i, step_data in enumerate(data.get("steps", [])):
        step = WorkflowStep(
            id=step_data.get("id", f"step_{i}"),
            name=step_data.get("name", f"Step {i}"),
            prompt=step_data.get("prompt", ""),
            depends_on=step_data.get("depends_on", []),
            max_retries=step_data.get("max_retries", 1),
            timeout=step_data.get("timeout", 300),
            condition=step_data.get("condition"),
        )
        workflow.add_step(step)

    return workflow
