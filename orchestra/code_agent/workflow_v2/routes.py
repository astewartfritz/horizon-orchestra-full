from fastapi import APIRouter, HTTPException

from orchestra.code_agent.workflow_v2.engine import DAGEngine, WorkflowManager
from orchestra.code_agent.workflow_v2.parser import parse_workflow, parse_workflow_json, parse_workflow_yaml, workflow_to_dict

_manager: WorkflowManager | None = None


def get_manager() -> WorkflowManager:
    global _manager
    if _manager is None:
        _manager = WorkflowManager()
    return _manager


def register_workflow_v2_routes(app, prefix: str = "/api/workflow-v2"):
    router = APIRouter(prefix=prefix)
    mgr = get_manager()

    @router.post("/workflows")
    async def create_workflow(body: dict):
        wf = parse_workflow(body)
        mgr.register_workflow(wf)
        return {"workflow_id": wf.id, "name": wf.name, "step_count": len(wf.steps)}

    @router.post("/workflows/from-json")
    async def create_from_json(body: dict):
        json_text = body.get("json", "")
        wf = parse_workflow_json(json_text)
        mgr.register_workflow(wf)
        return {"workflow_id": wf.id, "name": wf.name, "step_count": len(wf.steps)}

    @router.post("/workflows/from-yaml")
    async def create_from_yaml(body: dict):
        yaml_text = body.get("yaml", "")
        wf = parse_workflow_yaml(yaml_text)
        mgr.register_workflow(wf)
        return {"workflow_id": wf.id, "name": wf.name, "step_count": len(wf.steps)}

    @router.get("/workflows")
    async def list_workflows():
        return {
            "workflows": [
                {"id": w.id, "name": w.name, "steps": len(w.steps), "version": w.version}
                for w in mgr.list_workflows()
            ],
            "count": len(mgr.list_workflows()),
        }

    @router.get("/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str):
        wf = mgr.get_workflow(workflow_id)
        if not wf:
            raise HTTPException(404, "Workflow not found")
        return workflow_to_dict(wf)

    @router.post("/workflows/{workflow_id}/run")
    async def run_workflow(workflow_id: str, body: dict | None = None):
        body = body or {}
        try:
            ctx = await mgr.run_workflow(workflow_id, body.get("vars"))
        except ValueError as e:
            raise HTTPException(404, str(e))
        return {
            "instance_id": ctx.workflow_id,
            "status": ctx.status.value,
            "total_duration_ms": round(ctx.total_duration_ms, 2),
            "error": ctx.error,
            "results": {
                sid: {
                    "status": r.status.value,
                    "output": r.output[:500] if r.output else "",
                    "error": r.error,
                    "duration_ms": round(r.duration_ms, 2),
                    "child_count": len(r.child_results),
                }
                for sid, r in ctx.results.items()
            },
        }

    @router.post("/run")
    async def run_workflow_direct(body: dict):
        wf = parse_workflow(body)
        vars = body.get("vars", {})
        ctx = await mgr.run_workflow_direct(wf, vars)
        return {
            "instance_id": ctx.workflow_id,
            "workflow_name": ctx.workflow_name,
            "status": ctx.status.value,
            "total_duration_ms": round(ctx.total_duration_ms, 2),
            "results": {
                sid: {
                    "status": r.status.value,
                    "output": r.output[:500] if r.output else "",
                    "error": r.error,
                }
                for sid, r in ctx.results.items()
            },
        }

    @router.get("/instances")
    async def list_instances():
        return {
            "instances": [
                {
                    "id": inst.context.workflow_id,
                    "workflow_name": inst.context.workflow_name,
                    "status": inst.context.status.value,
                    "duration_ms": round(inst.context.total_duration_ms, 2),
                    "created_at": inst.created_at,
                }
                for inst in mgr.list_instances()
            ],
            "count": len(mgr.list_instances()),
        }

    @router.get("/instances/{instance_id}")
    async def get_instance(instance_id: str):
        inst = mgr.get_instance(instance_id)
        if not inst:
            raise HTTPException(404, "Instance not found")
        ctx = inst.context
        return {
            "instance_id": ctx.workflow_id,
            "workflow_name": ctx.workflow_name,
            "status": ctx.status.value,
            "error": ctx.error,
            "total_duration_ms": round(ctx.total_duration_ms, 2),
            "vars": dict(ctx.vars),
            "results": {
                sid: {
                    "status": r.status.value,
                    "output": r.output[:1000] if r.output else "",
                    "error": r.error,
                    "step_type": r.step_type,
                    "duration_ms": round(r.duration_ms, 2),
                }
                for sid, r in ctx.results.items()
            },
        }

    @router.post("/instances/{instance_id}/resume")
    async def resume_instance(instance_id: str, body: dict):
        step_id = body.get("step_id", "")
        response = body.get("response", "")
        ok = await mgr.resume_handoff(instance_id, step_id, response)
        if not ok:
            raise HTTPException(404, "Step not found or not waiting for human input")
        return {"status": "resumed", "instance_id": instance_id}

    @router.get("/steps/types")
    async def list_step_types():
        return {
            "step_types": [
                {"type": "agent", "description": "Run an agent with a prompt"},
                {"type": "tool", "description": "Execute a tool"},
                {"type": "transform", "description": "Transform or merge outputs"},
                {"type": "parallel", "description": "Run steps in parallel branches"},
                {"type": "condition", "description": "If/else branch"},
                {"type": "switch", "description": "Multi-case branch"},
                {"type": "loop", "description": "Iterate over items or while condition"},
                {"type": "human_handoff", "description": "Pause for human input"},
                {"type": "subworkflow", "description": "Run a sub-workflow"},
            ]
        }

    app.include_router(router)
