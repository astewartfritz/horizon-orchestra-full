"""Healthcare data models for Orchestra Health."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNKNOWN = "unknown"


class AppointmentStatus(str, Enum):
    SCHEDULED = "scheduled"
    CHECKED_IN = "checked_in"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class ClaimStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING = "pending"
    PAID = "paid"
    DENIED = "denied"
    PARTIAL = "partial"
    APPEALED = "appealed"


@dataclass
class Patient:
    id: str
    first_name: str
    last_name: str
    dob: str               # YYYY-MM-DD
    gender: Gender = Gender.UNKNOWN
    phone: str = ""
    email: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    insurance_name: str = ""
    insurance_id: str = ""
    insurance_group: str = ""
    emergency_contact: str = ""
    allergies: str = ""
    medications: str = ""
    notes: str = ""
    created_at: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self) -> int:
        try:
            born = date.fromisoformat(self.dob)
            today = date.today()
            return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        except Exception:
            return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "first_name": self.first_name, "last_name": self.last_name,
            "full_name": self.full_name, "dob": self.dob, "age": self.age,
            "gender": self.gender.value, "phone": self.phone, "email": self.email,
            "address": self.address, "city": self.city, "state": self.state, "zip": self.zip,
            "insurance_name": self.insurance_name, "insurance_id": self.insurance_id,
            "insurance_group": self.insurance_group, "emergency_contact": self.emergency_contact,
            "allergies": self.allergies, "medications": self.medications,
            "notes": self.notes, "created_at": self.created_at,
        }


@dataclass
class Appointment:
    id: str
    patient_id: str
    patient_name: str
    date: str          # YYYY-MM-DD
    time: str          # HH:MM
    duration_min: int = 30
    reason: str = ""
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
    provider: str = ""
    room: str = ""
    notes: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "patient_id": self.patient_id, "patient_name": self.patient_name,
            "date": self.date, "time": self.time, "duration_min": self.duration_min,
            "reason": self.reason, "status": self.status.value, "provider": self.provider,
            "room": self.room, "notes": self.notes, "created_at": self.created_at,
        }


@dataclass
class DiagnosisCode:
    code: str      # ICD-10 e.g. "E11.9"
    description: str
    category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "description": self.description, "category": self.category}


@dataclass
class ProcedureCode:
    code: str      # CPT e.g. "99213"
    description: str
    fee: float = 0.0
    rvu: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "description": self.description,
                "fee": self.fee, "rvu": self.rvu}


@dataclass
class SOAPNote:
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""
    icd10_codes: list[DiagnosisCode] = field(default_factory=list)
    cpt_codes: list[ProcedureCode] = field(default_factory=list)
    raw_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "subjective": self.subjective, "objective": self.objective,
            "assessment": self.assessment, "plan": self.plan,
            "icd10_codes": [c.to_dict() for c in self.icd10_codes],
            "cpt_codes": [c.to_dict() for c in self.cpt_codes],
            "raw_notes": self.raw_notes,
        }


@dataclass
class Encounter:
    id: str
    patient_id: str
    patient_name: str
    appointment_id: str = ""
    date: str = ""
    provider: str = ""
    soap: SOAPNote = field(default_factory=SOAPNote)
    claim_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "patient_id": self.patient_id, "patient_name": self.patient_name,
            "appointment_id": self.appointment_id, "date": self.date,
            "provider": self.provider, "soap": self.soap.to_dict(),
            "claim_id": self.claim_id, "created_at": self.created_at,
        }


@dataclass
class Claim:
    id: str
    patient_id: str
    patient_name: str
    encounter_id: str = ""
    date_of_service: str = ""
    provider_npi: str = ""
    provider_name: str = ""
    diagnosis_codes: list[str] = field(default_factory=list)
    procedure_codes: list[dict[str, Any]] = field(default_factory=list)
    total_charge: float = 0.0
    allowed_amount: float = 0.0
    paid_amount: float = 0.0
    patient_responsibility: float = 0.0
    insurance_name: str = ""
    insurance_id: str = ""
    status: ClaimStatus = ClaimStatus.DRAFT
    denial_reason: str = ""
    submitted_at: str = ""
    paid_at: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "patient_id": self.patient_id, "patient_name": self.patient_name,
            "encounter_id": self.encounter_id, "date_of_service": self.date_of_service,
            "provider_npi": self.provider_npi, "provider_name": self.provider_name,
            "diagnosis_codes": self.diagnosis_codes, "procedure_codes": self.procedure_codes,
            "total_charge": round(self.total_charge, 2),
            "allowed_amount": round(self.allowed_amount, 2),
            "paid_amount": round(self.paid_amount, 2),
            "patient_responsibility": round(self.patient_responsibility, 2),
            "insurance_name": self.insurance_name, "insurance_id": self.insurance_id,
            "status": self.status.value, "denial_reason": self.denial_reason,
            "submitted_at": self.submitted_at, "paid_at": self.paid_at,
            "created_at": self.created_at,
        }
