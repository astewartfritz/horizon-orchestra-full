"""FastAPI routes for the Healthcare module."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .billing import (
    generate_claim_from_encounter, lookup_cpt, lookup_icd10,
    search_cpt, search_icd10,
)
from .brain import generate_soap_note, suggest_codes_from_keywords
from .store import (
    create_appointment, create_claim, create_encounter, create_patient,
    delete_patient, get_analytics, get_appointment, get_claim, get_encounter,
    get_patient, init_db, list_appointments, list_claims, list_encounters,
    list_patients, update_appointment_status, update_claim, update_encounter_soap,
    update_patient,
)


def register_healthcare_routes(app: FastAPI) -> None:
    init_db()

    from orchestra.code_agent.ui.handlers.user_dep import optional_user_id

    # ── Patients ──────────────────────────────────────────────────────────────

    @app.get("/api/healthcare/patients")
    async def hc_list_patients(search: str = "", uid: str | None = Depends(optional_user_id)):
        patients = list_patients(search, user_id=uid or "")
        return {"patients": [p.to_dict() for p in patients]}

    @app.post("/api/healthcare/patients")
    async def hc_create_patient(request: Request, uid: str | None = Depends(optional_user_id)):
        data = await request.json()
        try:
            p = create_patient(data, user_id=uid or "")
        except KeyError as e:
            raise HTTPException(400, f"Missing required field: {e}")
        return p.to_dict()

    @app.get("/api/healthcare/patients/{patient_id}")
    async def hc_get_patient(patient_id: str):
        p = get_patient(patient_id)
        if not p:
            raise HTTPException(404, "Patient not found")
        return p.to_dict()

    @app.put("/api/healthcare/patients/{patient_id}")
    async def hc_update_patient(patient_id: str, request: Request):
        data = await request.json()
        p = update_patient(patient_id, data)
        if not p:
            raise HTTPException(404, "Patient not found")
        return p.to_dict()

    @app.delete("/api/healthcare/patients/{patient_id}")
    async def hc_delete_patient(patient_id: str):
        if not delete_patient(patient_id):
            raise HTTPException(404, "Patient not found")
        return {"deleted": patient_id}

    # ── Appointments ──────────────────────────────────────────────────────────

    @app.get("/api/healthcare/appointments")
    async def hc_list_appointments(
        date: str = "", patient_id: str = "", status: str = "",
        uid: str | None = Depends(optional_user_id),
    ):
        appts = list_appointments(date=date, patient_id=patient_id, status=status, user_id=uid or "")
        return {"appointments": [a.to_dict() for a in appts]}

    @app.post("/api/healthcare/appointments")
    async def hc_create_appointment(request: Request, uid: str | None = Depends(optional_user_id)):
        data = await request.json()
        try:
            a = create_appointment(data, user_id=uid or "")
        except KeyError as e:
            raise HTTPException(400, f"Missing required field: {e}")
        return a.to_dict()

    @app.get("/api/healthcare/appointments/{appt_id}")
    async def hc_get_appointment(appt_id: str):
        a = get_appointment(appt_id)
        if not a:
            raise HTTPException(404, "Appointment not found")
        return a.to_dict()

    @app.patch("/api/healthcare/appointments/{appt_id}/status")
    async def hc_update_appt_status(appt_id: str, request: Request):
        data = await request.json()
        a = update_appointment_status(appt_id, data.get("status", ""))
        if not a:
            raise HTTPException(404, "Appointment not found")
        return a.to_dict()

    # ── Encounters ────────────────────────────────────────────────────────────

    @app.get("/api/healthcare/encounters")
    async def hc_list_encounters(patient_id: str = "", uid: str | None = Depends(optional_user_id)):
        encs = list_encounters(patient_id=patient_id, user_id=uid or "")
        return {"encounters": [e.to_dict() for e in encs]}

    @app.post("/api/healthcare/encounters")
    async def hc_create_encounter(request: Request, uid: str | None = Depends(optional_user_id)):
        data = await request.json()
        try:
            e = create_encounter(data, user_id=uid or "")
        except KeyError as err:
            raise HTTPException(400, f"Missing required field: {err}")
        return e.to_dict()

    @app.get("/api/healthcare/encounters/{enc_id}")
    async def hc_get_encounter(enc_id: str):
        e = get_encounter(enc_id)
        if not e:
            raise HTTPException(404, "Encounter not found")
        return e.to_dict()

    @app.put("/api/healthcare/encounters/{enc_id}/soap")
    async def hc_update_soap(enc_id: str, request: Request):
        data = await request.json()
        e = update_encounter_soap(enc_id, data)
        if not e:
            raise HTTPException(404, "Encounter not found")
        return e.to_dict()

    # ── Claims ────────────────────────────────────────────────────────────────

    @app.get("/api/healthcare/claims")
    async def hc_list_claims(
        patient_id: str = "", status: str = "",
        uid: str | None = Depends(optional_user_id),
    ):
        claims = list_claims(patient_id=patient_id, status=status, user_id=uid or "")
        return {"claims": [c.to_dict() for c in claims]}

    @app.post("/api/healthcare/claims")
    async def hc_create_claim(request: Request, uid: str | None = Depends(optional_user_id)):
        data = await request.json()
        try:
            c = create_claim(data, user_id=uid or "")
        except KeyError as err:
            raise HTTPException(400, f"Missing required field: {err}")
        return c.to_dict()

    @app.post("/api/healthcare/claims/from-encounter/{enc_id}")
    async def hc_claim_from_encounter(enc_id: str, uid: str | None = Depends(optional_user_id)):
        enc = get_encounter(enc_id)
        if not enc:
            raise HTTPException(404, "Encounter not found")
        patient = get_patient(enc.patient_id)
        claim_data = generate_claim_from_encounter(
            enc.to_dict(), patient.to_dict() if patient else {}
        )
        c = create_claim(claim_data, user_id=uid or "")
        update_encounter_soap(enc_id, enc.soap.to_dict())
        return c.to_dict()

    @app.get("/api/healthcare/claims/{claim_id}")
    async def hc_get_claim(claim_id: str):
        c = get_claim(claim_id)
        if not c:
            raise HTTPException(404, "Claim not found")
        return c.to_dict()

    @app.put("/api/healthcare/claims/{claim_id}")
    async def hc_update_claim(claim_id: str, request: Request):
        data = await request.json()
        c = update_claim(claim_id, data)
        if not c:
            raise HTTPException(404, "Claim not found")
        return c.to_dict()

    # ── AI Brain — SOAP generation ────────────────────────────────────────────

    @app.post("/api/healthcare/brain/soap")
    async def hc_brain_soap(request: Request):
        data = await request.json()
        raw_notes = data.get("raw_notes", "").strip()
        if not raw_notes:
            raise HTTPException(400, "raw_notes is required")

        patient_id = data.get("patient_id")
        patient_context: dict[str, Any] | None = None
        if patient_id:
            p = get_patient(patient_id)
            if p:
                patient_context = {"age": p.age, "gender": p.gender.value,
                                   "allergies": p.allergies, "medications": p.medications}

        result = await generate_soap_note(
            raw_notes,
            patient_context,
            provider=data.get("provider", "anthropic"),
            model=data.get("model", "claude-opus-4-7"),
            api_key=data.get("api_key", ""),
        )
        return result

    @app.post("/api/healthcare/brain/suggest-codes")
    async def hc_brain_suggest(request: Request):
        data = await request.json()
        text = data.get("text", "")
        return suggest_codes_from_keywords(text)

    # ── Code Lookup ────────────────────────────────────────────────────────────

    @app.get("/api/healthcare/codes/cpt/search")
    async def hc_search_cpt(q: str = "", limit: int = 10):
        return {"results": search_cpt(q, limit)}

    @app.get("/api/healthcare/codes/cpt/{code}")
    async def hc_lookup_cpt(code: str):
        info = lookup_cpt(code)
        if not info:
            raise HTTPException(404, "CPT code not found")
        return {"code": code, **info}

    @app.get("/api/healthcare/codes/icd10/search")
    async def hc_search_icd10(q: str = "", limit: int = 10):
        return {"results": search_icd10(q, limit)}

    @app.get("/api/healthcare/codes/icd10/{code}")
    async def hc_lookup_icd10(code: str):
        info = lookup_icd10(code)
        if not info:
            raise HTTPException(404, "ICD-10 code not found")
        return {"code": code, **info}

    # ── Analytics ─────────────────────────────────────────────────────────────

    @app.get("/api/healthcare/analytics")
    async def hc_analytics():
        return get_analytics()
