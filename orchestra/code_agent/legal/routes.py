from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from orchestra.code_agent.legal import store as st
from orchestra.code_agent.legal.brain import (
    ACTIVITY_CODES, DOCUMENT_TEMPLATES, draft_document, analyze_matter
)


def register_legal_routes(app: FastAPI) -> None:

    # ── Init ─────────────────────────────────────────────────────────────────

    st.init_db()

    from orchestra.code_agent.ui.handlers.user_dep import optional_user_id

    # ── Clients ───────────────────────────────────────────────────────────────

    @app.get("/api/legal/clients")
    async def list_clients(search: str = "", uid: str | None = Depends(optional_user_id)):
        return [vars(c) for c in st.list_clients(search=search, user_id=uid or "")]

    @app.post("/api/legal/clients")
    async def create_client(body: dict, uid: str | None = Depends(optional_user_id)):
        if not body.get("name"):
            raise HTTPException(400, "name required")
        return vars(st.create_client(body, user_id=uid or ""))

    @app.get("/api/legal/clients/{client_id}")
    async def get_client(client_id: str):
        c = st.get_client(client_id)
        if not c:
            raise HTTPException(404, "Client not found")
        return vars(c)

    @app.patch("/api/legal/clients/{client_id}")
    async def update_client(client_id: str, body: dict):
        c = st.update_client(client_id, body)
        if not c:
            raise HTTPException(404, "Client not found")
        return vars(c)

    # ── Matters ───────────────────────────────────────────────────────────────

    @app.get("/api/legal/matters")
    async def list_matters(
        status: str = "", client_id: str = "", search: str = "",
        uid: str | None = Depends(optional_user_id),
    ):
        return [vars(m) for m in st.list_matters(status=status, client_id=client_id, search=search, user_id=uid or "")]

    @app.post("/api/legal/matters")
    async def create_matter(body: dict, uid: str | None = Depends(optional_user_id)):
        if not body.get("client_id") or not body.get("title"):
            raise HTTPException(400, "client_id and title required")
        return vars(st.create_matter(body, user_id=uid or ""))

    @app.get("/api/legal/matters/{matter_id}")
    async def get_matter(matter_id: str):
        m = st.get_matter(matter_id)
        if not m:
            raise HTTPException(404, "Matter not found")
        return vars(m)

    @app.patch("/api/legal/matters/{matter_id}")
    async def update_matter(matter_id: str, body: dict):
        m = st.update_matter(matter_id, body)
        if not m:
            raise HTTPException(404, "Matter not found")
        return vars(m)

    # ── Time Entries ──────────────────────────────────────────────────────────

    @app.get("/api/legal/time")
    async def list_time(matter_id: str = "", billed: str = ""):
        billed_filter = None
        if billed == "true":
            billed_filter = True
        elif billed == "false":
            billed_filter = False
        entries = st.list_time_entries(matter_id=matter_id, billed=billed_filter)
        return [vars(e) for e in entries]

    @app.post("/api/legal/time")
    async def create_time(body: dict):
        if not body.get("matter_id") or body.get("hours") is None or not body.get("description"):
            raise HTTPException(400, "matter_id, hours, and description required")
        return vars(st.create_time_entry(body))

    @app.patch("/api/legal/time/{entry_id}")
    async def update_time(entry_id: str, body: dict):
        e = st.update_time_entry(entry_id, body)
        if not e:
            raise HTTPException(404, "Time entry not found")
        return vars(e)

    @app.delete("/api/legal/time/{entry_id}")
    async def delete_time(entry_id: str):
        ok = st.delete_time_entry(entry_id)
        if not ok:
            raise HTTPException(404, "Time entry not found")
        return {"deleted": True}

    # ── Invoices ──────────────────────────────────────────────────────────────

    @app.get("/api/legal/invoices")
    async def list_invoices(status: str = "", matter_id: str = ""):
        return [vars(i) for i in st.list_invoices(status=status, matter_id=matter_id)]

    @app.post("/api/legal/invoices/from-matter/{matter_id}")
    async def invoice_from_matter(matter_id: str):
        try:
            inv = st.create_invoice_from_matter(matter_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return vars(inv)

    @app.patch("/api/legal/invoices/{invoice_id}")
    async def update_invoice(invoice_id: str, body: dict):
        inv = st.update_invoice(invoice_id, body)
        if not inv:
            raise HTTPException(404, "Invoice not found")
        return vars(inv)

    # ── Trust Ledger ──────────────────────────────────────────────────────────

    @app.get("/api/legal/trust")
    async def list_trust(matter_id: str = ""):
        return [vars(t) for t in st.list_trust_entries(matter_id=matter_id)]

    @app.post("/api/legal/trust")
    async def add_trust(body: dict):
        if not body.get("matter_id") or body.get("amount") is None or not body.get("description"):
            raise HTTPException(400, "matter_id, amount, and description required")
        try:
            return vars(st.add_trust_entry(body))
        except ValueError as e:
            raise HTTPException(400, str(e))

    # ── Analytics ─────────────────────────────────────────────────────────────

    @app.get("/api/legal/analytics")
    async def analytics():
        return st.get_analytics()

    # ── Reference Data ────────────────────────────────────────────────────────

    @app.get("/api/legal/activity-codes")
    async def activity_codes():
        return ACTIVITY_CODES

    @app.get("/api/legal/document-types")
    async def document_types():
        return DOCUMENT_TEMPLATES

    # ── AI Brain ──────────────────────────────────────────────────────────────

    @app.post("/api/legal/brain/draft")
    async def brain_draft(body: dict):
        doc_type = body.get("doc_type", "")
        facts = body.get("facts", "")
        if not doc_type or not facts:
            raise HTTPException(400, "doc_type and facts required")
        try:
            result = await draft_document(
                doc_type=doc_type,
                facts=facts,
                party_a=body.get("party_a", ""),
                party_b=body.get("party_b", ""),
                jurisdiction=body.get("jurisdiction", ""),
                additional_terms=body.get("additional_terms", ""),
                provider=body.get("provider", "anthropic"),
                model=body.get("model", "claude-opus-4-7"),
                api_key=body.get("api_key", ""),
            )
        except Exception as e:
            raise HTTPException(500, str(e))
        return result

    @app.post("/api/legal/brain/analyze")
    async def brain_analyze(body: dict):
        matter_title = body.get("matter_title", "Untitled Matter")
        matter_type = body.get("matter_type", "other")
        facts = body.get("facts", "")
        if not facts:
            raise HTTPException(400, "facts required")
        try:
            result = await analyze_matter(
                matter_title=matter_title,
                matter_type=matter_type,
                facts=facts,
                provider=body.get("provider", "anthropic"),
                model=body.get("model", "claude-opus-4-7"),
                api_key=body.get("api_key", ""),
            )
        except Exception as e:
            raise HTTPException(500, str(e))
        return result
