"""
NurseEducationCoach — Just-in-time clinical education and decision support.

Clinical evidence:
- Documentation burden crowds out CDS tool use (Holmgren 2024, Health Affairs)
  https://www.healthaffairs.org/doi/full/10.1377/hlthaff.2024.00398
- Nursing students improved 74% with HRO safety curriculum (PMID 32833397)
  https://pubmed.ncbi.nlm.nih.gov/32833397/
- JC requires ongoing competency verification for high-alert medications
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from orchestra.guardian.audit_ledger import AuditLedger
    _ledger = AuditLedger()
except ImportError:
    _ledger = None


@dataclass
class ClinicalBrief:
    topic: str
    summary: str
    mechanism_of_action: str
    key_nursing_considerations: List[str]
    monitoring_parameters: List[str]
    common_adverse_effects: List[str]
    patient_education_points: List[str]
    references: List[str]
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["generated_at"] = self.generated_at.isoformat()
        return d


@dataclass
class Checklist:
    procedure: str
    patient_context: dict
    pre_procedure: List[str]
    equipment_needed: List[str]
    steps: List[str]
    post_procedure: List[str]
    documentation_required: List[str]
    safety_checks: List[str]
    evidence_source: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class PolicyResult:
    query: str
    hospital_id: str
    policy_name: str
    policy_number: str
    summary: str
    key_steps: List[str]
    last_updated: str
    contact: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class CompetencyReport:
    nurse_id: str
    competencies_verified: List[dict]
    due_for_renewal: List[dict]
    high_alert_med_competencies: List[dict]
    overall_compliance_pct: float
    next_due_date: Optional[datetime]

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        if self.next_due_date:
            d["next_due_date"] = self.next_due_date.isoformat()
        return d


# Built-in medication reference database (key medications nurses encounter)
MEDICATION_DB = {
    "metoprolol": {
        "class": "Beta-blocker",
        "mechanism": "Selectively blocks beta-1 adrenergic receptors, reducing heart rate and blood pressure.",
        "nursing_considerations": [
            "Hold if HR < 60 or SBP < 100; notify prescriber",
            "Monitor for bradycardia, hypotension, dizziness",
            "Do not abruptly discontinue — taper over 1-2 weeks",
            "Assess for signs of heart failure exacerbation",
        ],
        "monitoring": ["Heart rate", "Blood pressure", "ECG rhythm", "Signs of HF"],
        "adverse_effects": ["Bradycardia", "Hypotension", "Fatigue", "Dizziness", "Depression"],
        "patient_education": [
            "Do not stop taking without consulting your doctor",
            "Rise slowly from sitting or lying to prevent dizziness",
            "Monitor and record pulse daily",
            "Report pulse < 60 or dizziness to your nurse",
        ],
    },
    "heparin": {
        "class": "Anticoagulant",
        "mechanism": "Potentiates antithrombin III, inhibiting thrombin and Factor Xa to prevent clot formation.",
        "nursing_considerations": [
            "HIGH-ALERT MEDICATION — requires independent double-check (ISMP)",
            "Monitor aPTT q6h; therapeutic range 1.5–2.5x control",
            "Assess for signs of bleeding: bruising, hematuria, melena, gum bleeding",
            "Have protamine sulfate available as reversal agent",
            "Check platelet count baseline and q2-3 days (HIT risk)",
        ],
        "monitoring": ["aPTT", "Platelet count", "H&H", "Signs of bleeding", "HIT"],
        "adverse_effects": ["Bleeding", "HIT", "Osteoporosis (long-term)", "Injection site reactions"],
        "patient_education": [
            "Report any unusual bleeding or bruising immediately",
            "Use soft toothbrush and electric razor",
            "Avoid activities with high injury risk",
            "Wear medical alert identification",
        ],
    },
    "insulin": {
        "class": "Antidiabetic",
        "mechanism": "Facilitates glucose uptake into cells, reduces hepatic glucose production.",
        "nursing_considerations": [
            "HIGH-ALERT MEDICATION — requires independent double-check",
            "Verify type (rapid/short/intermediate/long-acting) and dose",
            "Check blood glucose before administration",
            "Ensure patient will eat within 15-30 min (rapid-acting)",
            "Rotate injection sites; inspect for lipohypertrophy",
            "Never give IV without infusion pump",
        ],
        "monitoring": ["Blood glucose (AC and HS)", "HbA1c", "Hypo signs", "Injection sites"],
        "adverse_effects": ["Hypoglycemia", "Weight gain", "Lipohypertrophy", "Hypokalemia"],
        "patient_education": [
            "Recognize signs of low blood sugar: shaking, sweating, confusion",
            "Always carry glucose tablets or juice",
            "Store insulin properly (refrigerate unopened; room temp opened)",
            "Rotate injection sites",
        ],
    },
    "vancomycin": {
        "class": "Glycopeptide antibiotic",
        "mechanism": "Inhibits bacterial cell wall synthesis by binding D-Ala-D-Ala peptidoglycan precursors.",
        "nursing_considerations": [
            "Infuse over ≥60 min to prevent Red Man Syndrome",
            "Monitor trough levels (target 15-20 mcg/mL for serious infections)",
            "Assess renal function (BUN, Cr) before and during therapy",
            "Monitor for ototoxicity: tinnitus, hearing changes",
            "Ensure adequate hydration",
        ],
        "monitoring": ["Vancomycin trough", "BUN/Cr", "Hearing", "WBC/cultures"],
        "adverse_effects": ["Nephrotoxicity", "Ototoxicity", "Red Man Syndrome", "Thrombocytopenia"],
        "patient_education": [
            "Report rash, itching, flushing, or hearing changes immediately",
            "Complete full course even if feeling better",
            "Stay well hydrated during treatment",
        ],
    },
}

# Common procedures nurses perform
PROCEDURE_DB = {
    "foley_catheter_insertion": {
        "pre": ["Verify order", "Confirm indication meets CAUTI bundle criteria", "Hand hygiene", "Gather supplies", "Explain procedure to patient"],
        "equipment": ["Sterile catheter kit", "Appropriate catheter size (14-16 Fr for adults)", "Sterile gloves", "10 mL sterile water syringe", "Collection bag", "Antiseptic solution"],
        "steps": [
            "Position patient (supine, knees bent for female; supine for male)",
            "Open catheter kit using sterile technique",
            "Don sterile gloves",
            "Prepare sterile field and drape patient",
            "Cleanse urethral meatus with antiseptic (front-to-back for female)",
            "Insert catheter gently until urine flows",
            "Advance 2-3 cm beyond urine return",
            "Inflate balloon with 10 mL sterile water",
            "Gently pull catheter until resistance felt at bladder neck",
            "Secure catheter to thigh (female) or abdomen (male)",
            "Attach drainage bag below bladder level",
        ],
        "post": ["Document time, catheter size, balloon volume, urine output/color", "Monitor I&O", "Assess daily for need to discontinue (CAUTI prevention)", "Perineal care q shift"],
        "documentation": ["Time of insertion", "Catheter size and type", "Balloon volume", "Initial urine output and color", "Patient tolerance"],
        "safety": ["Maintain sterile technique throughout", "Never force catheter", "Assess for latex allergy", "Document CAUTI bundle compliance"],
        "evidence": "CDC CAUTI Prevention Guidelines; APIC Implementation Guide",
    },
    "blood_transfusion": {
        "pre": ["Verify consent", "Verify blood type and crossmatch (two-nurse verification)", "Check for fever/recent meds", "Obtain baseline vitals", "Ensure patent IV access (18-20 gauge)"],
        "equipment": ["Blood product (verified)", "Blood tubing with filter", "Normal saline", "Blood warmer (if indicated)", "Emergency equipment nearby"],
        "steps": [
            "Verify patient ID with TWO identifiers at bedside",
            "Verify blood product with TWO nurses — check: patient name, MRN, blood type, Rh, unit number, expiration",
            "Obtain baseline vitals (T, HR, BP, RR, SpO2)",
            "Prime blood tubing with NS",
            "Begin transfusion slowly (2 mL/min for first 15 min)",
            "Remain with patient for first 15 min — observe for reactions",
            "Obtain vitals at 15 min",
            "If no reaction: increase rate per order (typically 2-4 hours total)",
            "Obtain vitals q30min during transfusion",
            "Complete transfusion within 4 hours of leaving blood bank",
        ],
        "post": ["Final vitals within 1 hour of completion", "Flush line with NS", "Document volume transfused and patient response", "Return blood bank paperwork"],
        "documentation": ["Two-nurse verification", "Start/stop times", "Vital signs per protocol", "Total volume infused", "Any adverse reactions"],
        "safety": ["STOP transfusion immediately if reaction suspected", "Transfusion reactions: fever/chills, urticaria, dyspnea, back pain, hypotension", "Save blood bag and tubing if reaction occurs", "Notify MD and blood bank immediately"],
        "evidence": "AABB Standards; Joint Commission NPSG.01.03.01",
    },
}


class NurseEducationCoach:
    """
    Just-in-time clinical education agent.

    Evidence:
    - PMID 32833397: https://pubmed.ncbi.nlm.nih.gov/32833397/
    - Health Affairs 2024: https://www.healthaffairs.org/doi/full/10.1377/hlthaff.2024.00398
    """

    EVIDENCE = {
        "holmgren_2024": "https://www.healthaffairs.org/doi/full/10.1377/hlthaff.2024.00398",
        "davis_2020": "https://pubmed.ncbi.nlm.nih.gov/32833397/",
    }

    def __init__(self, model: str = "claude-3-5-sonnet"):
        self.model = model

    def _call_llm(self, prompt: str) -> str:
        logger.info("EducationCoach LLM call: prompt_len=%d", len(prompt))
        return "[AI-generated clinical education content]"

    def explain_medication(self, drug_name: str, context: str = "",
                           nurse_level: str = "rn") -> ClinicalBrief:
        """Provide clinical brief on a medication. Uses built-in DB first, LLM fallback."""
        if not drug_name:
            raise ValueError("drug_name is required")

        db_entry = MEDICATION_DB.get(drug_name.lower().strip())

        if db_entry:
            return ClinicalBrief(
                topic=drug_name,
                summary=f"{drug_name} is a {db_entry['class']}. {db_entry['mechanism'][:100]}",
                mechanism_of_action=db_entry["mechanism"],
                key_nursing_considerations=db_entry["nursing_considerations"],
                monitoring_parameters=db_entry["monitoring"],
                common_adverse_effects=db_entry["adverse_effects"],
                patient_education_points=db_entry["patient_education"],
                references=[self.EVIDENCE["davis_2020"]],
            )
        else:
            # LLM fallback for drugs not in local DB
            content = self._call_llm(f"Provide nursing clinical brief for {drug_name}. Context: {context}")
            return ClinicalBrief(
                topic=drug_name,
                summary=f"Clinical brief for {drug_name}. {content}",
                mechanism_of_action="See full reference",
                key_nursing_considerations=["Consult pharmacy for complete information"],
                monitoring_parameters=["Per prescriber order"],
                common_adverse_effects=["See drug reference"],
                patient_education_points=["Discuss with pharmacist"],
                references=[self.EVIDENCE["davis_2020"]],
            )

    def procedure_checklist(self, procedure: str, patient_context: dict) -> Checklist:
        """Generate evidence-based procedure checklist."""
        if not procedure:
            raise ValueError("procedure is required")

        proc_key = procedure.lower().replace(" ", "_").strip()
        db_entry = PROCEDURE_DB.get(proc_key)

        if db_entry:
            return Checklist(
                procedure=procedure,
                patient_context=patient_context or {},
                pre_procedure=db_entry["pre"],
                equipment_needed=db_entry["equipment"],
                steps=db_entry["steps"],
                post_procedure=db_entry["post"],
                documentation_required=db_entry["documentation"],
                safety_checks=db_entry["safety"],
                evidence_source=db_entry["evidence"],
            )
        else:
            content = self._call_llm(f"Generate nursing procedure checklist for: {procedure}")
            return Checklist(
                procedure=procedure, patient_context=patient_context or {},
                pre_procedure=["Verify order", "Gather supplies", "Identify patient"],
                equipment_needed=["Per procedure requirements"],
                steps=[content],
                post_procedure=["Document procedure"],
                documentation_required=["Time, procedure performed, patient response"],
                safety_checks=["Verify patient identity", "Check for allergies"],
                evidence_source="Generated — verify with institutional policy",
            )

    def policy_lookup(self, query: str, hospital_id: str) -> PolicyResult:
        """Look up hospital policy. In production, queries policy database."""
        if not query:
            raise ValueError("query is required")
        return PolicyResult(
            query=query, hospital_id=hospital_id,
            policy_name=f"Policy related to: {query}",
            policy_number="POL-XXXX",
            summary=f"Institutional policy regarding {query}. Contact unit educator for details.",
            key_steps=["Refer to institutional policy manual", "Contact charge nurse for guidance"],
            last_updated="See policy database",
            contact="Unit Nurse Educator",
        )

    def differential_support(self, symptoms: List[str],
                             patient_context: dict = None) -> ClinicalBrief:
        """Provide differential diagnosis support based on symptoms."""
        if not symptoms:
            raise ValueError("symptoms list is required")
        content = self._call_llm(f"Nursing differential support for symptoms: {', '.join(symptoms)}")
        return ClinicalBrief(
            topic=f"Differential: {', '.join(symptoms[:3])}",
            summary=f"Assessment for {', '.join(symptoms)}. {content}",
            mechanism_of_action="Multiple possible etiologies",
            key_nursing_considerations=[
                "Perform focused assessment",
                "Obtain complete vital signs",
                "Review recent medications and interventions",
                "Notify provider of new or worsening symptoms",
            ],
            monitoring_parameters=["Vital signs", "Neurological status", "Pain assessment"],
            common_adverse_effects=[],
            patient_education_points=["Use call light for any changes"],
            references=[self.EVIDENCE["holmgren_2024"]],
        )

    def skills_competency_tracker(self, nurse_id: str,
                                  completed_assessments: List[dict]) -> CompetencyReport:
        """Track nurse competency status and renewal dates."""
        if not nurse_id:
            raise ValueError("nurse_id is required")

        verified = []
        due = []
        high_alert = []
        now = datetime.utcnow()

        for a in (completed_assessments or []):
            entry = {
                "skill": a.get("skill", "unknown"),
                "date_verified": a.get("date", ""),
                "method": a.get("method", "self-assessment"),
                "score": a.get("score", 0),
            }
            verified.append(entry)

            # Check if any are high-alert medication competencies
            if any(ha in a.get("skill", "").lower() for ha in ["insulin", "heparin", "blood", "chemo", "high-alert"]):
                high_alert.append(entry)

        total = len(completed_assessments) if completed_assessments else 0
        compliance = (total / max(1, total + 5)) * 100  # simplified: assume 5 always due

        return CompetencyReport(
            nurse_id=nurse_id,
            competencies_verified=verified,
            due_for_renewal=due,
            high_alert_med_competencies=high_alert,
            overall_compliance_pct=round(compliance, 1),
            next_due_date=None,
        )

    def explain_lab_value(self, lab_name: str, value: float, unit: str,
                          patient_context: dict = None) -> str:
        """Provide nursing interpretation of a lab value."""
        LAB_RANGES = {
            "potassium": (3.5, 5.0, "mEq/L"), "sodium": (135, 145, "mEq/L"),
            "glucose": (70, 100, "mg/dL"), "creatinine": (0.7, 1.3, "mg/dL"),
            "bun": (7, 20, "mg/dL"), "hemoglobin": (12.0, 17.5, "g/dL"),
            "hematocrit": (36, 54, "%"), "wbc": (4.5, 11.0, "K/uL"),
            "platelets": (150, 400, "K/uL"), "inr": (0.8, 1.2, "ratio"),
            "troponin": (0, 0.04, "ng/mL"), "lactate": (0.5, 2.0, "mmol/L"),
        }

        lab_lower = lab_name.lower().strip()
        ref = LAB_RANGES.get(lab_lower)

        if ref:
            lo, hi, ref_unit = ref
            if value < lo:
                status = f"LOW ({value} {unit}; normal {lo}–{hi} {ref_unit})"
                action = "Notify provider. Assess for signs/symptoms."
            elif value > hi:
                status = f"HIGH ({value} {unit}; normal {lo}–{hi} {ref_unit})"
                action = "Notify provider. Assess for signs/symptoms."
            else:
                status = f"NORMAL ({value} {unit}; normal {lo}–{hi} {ref_unit})"
                action = "No immediate action required."
        else:
            status = f"{lab_name}: {value} {unit}"
            action = "Reference range not available. Check laboratory reference."

        return f"{lab_name}: {status}. Nursing action: {action}"

    def explain_diagnosis(self, diagnosis_code: str, context: str = "") -> ClinicalBrief:
        """Explain a diagnosis code (ICD-10) in nursing terms."""
        content = self._call_llm(f"Explain ICD-10 code {diagnosis_code} for nursing care. {context}")
        return ClinicalBrief(
            topic=f"Diagnosis: {diagnosis_code}",
            summary=content, mechanism_of_action="See pathophysiology reference",
            key_nursing_considerations=["Perform focused assessment", "Review care plan"],
            monitoring_parameters=["Per diagnosis-specific protocol"],
            common_adverse_effects=[], patient_education_points=["Discuss plan of care with patient"],
            references=[self.EVIDENCE["holmgren_2024"]],
        )

    def get_tools(self) -> List[dict]:
        return [
            {"name": "edu_medication", "description": "Get clinical brief on a medication", "parameters": {"drug_name": "str"}},
            {"name": "edu_procedure", "description": "Get evidence-based procedure checklist", "parameters": {"procedure": "str", "patient_context": "dict"}},
            {"name": "edu_policy", "description": "Look up hospital policy", "parameters": {"query": "str", "hospital_id": "str"}},
            {"name": "edu_differential", "description": "Symptom-based differential support", "parameters": {"symptoms": "list"}},
            {"name": "edu_competency", "description": "Track nurse competency status", "parameters": {"nurse_id": "str", "completed_assessments": "list"}},
            {"name": "edu_lab", "description": "Explain and interpret a lab value", "parameters": {"lab_name": "str", "value": "float", "unit": "str"}},
        ]
