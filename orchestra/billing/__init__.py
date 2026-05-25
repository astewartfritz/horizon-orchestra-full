from __future__ import annotations

"""Billing package for Horizon Orchestra.

Three layers:

1. :mod:`stripe_billing` — Core Stripe API integration (customers,
   subscriptions, invoices, webhooks, usage metering).
2. :mod:`architecture_billing` — Architecture-aware feature gating,
   per-architecture limits, cost estimation, and metering.
3. :mod:`middleware` — Drop-in middleware that wraps any architecture
   backend (A-E) with automatic billing enforcement.
"""

from .stripe_billing import (
    StripeBilling,
    BillingConfig,
    Subscription,
    UsageMeter,
    Invoice,
    PricingTier,
    PRICING_TIERS,
)
from .architecture_billing import (
    Architecture,
    ArchitectureProfile,
    ArchitectureLimits,
    ArchitectureMeter,
    ArchitectureBillingManager,
    CostEstimate,
    ARCHITECTURE_PROFILES,
    TIER_ARCHITECTURE_ACCESS,
    TIER_ARCHITECTURE_LIMITS,
    check_architecture_access,
    estimate_cost,
)
from .middleware import (
    BillingMiddleware,
    BillingWrappedAgent,
    BillingEvent,
    billing_gate,
)
from .scaffold import (
    BillingScaffold,
    ScaffoldConfig,
    TierTranslation,
    create_billing_router,
)

__all__ = [
    # Core Stripe
    "StripeBilling",
    "BillingConfig",
    "Subscription",
    "UsageMeter",
    "Invoice",
    "PricingTier",
    "PRICING_TIERS",
    # Architecture billing
    "Architecture",
    "ArchitectureProfile",
    "ArchitectureLimits",
    "ArchitectureMeter",
    "ArchitectureBillingManager",
    "CostEstimate",
    "ARCHITECTURE_PROFILES",
    "TIER_ARCHITECTURE_ACCESS",
    "TIER_ARCHITECTURE_LIMITS",
    "check_architecture_access",
    "estimate_cost",
    # Middleware
    "BillingMiddleware",
    "BillingWrappedAgent",
    "BillingEvent",
    "billing_gate",
    # Scaffold
    "BillingScaffold",
    "ScaffoldConfig",
    "TierTranslation",
    "create_billing_router",
]
