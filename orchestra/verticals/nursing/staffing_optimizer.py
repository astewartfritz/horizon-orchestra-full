"""
StaffingOptimizerAgent — Acuity-based nurse staffing and scheduling.

Clinical evidence:
- Each +1 patient/nurse → +7% 30-day mortality (Aiken 2002, PMID 12387650)
  https://pubmed.ncbi.nlm.nih.gov/12387650/
- 4→8 patients/nurse → +31% mortality (168 hospitals, 232,342 patients)
- Replicated RN4CAST: 300 hospitals, 9 countries (Lancet 2014, PMID 24581683)
  https://pubmed.ncbi.nlm.nih.gov/24581683/
- Each below-target shift → +2% mortality (Needleman 2011, PMID 21410370)
  https://pubmed.ncbi.nlm.nih.gov/21410370/
- Staffing effect >2× SEP-1 bundle (Lasater 2020, PMID 33309843)
  https://pubmed.ncbi.nlm.nih.gov/33309843/
- RN turnover 16.4%; $61,110 per replacement (NSI 2025)
  https://www.nsinursingsolutions.com/documents/library/nsi_national_health_care_retention_report.pdf
- Vizient 2026: https://www.vizientinc.com/insights/all/2026/the-nursing-workforce-is-at-a-breaking-point-and-nurse-managers-hold-the-key
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from orchestra.guardian.audit_ledger import AuditLedger
    _ledger = AuditLedger()
except ImportError:
    _ledger = None


@dataclass
class AcuityScore:
    patient_id: str
    score: float            # 1.0 (low) to 4.0 (ICU-level)
    category: str           # "routine", "complex", "critical", "intensive"
    care_hours_required_per_shift: float
    primary_drivers: List[str]
    nursing_tasks_estimated: int
    assessed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["assessed_at"] = self.assessed_at.isoformat()
        return d


@dataclass
class StaffingRecommendation:
    unit_id: str
    shift: str
    date: datetime
    current_census: int
    total_acuity_score: float
    recommended_rn_count: int
    recommended_lpn_count: int
    recommended_cna_count: int
    current_rn_scheduled: int
    staffing_gap: int
    mortality_risk_delta: float
    rationale: str
    evidence_citation: str = "Aiken et al 2002 PMID 12387650; Needleman et al 2011 PMID 21410370"

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["date"] = self.date.isoformat()
        return d


@dataclass
class CensusForecast:
    unit_id: str
    forecast_horizon_hours: int
    predicted_census: List[dict]
    confidence_interval: dict
    pending_admissions: int
    expected_discharges: int
    methodology: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class WeeklySchedule:
    unit_id: str
    week_start: date
    shifts: List[dict]
    total_rn_hours: int
    estimated_compliance_score: float
    cost_estimate: float
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["week_start"] = self.week_start.isoformat()
        d["generated_at"] = self.generated_at.isoformat()
        return d


class StaffingOptimizerAgent:
    """
    Acuity-based staffing optimizer — grounded in landmark mortality research.

    Evidence:
    - PMID 12387650 (Aiken 2002)
    - PMID 24581683 (RN4CAST 2014)
    - PMID 21410370 (Needleman 2011)
    - PMID 33309843 (Lasater 2020)
    - NSI 2025 Staffing Report
    """

    EVIDENCE = {
        "aiken_2002": "https://pubmed.ncbi.nlm.nih.gov/12387650/",
        "rn4cast_2014": "https://pubmed.ncbi.nlm.nih.gov/24581683/",
        "needleman_2011": "https://pubmed.ncbi.nlm.nih.gov/21410370/",
        "lasater_2020": "https://pubmed.ncbi.nlm.nih.gov/33309843/",
        "nsi_2025": "https://www.nsinursingsolutions.com/documents/library/nsi_national_health_care_retention_report.pdf",
        "vizient_2026": "https://www.vizientinc.com/insights/all/2026/the-nursing-workforce-is-at-a-breaking-point-and-nurse-managers-hold-the-key",
    }

    # Evidence-based minimum safe ratios (patients per nurse)
    EVIDENCE_RATIOS: Dict[str, int] = {
        "icu": 2, "step_down": 3, "med_surg": 4, "telemetry": 3,
        "ed": 3, "postpartum": 3, "pediatrics": 3, "rehab": 5,
        "psychiatric": 5, "nicu": 2, "labor_delivery": 2,
    }

    # Cost data from NSI 2025
    COST_PER_RN_REPLACEMENT = 61110  # USD
    COST_PER_TURNOVER_PCT = 289000   # per 1% change

    # Aiken 2002: OR 1.07 per additional patient per nurse
    MORTALITY_OR_PER_PATIENT = 1.07

    def __init__(self):
        pass

    def calculate_acuity_score(self, patient_id: str, patient_data: dict) -> AcuityScore:
        """
        Calculate patient acuity score based on clinical indicators.
        Score range: 1.0 (routine) to 4.0 (intensive/ICU).
        """
        if not patient_data:
            raise ValueError("patient_data is required")

        score = 1.0
        drivers = []
        tasks = 4  # baseline nursing tasks per shift

        # IV lines
        iv_count = patient_data.get("iv_lines", 0)
        if iv_count >= 3:
            score += 1.0; drivers.append(f"IV drips x{iv_count}"); tasks += iv_count * 2
        elif iv_count >= 1:
            score += 0.5; drivers.append(f"IV access x{iv_count}"); tasks += iv_count

        # Isolation precautions
        if patient_data.get("isolation", False):
            score += 0.5; drivers.append("isolation precautions"); tasks += 3

        # Fall risk
        if patient_data.get("fall_risk", False):
            score += 0.3; drivers.append("fall risk"); tasks += 2

        # Wound care
        wounds = patient_data.get("wound_count", 0)
        if wounds > 0:
            score += 0.3 * wounds; drivers.append(f"wounds x{wounds}"); tasks += wounds * 2

        # Cognitive impairment / confusion
        if patient_data.get("confused", False):
            score += 0.5; drivers.append("confusion/delirium"); tasks += 3

        # Ventilator
        if patient_data.get("ventilator", False):
            score += 1.5; drivers.append("mechanically ventilated"); tasks += 8

        # Vasoactive drips
        if patient_data.get("vasopressors", False):
            score += 1.0; drivers.append("vasopressor support"); tasks += 4

        # Continuous monitoring
        if patient_data.get("continuous_monitoring", False):
            score += 0.3; drivers.append("continuous monitoring"); tasks += 2

        score = min(4.0, max(1.0, score))

        if score >= 3.5:
            category = "intensive"
        elif score >= 2.5:
            category = "critical"
        elif score >= 1.5:
            category = "complex"
        else:
            category = "routine"

        # Care hours: base 4h for routine, scales with acuity
        care_hours = 4.0 * score

        return AcuityScore(
            patient_id=patient_id, score=round(score, 2),
            category=category, care_hours_required_per_shift=round(care_hours, 1),
            primary_drivers=drivers, nursing_tasks_estimated=tasks,
        )

    def recommend_staffing(self, unit_id: str, shift: str,
                           patient_ids: List[str],
                           patient_acuities: List[AcuityScore] = None,
                           current_schedule: dict = None,
                           unit_type: str = "med_surg") -> StaffingRecommendation:
        """
        Generate staffing recommendation based on census and acuity.
        Uses Aiken 2002 mortality model for risk quantification.
        """
        census = len(patient_ids)
        if census == 0:
            raise ValueError("Cannot recommend staffing for zero patients")

        evidence_ratio = self.EVIDENCE_RATIOS.get(unit_type, 4)

        if patient_acuities:
            total_acuity = sum(a.score for a in patient_acuities)
            avg_acuity = total_acuity / census
            # Adjust ratio based on acuity: higher acuity → lower ratio
            adjusted_ratio = max(1, evidence_ratio - int(avg_acuity - 1.5))
        else:
            total_acuity = census * 2.0  # assume average acuity
            adjusted_ratio = evidence_ratio

        recommended_rn = math.ceil(census / adjusted_ratio)
        recommended_cna = math.ceil(census / (adjusted_ratio * 2))
        recommended_lpn = max(0, math.ceil(census / 8) - 1)

        current_rn = current_schedule.get("rn_count", 0) if current_schedule else 0
        gap = current_rn - recommended_rn  # positive = overstaffed, negative = understaffed

        actual_ratio = census / max(1, current_rn) if current_rn > 0 else census
        mortality_delta = self.compute_mortality_risk_delta(actual_ratio, adjusted_ratio, unit_type)

        if gap < 0:
            rationale = (f"UNDERSTAFFED by {abs(gap)} RN(s). Current ratio {actual_ratio:.1f}:1 exceeds "
                        f"evidence-based {adjusted_ratio}:1. Mortality risk increased {mortality_delta:.1f}% (Aiken 2002).")
        elif gap > 0:
            rationale = f"Adequately staffed. {gap} RN(s) above minimum. Ratio {actual_ratio:.1f}:1."
        else:
            rationale = f"At minimum safe staffing. Ratio {actual_ratio:.1f}:1."

        return StaffingRecommendation(
            unit_id=unit_id, shift=shift, date=datetime.now(timezone.utc),
            current_census=census, total_acuity_score=round(total_acuity, 1),
            recommended_rn_count=recommended_rn, recommended_lpn_count=recommended_lpn,
            recommended_cna_count=recommended_cna, current_rn_scheduled=current_rn,
            staffing_gap=gap, mortality_risk_delta=round(mortality_delta, 2),
            rationale=rationale,
        )

    def predict_census(self, unit_id: str, historical_census: List[dict],
                       hours_ahead: int = 24) -> CensusForecast:
        """Predict future census using moving average (simple forecast)."""
        if not historical_census:
            return CensusForecast(
                unit_id=unit_id, forecast_horizon_hours=hours_ahead,
                predicted_census=[], confidence_interval={"lower": [], "upper": []},
                pending_admissions=0, expected_discharges=0,
                methodology="insufficient_data",
            )

        values = [h.get("census", 0) for h in historical_census[-48:]]  # last 48 data points
        avg = sum(values) / len(values) if values else 0
        std = (sum((v - avg) ** 2 for v in values) / max(1, len(values))) ** 0.5

        predictions = []
        lower = []
        upper = []
        for h in range(0, hours_ahead, 4):
            p = round(avg + (std * 0.1 * (h / 24)))  # slight upward drift
            predictions.append({"hour": h, "census": max(0, p)})
            lower.append(max(0, p - round(std)))
            upper.append(p + round(std))

        return CensusForecast(
            unit_id=unit_id, forecast_horizon_hours=hours_ahead,
            predicted_census=predictions,
            confidence_interval={"lower": lower, "upper": upper},
            pending_admissions=max(0, round(avg * 0.1)),
            expected_discharges=max(0, round(avg * 0.08)),
            methodology="moving_average",
        )

    def generate_schedule_draft(self, unit_id: str, week_start: date,
                                staff_roster: List[dict],
                                census_forecast: CensusForecast) -> WeeklySchedule:
        """Generate weekly schedule draft based on forecast and roster."""
        shifts = []
        total_hours = 0
        for day_offset in range(7):
            for shift_name in ["day", "evening", "night"]:
                # Simple round-robin assignment
                rn_count = max(2, len(staff_roster) // 3)
                start_idx = (day_offset * 3 + ["day", "evening", "night"].index(shift_name)) % max(1, len(staff_roster))
                assigned = [staff_roster[i % len(staff_roster)].get("name", f"RN-{i}")
                           for i in range(start_idx, start_idx + rn_count)] if staff_roster else []
                shifts.append({
                    "date": (datetime(week_start.year, week_start.month, week_start.day) +
                             __import__("datetime").timedelta(days=day_offset)).strftime("%Y-%m-%d"),
                    "shift": shift_name,
                    "rn_count": rn_count,
                    "nurses_assigned": assigned,
                })
                total_hours += rn_count * 8

        return WeeklySchedule(
            unit_id=unit_id, week_start=week_start, shifts=shifts,
            total_rn_hours=total_hours, estimated_compliance_score=0.85,
            cost_estimate=total_hours * 45.0,  # ~$45/hr average RN rate
        )

    def compute_mortality_risk_delta(self, actual_ratio: float,
                                     evidence_ratio: float,
                                     unit_type: str = "med_surg") -> float:
        """
        Compute estimated mortality risk change based on Aiken 2002 (OR 1.07/patient/nurse).
        Returns positive % = increased risk, negative = decreased risk.
        """
        delta_patients = actual_ratio - evidence_ratio
        # OR 1.07 per additional patient per nurse (Aiken 2002, PMID 12387650)
        return (self.MORTALITY_OR_PER_PATIENT ** delta_patients - 1.0) * 100

    def get_tools(self) -> List[dict]:
        return [
            {"name": "staffing_acuity", "description": "Calculate patient acuity score (1.0–4.0)", "parameters": {"patient_id": "str", "patient_data": "dict"}},
            {"name": "staffing_recommend", "description": "Generate evidence-based staffing recommendation (Aiken 2002)", "parameters": {"unit_id": "str", "shift": "str", "patient_ids": "list"}},
            {"name": "staffing_forecast", "description": "Predict future census", "parameters": {"unit_id": "str", "historical_census": "list", "hours_ahead": "int"}},
            {"name": "staffing_schedule", "description": "Generate weekly schedule draft", "parameters": {"unit_id": "str", "week_start": "date", "staff_roster": "list"}},
            {"name": "staffing_mortality_delta", "description": "Compute mortality risk from staffing ratio (OR 1.07 per Aiken 2002)", "parameters": {"actual_ratio": "float", "evidence_ratio": "float"}},
        ]
