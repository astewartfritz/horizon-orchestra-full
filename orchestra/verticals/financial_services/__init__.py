"""Financial Services vertical agent pack for Horizon Orchestra.

Provides domain-specialized agents for investment banking, risk/compliance,
and portfolio management workflows. Designed for institutional-grade
requirements at firms like JPMorgan, Goldman Sachs, and similar enterprises.

Agents
------
:class:`InvestmentBankingAgent`
    DCF modelling, comps analysis, LBO models, M&A advisory, fairness
    opinions, and capital-structure analysis.

:class:`FinancialRiskAgent`
    VaR calculation, stress testing, Basel III compliance, AML/KYC,
    trading surveillance, and CCAR scenario analysis.

:class:`PortfolioManagementAgent`
    Portfolio optimization, factor exposure analysis, attribution,
    ESG scoring, Monte Carlo simulation, and options analytics.

Pre-Built Teams
---------------
:func:`ma_advisory_team`
    M&A advisory pipeline (banker, risk, legal review).

:func:`risk_operations_team`
    Risk operations centre (risk analyst, compliance, surveillance).

:func:`asset_management_team`
    Asset management desk (PM, research, trading).
"""

from __future__ import annotations

from .investment_banking import InvestmentBankingAgent
from .risk_compliance import FinancialRiskAgent
from .portfolio_management import PortfolioManagementAgent
from .pre_built_teams import (
    ma_advisory_team,
    risk_operations_team,
    asset_management_team,
)

__all__ = [
    "InvestmentBankingAgent",
    "FinancialRiskAgent",
    "PortfolioManagementAgent",
    "ma_advisory_team",
    "risk_operations_team",
    "asset_management_team",
]
