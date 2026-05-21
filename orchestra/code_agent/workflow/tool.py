from __future__ import annotations

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec
from orchestra.code_agent.workflow.engine import WorkflowEngine, Workflow, WorkflowStep
from orchestra.code_agent.config import AgentConfig


class WorkflowTool(Tool):
    spec = ToolSpec(
        name="workflow",
        description="Define and run multi-step workflow pipelines. Steps can have dependencies and conditions.",
        parameters={
            "name": {"type": "string", "description": "Workflow name"},
            "definition": {"type": "string", "description": "YAML or JSON workflow definition string"},
            "action": {
                "type": "string",
                "description": "run (default), status, or list",
                "default": "run",
            },
        },
    )

    _engines: dict[str, WorkflowEngine] = {}

    async def __call__(self, name: str = "", definition: str = "", action: str = "run") -> ToolResult:
        try:
            if action == "list":
                if not self._engines:
                    return ToolResult(output="(no workflows)")
                lines = [f"Active workflows ({len(self._engines)}):"]
                for wf_name in self._engines:
                    lines.append(f"  {wf_name}")
                return ToolResult(output="\n".join(lines))

            if action == "status":
                if name and name in self._engines:
                    return ToolResult(output=f"Workflow '{name}' has results available")
                return ToolResult(output="(workflow not found)")

            if not definition:
                return ToolResult(error="definition is required for action=run")

            import json
            import yaml

            try:
                data = json.loads(definition)
            except json.JSONDecodeError:
                data = yaml.safe_load(definition)

            if not data or not isinstance(data, dict):
                return ToolResult(error="Invalid workflow definition")

            workflow = Workflow(
                name=data.get("name", name or "unnamed"),
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

            engine = WorkflowEngine()
            self._engines[name or workflow.name] = engine

            import asyncio
            results = await engine.run(workflow)

            lines = [f"Workflow '{workflow.name}' completed ({len(results)} steps):"]
            for r in results:
                icon = {"completed": "OK", "failed": "FAIL", "skipped": "-", "running": "..."}.get(
                    r.status.value, "?"
                )
                lines.append(f"  [{icon}] {r.step_id}")
                if r.error:
                    lines.append(f"         Error: {r.error}")

            return ToolResult(output="\n".join(lines))

        except Exception as e:
            return ToolResult(error=str(e))
