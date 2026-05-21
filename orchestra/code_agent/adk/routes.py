from __future__ import annotations

from orchestra.code_agent.adk.governance import AdkGovernanceMonitor
from orchestra.code_agent.adk.intents import IntentLibrary
from orchestra.code_agent.adk.playbook import PromptPlaybook, ReplayEngine
from orchestra.code_agent.adk.testing_sandbox import AgentTestingSandbox

__all__ = ["register_adk_routes"]

_PLAYBOOK = PromptPlaybook()
for _e in PromptPlaybook.default_entries():
    _PLAYBOOK.register(_e)

_REPLAY = ReplayEngine()

_INTENTS = IntentLibrary()
for _t in IntentLibrary.default_templates():
    _INTENTS.register(_t)

_SANDBOX = AgentTestingSandbox()
for _s in AgentTestingSandbox.default_scenarios():
    _SANDBOX.register_scenario(_s)

_GOV = AdkGovernanceMonitor()


def register_adk_routes(app: object) -> None:
    try:
        from fastapi import APIRouter, HTTPException
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel
    except ImportError:
        return

    router = APIRouter(prefix="/api/adk", tags=["adk"])

    # ── Prompt Playbook ────────────────────────────────────────────────

    @router.get("/playbook")
    async def list_playbook():
        return JSONResponse(content=[
            {"id": e.id, "name": e.name, "intent": e.intent.value,
             "description": e.description, "tags": e.tags,
             "required_params": e.required_params}
            for e in _PLAYBOOK.list_all()
        ])

    @router.get("/playbook/{entry_id}")
    async def get_playbook_entry(entry_id: str):
        entry = _PLAYBOOK.get(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        return JSONResponse(content={
            "id": entry.id, "name": entry.name, "intent": entry.intent.value,
            "prompt_template": entry.prompt_template, "description": entry.description,
            "tags": entry.tags, "required_params": entry.required_params,
            "expected_response_hint": entry.expected_response_hint,
        })

    @router.post("/playbook/build")
    async def build_prompt(entry_id: str, params: dict[str, str]):
        prompt = _PLAYBOOK.build_prompt(entry_id, params)
        if prompt is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        return JSONResponse(content={"prompt": prompt})

    # ── Replay Engine ──────────────────────────────────────────────────

    @router.get("/replay")
    async def list_replays(limit: int = 50):
        return JSONResponse(content=[
            {"id": r.id, "intent": r.intent, "timestamp": r.timestamp,
             "prompt": r.prompt[:100], "success": r.success, "latency_ms": r.latency_ms}
            for r in _REPLAY.list_recent(limit)
        ])

    @router.get("/replay/{record_id}")
    async def get_replay(record_id: str):
        record = _REPLAY.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Record not found")
        data = _REPLAY.export(record_id)
        import json
        return JSONResponse(content=json.loads(data))

    # ── Intent Templates ────────────────────────────────────────────────

    @router.get("/intents")
    async def list_intent_templates():
        return JSONResponse(content=[
            {"name": t.name, "intent": t.intent.value, "description": t.description,
             "header_value": t.header_value, "required_fields": t.required_fields,
             "example_prompt": t.example_prompt}
            for t in _INTENTS.list_all()
        ])

    @router.get("/intents/{intent_name}")
    async def get_intent_template(intent_name: str):
        template = _INTENTS.get(intent_name)
        if template is None:
            templates = _INTENTS.find_by_intent(
                next((i for i in __import__("orchestra.code_agent.agent_headers.models", fromlist=["Intent"]).Intent
                      if i.value == intent_name), None)  # type: ignore[union-attr]
            )
            if not templates:
                raise HTTPException(status_code=404, detail="Intent not found")
            template = templates[0]
        builder = _INTENTS.create_builder(template.name)
        return JSONResponse(content={
            "name": template.name, "intent": template.intent.value,
            "description": template.description, "header_value": template.header_value,
            "query_structure": template.query_structure,
            "required_fields": template.required_fields,
            "example_prompt": template.example_prompt,
        })

    # ── Testing Sandbox ────────────────────────────────────────────────

    @router.get("/sandbox/scenarios")
    async def list_scenarios():
        return JSONResponse(content=[
            {"id": s.id, "name": s.name, "description": s.description,
             "intent": s.intent.value if s.intent else "unknown", "tags": s.tags}
            for s in _SANDBOX.list_scenarios()
        ])

    @router.get("/sandbox/scenarios/{scenario_id}")
    async def get_scenario(scenario_id: str):
        scenario = _SANDBOX.get_scenario(scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="Scenario not found")
        return JSONResponse(content={
            "id": scenario.id, "name": scenario.name, "description": scenario.description,
            "intent": scenario.intent.value if scenario.intent else "unknown",
            "input_prompt": scenario.input_prompt, "tags": scenario.tags,
        })

    # ── Governance Monitor ──────────────────────────────────────────────

    @router.get("/governance/report")
    async def governance_report():
        report = _GOV.report()
        return JSONResponse(content={
            "total_calls": report.total_calls,
            "intent_success_rate": report.intent_success_rate,
            "error_count": report.error_count,
            "error_frequency": report.error_frequency,
            "avg_latency_ms": report.avg_latency_ms,
            "p95_latency_ms": report.p95_latency_ms,
            "anomaly_count": report.anomaly_count,
            "governance_violations": report.governance_violations,
        })

    @router.get("/governance/anomalies")
    async def recent_anomalies(limit: int = 20):
        return JSONResponse(content=_GOV.recent_anomalies(limit))

    @router.get("/governance/violations")
    async def recent_violations(limit: int = 20):
        return JSONResponse(content=_GOV.recent_violations(limit))

    app.include_router(router)
