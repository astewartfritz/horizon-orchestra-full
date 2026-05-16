"""Manufacturing / MRO vertical agent pack for Horizon Orchestra.

Provides domain-specialized agents for production planning, quality
management, and supply chain workflows. Designed for enterprise
manufacturers like GE, 3M, Siemens, and similar organisations.

Agents
------
:class:`ProductionPlanningAgent`
    MRP calculations, production scheduling, capacity planning, OEE
    analysis, and preventive maintenance planning.

:class:`QualityManagementAgent`
    SPC analysis, FMEA, 8D reporting, Cpk/Ppk calculation, and
    ISO 9001 / AS9100 compliance.

:class:`ManufacturingSupplyChainAgent`
    Supplier risk analysis, safety stock optimization, S&OP planning,
    make-vs-buy analysis, and total cost of ownership.

Pre-Built Teams
---------------
:func:`lean_manufacturing_team`
    Lean manufacturing pipeline (planner, quality, continuous improvement).

:func:`quality_ops_team`
    Quality operations (quality engineer, supplier quality, audit).

:func:`scm_team`
    Supply chain management (procurement, logistics, demand planner).
"""

from __future__ import annotations

from .production_planning import ProductionPlanningAgent
from .quality_management import QualityManagementAgent
from .supply_chain import ManufacturingSupplyChainAgent
from .pre_built_teams import (
    lean_manufacturing_team,
    quality_ops_team,
    scm_team,
)

__all__ = [
    "ProductionPlanningAgent",
    "QualityManagementAgent",
    "ManufacturingSupplyChainAgent",
    "lean_manufacturing_team",
    "quality_ops_team",
    "scm_team",
]
