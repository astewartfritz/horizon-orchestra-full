"""
MedReconciliationAgent — Medication safety and 5 Rights verification.

Clinical evidence:
- ≥1.3 million Americans injured by medication errors annually (ISMP/IOM)
  https://home.ecri.org/pages/ismp
- ≥1 death per day from medication errors
- 38% of medication errors at administration phase (StatPearls NBK560654)
  https://www.ncbi.nlm.nih.gov/books/NBK560654/
- 55% of nurses admit making medication errors; <5% reported (PMID 32833397)
  https://pubmed.ncbi.nlm.nih.gov/32833397/
- 5 Rights classified "low-leverage" by ISMP — automation needed
- BCMA scan rates as low as 0–20% baseline (Grailey et al 2024, PMID 38902018)
  https://pubmed.ncbi.nlm.nih.gov/38902018/
- JC 2024: 1,575 sentinel events; medication management major category
  https://www.jointcommission.org/en-us/knowledge-library/sentinel-events
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from orchestra.guardian.audit_ledger import AuditLedger
    _ledger = AuditLedger()
except ImportError:
    _ledger = None


@dataclass
class SafetyCheck:
    patient_id: str
    drug: str
    dose: str
    route: str
    scheduled_time: datetime
    right_patient: bool
    right_drug: bool
    right_dose: bool
    right_route: bool
    right_time: bool
    all_five_rights_pass: bool
    alerts: List[str]
    recommendations: List[str]
    risk_level: str  # "safe", "caution", "hold", "critical"
    checked_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["scheduled_time"] = self.scheduled_time.isoformat()
        d["checked_at"] = self.checked_at.isoformat()
        return d


@dataclass
class DrugInteraction:
    drug_a: str
    drug_b: str
    severity: str  # "contraindicated", "major", "moderate", "minor"
    mechanism: str
    clinical_effect: str
    management: str
    references: List[str]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class AllergyAlert:
    patient_id: str
    drug: str
    allergen: str
    reaction_type: str
    severity: str  # "anaphylaxis", "severe", "moderate", "mild"
    cross_reactivity_risk: Optional[str]
    action_required: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class DoseVerification:
    patient_id: str
    drug: str
    ordered_dose: str
    ordered_dose_mg: float
    weight_kg: float
    calculated_dose_mgkg: float
    recommended_range_mgkg: str
    within_range: bool
    recommendation: str
    flag: Optional[str] = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ReconciliationReport:
    patient_id: str
    home_medications: List[dict]
    ordered_medications: List[dict]
    discrepancies: List[dict]
    intentional_changes: List[dict]
    unresolved_discrepancies: List[dict]
    review_required: bool
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["generated_at"] = self.generated_at.isoformat()
        return d


class MedReconciliationAgent:
    """
    Medication safety agent — 5 Rights + interaction detection + dose verification.

    Evidence:
    - ISMP: https://home.ecri.org/pages/ismp
    - IOM: https://www.nationalacademies.org/news/medication-errors-injure-one-point-five-million-people-and-cost-billions-of-dollars-annually-report-offers-comprehensive-strategies-for-reducing-drug-related-mistakes
    - JC Sentinel Events: https://www.jointcommission.org/en-us/knowledge-library/sentinel-events
    """

    EVIDENCE = {
        "ismp": "https://home.ecri.org/pages/ismp",
        "iom": "https://www.nationalacademies.org/news/medication-errors-injure-one-point-five-million-people-and-cost-billions-of-dollars-annually-report-offers-comprehensive-strategies-for-reducing-drug-related-mistakes",
        "statpearls": "https://www.ncbi.nlm.nih.gov/books/NBK560654/",
        "grailey_2024": "https://pubmed.ncbi.nlm.nih.gov/38902018/",
        "jc_sentinel": "https://www.jointcommission.org/en-us/knowledge-library/sentinel-events",
    }

    HIGH_ALERT_MEDS = frozenset([
        "insulin", "heparin", "warfarin", "enoxaparin", "methotrexate",
        "morphine", "hydromorphone", "fentanyl", "oxycodone",
        "potassium chloride", "sodium chloride 3%", "magnesium sulfate",
        "digoxin", "amiodarone", "dopamine", "epinephrine", "norepinephrine",
        "nitroprusside", "propofol", "succinylcholine", "vecuronium",
        "cisplatin", "doxorubicin", "vincristine", "cyclophosphamide",
    ])

    COMMON_INTERACTIONS: Dict[Tuple[str, str], Tuple[str, str, str, str]] = {
        ("warfarin", "aspirin"): ("major", "additive anticoagulation + platelet inhibition", "increased bleeding risk", "monitor INR closely, minimize ASA dose"),
        ("warfarin", "ibuprofen"): ("major", "additive anticoagulation + GI irritation", "increased bleeding and GI risk", "avoid combination; use acetaminophen"),
        ("metformin", "contrast"): ("major", "renal impairment → lactic acidosis", "lactic acidosis risk", "hold metformin 48h before/after contrast"),
        ("ssri", "tramadol"): ("major", "dual serotonergic activity", "serotonin syndrome risk", "avoid combination; use alternative analgesic"),
        ("ssri", "maoi"): ("contraindicated", "dual serotonergic activity", "fatal serotonin syndrome", "absolutely contraindicated; 14-day washout"),
        ("quinolone", "antacid"): ("moderate", "chelation reduces absorption", "reduced antibiotic efficacy", "separate by 2 hours"),
        ("ace_inhibitor", "potassium"): ("moderate", "reduced K+ excretion", "hyperkalemia risk", "monitor K+ levels closely"),
        ("digoxin", "amiodarone"): ("major", "reduced digoxin clearance", "digoxin toxicity risk", "reduce digoxin dose 50%; monitor levels"),
        ("statin", "gemfibrozil"): ("major", "inhibited statin metabolism", "rhabdomyolysis risk", "use fenofibrate instead; monitor CK"),
    }

    VALID_ROUTES = frozenset([
        "oral", "iv", "im", "subq", "topical", "inhaled", "rectal",
        "sublingual", "transdermal", "ophthalmic", "otic", "nasal",
        "intrathecal", "epidural", "intraosseous",
    ])

    def __init__(self, hipaa_mode: bool = True):
        self.hipaa_mode = hipaa_mode

    def _audit(self, action: str, patient_id: str, drug: str = ""):
        if _ledger:
            try:
                _ledger.log(event=f"med_rec.{action}", data={
                    "patient_hash": hashlib.sha256(patient_id.encode()).hexdigest()[:16],
                    "drug": drug, "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass

    def check_five_rights(self, patient_id: str, drug: str, dose: str,
                          route: str, scheduled_time: datetime,
                          patient_context: dict = None) -> SafetyCheck:
        """
        Verify the 5 Rights of medication administration.
        Note: ISMP classifies 5 Rights as 'low-leverage' — this check supplements
        (not replaces) BCMA and other high-leverage safety systems.
        """
        if not all([patient_id, drug, dose, route]):
            raise ValueError("patient_id, drug, dose, and route are all required")
        self._audit("five_rights", patient_id, drug)

        ctx = patient_context or {}
        alerts = []
        recommendations = []

        # Right Patient
        right_patient = bool(patient_id and patient_id == ctx.get("confirmed_patient_id", patient_id))

        # Right Drug
        ordered_drug = ctx.get("ordered_drug", drug)
        right_drug = drug.lower().strip() == ordered_drug.lower().strip()
        if not right_drug:
            alerts.append(f"Drug mismatch: ordered '{ordered_drug}', presenting '{drug}'")

        # Right Dose
        ordered_dose = ctx.get("ordered_dose", dose)
        right_dose = dose.lower().strip() == ordered_dose.lower().strip()
        if not right_dose:
            alerts.append(f"Dose mismatch: ordered '{ordered_dose}', presenting '{dose}'")

        # Right Route
        right_route = route.lower().strip() in self.VALID_ROUTES
        ordered_route = ctx.get("ordered_route", route)
        if route.lower().strip() != ordered_route.lower().strip():
            right_route = False
            alerts.append(f"Route mismatch: ordered '{ordered_route}', presenting '{route}'")

        # Right Time
        now = datetime.now(timezone.utc)
        time_window_minutes = 30  # Standard ±30 min window
        time_diff = abs((now - scheduled_time).total_seconds()) / 60
        right_time = time_diff <= time_window_minutes
        if not right_time:
            alerts.append(f"Time window: {time_diff:.0f} min from scheduled (±{time_window_minutes} min allowed)")

        all_pass = all([right_patient, right_drug, right_dose, right_route, right_time])

        # High-alert medication check
        if drug.lower() in self.HIGH_ALERT_MEDS:
            alerts.append(f"HIGH-ALERT MEDICATION: {drug} — requires independent double-check (ISMP)")
            recommendations.append("Perform independent double-check per ISMP guidelines")

        # Determine risk level
        if not all_pass and any(not x for x in [right_patient, right_drug]):
            risk = "critical"
        elif not all_pass:
            risk = "hold"
        elif alerts:
            risk = "caution"
        else:
            risk = "safe"

        return SafetyCheck(
            patient_id=patient_id, drug=drug, dose=dose, route=route,
            scheduled_time=scheduled_time,
            right_patient=right_patient, right_drug=right_drug,
            right_dose=right_dose, right_route=right_route, right_time=right_time,
            all_five_rights_pass=all_pass, alerts=alerts,
            recommendations=recommendations, risk_level=risk,
        )

    def detect_interactions(self, med_list: List[str]) -> List[DrugInteraction]:
        """Check for known drug-drug interactions in a medication list."""
        if not med_list:
            return []
        interactions = []
        normalized = [m.lower().strip() for m in med_list]

        for i, drug_a in enumerate(normalized):
            for drug_b in normalized[i + 1:]:
                key = (drug_a, drug_b)
                reverse_key = (drug_b, drug_a)
                match = self.COMMON_INTERACTIONS.get(key) or self.COMMON_INTERACTIONS.get(reverse_key)
                if match:
                    severity, mechanism, effect, management = match
                    interactions.append(DrugInteraction(
                        drug_a=drug_a, drug_b=drug_b, severity=severity,
                        mechanism=mechanism, clinical_effect=effect,
                        management=management,
                        references=[self.EVIDENCE["ismp"], self.EVIDENCE["statpearls"]],
                    ))

        return interactions

    def verify_allergy_conflict(self, patient_id: str, drug: str,
                                allergy_list: List[dict] = None) -> Optional[AllergyAlert]:
        """Check if drug conflicts with patient allergies."""
        self._audit("allergy_check", patient_id, drug)
        if not allergy_list:
            return None

        drug_lower = drug.lower().strip()
        for allergy in allergy_list:
            allergen = allergy.get("allergen", "").lower()
            if allergen and (allergen in drug_lower or drug_lower in allergen):
                return AllergyAlert(
                    patient_id=patient_id, drug=drug, allergen=allergy.get("allergen", ""),
                    reaction_type=allergy.get("reaction", "unknown"),
                    severity=allergy.get("severity", "unknown"),
                    cross_reactivity_risk=allergy.get("cross_reactivity"),
                    action_required=f"DO NOT ADMINISTER {drug}. Contact prescriber for alternative.",
                )

        # Check cross-reactivity classes
        CROSS_REACT = {
            "penicillin": ["amoxicillin", "ampicillin", "piperacillin", "nafcillin"],
            "cephalosporin": ["cefazolin", "ceftriaxone", "cefepime", "cephalexin"],
            "sulfa": ["sulfamethoxazole", "sulfasalazine", "celecoxib", "furosemide"],
            "nsaid": ["ibuprofen", "naproxen", "ketorolac", "diclofenac", "aspirin"],
        }
        for allergy in allergy_list:
            allergen = allergy.get("allergen", "").lower()
            for drug_class, members in CROSS_REACT.items():
                if allergen in members or allergen == drug_class:
                    if drug_lower in members or drug_lower == drug_class:
                        return AllergyAlert(
                            patient_id=patient_id, drug=drug,
                            allergen=allergy.get("allergen", ""),
                            reaction_type=allergy.get("reaction", "unknown"),
                            severity="moderate",
                            cross_reactivity_risk=f"Cross-reactivity with {drug_class} class",
                            action_required=f"Potential cross-reactivity ({drug_class}). Verify with pharmacist.",
                        )
        return None

    def weight_based_dose_check(self, patient_id: str, drug: str,
                                ordered_dose: str, weight_kg: float) -> DoseVerification:
        """Verify dose against weight-based ranges."""
        if weight_kg <= 0:
            raise ValueError("weight_kg must be positive")
        self._audit("dose_check", patient_id, drug)

        # Parse numeric dose
        dose_mg = 0.0
        for part in ordered_dose.split():
            try:
                dose_mg = float(part.replace("mg", "").replace("mcg", "").replace("g", ""))
                break
            except ValueError:
                continue

        calculated_mgkg = dose_mg / weight_kg if weight_kg > 0 else 0

        # Simplified reference ranges (mg/kg) — in production, use RxNorm/DrugBank
        DOSE_RANGES = {
            "acetaminophen": (10, 15), "ibuprofen": (5, 10), "morphine": (0.05, 0.1),
            "vancomycin": (10, 15), "gentamicin": (1, 2.5), "amoxicillin": (20, 40),
            "ceftriaxone": (20, 50), "metformin": (5, 25),
        }
        drug_lower = drug.lower().strip()
        range_ref = DOSE_RANGES.get(drug_lower)

        if range_ref:
            lo, hi = range_ref
            within = lo <= calculated_mgkg <= hi
            rec = "Dose within recommended range." if within else f"Dose outside range ({lo}–{hi} mg/kg). Verify with prescriber."
            flag = None if within else "OUTSIDE_RANGE"
            range_str = f"{lo}–{hi} mg/kg"
        else:
            within = True  # Unknown drug, assume OK but flag
            rec = f"No weight-based reference available for {drug}. Clinical judgment required."
            flag = "NO_REFERENCE"
            range_str = "N/A"

        return DoseVerification(
            patient_id=patient_id, drug=drug, ordered_dose=ordered_dose,
            ordered_dose_mg=dose_mg, weight_kg=weight_kg,
            calculated_dose_mgkg=round(calculated_mgkg, 3),
            recommended_range_mgkg=range_str, within_range=within,
            recommendation=rec, flag=flag,
        )

    def reconcile_home_meds(self, patient_id: str, home_meds: List[dict],
                            ordered_meds: List[dict]) -> ReconciliationReport:
        """Compare home medications vs. ordered medications."""
        self._audit("reconciliation", patient_id)

        home_set = {m.get("drug", "").lower().strip() for m in home_meds}
        ordered_set = {m.get("drug", "").lower().strip() for m in ordered_meds}

        omissions = home_set - ordered_set
        additions = ordered_set - home_set

        discrepancies = []
        for drug in omissions:
            discrepancies.append({"type": "omission", "drug": drug, "details": "Home med not ordered. Intentional?"})
        for drug in additions:
            discrepancies.append({"type": "addition", "drug": drug, "details": "New medication not on home med list."})

        return ReconciliationReport(
            patient_id=patient_id, home_medications=home_meds,
            ordered_medications=ordered_meds, discrepancies=discrepancies,
            intentional_changes=[], unresolved_discrepancies=discrepancies,
            review_required=len(discrepancies) > 0,
        )

    def high_alert_medication_check(self, drug: str) -> dict:
        """Check if drug is on ISMP high-alert medication list."""
        is_high = drug.lower().strip() in self.HIGH_ALERT_MEDS
        return {
            "drug": drug, "is_high_alert": is_high,
            "category": "ISMP High-Alert" if is_high else "standard",
            "precautions": [
                "Independent double-check required",
                "Use smart pump with DERS",
                "Verify weight-based dosing",
                "Confirm patient allergies",
            ] if is_high else [],
            "reference": self.EVIDENCE["ismp"],
        }

    def get_tools(self) -> List[dict]:
        return [
            {"name": "med_five_rights", "description": "Verify 5 Rights of medication administration", "parameters": {"patient_id": "str", "drug": "str", "dose": "str", "route": "str", "scheduled_time": "datetime"}},
            {"name": "med_interactions", "description": "Check drug-drug interactions", "parameters": {"med_list": "list"}},
            {"name": "med_allergy_check", "description": "Verify drug vs patient allergies", "parameters": {"patient_id": "str", "drug": "str"}},
            {"name": "med_dose_check", "description": "Weight-based dose verification", "parameters": {"patient_id": "str", "drug": "str", "ordered_dose": "str", "weight_kg": "float"}},
            {"name": "med_reconciliation", "description": "Compare home vs ordered medications", "parameters": {"patient_id": "str", "home_meds": "list", "ordered_meds": "list"}},
            {"name": "med_high_alert", "description": "Check if drug is ISMP high-alert", "parameters": {"drug": "str"}},
        ]
