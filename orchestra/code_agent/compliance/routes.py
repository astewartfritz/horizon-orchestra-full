"""Compliance API — break-glass, lifecycle, and posture reports."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from orchestra.code_agent.rbac.deps import require_perm
from orchestra.code_agent.rbac.roles import Perm


def register_compliance_routes(app: FastAPI) -> None:
    from orchestra.code_agent.compliance import lifecycle, breakglass
    from orchestra.code_agent.compliance.reports import hipaa_report, sox_report, gdpr_report, combined_report
    from orchestra.code_agent.compliance import breach_notification, dpo, hipaa_contingency

    lifecycle.init_db()
    breakglass.init_db()
    breach_notification.init_db()
    dpo.init_db()
    hipaa_contingency.init_db()

    # ── Compliance Reports ────────────────────────────────────────────────────

    @app.get("/api/compliance/report/hipaa")
    async def report_hipaa(_uid=Depends(require_perm(Perm.COMPLIANCE_REPORT))):
        return hipaa_report()

    @app.get("/api/compliance/report/sox")
    async def report_sox(_uid=Depends(require_perm(Perm.COMPLIANCE_REPORT))):
        return sox_report()

    @app.get("/api/compliance/report/gdpr")
    async def report_gdpr(_uid=Depends(require_perm(Perm.COMPLIANCE_REPORT))):
        return gdpr_report()

    @app.get("/api/compliance/report")
    async def report_combined(_uid=Depends(require_perm(Perm.COMPLIANCE_REPORT))):
        """Combined HIPAA + SOX + GDPR posture with overall score and top gaps."""
        return combined_report()

    # ── Break-Glass ───────────────────────────────────────────────────────────

    @app.post("/api/compliance/break-glass")
    async def initiate_break_glass(body: dict, request: Request):
        """
        Initiate emergency access to a protected resource.

        Required: initiator_user_id, resource_type, resource_id, justification
        Optional: initiator_name, initiator_role, resource_description, ttl_seconds
        """
        required = ("initiator_user_id", "resource_type", "resource_id", "justification")
        missing = [k for k in required if not body.get(k)]
        if missing:
            raise HTTPException(400, f"Missing required fields: {missing}")

        try:
            event = breakglass.initiate(
                initiator_user_id=body["initiator_user_id"],
                resource_type=body["resource_type"],
                resource_id=body["resource_id"],
                justification=body["justification"],
                initiator_name=body.get("initiator_name", ""),
                initiator_role=body.get("initiator_role", ""),
                resource_description=body.get("resource_description", ""),
                ttl_seconds=int(body.get("ttl_seconds", 4 * 3600)),
                ip_address=request.client.host if request.client else "",
            )
        except ValueError as e:
            raise HTTPException(400, str(e))

        return asdict(event)

    @app.get("/api/compliance/break-glass")
    async def list_break_glass_events(
        status: str = Query("", description="active | expired | revoked | reviewed"),
        resource_type: str = Query(""),
        initiator_user_id: str = Query(""),
        limit: int = Query(50, ge=1, le=200),
        _uid=Depends(require_perm(Perm.AUDIT_READ)),
    ):
        events = breakglass.list_events(
            status=status, resource_type=resource_type,
            initiator_user_id=initiator_user_id, limit=limit,
        )
        return [asdict(e) for e in events]

    @app.post("/api/compliance/break-glass/{event_id}/review")
    async def review_break_glass(
        event_id: str,
        body: dict,
        _uid=Depends(require_perm(Perm.AUDIT_READ)),
    ):
        event = breakglass.review(
            event_id,
            reviewer_user_id=body.get("reviewer_user_id", ""),
            notes=body.get("notes", ""),
        )
        if not event:
            raise HTTPException(404, "Break-glass event not found")
        return asdict(event)

    @app.post("/api/compliance/break-glass/{event_id}/revoke")
    async def revoke_break_glass(
        event_id: str,
        _uid=Depends(require_perm(Perm.AUDIT_READ)),
    ):
        event = breakglass.revoke(event_id)
        if not event:
            raise HTTPException(404, "Break-glass event not found")
        return asdict(event)

    @app.get("/api/compliance/break-glass/check")
    async def check_break_glass_access(
        user_id: str = Query(...),
        resource_type: str = Query(...),
        resource_id: str = Query(...),
    ):
        return {
            "has_active_access": breakglass.is_active(user_id, resource_type, resource_id),
        }

    # ── Data Lifecycle ────────────────────────────────────────────────────────

    @app.get("/api/compliance/lifecycle/policies")
    async def retention_policies():
        return lifecycle.list_policies()

    @app.get("/api/compliance/lifecycle/policies/{resource_type}")
    async def retention_policy(resource_type: str):
        return lifecycle.get_retention_schedule(resource_type)

    @app.get("/api/compliance/lifecycle/holds")
    async def list_holds(
        status: str = Query("active"),
        resource_type: str = Query(""),
        _uid=Depends(require_perm(Perm.LIFECYCLE_MANAGE)),
    ):
        holds = lifecycle.list_holds(status=status, resource_type=resource_type)
        return [asdict(h) for h in holds]

    @app.post("/api/compliance/lifecycle/holds")
    async def place_hold(
        body: dict,
        _uid=Depends(require_perm(Perm.LIFECYCLE_MANAGE)),
    ):
        required = ("resource_type", "resource_id", "hold_reason")
        missing = [k for k in required if not body.get(k)]
        if missing:
            raise HTTPException(400, f"Missing: {missing}")
        hold = lifecycle.place_hold(
            resource_type=body["resource_type"],
            resource_id=body["resource_id"],
            hold_reason=body["hold_reason"],
            held_by=body.get("held_by", ""),
            held_by_name=body.get("held_by_name", ""),
            metadata=body.get("metadata"),
        )
        return asdict(hold)

    @app.post("/api/compliance/lifecycle/holds/{hold_id}/release")
    async def release_hold(
        hold_id: str,
        _uid=Depends(require_perm(Perm.LIFECYCLE_MANAGE)),
    ):
        hold = lifecycle.release_hold(hold_id)
        if not hold:
            raise HTTPException(404, "Hold not found")
        return asdict(hold)

    @app.post("/api/compliance/lifecycle/deletion-requests")
    async def request_deletion(
        body: dict,
        _uid=Depends(require_perm(Perm.LIFECYCLE_MANAGE)),
    ):
        required = ("resource_type", "resource_id", "requester_user_id")
        missing = [k for k in required if not body.get(k)]
        if missing:
            raise HTTPException(400, f"Missing: {missing}")
        req = lifecycle.request_deletion(
            resource_type=body["resource_type"],
            resource_id=body["resource_id"],
            requester_user_id=body["requester_user_id"],
            request_type=body.get("request_type", "gdpr_erasure"),
            delay_days=int(body.get("delay_days", 30)),
            notes=body.get("notes", ""),
        )
        return asdict(req)

    @app.get("/api/compliance/lifecycle/deletion-requests")
    async def list_deletion_requests(
        status: str = Query(""),
        resource_type: str = Query(""),
        _uid=Depends(require_perm(Perm.LIFECYCLE_MANAGE)),
    ):
        reqs = lifecycle.list_deletion_requests(status=status, resource_type=resource_type)
        return [asdict(r) for r in reqs]

    @app.get("/api/compliance/lifecycle/check/{resource_type}/{resource_id}")
    async def check_on_hold(resource_type: str, resource_id: str):
        return {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "on_hold": lifecycle.is_on_hold(resource_type, resource_id),
            "retention": lifecycle.get_retention_schedule(resource_type),
        }

    # ── GDPR Art. 33 Breach Notification ─────────────────────────────────────

    @app.post("/api/compliance/breaches", status_code=201)
    async def create_breach(body: dict, _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT))):
        required = ("org_id", "title", "discovered_at")
        missing = [k for k in required if not body.get(k)]
        if missing:
            raise HTTPException(400, f"Missing: {missing}")
        b = breach_notification.create_breach(
            org_id=body["org_id"],
            title=body["title"],
            discovered_at=float(body["discovered_at"]),
            breach_type=body.get("breach_type", "other"),
            data_subjects_count=int(body.get("data_subjects_count", 0)),
            records_count=int(body.get("records_count", 0)),
            categories=body.get("categories", []),
            likely_consequences=body.get("likely_consequences", ""),
            measures_taken=body.get("measures_taken", ""),
            reporter_user_id=str(_uid),
        )
        return asdict(b)

    @app.get("/api/compliance/breaches")
    async def list_breaches(
        org_id: str = Query(...),
        status: str = Query(""),
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        return [asdict(b) for b in breach_notification.list_breaches(org_id, status=status)]

    @app.get("/api/compliance/breaches/overdue")
    async def overdue_breaches(
        org_id: str = Query(""),
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        return [asdict(b) for b in breach_notification.overdue_breaches(org_id or None)]

    @app.patch("/api/compliance/breaches/{breach_id}")
    async def update_breach(
        breach_id: str,
        body: dict,
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        org_id = body.pop("org_id", "")
        if not org_id:
            raise HTTPException(400, "org_id required in body")
        b = breach_notification.update_breach(breach_id, org_id, **body)
        if not b:
            raise HTTPException(404, "Breach not found")
        return asdict(b)

    @app.post("/api/compliance/breaches/{breach_id}/notify")
    async def notify_breach_authority(
        breach_id: str,
        body: dict,
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        org_id = body.get("org_id", "")
        if not org_id:
            raise HTTPException(400, "org_id required")
        b = breach_notification.notify_authority(breach_id, org_id)
        if not b:
            raise HTTPException(404, "Draft breach not found")
        return asdict(b)

    @app.post("/api/compliance/breaches/{breach_id}/close")
    async def close_breach(
        breach_id: str,
        body: dict,
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        org_id = body.get("org_id", "")
        b = breach_notification.close_breach(breach_id, org_id)
        if not b:
            raise HTTPException(404, "Breach not found")
        return asdict(b)

    # ── DPO Designation ───────────────────────────────────────────────────────

    @app.put("/api/compliance/dpo/{org_id}")
    async def upsert_dpo(
        org_id: str,
        body: dict,
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        name = (body.get("name") or "").strip()
        email = (body.get("email") or "").strip()
        if not name or not email:
            raise HTTPException(400, "name and email are required")
        record = dpo.upsert_dpo(
            org_id=org_id,
            name=name,
            email=email,
            phone=body.get("phone", ""),
            organization=body.get("organization", ""),
            is_external=bool(body.get("is_external", False)),
            designated_at=body.get("designated_at"),
            designation_expires_at=body.get("designation_expires_at"),
            published_to_authority=bool(body.get("published_to_authority", False)),
            notes=body.get("notes", ""),
            created_by=str(_uid),
        )
        return asdict(record)

    @app.get("/api/compliance/dpo/{org_id}")
    async def get_dpo(org_id: str, _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT))):
        record = dpo.get_dpo(org_id)
        if not record:
            raise HTTPException(404, "No DPO designated for this org")
        return asdict(record)

    @app.delete("/api/compliance/dpo/{org_id}", status_code=204)
    async def delete_dpo(org_id: str, _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT))):
        if not dpo.delete_dpo(org_id):
            raise HTTPException(404, "No DPO record found")

    # ── HIPAA Contingency Plans ───────────────────────────────────────────────

    @app.put("/api/compliance/hipaa/contingency/{org_id}/{plan_type}")
    async def upsert_contingency_plan(
        org_id: str,
        plan_type: str,
        body: dict,
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        try:
            plan = hipaa_contingency.upsert_plan(
                org_id=org_id,
                plan_type=plan_type,
                title=body.get("title", plan_type.replace("_", " ").title()),
                description=body.get("description", ""),
                procedures=body.get("procedures", []),
                responsible_party=body.get("responsible_party", ""),
                review_frequency_days=int(body.get("review_frequency_days", 365)),
                status=body.get("status", "draft"),
                created_by=str(_uid),
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return asdict(plan)

    @app.get("/api/compliance/hipaa/contingency/{org_id}")
    async def list_contingency_plans(
        org_id: str,
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        return [asdict(p) for p in hipaa_contingency.list_plans(org_id)]

    @app.get("/api/compliance/hipaa/contingency/{org_id}/posture")
    async def contingency_posture(
        org_id: str,
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        return hipaa_contingency.contingency_posture(org_id)

    @app.post("/api/compliance/hipaa/contingency/{org_id}/{plan_type}/review")
    async def mark_plan_reviewed(
        org_id: str,
        plan_type: str,
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        plan = hipaa_contingency.mark_reviewed(org_id, plan_type, reviewer=str(_uid))
        if not plan:
            raise HTTPException(404, "Plan not found")
        return asdict(plan)

    @app.post("/api/compliance/hipaa/contingency/{org_id}/{plan_type}/test")
    async def add_contingency_test(
        org_id: str,
        plan_type: str,
        body: dict,
        _uid=Depends(require_perm(Perm.COMPLIANCE_REPORT)),
    ):
        result = hipaa_contingency.add_test_result(
            org_id=org_id,
            plan_type=plan_type,
            test_type=body.get("test_type", "tabletop"),
            tested_by=body.get("tested_by", str(_uid)),
            outcome=body.get("outcome", "partial"),
            findings=body.get("findings", ""),
            corrective_actions=body.get("corrective_actions", ""),
            next_test_days=int(body.get("next_test_days", 365)),
        )
        if not result:
            raise HTTPException(404, "Plan not found")
        return asdict(result)
