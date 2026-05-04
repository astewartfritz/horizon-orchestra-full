"""
Orchestra Nursing Vertical — Evidence-Based AI Agents for Nursing.

6 agents, grounded in peer-reviewed clinical research:
- ShiftScribeAgent: AI documentation (AHRQ ENDburden, PMID 35668677)
- HandoffAgent: SBAR shift handoffs (JC Sentinel Events, PMID 30139905)
- MedReconciliationAgent: Medication safety 5 Rights (ISMP, PMID 38902018)
- EarlyWarningAgent: NEWS2/MEWS deterioration detection (PMID 23295778, PMID 39405061)
- StaffingOptimizerAgent: Acuity-based staffing (PMID 12387650, PMID 24581683)
- NurseEducationCoach: Just-in-time clinical education (PMID 32833397)
"""

try:
    from orchestra.verticals.nursing.shift_scribe import ShiftScribeAgent
except ImportError:
    ShiftScribeAgent = None

try:
    from orchestra.verticals.nursing.handoff_agent import HandoffAgent
except ImportError:
    HandoffAgent = None

try:
    from orchestra.verticals.nursing.med_reconciliation import MedReconciliationAgent
except ImportError:
    MedReconciliationAgent = None

try:
    from orchestra.verticals.nursing.early_warning import EarlyWarningAgent
except ImportError:
    EarlyWarningAgent = None

try:
    from orchestra.verticals.nursing.staffing_optimizer import StaffingOptimizerAgent
except ImportError:
    StaffingOptimizerAgent = None

try:
    from orchestra.verticals.nursing.education_coach import NurseEducationCoach
except ImportError:
    NurseEducationCoach = None

__all__ = [
    "ShiftScribeAgent",
    "HandoffAgent",
    "MedReconciliationAgent",
    "EarlyWarningAgent",
    "StaffingOptimizerAgent",
    "NurseEducationCoach",
]
