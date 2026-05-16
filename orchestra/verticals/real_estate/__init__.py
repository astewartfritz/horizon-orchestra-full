"""Real Estate vertical agent pack for Horizon Orchestra.

Provides domain-specialized agents for property analysis and lease
management workflows. Designed for commercial real estate firms like
CBRE, JLL, Cushman & Wakefield, and similar enterprises.

Agents
------
:class:`PropertyAnalysisAgent`
    DCF valuation, cap rate analysis, comparable sales, rent roll
    analysis, zoning compliance, and investment memo generation.

:class:`LeaseManagementAgent`
    Lease abstracting, rent escalation calculation, CAM reconciliation,
    tenant creditworthiness, and lease-vs-buy analysis.

Pre-Built Teams
---------------
:func:`acquisitions_team`
    Acquisitions pipeline (analyst, underwriter, legal).

:func:`asset_management_team`
    Asset management (PM, leasing agent, financial analyst).

:func:`leasing_team`
    Leasing team (leasing agent, market analyst, legal).
"""

from __future__ import annotations

from .property_analysis import PropertyAnalysisAgent
from .lease_management import LeaseManagementAgent
from .pre_built_teams import (
    acquisitions_team,
    asset_management_team,
    leasing_team,
)

__all__ = [
    "PropertyAnalysisAgent",
    "LeaseManagementAgent",
    "acquisitions_team",
    "asset_management_team",
    "leasing_team",
]
