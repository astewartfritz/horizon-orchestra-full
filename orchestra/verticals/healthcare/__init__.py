"""Horizon Orchestra — Healthcare Industry Vertical.

Domain-specific AI agents for pharmaceutical companies, health
systems, and medical device manufacturers.

Target customers
----------------
Johnson & Johnson, Moderna, Pfizer, Merck, AstraZeneca, Roche,
Mayo Clinic, HCA Healthcare.

Agents
------
:class:`ClinicalTrialAgent`
    Clinical trial operations: protocol design, patient screening,
    AE detection, CIOMS/E2B safety reports, enrollment forecasting.

:class:`PharmacovigilanceAgent`
    Drug safety surveillance: signal detection, literature monitoring,
    PSUR/PBRER authoring, benefit-risk assessment.

:class:`FHIRAgent`
    FHIR R4/R5 healthcare data integration: Patient, Observation,
    Condition, Medication resources, CDS Hooks, Bulk Data Export.

:class:`MedicalCodingAgent`
    Medical coding for revenue cycle: ICD-10-CM/PCS, CPT, DRG,
    HCC risk adjustment, E/M coding.

:class:`RegulatoryAgent`
    FDA/EMA regulatory submissions: eCTD assembly, label review,
    guidance monitoring, IND/NDA/BLA support.

Pre-built teams
---------------
See :mod:`orchestra.verticals.healthcare.pre_built_teams` for
ready-to-use team factories.
"""

from __future__ import annotations

from .clinical_trials import ClinicalTrialAgent
from .pharmacovigilance import PharmacovigilanceAgent
from .fhir_integration import FHIRAgent
from .medical_coding import MedicalCodingAgent
from .regulatory_submissions import RegulatoryAgent

__all__ = [
    "ClinicalTrialAgent",
    "PharmacovigilanceAgent",
    "FHIRAgent",
    "MedicalCodingAgent",
    "RegulatoryAgent",
]
