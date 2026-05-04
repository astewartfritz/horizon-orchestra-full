"""
EarlyWarningAgent — NEWS2 and MEWS patient deterioration detection.

Clinical evidence:
- NEWS2 AUROC 0.894 for death, 0.857 for ICU (Smith et al 2013, PMID 23295778)
  https://pubmed.ncbi.nlm.nih.gov/23295778/
- NEWS2 vs MEWS: 0.831 vs 0.757 across 362,000 encounters, 7 hospitals
  (Edelson et al 2024, JAMA Network Open, PMID 39405061)
  https://pubmed.ncbi.nlm.nih.gov/39405061/
- NEWS2 ≥5: Sensitivity 88.3%, Specificity 94.4% for mortality
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12550795/
- MEWS ≥5: OR 5.4 for death, OR 10.9 for ICU (Subbe 2001, PMID 11588210)
  https://pubmed.ncbi.nlm.nih.gov/11588210/
- Endorsed by NHS England / RCP: https://www.rcp.ac.uk/resources/national-early-warning-score-news-2/
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from orchestra.guardian.audit_ledger import AuditLedger
    _ledger = AuditLedger()
except ImportError:
    _ledger = None


@dataclass
class VitalsBundle:
    patient_id: str
    timestamp: datetime
    respiratory_rate: int
    spo2: float
    supplemental_oxygen: bool
    hypercapnic_risk: bool
    systolic_bp: int
    heart_rate: int
    consciousness: str  # "alert", "voice", "pain", "unresponsive"
    temperature: float  # Celsius
    nurse_id: str = ""

    def to_dict(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in self.__dict__.items()}


@dataclass
class NEWS2Score:
    patient_id: str
    timestamp: datetime
    total_score: int
    component_scores: Dict[str, int]
    risk_level: str
    clinical_response: str
    alert_triggered: bool
    vitals: Optional[VitalsBundle] = None
    auroc_reference: float = 0.894  # Smith et al 2013

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "vitals"}
        d["timestamp"] = self.timestamp.isoformat()
        if self.vitals:
            d["vitals"] = self.vitals.to_dict()
        return d


@dataclass
class MEWSScore:
    patient_id: str
    timestamp: datetime
    total_score: int
    risk_level: str
    alert_triggered: bool
    vitals: Optional[VitalsBundle] = None

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "vitals"}
        d["timestamp"] = self.timestamp.isoformat()
        return d


@dataclass
class Alert:
    patient_id: str
    alert_type: str
    score: int
    risk_level: str
    message: str
    recommended_action: str
    triggered_at: datetime
    vitals: Optional[VitalsBundle] = None

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["triggered_at"] = self.triggered_at.isoformat()
        if self.vitals:
            d["vitals"] = self.vitals.to_dict()
        return d


@dataclass
class VitalsTrend:
    patient_id: str
    period_hours: int
    news2_scores: List[NEWS2Score]
    trend_direction: str
    rate_of_change: float
    predicted_next_score: Optional[float]
    recommendation: str


@dataclass
class RRTBrief:
    """Rapid Response Team brief for RRT activation."""
    patient_id: str
    triggering_score: NEWS2Score
    current_vitals: VitalsBundle
    recent_trend: Optional[VitalsTrend]
    relevant_history: str
    current_medications: List[str]
    allergies: List[str]
    attending_physician: str
    full_code_status: str
    sbar_brief: str


class EarlyWarningAgent:
    """
    NEWS2/MEWS patient deterioration monitoring agent.

    Evidence:
    - PMID 23295778: AUROC 0.894 (death), 0.857 (ICU)
    - PMID 39405061: NEWS2 0.831 vs MEWS 0.757 (362K encounters)
    - RCP NEWS2: https://www.rcp.ac.uk/resources/national-early-warning-score-news-2/
    """

    EVIDENCE = {
        "smith_2013": "https://pubmed.ncbi.nlm.nih.gov/23295778/",
        "edelson_2024": "https://pubmed.ncbi.nlm.nih.gov/39405061/",
        "singapore_2025": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12550795/",
        "subbe_2001": "https://pubmed.ncbi.nlm.nih.gov/11588210/",
        "rcp_news2": "https://www.rcp.ac.uk/resources/national-early-warning-score-news-2/",
    }

    def score_news2(self, vitals: VitalsBundle) -> NEWS2Score:
        """
        Compute NEWS2 score per RCP 2017 protocol.
        7 parameters: RR, SpO2, supplemental O2, systolic BP, HR, consciousness, temperature.
        """
        scores: Dict[str, int] = {}

        # Respiratory rate
        rr = vitals.respiratory_rate
        if rr <= 8:
            scores["respiratory_rate"] = 3
        elif rr <= 11:
            scores["respiratory_rate"] = 1
        elif rr <= 20:
            scores["respiratory_rate"] = 0
        elif rr <= 24:
            scores["respiratory_rate"] = 2
        else:
            scores["respiratory_rate"] = 3

        # SpO2 — Scale 1 (standard) vs Scale 2 (hypercapnic)
        spo2 = vitals.spo2
        if vitals.hypercapnic_risk:
            # Scale 2: target 88–92% for COPD/hypercapnic patients
            if spo2 <= 83:
                scores["spo2"] = 3
            elif spo2 <= 85:
                scores["spo2"] = 2
            elif spo2 <= 87:
                scores["spo2"] = 1
            elif spo2 <= 92:
                scores["spo2"] = 0
            elif spo2 <= 94:
                scores["spo2"] = 1
            elif spo2 <= 96:
                scores["spo2"] = 2
            else:
                scores["spo2"] = 3
        else:
            # Scale 1: standard
            if spo2 <= 91:
                scores["spo2"] = 3
            elif spo2 <= 93:
                scores["spo2"] = 2
            elif spo2 <= 95:
                scores["spo2"] = 1
            else:
                scores["spo2"] = 0

        # Supplemental oxygen (Scale 1 only)
        if not vitals.hypercapnic_risk:
            scores["supplemental_oxygen"] = 2 if vitals.supplemental_oxygen else 0
        else:
            scores["supplemental_oxygen"] = 2 if (vitals.supplemental_oxygen and spo2 > 92) else 0

        # Systolic BP
        sbp = vitals.systolic_bp
        if sbp <= 90:
            scores["systolic_bp"] = 3
        elif sbp <= 100:
            scores["systolic_bp"] = 2
        elif sbp <= 110:
            scores["systolic_bp"] = 1
        elif sbp <= 219:
            scores["systolic_bp"] = 0
        else:
            scores["systolic_bp"] = 3

        # Heart rate
        hr = vitals.heart_rate
        if hr <= 40:
            scores["heart_rate"] = 3
        elif hr <= 50:
            scores["heart_rate"] = 1
        elif hr <= 90:
            scores["heart_rate"] = 0
        elif hr <= 110:
            scores["heart_rate"] = 1
        elif hr <= 130:
            scores["heart_rate"] = 2
        else:
            scores["heart_rate"] = 3

        # Consciousness (AVPU)
        consciousness_map = {"alert": 0, "voice": 3, "pain": 3, "unresponsive": 3}
        scores["consciousness"] = consciousness_map.get(vitals.consciousness.lower(), 3)

        # Temperature (Celsius)
        temp = vitals.temperature
        if temp <= 35.0:
            scores["temperature"] = 3
        elif temp <= 36.0:
            scores["temperature"] = 1
        elif temp <= 38.0:
            scores["temperature"] = 0
        elif temp <= 39.0:
            scores["temperature"] = 1
        else:
            scores["temperature"] = 2

        total = sum(scores.values())
        single_param_3 = any(v == 3 for v in scores.values())

        # Risk level per RCP protocol
        if total >= 7:
            risk = "high"
        elif total >= 5 or single_param_3:
            risk = "medium"
        else:
            risk = "low"

        clinical_response = self.compute_news2_clinical_response(total, single_param_3)
        alert_triggered = risk in ("medium", "high")

        result = NEWS2Score(
            patient_id=vitals.patient_id,
            timestamp=vitals.timestamp,
            total_score=total,
            component_scores=scores,
            risk_level=risk,
            clinical_response=clinical_response,
            alert_triggered=alert_triggered,
            vitals=vitals,
        )

        if _ledger and alert_triggered:
            try:
                _ledger.log(event="news2_alert", data={"patient_id": vitals.patient_id, "score": total, "risk": risk})
            except Exception:
                pass

        return result

    def score_mews(self, vitals: VitalsBundle) -> MEWSScore:
        """Compute Modified Early Warning Score (5 parameters)."""
        score = 0

        # Systolic BP
        sbp = vitals.systolic_bp
        if sbp <= 70:
            score += 3
        elif sbp <= 80:
            score += 2
        elif sbp <= 100:
            score += 1
        elif sbp <= 199:
            score += 0
        else:
            score += 2

        # Heart rate
        hr = vitals.heart_rate
        if hr < 40:
            score += 2
        elif hr <= 50:
            score += 1
        elif hr <= 100:
            score += 0
        elif hr <= 110:
            score += 1
        elif hr <= 129:
            score += 2
        else:
            score += 3

        # Respiratory rate
        rr = vitals.respiratory_rate
        if rr < 9:
            score += 2
        elif rr <= 14:
            score += 0
        elif rr <= 20:
            score += 1
        elif rr <= 29:
            score += 2
        else:
            score += 3

        # Temperature
        temp = vitals.temperature
        if temp < 35.0:
            score += 2
        elif temp <= 38.4:
            score += 0
        else:
            score += 2

        # Consciousness (AVPU)
        avpu_map = {"alert": 0, "voice": 1, "pain": 2, "unresponsive": 3}
        score += avpu_map.get(vitals.consciousness.lower(), 3)

        if score < 3:
            risk = "low"
        elif score < 5:
            risk = "moderate"
        else:
            risk = "urgent"

        return MEWSScore(
            patient_id=vitals.patient_id,
            timestamp=vitals.timestamp,
            total_score=score,
            risk_level=risk,
            alert_triggered=score >= 5,
            vitals=vitals,
        )

    @staticmethod
    def compute_news2_clinical_response(score: int, single_param_3: bool = False) -> str:
        """Return RCP-specified clinical response for a NEWS2 score."""
        if score >= 7:
            return ("High: Emergency assessment by clinical team with critical care "
                    "competencies within 30 min. Consider transfer to higher level of care.")
        elif score >= 5 or single_param_3:
            return ("Medium: Urgent review by competent clinician within 30-60 min. "
                    "Increase monitoring frequency to minimum 1-hourly.")
        elif score >= 1:
            return "Low: Minimum 4–6 hourly monitoring. Nurse assessment."
        else:
            return "Routine: Minimum 12-hourly monitoring."

    def trend_analysis(self, patient_id: str, historical_scores: List[NEWS2Score]) -> VitalsTrend:
        """Analyze NEWS2 score trend over time."""
        if not historical_scores:
            return VitalsTrend(
                patient_id=patient_id, period_hours=0, news2_scores=[],
                trend_direction="unknown", rate_of_change=0.0,
                predicted_next_score=None, recommendation="Insufficient data for trend analysis.",
            )

        sorted_scores = sorted(historical_scores, key=lambda s: s.timestamp)
        first_score = sorted_scores[0].total_score
        last_score = sorted_scores[-1].total_score
        delta = last_score - first_score

        if len(sorted_scores) >= 2:
            hours = max(0.1, (sorted_scores[-1].timestamp - sorted_scores[0].timestamp).total_seconds() / 3600)
            rate = delta / hours
        else:
            hours = 0
            rate = 0.0

        if delta > 1:
            direction = "deteriorating"
            rec = "Patient deteriorating. Increase monitoring frequency. Consider urgent clinical review."
        elif delta < -1:
            direction = "improving"
            rec = "Patient improving. Continue current plan."
        else:
            direction = "stable"
            rec = "Patient stable. Continue routine monitoring per NEWS2 protocol."

        predicted = last_score + rate * 4 if rate != 0 else None  # predict 4h ahead
        if predicted is not None:
            predicted = max(0, min(20, predicted))

        return VitalsTrend(
            patient_id=patient_id, period_hours=int(hours),
            news2_scores=sorted_scores, trend_direction=direction,
            rate_of_change=round(rate, 2), predicted_next_score=round(predicted, 1) if predicted else None,
            recommendation=rec,
        )

    def generate_rapid_response_brief(self, patient_id: str, news2: NEWS2Score,
                                       recent_vitals: List[VitalsBundle],
                                       history: str = "", meds: List[str] = None,
                                       allergies: List[str] = None,
                                       attending: str = "", code_status: str = "Full code") -> RRTBrief:
        """Generate structured brief for Rapid Response Team activation."""
        trend = self.trend_analysis(patient_id, [news2]) if news2 else None

        sbar = (
            f"SITUATION: {patient_id} — NEWS2 score {news2.total_score} ({news2.risk_level} risk). "
            f"Triggering RRT activation.\n"
            f"BACKGROUND: {history or 'See chart'}. Attending: {attending or 'on call'}. "
            f"Code status: {code_status}.\n"
            f"ASSESSMENT: {news2.clinical_response}\n"
            f"RECOMMENDATION: Immediate bedside assessment required. "
            f"Consider ICU transfer if score ≥7."
        )

        return RRTBrief(
            patient_id=patient_id, triggering_score=news2,
            current_vitals=news2.vitals if news2.vitals else recent_vitals[-1] if recent_vitals else None,
            recent_trend=trend, relevant_history=history or "See chart",
            current_medications=meds or [], allergies=allergies or [],
            attending_physician=attending or "On call",
            full_code_status=code_status, sbar_brief=sbar,
        )

    def get_tools(self) -> List[dict]:
        """Return tool definitions for agent loop."""
        return [
            {"name": "score_news2", "description": "Compute NEWS2 early warning score from vitals (AUROC 0.894)", "parameters": {"vitals": "VitalsBundle"}},
            {"name": "score_mews", "description": "Compute MEWS score from vitals", "parameters": {"vitals": "VitalsBundle"}},
            {"name": "trend_analysis", "description": "Analyze NEWS2 score trend and predict deterioration", "parameters": {"patient_id": "str", "historical_scores": "list"}},
            {"name": "generate_rrt_brief", "description": "Generate Rapid Response Team activation brief", "parameters": {"patient_id": "str", "news2": "NEWS2Score"}},
        ]
