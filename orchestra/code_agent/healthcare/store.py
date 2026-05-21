"""SQLite persistence layer for Healthcare module."""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    Appointment, AppointmentStatus, Claim, ClaimStatus,
    DiagnosisCode, Encounter, Gender, Patient, ProcedureCode, SOAPNote,
)

DB_PATH = Path.home() / ".orchestra_healthcare.db"


def _now() -> str:
    return datetime.utcnow().isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())[:8].upper()


@contextmanager
def _conn():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            dob TEXT NOT NULL,
            gender TEXT DEFAULT 'unknown',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            address TEXT DEFAULT '',
            city TEXT DEFAULT '',
            state TEXT DEFAULT '',
            zip TEXT DEFAULT '',
            insurance_name TEXT DEFAULT '',
            insurance_id TEXT DEFAULT '',
            insurance_group TEXT DEFAULT '',
            emergency_contact TEXT DEFAULT '',
            allergies TEXT DEFAULT '',
            medications TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS appointments (
            id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            duration_min INTEGER DEFAULT 30,
            reason TEXT DEFAULT '',
            status TEXT DEFAULT 'scheduled',
            provider TEXT DEFAULT '',
            room TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS encounters (
            id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            appointment_id TEXT DEFAULT '',
            date TEXT NOT NULL,
            provider TEXT DEFAULT '',
            subjective TEXT DEFAULT '',
            objective TEXT DEFAULT '',
            assessment TEXT DEFAULT '',
            plan TEXT DEFAULT '',
            icd10_codes TEXT DEFAULT '[]',
            cpt_codes TEXT DEFAULT '[]',
            raw_notes TEXT DEFAULT '',
            claim_id TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            encounter_id TEXT DEFAULT '',
            date_of_service TEXT NOT NULL,
            provider_npi TEXT DEFAULT '',
            provider_name TEXT DEFAULT '',
            diagnosis_codes TEXT DEFAULT '[]',
            procedure_codes TEXT DEFAULT '[]',
            total_charge REAL DEFAULT 0.0,
            allowed_amount REAL DEFAULT 0.0,
            paid_amount REAL DEFAULT 0.0,
            patient_responsibility REAL DEFAULT 0.0,
            insurance_name TEXT DEFAULT '',
            insurance_id TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            denial_reason TEXT DEFAULT '',
            submitted_at TEXT DEFAULT '',
            paid_at TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        """)


# ── Patients ──────────────────────────────────────────────────────────────────

def _row_to_patient(row: sqlite3.Row) -> Patient:
    return Patient(
        id=row["id"], first_name=row["first_name"], last_name=row["last_name"],
        dob=row["dob"], gender=Gender(row["gender"]),
        phone=row["phone"], email=row["email"],
        address=row["address"], city=row["city"], state=row["state"], zip=row["zip"],
        insurance_name=row["insurance_name"], insurance_id=row["insurance_id"],
        insurance_group=row["insurance_group"],
        emergency_contact=row["emergency_contact"],
        allergies=row["allergies"], medications=row["medications"],
        notes=row["notes"], created_at=row["created_at"],
    )


def create_patient(data: dict[str, Any]) -> Patient:
    p = Patient(
        id=_new_id(),
        first_name=data["first_name"], last_name=data["last_name"],
        dob=data["dob"], gender=Gender(data.get("gender", "unknown")),
        phone=data.get("phone", ""), email=data.get("email", ""),
        address=data.get("address", ""), city=data.get("city", ""),
        state=data.get("state", ""), zip=data.get("zip", ""),
        insurance_name=data.get("insurance_name", ""),
        insurance_id=data.get("insurance_id", ""),
        insurance_group=data.get("insurance_group", ""),
        emergency_contact=data.get("emergency_contact", ""),
        allergies=data.get("allergies", ""),
        medications=data.get("medications", ""),
        notes=data.get("notes", ""),
        created_at=_now(),
    )
    with _conn() as con:
        con.execute(
            """INSERT INTO patients VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (p.id, p.first_name, p.last_name, p.dob, p.gender.value,
             p.phone, p.email, p.address, p.city, p.state, p.zip,
             p.insurance_name, p.insurance_id, p.insurance_group,
             p.emergency_contact, p.allergies, p.medications, p.notes, p.created_at),
        )
    return p


def get_patient(patient_id: str) -> Patient | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
    return _row_to_patient(row) if row else None


def list_patients(search: str = "") -> list[Patient]:
    with _conn() as con:
        if search:
            q = f"%{search}%"
            rows = con.execute(
                "SELECT * FROM patients WHERE first_name LIKE ? OR last_name LIKE ? OR phone LIKE ? OR email LIKE ? ORDER BY last_name, first_name",
                (q, q, q, q),
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM patients ORDER BY last_name, first_name").fetchall()
    return [_row_to_patient(r) for r in rows]


def update_patient(patient_id: str, data: dict[str, Any]) -> Patient | None:
    p = get_patient(patient_id)
    if not p:
        return None
    for k, v in data.items():
        if hasattr(p, k) and k not in ("id", "created_at"):
            if k == "gender":
                v = Gender(v)
            setattr(p, k, v)
    with _conn() as con:
        con.execute(
            """UPDATE patients SET first_name=?,last_name=?,dob=?,gender=?,phone=?,email=?,
            address=?,city=?,state=?,zip=?,insurance_name=?,insurance_id=?,insurance_group=?,
            emergency_contact=?,allergies=?,medications=?,notes=? WHERE id=?""",
            (p.first_name, p.last_name, p.dob, p.gender.value, p.phone, p.email,
             p.address, p.city, p.state, p.zip, p.insurance_name, p.insurance_id,
             p.insurance_group, p.emergency_contact, p.allergies, p.medications,
             p.notes, patient_id),
        )
    return p


def delete_patient(patient_id: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM patients WHERE id=?", (patient_id,))
    return cur.rowcount > 0


# ── Appointments ──────────────────────────────────────────────────────────────

def _row_to_appt(row: sqlite3.Row) -> Appointment:
    return Appointment(
        id=row["id"], patient_id=row["patient_id"], patient_name=row["patient_name"],
        date=row["date"], time=row["time"], duration_min=row["duration_min"],
        reason=row["reason"], status=AppointmentStatus(row["status"]),
        provider=row["provider"], room=row["room"], notes=row["notes"],
        created_at=row["created_at"],
    )


def create_appointment(data: dict[str, Any]) -> Appointment:
    patient = get_patient(data["patient_id"])
    a = Appointment(
        id=_new_id(),
        patient_id=data["patient_id"],
        patient_name=patient.full_name if patient else data.get("patient_name", ""),
        date=data["date"], time=data["time"],
        duration_min=data.get("duration_min", 30),
        reason=data.get("reason", ""),
        status=AppointmentStatus(data.get("status", "scheduled")),
        provider=data.get("provider", ""),
        room=data.get("room", ""),
        notes=data.get("notes", ""),
        created_at=_now(),
    )
    with _conn() as con:
        con.execute(
            "INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (a.id, a.patient_id, a.patient_name, a.date, a.time, a.duration_min,
             a.reason, a.status.value, a.provider, a.room, a.notes, a.created_at),
        )
    return a


def get_appointment(appt_id: str) -> Appointment | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
    return _row_to_appt(row) if row else None


def list_appointments(date: str = "", patient_id: str = "", status: str = "") -> list[Appointment]:
    clauses, params = [], []
    if date:
        clauses.append("date=?"); params.append(date)
    if patient_id:
        clauses.append("patient_id=?"); params.append(patient_id)
    if status:
        clauses.append("status=?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as con:
        rows = con.execute(f"SELECT * FROM appointments {where} ORDER BY date, time", params).fetchall()
    return [_row_to_appt(r) for r in rows]


def update_appointment_status(appt_id: str, status: str) -> Appointment | None:
    with _conn() as con:
        con.execute("UPDATE appointments SET status=? WHERE id=?", (status, appt_id))
    return get_appointment(appt_id)


# ── Encounters ────────────────────────────────────────────────────────────────

import json as _json


def _row_to_encounter(row: sqlite3.Row) -> Encounter:
    icd10 = [DiagnosisCode(**c) for c in _json.loads(row["icd10_codes"] or "[]")]
    cpt = [ProcedureCode(**c) for c in _json.loads(row["cpt_codes"] or "[]")]
    soap = SOAPNote(
        subjective=row["subjective"], objective=row["objective"],
        assessment=row["assessment"], plan=row["plan"],
        icd10_codes=icd10, cpt_codes=cpt, raw_notes=row["raw_notes"],
    )
    return Encounter(
        id=row["id"], patient_id=row["patient_id"], patient_name=row["patient_name"],
        appointment_id=row["appointment_id"], date=row["date"], provider=row["provider"],
        soap=soap, claim_id=row["claim_id"], created_at=row["created_at"],
    )


def create_encounter(data: dict[str, Any]) -> Encounter:
    patient = get_patient(data["patient_id"])
    soap_data = data.get("soap", {})
    icd10 = [DiagnosisCode(**c) for c in soap_data.get("icd10_codes", [])]
    cpt = [ProcedureCode(**c) for c in soap_data.get("cpt_codes", [])]
    soap = SOAPNote(
        subjective=soap_data.get("subjective", ""),
        objective=soap_data.get("objective", ""),
        assessment=soap_data.get("assessment", ""),
        plan=soap_data.get("plan", ""),
        icd10_codes=icd10, cpt_codes=cpt,
        raw_notes=soap_data.get("raw_notes", ""),
    )
    e = Encounter(
        id=_new_id(),
        patient_id=data["patient_id"],
        patient_name=patient.full_name if patient else data.get("patient_name", ""),
        appointment_id=data.get("appointment_id", ""),
        date=data.get("date", _now()[:10]),
        provider=data.get("provider", ""),
        soap=soap,
        created_at=_now(),
    )
    with _conn() as con:
        con.execute(
            "INSERT INTO encounters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.id, e.patient_id, e.patient_name, e.appointment_id, e.date, e.provider,
             soap.subjective, soap.objective, soap.assessment, soap.plan,
             _json.dumps([c.to_dict() for c in icd10]),
             _json.dumps([c.to_dict() for c in cpt]),
             soap.raw_notes, e.claim_id, e.created_at),
        )
    return e


def get_encounter(enc_id: str) -> Encounter | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM encounters WHERE id=?", (enc_id,)).fetchone()
    return _row_to_encounter(row) if row else None


def update_encounter_soap(enc_id: str, soap_data: dict[str, Any]) -> Encounter | None:
    enc = get_encounter(enc_id)
    if not enc:
        return None
    icd10 = [DiagnosisCode(**c) for c in soap_data.get("icd10_codes", [])]
    cpt = [ProcedureCode(**c) for c in soap_data.get("cpt_codes", [])]
    with _conn() as con:
        con.execute(
            """UPDATE encounters SET subjective=?,objective=?,assessment=?,plan=?,
            icd10_codes=?,cpt_codes=?,raw_notes=? WHERE id=?""",
            (soap_data.get("subjective", enc.soap.subjective),
             soap_data.get("objective", enc.soap.objective),
             soap_data.get("assessment", enc.soap.assessment),
             soap_data.get("plan", enc.soap.plan),
             _json.dumps([c.to_dict() for c in icd10]),
             _json.dumps([c.to_dict() for c in cpt]),
             soap_data.get("raw_notes", enc.soap.raw_notes),
             enc_id),
        )
    return get_encounter(enc_id)


def list_encounters(patient_id: str = "") -> list[Encounter]:
    with _conn() as con:
        if patient_id:
            rows = con.execute(
                "SELECT * FROM encounters WHERE patient_id=? ORDER BY date DESC", (patient_id,)
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM encounters ORDER BY date DESC").fetchall()
    return [_row_to_encounter(r) for r in rows]


# ── Claims ────────────────────────────────────────────────────────────────────

def _row_to_claim(row: sqlite3.Row) -> Claim:
    return Claim(
        id=row["id"], patient_id=row["patient_id"], patient_name=row["patient_name"],
        encounter_id=row["encounter_id"], date_of_service=row["date_of_service"],
        provider_npi=row["provider_npi"], provider_name=row["provider_name"],
        diagnosis_codes=_json.loads(row["diagnosis_codes"] or "[]"),
        procedure_codes=_json.loads(row["procedure_codes"] or "[]"),
        total_charge=row["total_charge"], allowed_amount=row["allowed_amount"],
        paid_amount=row["paid_amount"], patient_responsibility=row["patient_responsibility"],
        insurance_name=row["insurance_name"], insurance_id=row["insurance_id"],
        status=ClaimStatus(row["status"]), denial_reason=row["denial_reason"],
        submitted_at=row["submitted_at"], paid_at=row["paid_at"], created_at=row["created_at"],
    )


def create_claim(data: dict[str, Any]) -> Claim:
    patient = get_patient(data["patient_id"])
    c = Claim(
        id=_new_id(),
        patient_id=data["patient_id"],
        patient_name=patient.full_name if patient else data.get("patient_name", ""),
        encounter_id=data.get("encounter_id", ""),
        date_of_service=data.get("date_of_service", _now()[:10]),
        provider_npi=data.get("provider_npi", ""),
        provider_name=data.get("provider_name", ""),
        diagnosis_codes=data.get("diagnosis_codes", []),
        procedure_codes=data.get("procedure_codes", []),
        total_charge=data.get("total_charge", 0.0),
        insurance_name=patient.insurance_name if patient else data.get("insurance_name", ""),
        insurance_id=patient.insurance_id if patient else data.get("insurance_id", ""),
        status=ClaimStatus.DRAFT,
        created_at=_now(),
    )
    with _conn() as con:
        con.execute(
            "INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c.id, c.patient_id, c.patient_name, c.encounter_id, c.date_of_service,
             c.provider_npi, c.provider_name,
             _json.dumps(c.diagnosis_codes), _json.dumps(c.procedure_codes),
             c.total_charge, c.allowed_amount, c.paid_amount, c.patient_responsibility,
             c.insurance_name, c.insurance_id, c.status.value, c.denial_reason,
             c.submitted_at, c.paid_at, c.created_at),
        )
    return c


def get_claim(claim_id: str) -> Claim | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    return _row_to_claim(row) if row else None


def list_claims(patient_id: str = "", status: str = "") -> list[Claim]:
    clauses, params = [], []
    if patient_id:
        clauses.append("patient_id=?"); params.append(patient_id)
    if status:
        clauses.append("status=?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as con:
        rows = con.execute(f"SELECT * FROM claims {where} ORDER BY date_of_service DESC", params).fetchall()
    return [_row_to_claim(r) for r in rows]


def update_claim(claim_id: str, data: dict[str, Any]) -> Claim | None:
    c = get_claim(claim_id)
    if not c:
        return None
    allowed_fields = {
        "status", "denial_reason", "allowed_amount", "paid_amount",
        "patient_responsibility", "submitted_at", "paid_at",
        "provider_npi", "provider_name", "diagnosis_codes", "procedure_codes", "total_charge",
    }
    for k, v in data.items():
        if k in allowed_fields:
            if k == "status":
                v = ClaimStatus(v)
            setattr(c, k, v)
    with _conn() as con:
        con.execute(
            """UPDATE claims SET status=?,denial_reason=?,allowed_amount=?,paid_amount=?,
            patient_responsibility=?,submitted_at=?,paid_at=?,provider_npi=?,provider_name=?,
            diagnosis_codes=?,procedure_codes=?,total_charge=? WHERE id=?""",
            (c.status.value, c.denial_reason, c.allowed_amount, c.paid_amount,
             c.patient_responsibility, c.submitted_at, c.paid_at, c.provider_npi,
             c.provider_name, _json.dumps(c.diagnosis_codes), _json.dumps(c.procedure_codes),
             c.total_charge, claim_id),
        )
    return c


# ── Analytics ─────────────────────────────────────────────────────────────────

def get_analytics() -> dict[str, Any]:
    with _conn() as con:
        total_patients = con.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        today = datetime.utcnow().date().isoformat()
        todays_appts = con.execute(
            "SELECT COUNT(*) FROM appointments WHERE date=?", (today,)
        ).fetchone()[0]
        pending_claims = con.execute(
            "SELECT COUNT(*), SUM(total_charge) FROM claims WHERE status IN ('draft','submitted','pending')"
        ).fetchone()
        revenue_this_month = con.execute(
            "SELECT SUM(paid_amount) FROM claims WHERE status='paid' AND paid_at LIKE ?",
            (f"{today[:7]}%",),
        ).fetchone()[0] or 0.0
        ar_total = con.execute(
            "SELECT SUM(total_charge - paid_amount) FROM claims WHERE status NOT IN ('paid','denied')"
        ).fetchone()[0] or 0.0
        recent_claims = con.execute(
            "SELECT * FROM claims ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    return {
        "total_patients": total_patients,
        "todays_appointments": todays_appts,
        "pending_claims_count": pending_claims[0],
        "pending_claims_value": round(pending_claims[1] or 0.0, 2),
        "revenue_this_month": round(revenue_this_month, 2),
        "ar_total": round(ar_total, 2),
        "recent_claims": [_row_to_claim(r).to_dict() for r in recent_claims],
    }
