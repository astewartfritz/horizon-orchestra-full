"""Retail / CPG vertical agent pack for Horizon Orchestra.

Provides domain-specialized agents for merchandising, customer experience,
and e-commerce workflows. Designed for enterprise retailers like Walmart,
Target, Kroger, and similar organisations.

Agents
------
:class:`MerchandisingAgent`
    Assortment optimization, pricing strategy, promotion effectiveness,
    planogram management, and category performance analysis.

:class:`RetailCXAgent`
    Customer sentiment, personalization, churn prediction, segmentation,
    loyalty programs, and NPS analysis.

:class:`ECommerceAgent`
    Product listing optimization, conversion funnel analysis, fraud
    detection, cart abandonment, and marketplace performance.

Pre-Built Teams
---------------
:func:`category_management_team`
    Category management (buyer, analyst, pricing specialist).

:func:`cx_ops_team`
    Customer experience operations (CX analyst, loyalty, support).

:func:`digital_commerce_team`
    Digital commerce (e-commerce manager, SEO, marketing).
"""

from __future__ import annotations

from .merchandising import MerchandisingAgent
from .customer_experience import RetailCXAgent
from .ecommerce import ECommerceAgent
from .pre_built_teams import (
    category_management_team,
    cx_ops_team,
    digital_commerce_team,
)

__all__ = [
    "MerchandisingAgent",
    "RetailCXAgent",
    "ECommerceAgent",
    "category_management_team",
    "cx_ops_team",
    "digital_commerce_team",
]
