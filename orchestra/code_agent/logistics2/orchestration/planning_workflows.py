"""Planning workflows — multi-step logistics planning workflows (Temporal/Cadence-style)."""

from __future__ import annotations

from orchestra.code_agent.logistics2.orchestration.workflow_engine import WorkflowEngine, WorkflowStep


def register_planning_workflows(engine: WorkflowEngine) -> None:
    """Register standard logistics planning workflows."""

    # ── Week-end closing workflow ─────────────
    engine.define("week_end_closing", [
        WorkflowStep("validate_shipments", _validate_all_shipments),
        WorkflowStep("calculate_commission", _calculate_commissions),
        WorkflowStep("audit_compliance", _audit_compliance),
        WorkflowStep("generate_report", _generate_weekly_report),
    ])

    # ── Daily dispatch optimization ──────────
    engine.define("daily_dispatch", [
        WorkflowStep("load_pending_shipments", _load_pending),
        WorkflowStep("match_loads_to_trucks", _match_loads),
        WorkflowStep("optimize_routes", _optimize_dispatch_routes),
        WorkflowStep("assign_drivers", _assign_drivers),
        WorkflowStep("notify_dispatchers", _notify_dispatchers),
    ])

    # ── Contract compliance check ────────────
    engine.define("contract_compliance", [
        WorkflowStep("load_contracts", _load_contracts),
        WorkflowStep("validate_rates", _validate_rates),
        WorkflowStep("check_service_levels", _check_service_levels),
        WorkflowStep("report_violations", _report_violations),
    ])


def _validate_all_shipments(ctx):
    shipments = ctx.get("shipments", [])
    return {"validated": len(shipments), "errors": 0}

def _calculate_commissions(ctx):
    revenue = ctx.get("weekly_revenue", 100000)
    return {"total_commission": round(revenue * 0.08, 2)}

def _audit_compliance(ctx):
    return {"compliant": True, "violations": 0}

def _generate_weekly_report(ctx):
    return {"report": "weekly_summary_generated"}

def _load_pending(ctx):
    return {"pending_count": 42}

def _match_loads(ctx):
    return {"matched": 38, "unmatched": 4}

def _optimize_dispatch_routes(ctx):
    return {"routes_optimized": 38, "saved_km": 1200}

def _assign_drivers(ctx):
    return {"assigned": 35, "unassigned": 3}

def _notify_dispatchers(ctx):
    return {"notified": 5}

def _load_contracts(ctx):
    return {"contracts": 15}

def _validate_rates(ctx):
    return {"valid": 14, "violations": 1}

def _check_service_levels(ctx):
    return {"on_time": 0.94}

def _report_violations(ctx):
    return {"reported": 1}
