"""
ShiftScribeAgent — AI-powered nursing documentation.

Clinical evidence:
- Nurses spend 19–35% of shift documenting in EHR (AHRQ ENDburden, R01 HS028454)
  https://digital.ahrq.gov/ahrq-funded-projects/essential-nurse-documentation-studying-ehr-burden-during-covid-19-endburden
- Average 162 min/12-hr shift in EHR; 45% perceived as duplicative (PMID 35668677)
  https://pmc.ncbi.nlm.nih.gov/articles/PMC9300261/
- >60% of nurses rate Flowsheets & Care Plans burdensome (PMID 39259920)
  https://pmc.ncbi.nlm.nih.gov/articles/PMC11491602/
- High EHR burden crowds out HIE and CDS use (Holmgren 2024, Health Affairs)
  https://www.healthaffairs.org/doi/full/10.1377/hlthaff.2024.00398
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# --- Guardian integration (graceful fallback) ---
try:
    from orchestra.guardian.beyond_guardrails import BeyondGuardrails
    from orchestra.guardian.audit_ledger import AuditLedger
    _guardrails = BeyondGuardrails()
    _ledger = AuditLedger()
except ImportError:
    _guardrails = None
    _ledger = None

# --- HIPAA integration ---
try:
    from orchestra.compliance.hipaa import HIPAAComplianceManager
    _hipaa = HIPAAComplianceManager()
except ImportError:
    _hipaa = None


class NoteType(Enum):
    SOAP = "soap"
    NARRATIVE = "narrative"
    FOCUSED = "focused"
    DISCHARGE = "discharge"
    CARE_PLAN = "care_plan"
    INCIDENT = "incident"


@dataclass
class NursingNote:
    patient_id: str
    nurse_id: str
    note_type: NoteType
    content: str
    fhir_bundle: Optional[dict] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    shift: str = ""
    unit: str = ""
    word_count: int = 0
    draft: bool = True
    evidence_citations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "nurse_id": self.nurse_id,
            "note_type": self.note_type.value,
            "content": self.content,
            "fhir_bundle": self.fhir_bundle,
            "created_at": self.created_at.isoformat(),
            "shift": self.shift,
            "unit": self.unit,
            "word_count": self.word_count,
            "draft": self.draft,
        }

    def to_fhir_composition(self) -> dict:
        """Convert to FHIR R4 Composition resource."""
        return {
            "resourceType": "Composition",
            "id": str(uuid.uuid4()),
            "status": "preliminary" if self.draft else "final",
            "type": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "34108-1",
                    "display": "Outpatient Note"
                }]
            },
            "subject": {"reference": f"Patient/{self.patient_id}"},
            "date": self.created_at.isoformat(),
            "author": [{"reference": f"Practitioner/{self.nurse_id}"}],
            "title": f"Nursing {self.note_type.value.replace('_', ' ').title()} Note",
            "section": [{
                "title": self.note_type.value.upper(),
                "text": {
                    "status": "generated",
                    "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>{self.content}</div>"
                }
            }]
        }


@dataclass
class SOAPNote:
    subjective: str
    objective: str
    assessment: str
    plan: str
    patient_id: str
    nurse_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict:
        return {
            "subjective": self.subjective,
            "objective": self.objective,
            "assessment": self.assessment,
            "plan": self.plan,
            "patient_id": self.patient_id,
            "nurse_id": self.nurse_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class FlowsheetEntry:
    patient_id: str
    nurse_id: str
    timestamp: datetime
    vitals: Dict[str, Any]
    interventions: List[str]
    assessment_findings: str
    fhir_observation_bundle: Optional[dict] = None

    VITAL_RANGES = {
        "hr": (40, 180), "bp_sys": (60, 250), "bp_dia": (30, 150),
        "rr": (4, 60), "temp": (90.0, 107.0), "spo2": (50, 100), "pain": (0, 10),
    }

    def validate_vitals(self) -> List[str]:
        """Validate vital sign ranges, return list of abnormals."""
        abnormals = []
        for key, (lo, hi) in self.VITAL_RANGES.items():
            val = self.vitals.get(key)
            if val is not None and not (lo <= val <= hi):
                abnormals.append(f"{key}={val} (expected {lo}–{hi})")
        return abnormals

    def to_fhir_observations(self) -> dict:
        """Generate FHIR R4 Observation bundle from vitals."""
        loinc_map = {
            "hr": ("8867-4", "Heart rate"),
            "bp_sys": ("8480-6", "Systolic blood pressure"),
            "bp_dia": ("8462-4", "Diastolic blood pressure"),
            "rr": ("9279-1", "Respiratory rate"),
            "temp": ("8310-5", "Body temperature"),
            "spo2": ("2708-6", "Oxygen saturation"),
            "pain": ("72514-3", "Pain severity"),
        }
        entries = []
        for key, val in self.vitals.items():
            if val is not None and key in loinc_map:
                code, display = loinc_map[key]
                entries.append({
                    "resource": {
                        "resourceType": "Observation",
                        "id": str(uuid.uuid4()),
                        "status": "final",
                        "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
                        "subject": {"reference": f"Patient/{self.patient_id}"},
                        "effectiveDateTime": self.timestamp.isoformat(),
                        "valueQuantity": {"value": val},
                        "performer": [{"reference": f"Practitioner/{self.nurse_id}"}],
                    }
                })
        return {"resourceType": "Bundle", "type": "collection", "entry": entries}


@dataclass
class DischargeSummary:
    patient_id: str
    admission_date: datetime
    discharge_date: datetime
    primary_diagnosis: str
    procedures: List[str]
    medications_at_discharge: List[dict]
    follow_up_instructions: str
    patient_education_provided: List[str]
    return_precautions: str
    nurse_id: str

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "admission_date": self.admission_date.isoformat(),
            "discharge_date": self.discharge_date.isoformat(),
            "primary_diagnosis": self.primary_diagnosis,
            "procedures": self.procedures,
            "medications_at_discharge": self.medications_at_discharge,
            "follow_up_instructions": self.follow_up_instructions,
            "patient_education_provided": self.patient_education_provided,
            "return_precautions": self.return_precautions,
            "nurse_id": self.nurse_id,
        }


class ShiftScribeAgent:
    """
    AI documentation agent. Target: reduce nurse documentation burden by ≥40%.

    Evidence base:
    - AHRQ ENDburden R01 HS028454
    - Lindsay & Lytle 2022 PMID 35668677
    - Cho et al 2024 PMID 39259920
    - Holmgren et al 2024, Health Affairs
    """

    EVIDENCE = {
        "ahrq_endburden": "https://digital.ahrq.gov/ahrq-funded-projects/essential-nurse-documentation-studying-ehr-burden-during-covid-19-endburden",
        "lindsay_lytle_2022": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9300261/",
        "cho_2024": "https://pmc.ncbi.nlm.nih.gov/articles/PMC11491602/",
        "holmgren_2024": "https://www.healthaffairs.org/doi/full/10.1377/hlthaff.2024.00398",
    }

    def __init__(self, model: str = "claude-3-5-sonnet", hipaa_mode: bool = True):
        self.model = model
        self.hipaa_mode = hipaa_mode

    def _audit(self, action: str, patient_id: str, nurse_id: str, details: str = ""):
        """Log to AuditLedger if available."""
        if _ledger:
            try:
                _ledger.log(event=f"shift_scribe.{action}", data={
                    "patient_id_hash": hashlib.sha256(patient_id.encode()).hexdigest()[:16],
                    "nurse_id": nurse_id, "details": details,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.warning("AuditLedger unavailable: %s", e)

    def _call_llm(self, prompt: str, context: dict = None) -> str:
        """Call LLM for note generation. Returns structured text."""
        logger.info("ShiftScribe LLM call: model=%s, prompt_len=%d", self.model, len(prompt))
        # In production: call orchestra.cloud.inference_router with self.model
        # For now: return structured mock to enable testing
        return f"[AI-generated nursing documentation based on provided context]"

    def transcribe_voice_note(self, audio_bytes: bytes, patient_id: str,
                              nurse_id: str, context: dict = None) -> NursingNote:
        """Convert nurse voice note to structured nursing note via Whisper STT → LLM."""
        if not audio_bytes:
            raise ValueError("audio_bytes cannot be empty")
        self._audit("transcribe_voice", patient_id, nurse_id, f"audio_size={len(audio_bytes)}")

        # Step 1: STT (in production: call orchestra.media.whisper)
        transcript = f"[Transcribed from {len(audio_bytes)} bytes of audio]"
        # Step 2: Structure via LLM
        prompt = f"Convert this nurse voice note into a structured nursing note:\n\n{transcript}"
        if context:
            prompt += f"\n\nPatient context: {json.dumps(context, default=str)}"
        content = self._call_llm(prompt, context)

        note = NursingNote(
            patient_id=patient_id, nurse_id=nurse_id,
            note_type=NoteType.NARRATIVE, content=content,
            word_count=len(content.split()),
            evidence_citations=list(self.EVIDENCE.values()),
        )
        note.fhir_bundle = note.to_fhir_composition()
        return note

    def generate_soap_note(self, patient_id: str, nurse_id: str,
                           encounter_data: dict, shift: str = "day") -> SOAPNote:
        """Generate SOAP note from structured encounter data."""
        if not encounter_data:
            raise ValueError("encounter_data cannot be empty")
        self._audit("soap_note", patient_id, nurse_id)

        prompt = (
            "Generate a nursing SOAP note from the following encounter data:\n"
            f"Chief complaint: {encounter_data.get('chief_complaint', 'N/A')}\n"
            f"Vitals: {encounter_data.get('vitals', {})}\n"
            f"Interventions: {encounter_data.get('interventions_performed', [])}\n"
            f"Assessment findings: {encounter_data.get('assessment_findings', '')}\n"
            f"Current meds: {encounter_data.get('current_meds', [])}\n"
            f"Allergies: {encounter_data.get('allergies', [])}\n"
        )
        content = self._call_llm(prompt, encounter_data)

        cc = encounter_data.get("chief_complaint", "")
        vitals = encounter_data.get("vitals", {})
        findings = encounter_data.get("assessment_findings", "")
        interventions = encounter_data.get("interventions_performed", [])

        return SOAPNote(
            subjective=f"Patient reports: {cc}" if cc else "No subjective data provided.",
            objective=f"Vitals: {vitals}. Findings: {findings}" if vitals else "See flowsheet.",
            assessment=f"Nursing assessment based on presentation and findings. {content}",
            plan=f"Continue current plan. Interventions: {', '.join(interventions) if interventions else 'standard nursing care'}.",
            patient_id=patient_id, nurse_id=nurse_id,
        )

    def generate_narrative_note(self, patient_id: str, nurse_id: str,
                                brief_description: str, context: dict = None) -> NursingNote:
        """Generate narrative note from brief nurse description."""
        if not brief_description:
            raise ValueError("brief_description cannot be empty")
        self._audit("narrative_note", patient_id, nurse_id)
        prompt = f"Expand this brief nursing note into a complete narrative:\n\n{brief_description}"
        content = self._call_llm(prompt, context)
        return NursingNote(
            patient_id=patient_id, nurse_id=nurse_id,
            note_type=NoteType.NARRATIVE, content=content,
            word_count=len(content.split()),
        )

    def auto_fill_flowsheet(self, patient_id: str, nurse_id: str,
                            vitals: dict, interventions: List[str],
                            findings: str) -> FlowsheetEntry:
        """Auto-populate EHR flowsheet fields with FHIR Observation bundle."""
        if not vitals:
            raise ValueError("vitals cannot be empty")
        self._audit("flowsheet", patient_id, nurse_id, f"vitals_keys={list(vitals.keys())}")

        entry = FlowsheetEntry(
            patient_id=patient_id, nurse_id=nurse_id,
            timestamp=datetime.now(timezone.utc), vitals=vitals,
            interventions=interventions or [], assessment_findings=findings or "",
        )
        abnormals = entry.validate_vitals()
        if abnormals:
            logger.warning("Abnormal vitals for %s: %s", patient_id, abnormals)
        entry.fhir_observation_bundle = entry.to_fhir_observations()
        return entry

    def draft_discharge_summary(self, patient_id: str, nurse_id: str,
                                admission_context: dict) -> DischargeSummary:
        """Generate discharge summary from admission data."""
        self._audit("discharge", patient_id, nurse_id)
        return DischargeSummary(
            patient_id=patient_id, nurse_id=nurse_id,
            admission_date=admission_context.get("admission_date", datetime.now(timezone.utc)),
            discharge_date=datetime.now(timezone.utc),
            primary_diagnosis=admission_context.get("primary_diagnosis", "See chart"),
            procedures=admission_context.get("procedures", []),
            medications_at_discharge=admission_context.get("discharge_meds", []),
            follow_up_instructions=admission_context.get("follow_up", "Follow up with PCP in 7 days"),
            patient_education_provided=admission_context.get("education", ["Disease process", "Medications"]),
            return_precautions=admission_context.get("return_precautions", "Return to ED if symptoms worsen"),
        )

    def generate_care_plan_update(self, patient_id: str, nurse_id: str,
                                  changes: List[str], current_plan: dict = None) -> NursingNote:
        """Update nursing care plan based on clinical changes."""
        self._audit("care_plan_update", patient_id, nurse_id)
        content = f"Care plan updated. Changes: {'; '.join(changes)}."
        if current_plan:
            content += f" Previous plan elements: {json.dumps(current_plan, default=str)}"
        return NursingNote(
            patient_id=patient_id, nurse_id=nurse_id,
            note_type=NoteType.CARE_PLAN, content=content,
            word_count=len(content.split()),
        )

    def generate_incident_report(self, patient_id: str, nurse_id: str,
                                 incident_type: str, description: str,
                                 witnesses: List[str] = None) -> NursingNote:
        """Generate structured incident report."""
        self._audit("incident_report", patient_id, nurse_id, f"type={incident_type}")
        content = (
            f"INCIDENT REPORT\n"
            f"Type: {incident_type}\n"
            f"Date/Time: {datetime.now(timezone.utc).isoformat()}\n"
            f"Description: {description}\n"
            f"Witnesses: {', '.join(witnesses) if witnesses else 'None listed'}\n"
            f"Reporting nurse: {nurse_id}\n"
            f"Patient: {patient_id}\n"
        )
        return NursingNote(
            patient_id=patient_id, nurse_id=nurse_id,
            note_type=NoteType.INCIDENT, content=content,
            word_count=len(content.split()),
        )

    def translate_to_fhir(self, note: NursingNote) -> dict:
        """Convert NursingNote to FHIR R4 Composition resource."""
        return note.to_fhir_composition()

    def get_tools(self) -> List[dict]:
        """Return tool definitions for agent loop integration."""
        return [
            {"name": "scribe_voice_note", "description": "Transcribe voice note into structured FHIR nursing note", "parameters": {"audio_bytes": "bytes", "patient_id": "str", "nurse_id": "str"}},
            {"name": "scribe_soap_note", "description": "Generate SOAP note from encounter data", "parameters": {"patient_id": "str", "nurse_id": "str", "encounter_data": "dict"}},
            {"name": "scribe_flowsheet", "description": "Auto-fill flowsheet from vitals", "parameters": {"patient_id": "str", "nurse_id": "str", "vitals": "dict", "interventions": "list"}},
            {"name": "scribe_discharge", "description": "Generate discharge summary", "parameters": {"patient_id": "str", "nurse_id": "str", "admission_context": "dict"}},
            {"name": "scribe_care_plan", "description": "Update nursing care plan", "parameters": {"patient_id": "str", "nurse_id": "str", "changes": "list"}},
            {"name": "scribe_incident", "description": "Generate incident report", "parameters": {"patient_id": "str", "nurse_id": "str", "incident_type": "str", "description": "str"}},
        ]
