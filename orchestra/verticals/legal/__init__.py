"""Legal vertical agent pack for Horizon Orchestra.

Provides domain-specialized agents for enterprise legal operations,
targeting Am Law 100 firms (Kirkland & Ellis, Sidley Austin, Latham &
Watkins) and Fortune 500 in-house legal departments.

Agents
------
:class:`ContractAnalysisAgent`
    NDA review, MSA analysis, M&A due diligence, ISDA agreements,
    real estate leases, employment agreements, IP licenses, SaaS
    agreements.  Risk scoring, playbook enforcement, redlining.

:class:`LegalResearchAgent`
    Case law research, statutory analysis, circuit-split detection,
    PACER/CourtListener integration, legal memo and brief drafting.

:class:`EDiscoveryAgent`
    Document review, privilege detection, responsive coding,
    deduplication, concept clustering, EDRM-compliant workflows.

:class:`MatterManagementAgent`
    Time tracking, budget management, staffing optimization, bill
    review, AFA (Alternative Fee Arrangements), client reporting.

Pre-Built Teams
---------------
:func:`ma_due_diligence_team`
    M&A deal team (contract analysis + research + eDiscovery).

:func:`litigation_support_team`
    eDiscovery + legal research pipeline.

:func:`corporate_legal_team`
    Contracts + compliance + matter management.

:func:`regulatory_counsel_team`
    Regulatory research + compliance + government relations.
"""

from __future__ import annotations

from .contract_analysis import ContractAnalysisAgent
from .legal_research import LegalResearchAgent
from .ediscovery import EDiscoveryAgent
from .matter_management import MatterManagementAgent
from .pre_built_teams import (
    ma_due_diligence_team,
    litigation_support_team,
    corporate_legal_team,
    regulatory_counsel_team,
)

__all__ = [
    "ContractAnalysisAgent",
    "LegalResearchAgent",
    "EDiscoveryAgent",
    "MatterManagementAgent",
    "ma_due_diligence_team",
    "litigation_support_team",
    "corporate_legal_team",
    "regulatory_counsel_team",
]
