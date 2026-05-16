"""Horizon Orchestra — Stripe Billing Integration.

Manages subscription plans, usage metering, customer lifecycle, and
billing for Orchestra's multi-model, multi-modal agentic platform.

Pricing is designed around Orchestra's unique capabilities:
- Multi-model backbone access (Gemma 4, Claude, Kimi, Sonar)
- Speech/audio pipeline (STT/TTS with 12 backends)
- Architecture tiers (Monolithic, Swarm, Production)
- Security policy levels
- Domain-aware routing

Uses Stripe's meter events API for real-time usage tracking and
graduated pricing for compute-intensive overages.

Usage::

    from orchestra.stripe_billing import BillingManager, PricingTier

    billing = BillingManager()

    # Create a customer on Builder plan
    customer = await billing.create_customer(
        email="dev@example.com",
        name="Ashton Fritz",
        tier=PricingTier.BUILDER,
    )

    # Record usage
    await billing.record_llm_usage(customer.stripe_customer_id, input_tokens=5000, output_tokens=1200, model="gemma-4-31b")
    await billing.record_stt_usage(customer.stripe_customer_id, duration_seconds=120, backend="whisper_api")
    await billing.record_tool_usage(customer.stripe_customer_id, tool_name="web_search", count=1)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    import stripe
    from stripe import StripeClient  # type: ignore[attr-defined]
    HAS_STRIPE = True
except ImportError:
    stripe = None  # type: ignore[assignment]
    StripeClient = None  # type: ignore[assignment]
    HAS_STRIPE = False

__all__ = [
    # Enums
    "PricingTier",
    "UsageType",
    # Dataclasses
    "TierConfig",
    "Customer",
    "UsageRecord",
    "UsageSummary",
    "BillingEvent",
    # Managers
    "BillingManager",
    "NullBillingManager",
    # Constants
    "MODEL_COSTS",
    "STT_COSTS",
    "TTS_COSTS",
    "TIER_CONFIGS",
    "STRIPE_METERS",
]

log = logging.getLogger("orchestra.stripe_billing")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PricingTier(str, Enum):
    """Subscription tier for an Orchestra customer."""
    MAKER = "maker"
    BUILDER = "builder"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class UsageType(str, Enum):
    """Billable usage dimensions tracked per customer."""
    LLM_INPUT_TOKENS = "llm_input_tokens"
    LLM_OUTPUT_TOKENS = "llm_output_tokens"
    TOOL_CALLS = "tool_calls"
    SWARM_SPAWNS = "swarm_spawns"
    STT_SECONDS = "stt_seconds"
    TTS_CHARACTERS = "tts_characters"
    MEMORY_ENTRIES = "memory_entries"
    CODE_EXECUTIONS = "code_executions"
    BROWSER_ACTIONS = "browser_actions"


# ---------------------------------------------------------------------------
# Cost tables
# ---------------------------------------------------------------------------

# (input_per_1m_tokens, output_per_1m_tokens) in USD
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "kimi-k2.5": (0.60, 2.50),
    "gemma-4-31b": (0.15, 0.60),
    "gemma-4-26b-moe": (0.10, 0.40),
    "gemma-4-e4b": (0.0, 0.0),
    "gemma-4-e2b": (0.0, 0.0),
    # Anthropic via direct API
    "claude-opus-4.6": (5.00, 25.00),
    "claude-sonnet-4.6": (3.00, 15.00),
    "claude-haiku-4.5": (1.00, 5.00),
    # OpenRouter variants
    "claude-opus-4.6-openrouter": (5.00, 25.00),
    "claude-sonnet-4.6-openrouter": (3.00, 15.00),
    "claude-haiku-4.5-openrouter": (1.00, 5.00),
    # Other providers
    "gpt-5.4": (2.00, 10.00),
    "grok-3": (0.30, 1.50),
    "sonar": (1.00, 1.00),
    "sonar-pro": (3.00, 15.00),
    "sonar-reasoning-pro": (3.00, 15.00),
    # Local / free models
    "kimi-k2.5-local": (0.0, 0.0),
    "gemma-4-31b-local": (0.0, 0.0),
    "gemma-4-ollama": (0.0, 0.0),
    "ollama-local": (0.0, 0.0),
}

# STT costs in USD per minute
STT_COSTS: dict[str, float] = {
    "whisper_api": 0.006,          # OpenAI Whisper API
    "deepgram_nova3": 0.0077,      # Deepgram Nova-3
    "groq_whisper": 0.04 / 60.0,  # Groq Whisper: $0.04/hr → per-minute
    "elevenlabs_scribe": 0.40 / 60.0,  # ElevenLabs Scribe: $0.40/hr → per-minute
    # Local backends: free
    "whisper_local": 0.0,
    "faster_whisper": 0.0,
}

# TTS costs in USD per 1,000 characters
TTS_COSTS: dict[str, float] = {
    "openai_tts": 15.0 / 1_000,   # $15/1M chars → per-1k
    "elevenlabs": 0.10,            # midpoint of $0.08–0.12/1k chars
    "deepgram_aura": 30.0 / 1_000,  # $30/1M chars → per-1k
    # Local backends: free
    "kokoro": 0.0,
    "fish_speech": 0.0,
    "chatterbox": 0.0,
}

# Stripe meter event names (registered with Stripe's Billing Meter API)
STRIPE_METERS: dict[str, str] = {
    "llm_input_tokens": "orchestra_llm_input_tokens",
    "llm_output_tokens": "orchestra_llm_output_tokens",
    "tool_calls": "orchestra_tool_calls",
    "swarm_spawns": "orchestra_swarm_spawns",
    "stt_seconds": "orchestra_stt_seconds",
    "tts_characters": "orchestra_tts_characters",
    "memory_entries": "orchestra_memory_entries",
    "code_executions": "orchestra_code_executions",
    "browser_actions": "orchestra_browser_actions",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TierConfig:
    """Complete configuration for a pricing tier."""
    name: str
    display_name: str
    price_monthly: int                    # cents per month (0 = free)
    stripe_price_id: str = ""            # set during setup_stripe_products()

    # Model access
    allowed_models: set[str] = field(default_factory=set)

    # Audio access
    allowed_stt_backends: set[str] = field(default_factory=set)
    allowed_tts_backends: set[str] = field(default_factory=set)

    # Architecture and security
    allowed_architectures: set[str] = field(default_factory=set)
    allowed_security_policies: set[str] = field(default_factory=set)

    # Feature flags
    enable_domain_router: bool = False
    enable_voice_cloning: bool = False

    # Usage limits (0 = unlimited)
    max_tool_calls_monthly: int = 0
    max_sessions_daily: int = 0
    max_swarm_agents: int = 0
    max_memory_entries: int = 0

    # Included audio allowances
    included_stt_minutes: int = 0
    included_tts_minutes: int = 0

    # Included model credit (cents)
    included_model_credit_cents: int = 0

    # Overage pricing
    overage_tool_call_cents: int = 0     # mills (1/10 cent) — $0.001 = 1 mill
    markup_percentage: float = 0.30      # 30% on pass-through model costs


@dataclass
class Customer:
    """Represents an Orchestra billing customer."""
    id: str                               # internal UUID
    stripe_customer_id: str
    email: str
    name: str
    tier: PricingTier
    stripe_subscription_id: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageRecord:
    """A single raw usage event before billing is applied."""
    customer_id: str
    usage_type: UsageType
    value: float                          # tokens, seconds, characters, counts
    model: str = ""                       # which model or backend
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageSummary:
    """Aggregated usage and cost summary for a billing period."""
    customer_id: str
    tier: PricingTier
    period_start: float
    period_end: float
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cost_cents: int = 0              # raw model cost before markup
    tool_calls: int = 0
    swarm_spawns: int = 0
    stt_seconds: float = 0.0
    stt_cost_cents: int = 0
    tts_characters: int = 0
    tts_cost_cents: int = 0
    memory_entries: int = 0
    code_executions: int = 0
    browser_actions: int = 0
    total_cost_cents: int = 0            # after markup + overages + credits
    model_credit_remaining_cents: int = 0
    overages: dict[str, int] = field(default_factory=dict)  # per-type overage cents


@dataclass
class BillingEvent:
    """Represents a single billable event for the audit trail."""
    event_id: str
    customer_id: str
    usage_type: UsageType
    value: float
    unit_cost_cents: float               # cost per unit (fractional OK here)
    total_cost_cents: float
    model: str = ""
    timestamp: float = field(default_factory=time.time)
    stripe_meter_event_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tier configurations
# ---------------------------------------------------------------------------

# Shared model sets, built incrementally so each tier is additive.
_FREE_MODELS: set[str] = {
    "gemma-4-e4b",
    "gemma-4-e2b",
    "gemma-4-ollama",
    "ollama-local",
}

_BUILDER_MODELS: set[str] = _FREE_MODELS | {
    "gemma-4-31b",
    "gemma-4-26b-moe",
    "gemma-4-31b-local",
    "kimi-k2.5",
    "kimi-k2.5-local",
    "grok-3",
    "sonar",
    "sonar-pro",
    "sonar-reasoning-pro",
}

_PRO_MODELS: set[str] = _BUILDER_MODELS | {
    "claude-opus-4.6",
    "claude-sonnet-4.6",
    "claude-haiku-4.5",
    "claude-opus-4.6-openrouter",
    "claude-sonnet-4.6-openrouter",
    "claude-haiku-4.5-openrouter",
    "gpt-5.4",
}

_ENTERPRISE_MODELS: set[str] = _PRO_MODELS  # same set, fast mode unlocked separately

_FREE_STT: set[str] = {"whisper_local", "faster_whisper"}
_BUILDER_STT: set[str] = _FREE_STT | {"whisper_api", "deepgram_nova3", "groq_whisper"}
_PRO_STT: set[str] = _BUILDER_STT | {"elevenlabs_scribe"}
_ENTERPRISE_STT: set[str] = _PRO_STT

_FREE_TTS: set[str] = {"kokoro", "chatterbox"}
_BUILDER_TTS: set[str] = _FREE_TTS | {"openai_tts", "fish_speech"}
_PRO_TTS: set[str] = _BUILDER_TTS | {"elevenlabs", "deepgram_aura"}
_ENTERPRISE_TTS: set[str] = _PRO_TTS

TIER_CONFIGS: dict[PricingTier, TierConfig] = {
    PricingTier.MAKER: TierConfig(
        name="maker",
        display_name="Maker",
        price_monthly=0,
        allowed_models=_FREE_MODELS,
        allowed_stt_backends=_FREE_STT,
        allowed_tts_backends=_FREE_TTS,
        allowed_architectures={"A"},
        allowed_security_policies={"standard"},
        enable_domain_router=False,
        enable_voice_cloning=False,
        max_tool_calls_monthly=1_000,
        max_sessions_daily=10,
        max_swarm_agents=0,               # no swarm
        max_memory_entries=100,
        included_stt_minutes=60,
        included_tts_minutes=30,
        included_model_credit_cents=0,
        overage_tool_call_cents=1,        # $0.001 in mills
        markup_percentage=0.30,
    ),
    PricingTier.BUILDER: TierConfig(
        name="builder",
        display_name="Builder",
        price_monthly=2_900,              # $29.00
        allowed_models=_BUILDER_MODELS,
        allowed_stt_backends=_BUILDER_STT,
        allowed_tts_backends=_BUILDER_TTS,
        allowed_architectures={"A", "C"},
        allowed_security_policies={"standard", "strict"},
        enable_domain_router=False,
        enable_voice_cloning=False,
        max_tool_calls_monthly=50_000,
        max_sessions_daily=100,
        max_swarm_agents=5,
        max_memory_entries=5_000,
        included_stt_minutes=600,
        included_tts_minutes=120,
        included_model_credit_cents=1_000,  # $10.00
        overage_tool_call_cents=1,
        markup_percentage=0.30,
    ),
    PricingTier.PRO: TierConfig(
        name="pro",
        display_name="Pro",
        price_monthly=9_900,              # $99.00
        allowed_models=_PRO_MODELS,
        allowed_stt_backends=_PRO_STT,
        allowed_tts_backends=_PRO_TTS,
        allowed_architectures={"A", "C", "E"},
        allowed_security_policies={"standard", "strict", "safety_critical"},
        enable_domain_router=True,
        enable_voice_cloning=False,
        max_tool_calls_monthly=500_000,
        max_sessions_daily=0,             # unlimited
        max_swarm_agents=100,
        max_memory_entries=50_000,
        included_stt_minutes=6_000,
        included_tts_minutes=1_200,
        included_model_credit_cents=5_000,  # $50.00
        overage_tool_call_cents=1,
        markup_percentage=0.25,
    ),
    PricingTier.ENTERPRISE: TierConfig(
        name="enterprise",
        display_name="Enterprise",
        price_monthly=49_900,             # $499.00
        allowed_models=_ENTERPRISE_MODELS,
        allowed_stt_backends=_ENTERPRISE_STT,
        allowed_tts_backends=_ENTERPRISE_TTS,
        allowed_architectures={"A", "C", "E", "custom"},
        allowed_security_policies={"standard", "strict", "safety_critical", "custom"},
        enable_domain_router=True,
        enable_voice_cloning=True,
        max_tool_calls_monthly=0,         # unlimited
        max_sessions_daily=0,             # unlimited
        max_swarm_agents=0,               # unlimited
        max_memory_entries=0,             # unlimited
        included_stt_minutes=0,           # unlimited (0 = unlimited for enterprise)
        included_tts_minutes=0,
        included_model_credit_cents=20_000,  # $200.00
        overage_tool_call_cents=1,
        markup_percentage=0.20,
    ),
}


# ---------------------------------------------------------------------------
# BillingManager
# ---------------------------------------------------------------------------

class BillingManager:
    """Manages Stripe billing for Orchestra customers.

    Handles customer creation, subscription management, usage metering,
    and billing event recording.

    When Stripe is not configured (no API key), falls back to in-memory
    tracking suitable for local development and testing.
    """

    def __init__(self, stripe_api_key: str = "") -> None:
        """Initialise the billing manager.

        Args:
            stripe_api_key: Stripe secret key.  If omitted, read from
                ``STRIPE_SECRET_KEY`` environment variable.  If neither
                is present the manager runs in offline/fallback mode.
        """
        self._api_key: str = stripe_api_key or os.environ.get("STRIPE_SECRET_KEY", "")
        self._webhook_secret: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        self._stripe_client: Any = None

        # In-memory fallback stores (also used as cache for low-latency reads)
        self._customers: dict[str, Customer] = {}              # id → Customer
        self._customers_by_stripe: dict[str, Customer] = {}    # stripe_id → Customer
        self._events: dict[str, list[BillingEvent]] = defaultdict(list)  # customer_id → events
        self._meter_ids: dict[str, str] = {}                   # meter name → stripe meter ID
        self._product_ids: dict[str, str] = {}                 # tier name → stripe product ID

        # Stripe meter event batching
        self._pending_meter_events: list[dict[str, Any]] = []
        self._batch_lock = asyncio.Lock()

        if not HAS_STRIPE:
            log.warning(
                "stripe SDK not installed; running in offline mode. "
                "Install with: pip install stripe"
            )
        elif not self._api_key:
            log.warning(
                "STRIPE_SECRET_KEY not set; running in offline mode. "
                "Real Stripe calls will be skipped."
            )
        else:
            self._stripe_client = stripe.StripeClient(self._api_key)  # type: ignore[union-attr]
            log.info("BillingManager initialised with Stripe (live mode=%s)", not self._api_key.startswith("sk_test_"))

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def is_stripe_enabled(self) -> bool:
        """True when a live Stripe client is available."""
        return self._stripe_client is not None

    # ── Customer Management ──────────────────────────────────────────────────

    async def create_customer(
        self,
        email: str,
        name: str,
        tier: PricingTier = PricingTier.MAKER,
        payment_method_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Customer:
        """Create a new Orchestra customer and (optionally) subscribe them.

        Args:
            email: Customer email address.
            name: Display name.
            tier: Starting subscription tier (default: Maker / free).
            payment_method_id: Stripe payment method ID.  Required for
                paid tiers.
            metadata: Additional key/value pairs stored on the Stripe
                customer object.

        Returns:
            The newly created :class:`Customer`.
        """
        metadata = metadata or {}
        customer_id = str(uuid.uuid4())
        stripe_customer_id = ""
        stripe_subscription_id = ""

        tier_cfg = TIER_CONFIGS[tier]

        if self.is_stripe_enabled:
            try:
                stripe_meta = {
                    "orchestra_customer_id": customer_id,
                    "tier": tier.value,
                    **{str(k): str(v) for k, v in metadata.items()},
                }
                create_params: dict[str, Any] = {
                    "email": email,
                    "name": name,
                    "metadata": stripe_meta,
                }
                if payment_method_id:
                    create_params["payment_method"] = payment_method_id
                    create_params["invoice_settings"] = {
                        "default_payment_method": payment_method_id,
                    }

                stripe_customer = await asyncio.to_thread(
                    self._stripe_client.customers.create,
                    create_params,
                )
                stripe_customer_id = stripe_customer.id
                log.info("Created Stripe customer %s for %s", stripe_customer_id, email)

                # Subscribe to tier (skip for free tier or missing price ID)
                if tier_cfg.price_monthly > 0 and tier_cfg.stripe_price_id and payment_method_id:
                    sub = await asyncio.to_thread(
                        self._stripe_client.subscriptions.create,
                        {
                            "customer": stripe_customer_id,
                            "items": [{"price": tier_cfg.stripe_price_id}],
                            "payment_behavior": "default_incomplete",
                            "expand": ["latest_invoice.payment_intent"],
                        },
                    )
                    stripe_subscription_id = sub.id
                    log.info(
                        "Created Stripe subscription %s (tier=%s) for customer %s",
                        stripe_subscription_id,
                        tier.value,
                        stripe_customer_id,
                    )

            except Exception as exc:  # noqa: BLE001
                log.error("Stripe customer creation failed: %s", exc)
                stripe_customer_id = f"offline_{customer_id}"
        else:
            stripe_customer_id = f"offline_{customer_id}"

        customer = Customer(
            id=customer_id,
            stripe_customer_id=stripe_customer_id,
            email=email,
            name=name,
            tier=tier,
            stripe_subscription_id=stripe_subscription_id,
            created_at=time.time(),
            metadata=metadata,
        )

        self._customers[customer_id] = customer
        self._customers_by_stripe[stripe_customer_id] = customer
        log.info("Customer created: id=%s tier=%s email=%s", customer_id, tier.value, email)
        return customer

    async def get_customer(self, customer_id: str) -> Customer | None:
        """Retrieve a customer by internal ID.

        Checks local cache first, then falls back to Stripe.

        Args:
            customer_id: Internal Orchestra customer UUID.

        Returns:
            The :class:`Customer`, or ``None`` if not found.
        """
        if customer_id in self._customers:
            return self._customers[customer_id]

        if self.is_stripe_enabled:
            try:
                # Search by metadata field
                results = await asyncio.to_thread(
                    self._stripe_client.customers.search,
                    {"query": f"metadata['orchestra_customer_id']:'{customer_id}'"},
                )
                if results.data:
                    sc = results.data[0]
                    tier_val = sc.metadata.get("tier", PricingTier.MAKER.value)
                    try:
                        tier = PricingTier(tier_val)
                    except ValueError:
                        tier = PricingTier.MAKER

                    customer = Customer(
                        id=customer_id,
                        stripe_customer_id=sc.id,
                        email=sc.email or "",
                        name=sc.name or "",
                        tier=tier,
                        created_at=sc.created or time.time(),
                        metadata=dict(sc.metadata),
                    )
                    self._customers[customer_id] = customer
                    self._customers_by_stripe[sc.id] = customer
                    return customer
            except Exception as exc:  # noqa: BLE001
                log.error("Failed to fetch customer from Stripe: %s", exc)

        log.debug("Customer %s not found", customer_id)
        return None

    async def update_tier(
        self,
        customer_id: str,
        new_tier: PricingTier,
    ) -> Customer:
        """Change a customer's subscription tier.

        Updates the Stripe subscription to the new price and the
        customer's metadata, then refreshes the local cache.

        Args:
            customer_id: Internal Orchestra customer UUID.
            new_tier: The new :class:`PricingTier` to move to.

        Returns:
            The updated :class:`Customer`.

        Raises:
            ValueError: If the customer is not found.
        """
        customer = await self.get_customer(customer_id)
        if customer is None:
            raise ValueError(f"Customer not found: {customer_id}")

        new_cfg = TIER_CONFIGS[new_tier]
        old_tier = customer.tier
        customer.tier = new_tier

        if self.is_stripe_enabled:
            try:
                # Update metadata on Stripe customer
                await asyncio.to_thread(
                    self._stripe_client.customers.update,
                    customer.stripe_customer_id,
                    {"metadata": {"tier": new_tier.value}},
                )

                # Update subscription price if there is an active subscription
                if customer.stripe_subscription_id and new_cfg.stripe_price_id:
                    sub = await asyncio.to_thread(
                        self._stripe_client.subscriptions.retrieve,
                        customer.stripe_subscription_id,
                    )
                    item_id = sub.items.data[0].id if sub.items.data else None
                    if item_id:
                        await asyncio.to_thread(
                            self._stripe_client.subscriptions.update,
                            customer.stripe_subscription_id,
                            {
                                "items": [{"id": item_id, "price": new_cfg.stripe_price_id}],
                                "proration_behavior": "always_invoice",
                            },
                        )
                        log.info(
                            "Updated subscription %s: %s → %s",
                            customer.stripe_subscription_id,
                            old_tier.value,
                            new_tier.value,
                        )

            except Exception as exc:  # noqa: BLE001
                log.error("Failed to update tier on Stripe: %s", exc)

        log.info(
            "Customer %s tier changed: %s → %s",
            customer_id,
            old_tier.value,
            new_tier.value,
        )
        return customer

    async def cancel_subscription(self, customer_id: str) -> bool:
        """Cancel a customer's subscription at period end.

        Args:
            customer_id: Internal Orchestra customer UUID.

        Returns:
            ``True`` if cancellation was successful, ``False`` otherwise.
        """
        customer = await self.get_customer(customer_id)
        if customer is None:
            log.warning("cancel_subscription: customer %s not found", customer_id)
            return False

        if not customer.stripe_subscription_id:
            log.info("Customer %s has no active subscription to cancel", customer_id)
            return True

        if self.is_stripe_enabled:
            try:
                await asyncio.to_thread(
                    self._stripe_client.subscriptions.update,
                    customer.stripe_subscription_id,
                    {"cancel_at_period_end": True},
                )
                log.info("Subscription %s set to cancel at period end", customer.stripe_subscription_id)
            except Exception as exc:  # noqa: BLE001
                log.error("Failed to cancel subscription %s: %s", customer.stripe_subscription_id, exc)
                return False

        # Downgrade to Maker in-memory so entitlement checks are accurate
        customer.tier = PricingTier.MAKER
        return True

    # ── Usage Recording ──────────────────────────────────────────────────────

    async def record_llm_usage(
        self,
        customer_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> BillingEvent:
        """Record LLM token usage and send to Stripe meters.

        Calculates the raw API cost for the model, applies the tier's
        markup, and deducts from the customer's included model credit
        before reporting overages.

        Args:
            customer_id: Internal Orchestra customer UUID.
            input_tokens: Number of prompt/input tokens.
            output_tokens: Number of completion/output tokens.
            model: Model key (from :data:`MODEL_COSTS`).

        Returns:
            A :class:`BillingEvent` with cost details.
        """
        raw_cost = self._calculate_llm_cost(model, input_tokens, output_tokens)
        customer = await self.get_customer(customer_id)
        markup = TIER_CONFIGS[customer.tier].markup_percentage if customer else 0.30
        final_cost = self._apply_markup(raw_cost, customer.tier if customer else PricingTier.MAKER)

        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.LLM_INPUT_TOKENS,
            value=float(input_tokens + output_tokens),
            unit_cost_cents=raw_cost / max(input_tokens + output_tokens, 1) if (input_tokens + output_tokens) else 0.0,
            total_cost_cents=float(final_cost),
            model=model,
            timestamp=time.time(),
            metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "raw_cost_cents": raw_cost,
                "markup_pct": markup,
            },
        )

        # Send both input and output meter events
        if input_tokens > 0:
            event.stripe_meter_event_id = await self._send_meter_event(
                STRIPE_METERS["llm_input_tokens"], customer_id, input_tokens
            )
        if output_tokens > 0:
            await self._send_meter_event(
                STRIPE_METERS["llm_output_tokens"], customer_id, output_tokens
            )

        self._events[customer_id].append(event)
        log.debug(
            "LLM usage: customer=%s model=%s in=%d out=%d cost=%d¢",
            customer_id, model, input_tokens, output_tokens, final_cost,
        )
        return event

    async def record_tool_usage(
        self,
        customer_id: str,
        tool_name: str,
        count: int = 1,
    ) -> BillingEvent:
        """Record tool call usage.

        Args:
            customer_id: Internal Orchestra customer UUID.
            tool_name: Human-readable tool name (e.g. ``"web_search"``).
            count: Number of tool executions (default 1).

        Returns:
            A :class:`BillingEvent`.
        """
        customer = await self.get_customer(customer_id)
        tier = customer.tier if customer else PricingTier.MAKER
        cfg = TIER_CONFIGS[tier]
        unit_cost = cfg.overage_tool_call_cents / 1_000.0  # mills → cents
        total_cost = unit_cost * count

        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.TOOL_CALLS,
            value=float(count),
            unit_cost_cents=unit_cost,
            total_cost_cents=total_cost,
            model=tool_name,
            timestamp=time.time(),
            metadata={"tool_name": tool_name, "count": count},
        )
        event.stripe_meter_event_id = await self._send_meter_event(
            STRIPE_METERS["tool_calls"], customer_id, count
        )

        self._events[customer_id].append(event)
        log.debug("Tool usage: customer=%s tool=%s count=%d", customer_id, tool_name, count)
        return event

    async def record_swarm_spawn(
        self,
        customer_id: str,
        agent_id: str,
        model: str,
    ) -> BillingEvent:
        """Record an agent swarm spawn (Arch C).

        Each sub-agent spawned within an Arch C session is a billable
        event.  Overages are charged at $0.01 per spawn beyond the
        tier's swarm limit.

        Args:
            customer_id: Internal Orchestra customer UUID.
            agent_id: The spawned agent's identifier.
            model: Model used by the spawned agent.

        Returns:
            A :class:`BillingEvent`.
        """
        _SWARM_SPAWN_COST_CENTS = 1.0  # $0.01 per spawn

        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.SWARM_SPAWNS,
            value=1.0,
            unit_cost_cents=_SWARM_SPAWN_COST_CENTS,
            total_cost_cents=_SWARM_SPAWN_COST_CENTS,
            model=model,
            timestamp=time.time(),
            metadata={"agent_id": agent_id},
        )
        event.stripe_meter_event_id = await self._send_meter_event(
            STRIPE_METERS["swarm_spawns"], customer_id, 1
        )

        self._events[customer_id].append(event)
        log.debug("Swarm spawn: customer=%s agent=%s model=%s", customer_id, agent_id, model)
        return event

    async def record_stt_usage(
        self,
        customer_id: str,
        duration_seconds: float,
        backend: str,
    ) -> BillingEvent:
        """Record speech-to-text usage.

        Applies the pass-through backend cost plus the tier's markup
        percentage.  Seconds within the tier's included STT allowance
        are free; excess is charged at the marked-up rate.

        Args:
            customer_id: Internal Orchestra customer UUID.
            duration_seconds: Audio duration transcribed.
            backend: STT backend key (from :data:`STT_COSTS`).

        Returns:
            A :class:`BillingEvent`.
        """
        raw_cost = self._calculate_stt_cost(backend, duration_seconds)
        customer = await self.get_customer(customer_id)
        final_cost = self._apply_markup(raw_cost, customer.tier if customer else PricingTier.MAKER)

        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.STT_SECONDS,
            value=duration_seconds,
            unit_cost_cents=STT_COSTS.get(backend, 0.0) * 100 / 60,  # per-second in cents
            total_cost_cents=float(final_cost),
            model=backend,
            timestamp=time.time(),
            metadata={"duration_seconds": duration_seconds, "raw_cost_cents": raw_cost},
        )
        event.stripe_meter_event_id = await self._send_meter_event(
            STRIPE_METERS["stt_seconds"], customer_id, duration_seconds
        )

        self._events[customer_id].append(event)
        log.debug(
            "STT usage: customer=%s backend=%s duration=%.1fs cost=%d¢",
            customer_id, backend, duration_seconds, final_cost,
        )
        return event

    async def record_tts_usage(
        self,
        customer_id: str,
        text_length: int,
        backend: str,
    ) -> BillingEvent:
        """Record text-to-speech usage.

        Applies the pass-through backend cost plus the tier's markup.

        Args:
            customer_id: Internal Orchestra customer UUID.
            text_length: Number of characters synthesised.
            backend: TTS backend key (from :data:`TTS_COSTS`).

        Returns:
            A :class:`BillingEvent`.
        """
        raw_cost = self._calculate_tts_cost(backend, text_length)
        customer = await self.get_customer(customer_id)
        final_cost = self._apply_markup(raw_cost, customer.tier if customer else PricingTier.MAKER)

        per_char_cents = (TTS_COSTS.get(backend, 0.0) * 100) / 1_000  # per-char in cents
        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.TTS_CHARACTERS,
            value=float(text_length),
            unit_cost_cents=per_char_cents,
            total_cost_cents=float(final_cost),
            model=backend,
            timestamp=time.time(),
            metadata={"characters": text_length, "raw_cost_cents": raw_cost},
        )
        event.stripe_meter_event_id = await self._send_meter_event(
            STRIPE_METERS["tts_characters"], customer_id, text_length
        )

        self._events[customer_id].append(event)
        log.debug(
            "TTS usage: customer=%s backend=%s chars=%d cost=%d¢",
            customer_id, backend, text_length, final_cost,
        )
        return event

    async def record_memory_usage(
        self,
        customer_id: str,
        entries_added: int = 1,
    ) -> BillingEvent:
        """Record memory store entries added.

        Overages beyond the tier's ``max_memory_entries`` limit are
        billed at $0.001 per entry.

        Args:
            customer_id: Internal Orchestra customer UUID.
            entries_added: Number of new memory entries persisted.

        Returns:
            A :class:`BillingEvent`.
        """
        _MEMORY_ENTRY_OVERAGE_CENTS = 0.1  # $0.001 in cents (10 mills)

        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.MEMORY_ENTRIES,
            value=float(entries_added),
            unit_cost_cents=_MEMORY_ENTRY_OVERAGE_CENTS,
            total_cost_cents=_MEMORY_ENTRY_OVERAGE_CENTS * entries_added,
            timestamp=time.time(),
            metadata={"entries_added": entries_added},
        )
        event.stripe_meter_event_id = await self._send_meter_event(
            STRIPE_METERS["memory_entries"], customer_id, entries_added
        )

        self._events[customer_id].append(event)
        log.debug("Memory usage: customer=%s entries=%d", customer_id, entries_added)
        return event

    async def record_code_execution(self, customer_id: str) -> BillingEvent:
        """Record a code sandbox execution.

        Args:
            customer_id: Internal Orchestra customer UUID.

        Returns:
            A :class:`BillingEvent`.
        """
        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.CODE_EXECUTIONS,
            value=1.0,
            unit_cost_cents=0.0,   # included; future overage may apply
            total_cost_cents=0.0,
            timestamp=time.time(),
        )
        event.stripe_meter_event_id = await self._send_meter_event(
            STRIPE_METERS["code_executions"], customer_id, 1
        )

        self._events[customer_id].append(event)
        log.debug("Code execution: customer=%s", customer_id)
        return event

    async def record_browser_action(self, customer_id: str) -> BillingEvent:
        """Record a browser automation action.

        Args:
            customer_id: Internal Orchestra customer UUID.

        Returns:
            A :class:`BillingEvent`.
        """
        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.BROWSER_ACTIONS,
            value=1.0,
            unit_cost_cents=0.0,   # included; future overage may apply
            total_cost_cents=0.0,
            timestamp=time.time(),
        )
        event.stripe_meter_event_id = await self._send_meter_event(
            STRIPE_METERS["browser_actions"], customer_id, 1
        )

        self._events[customer_id].append(event)
        log.debug("Browser action: customer=%s", customer_id)
        return event

    # ── Usage Queries ────────────────────────────────────────────────────────

    async def get_usage_summary(
        self,
        customer_id: str,
        period_start: float | None = None,
        period_end: float | None = None,
    ) -> UsageSummary:
        """Compute a usage summary for a customer over a billing period.

        Aggregates all in-memory :class:`BillingEvent` records for the
        specified time window.  For production use, this should be
        supplemented with Stripe's usage records API for events that
        arrived before the process restarted.

        Args:
            customer_id: Internal Orchestra customer UUID.
            period_start: Unix timestamp for the start of the period
                (default: 30 days ago).
            period_end: Unix timestamp for the end of the period
                (default: now).

        Returns:
            A :class:`UsageSummary` covering the period.
        """
        now = time.time()
        period_end = period_end or now
        period_start = period_start or (now - 30 * 86_400)

        customer = await self.get_customer(customer_id)
        tier = customer.tier if customer else PricingTier.MAKER
        cfg = TIER_CONFIGS[tier]

        summary = UsageSummary(
            customer_id=customer_id,
            tier=tier,
            period_start=period_start,
            period_end=period_end,
            model_credit_remaining_cents=cfg.included_model_credit_cents,
        )

        events = [
            e for e in self._events.get(customer_id, [])
            if period_start <= e.timestamp <= period_end
        ]

        for event in events:
            ut = event.usage_type
            if ut == UsageType.LLM_INPUT_TOKENS:
                summary.llm_input_tokens += int(event.metadata.get("input_tokens", 0))
                summary.llm_output_tokens += int(event.metadata.get("output_tokens", 0))
                raw = int(event.metadata.get("raw_cost_cents", 0))
                summary.llm_cost_cents += raw

                # Deduct from credit, then charge overage with markup
                if summary.model_credit_remaining_cents > 0:
                    deduct = min(raw, summary.model_credit_remaining_cents)
                    summary.model_credit_remaining_cents -= deduct
                    raw -= deduct

                if raw > 0:
                    marked_up = self._apply_markup(raw, tier)
                    summary.total_cost_cents += marked_up
                    summary.overages["llm"] = summary.overages.get("llm", 0) + marked_up

            elif ut == UsageType.TOOL_CALLS:
                summary.tool_calls += int(event.value)
                # Overage beyond included limit
                if cfg.max_tool_calls_monthly > 0:
                    excess = max(0, summary.tool_calls - cfg.max_tool_calls_monthly)
                    if excess > 0:
                        overage_cost = excess * (cfg.overage_tool_call_cents / 1_000)
                        summary.overages["tool_calls"] = int(overage_cost)
                        summary.total_cost_cents += int(overage_cost)

            elif ut == UsageType.SWARM_SPAWNS:
                summary.swarm_spawns += int(event.value)
                summary.total_cost_cents += int(event.total_cost_cents)
                summary.overages["swarm"] = summary.overages.get("swarm", 0) + int(event.total_cost_cents)

            elif ut == UsageType.STT_SECONDS:
                summary.stt_seconds += event.value
                summary.stt_cost_cents += int(event.total_cost_cents)

                # Check included STT minutes
                included_secs = cfg.included_stt_minutes * 60
                if summary.stt_seconds > included_secs and included_secs > 0:
                    # Only count cost above included
                    summary.total_cost_cents += int(event.total_cost_cents)
                    summary.overages["stt"] = summary.overages.get("stt", 0) + int(event.total_cost_cents)

            elif ut == UsageType.TTS_CHARACTERS:
                summary.tts_characters += int(event.value)
                summary.tts_cost_cents += int(event.total_cost_cents)
                # Enterprise has unlimited TTS; others check included allowance
                if tier != PricingTier.ENTERPRISE:
                    summary.total_cost_cents += int(event.total_cost_cents)
                    summary.overages["tts"] = summary.overages.get("tts", 0) + int(event.total_cost_cents)

            elif ut == UsageType.MEMORY_ENTRIES:
                summary.memory_entries += int(event.value)

            elif ut == UsageType.CODE_EXECUTIONS:
                summary.code_executions += int(event.value)

            elif ut == UsageType.BROWSER_ACTIONS:
                summary.browser_actions += int(event.value)

        return summary

    async def get_billing_events(
        self,
        customer_id: str,
        limit: int = 100,
        usage_type: UsageType | None = None,
    ) -> list[BillingEvent]:
        """Retrieve recent billing events for a customer.

        Args:
            customer_id: Internal Orchestra customer UUID.
            limit: Maximum number of events to return (newest first).
            usage_type: If set, filter to this usage dimension only.

        Returns:
            List of :class:`BillingEvent`, newest first.
        """
        events = self._events.get(customer_id, [])
        if usage_type is not None:
            events = [e for e in events if e.usage_type == usage_type]
        return list(reversed(events[-limit:]))

    async def estimate_cost(
        self,
        customer_id: str,
        usage_type: UsageType,
        value: float,
        model: str = "",
    ) -> float:
        """Estimate the cost (in cents) for a hypothetical usage event.

        Args:
            customer_id: Internal Orchestra customer UUID.
            usage_type: The :class:`UsageType` to estimate.
            value: The quantity (tokens, seconds, characters, etc.).
            model: Model or backend key (required for LLM/STT/TTS).

        Returns:
            Estimated cost in cents (float).
        """
        customer = await self.get_customer(customer_id)
        tier = customer.tier if customer else PricingTier.MAKER

        if usage_type == UsageType.LLM_INPUT_TOKENS:
            raw = self._calculate_llm_cost(model, int(value), 0)
            return float(self._apply_markup(raw, tier))
        elif usage_type == UsageType.LLM_OUTPUT_TOKENS:
            raw = self._calculate_llm_cost(model, 0, int(value))
            return float(self._apply_markup(raw, tier))
        elif usage_type == UsageType.STT_SECONDS:
            raw = self._calculate_stt_cost(model, value)
            return float(self._apply_markup(raw, tier))
        elif usage_type == UsageType.TTS_CHARACTERS:
            raw = self._calculate_tts_cost(model, int(value))
            return float(self._apply_markup(raw, tier))
        elif usage_type == UsageType.TOOL_CALLS:
            cfg = TIER_CONFIGS[tier]
            return value * (cfg.overage_tool_call_cents / 1_000.0)
        elif usage_type == UsageType.SWARM_SPAWNS:
            return value * 1.0   # $0.01 per spawn in cents
        elif usage_type == UsageType.MEMORY_ENTRIES:
            return value * 0.1   # $0.001 per entry in cents
        else:
            return 0.0

    # ── Entitlement Checks ───────────────────────────────────────────────────

    def check_model_access(
        self,
        tier: PricingTier,
        model: str,
    ) -> tuple[bool, str]:
        """Check whether a tier has access to a given model.

        Args:
            tier: The customer's :class:`PricingTier`.
            model: Model key to check.

        Returns:
            ``(allowed, reason)`` tuple.
        """
        cfg = TIER_CONFIGS[tier]
        if model in cfg.allowed_models:
            return True, ""
        # Provide upgrade hints
        for upgrade_tier in (PricingTier.BUILDER, PricingTier.PRO, PricingTier.ENTERPRISE):
            if model in TIER_CONFIGS[upgrade_tier].allowed_models:
                return False, (
                    f"Model '{model}' requires {TIER_CONFIGS[upgrade_tier].display_name} tier "
                    f"or above. Current tier: {cfg.display_name}."
                )
        return False, f"Model '{model}' is not available on any Orchestra tier."

    def check_stt_access(
        self,
        tier: PricingTier,
        backend: str,
    ) -> tuple[bool, str]:
        """Check whether a tier has access to a given STT backend.

        Args:
            tier: The customer's :class:`PricingTier`.
            backend: STT backend key.

        Returns:
            ``(allowed, reason)`` tuple.
        """
        cfg = TIER_CONFIGS[tier]
        if backend in cfg.allowed_stt_backends:
            return True, ""
        for upgrade_tier in (PricingTier.BUILDER, PricingTier.PRO, PricingTier.ENTERPRISE):
            if backend in TIER_CONFIGS[upgrade_tier].allowed_stt_backends:
                return False, (
                    f"STT backend '{backend}' requires {TIER_CONFIGS[upgrade_tier].display_name} "
                    f"tier or above. Current tier: {cfg.display_name}."
                )
        return False, f"STT backend '{backend}' is not available on any Orchestra tier."

    def check_tts_access(
        self,
        tier: PricingTier,
        backend: str,
    ) -> tuple[bool, str]:
        """Check whether a tier has access to a given TTS backend.

        Args:
            tier: The customer's :class:`PricingTier`.
            backend: TTS backend key.

        Returns:
            ``(allowed, reason)`` tuple.
        """
        cfg = TIER_CONFIGS[tier]
        if backend in cfg.allowed_tts_backends:
            return True, ""
        for upgrade_tier in (PricingTier.BUILDER, PricingTier.PRO, PricingTier.ENTERPRISE):
            if backend in TIER_CONFIGS[upgrade_tier].allowed_tts_backends:
                return False, (
                    f"TTS backend '{backend}' requires {TIER_CONFIGS[upgrade_tier].display_name} "
                    f"tier or above. Current tier: {cfg.display_name}."
                )
        return False, f"TTS backend '{backend}' is not available on any Orchestra tier."

    def check_architecture_access(
        self,
        tier: PricingTier,
        arch: str,
    ) -> tuple[bool, str]:
        """Check whether a tier has access to a given agent architecture.

        Args:
            tier: The customer's :class:`PricingTier`.
            arch: Architecture identifier, e.g. ``"A"``, ``"C"``, ``"E"``.

        Returns:
            ``(allowed, reason)`` tuple.
        """
        cfg = TIER_CONFIGS[tier]
        if arch in cfg.allowed_architectures:
            return True, ""
        for upgrade_tier in (PricingTier.BUILDER, PricingTier.PRO, PricingTier.ENTERPRISE):
            if arch in TIER_CONFIGS[upgrade_tier].allowed_architectures:
                return False, (
                    f"Architecture '{arch}' requires {TIER_CONFIGS[upgrade_tier].display_name} "
                    f"tier or above. Current tier: {cfg.display_name}."
                )
        return False, f"Architecture '{arch}' is not available on any Orchestra tier."

    def check_feature_access(
        self,
        tier: PricingTier,
        feature: str,
    ) -> tuple[bool, str]:
        """Check access to a named platform feature flag.

        Recognised features: ``"domain_router"``, ``"voice_cloning"``,
        ``"swarm"``, ``"audio_stt_api"``, ``"all_models"``.

        Args:
            tier: The customer's :class:`PricingTier`.
            feature: Feature identifier string.

        Returns:
            ``(allowed, reason)`` tuple.
        """
        cfg = TIER_CONFIGS[tier]
        _FEATURE_CHECKS: dict[str, tuple[bool, str]] = {
            "domain_router": (
                cfg.enable_domain_router,
                f"Domain routing requires Pro tier or above. Current: {cfg.display_name}.",
            ),
            "voice_cloning": (
                cfg.enable_voice_cloning,
                f"Voice cloning requires Enterprise tier. Current: {cfg.display_name}.",
            ),
            "swarm": (
                cfg.max_swarm_agents != 0 or tier == PricingTier.ENTERPRISE,
                f"Agent swarm (Arch C) requires Builder tier or above. Current: {cfg.display_name}.",
            ),
            "audio_stt_api": (
                bool(cfg.allowed_stt_backends - _FREE_STT),
                f"API-based STT requires Builder tier or above. Current: {cfg.display_name}.",
            ),
            "all_models": (
                tier in (PricingTier.PRO, PricingTier.ENTERPRISE),
                f"Full model access requires Pro tier or above. Current: {cfg.display_name}.",
            ),
        }

        if feature in _FEATURE_CHECKS:
            allowed, reason = _FEATURE_CHECKS[feature]
            return allowed, ("" if allowed else reason)

        log.warning("Unknown feature check requested: %s", feature)
        return False, f"Unknown feature: '{feature}'."

    def get_tier_limits(self, tier: PricingTier) -> TierConfig:
        """Return the full :class:`TierConfig` for a given tier.

        Args:
            tier: The :class:`PricingTier` to look up.

        Returns:
            The corresponding :class:`TierConfig`.
        """
        return TIER_CONFIGS[tier]

    # ── Stripe Setup ─────────────────────────────────────────────────────────

    async def setup_stripe_products(self) -> dict[str, str]:
        """Create Stripe products and prices for all Orchestra tiers.

        Run once during initial deployment to populate Stripe with the
        product catalogue.  The returned mapping should be stored in
        config (e.g. ``.env``) and used to populate each
        :class:`TierConfig`'s ``stripe_price_id``.

        Returns:
            Mapping of tier name → Stripe price ID.
        """
        if not self.is_stripe_enabled:
            log.warning("setup_stripe_products called in offline mode — no-op")
            return {}

        created: dict[str, str] = {}

        for tier, cfg in TIER_CONFIGS.items():
            if cfg.price_monthly == 0:
                log.info("Skipping free tier %s (no Stripe product needed)", tier.value)
                continue

            try:
                # Create product
                product = await asyncio.to_thread(
                    self._stripe_client.products.create,
                    {
                        "name": f"Horizon Orchestra — {cfg.display_name}",
                        "description": (
                            f"Horizon Orchestra {cfg.display_name} plan: "
                            f"${cfg.price_monthly // 100}/mo with ${cfg.included_model_credit_cents // 100} "
                            f"model credit included."
                        ),
                        "metadata": {"tier": tier.value},
                    },
                )
                self._product_ids[tier.value] = product.id
                log.info("Created Stripe product %s for tier %s", product.id, tier.value)

                # Create recurring price
                price = await asyncio.to_thread(
                    self._stripe_client.prices.create,
                    {
                        "product": product.id,
                        "unit_amount": cfg.price_monthly,
                        "currency": "usd",
                        "recurring": {"interval": "month"},
                        "nickname": f"Orchestra {cfg.display_name} Monthly",
                        "metadata": {"tier": tier.value},
                    },
                )
                cfg.stripe_price_id = price.id
                created[tier.value] = price.id
                log.info("Created Stripe price %s for tier %s", price.id, tier.value)

            except Exception as exc:  # noqa: BLE001
                log.error("Failed to create Stripe product for tier %s: %s", tier.value, exc)

        return created

    async def setup_stripe_meters(self) -> dict[str, str]:
        """Create Stripe Billing Meters for all Orchestra usage dimensions.

        Run once during initial deployment.  Meters track usage events
        sent via :meth:`_send_meter_event` and generate usage-based
        charges automatically.

        Returns:
            Mapping of usage key → Stripe meter ID.
        """
        if not self.is_stripe_enabled:
            log.warning("setup_stripe_meters called in offline mode — no-op")
            return {}

        created: dict[str, str] = {}
        meter_definitions = [
            ("llm_input_tokens",  "Orchestra LLM Input Tokens",   "sum"),
            ("llm_output_tokens", "Orchestra LLM Output Tokens",  "sum"),
            ("tool_calls",        "Orchestra Tool Calls",          "sum"),
            ("swarm_spawns",      "Orchestra Swarm Agent Spawns",  "sum"),
            ("stt_seconds",       "Orchestra STT Seconds",         "sum"),
            ("tts_characters",    "Orchestra TTS Characters",      "sum"),
            ("memory_entries",    "Orchestra Memory Entries",      "sum"),
            ("code_executions",   "Orchestra Code Executions",     "sum"),
            ("browser_actions",   "Orchestra Browser Actions",     "sum"),
        ]

        for key, display_name, agg in meter_definitions:
            event_name = STRIPE_METERS[key]
            try:
                meter = await asyncio.to_thread(
                    self._stripe_client.billing.meters.create,
                    {
                        "display_name": display_name,
                        "event_name": event_name,
                        "default_aggregation": {"formula": agg},
                        "customer_mapping": {
                            "event_payload_key": "stripe_customer_id",
                            "type": "by_id",
                        },
                        "value_settings": {"event_payload_key": "value"},
                    },
                )
                self._meter_ids[key] = meter.id
                created[key] = meter.id
                log.info("Created Stripe meter %s → %s", event_name, meter.id)

            except Exception as exc:  # noqa: BLE001
                log.error("Failed to create Stripe meter %s: %s", event_name, exc)

        return created

    # ── Internal Helpers ─────────────────────────────────────────────────────

    async def _send_meter_event(
        self,
        event_name: str,
        customer_id: str,
        value: float,
    ) -> str:
        """Send a single usage event to Stripe's Meter Events API.

        Falls back silently to a no-op when Stripe is not configured.
        Batches events internally when called in rapid succession to
        stay within Stripe's 1,000 events/sec limit.

        Args:
            event_name: Stripe meter event name (from :data:`STRIPE_METERS`).
            customer_id: Internal customer ID, resolved to a Stripe
                customer ID before sending.
            value: Numeric quantity for the event.

        Returns:
            Stripe meter event ID, or empty string in offline mode.
        """
        if not self.is_stripe_enabled:
            return ""

        # Resolve Stripe customer ID
        customer = self._customers.get(customer_id)
        if customer is None:
            log.warning("_send_meter_event: unknown customer %s", customer_id)
            return ""

        stripe_customer_id = customer.stripe_customer_id
        if stripe_customer_id.startswith("offline_"):
            return ""  # offline fallback customer

        try:
            meter_event = await asyncio.to_thread(
                self._stripe_client.billing.meter_events.create,
                {
                    "event_name": event_name,
                    "payload": {
                        "stripe_customer_id": stripe_customer_id,
                        "value": str(value),
                    },
                    "timestamp": int(time.time()),
                },
            )
            return meter_event.identifier
        except Exception as exc:  # noqa: BLE001
            log.error(
                "Failed to send meter event %s for customer %s: %s",
                event_name, customer_id, exc,
            )
            return ""

    def _calculate_llm_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        """Calculate raw LLM cost in cents (before markup).

        Args:
            model: Model key from :data:`MODEL_COSTS`.
            input_tokens: Number of input/prompt tokens.
            output_tokens: Number of output/completion tokens.

        Returns:
            Cost in integer cents.
        """
        costs = MODEL_COSTS.get(model)
        if costs is None:
            log.warning("Unknown model '%s' in _calculate_llm_cost; using $0 cost", model)
            return 0

        input_cost_usd, output_cost_usd = costs
        # Convert per-1M rates to per-token, multiply by count, convert to cents
        total_usd = (
            (input_tokens / 1_000_000) * input_cost_usd
            + (output_tokens / 1_000_000) * output_cost_usd
        )
        return int(round(total_usd * 100))

    def _calculate_stt_cost(
        self,
        backend: str,
        duration_seconds: float,
    ) -> int:
        """Calculate raw STT cost in cents (before markup).

        Args:
            backend: STT backend key from :data:`STT_COSTS`.
            duration_seconds: Duration of audio processed.

        Returns:
            Cost in integer cents.
        """
        cost_per_min_usd = STT_COSTS.get(backend)
        if cost_per_min_usd is None:
            log.warning("Unknown STT backend '%s'; using $0 cost", backend)
            return 0

        duration_minutes = duration_seconds / 60.0
        total_usd = duration_minutes * cost_per_min_usd
        return int(round(total_usd * 100))

    def _calculate_tts_cost(
        self,
        backend: str,
        characters: int,
    ) -> int:
        """Calculate raw TTS cost in cents (before markup).

        Args:
            backend: TTS backend key from :data:`TTS_COSTS`.
            characters: Number of characters synthesised.

        Returns:
            Cost in integer cents.
        """
        cost_per_1k_usd = TTS_COSTS.get(backend)
        if cost_per_1k_usd is None:
            log.warning("Unknown TTS backend '%s'; using $0 cost", backend)
            return 0

        total_usd = (characters / 1_000.0) * cost_per_1k_usd
        return int(round(total_usd * 100))

    def _apply_markup(self, cost_cents: int, tier: PricingTier) -> int:
        """Apply the tier's markup percentage to a raw cost.

        Args:
            cost_cents: Raw cost in integer cents.
            tier: Customer's :class:`PricingTier` (determines markup %).

        Returns:
            Final cost in integer cents after markup.
        """
        cfg = TIER_CONFIGS[tier]
        markup = cfg.markup_percentage
        return int(round(cost_cents * (1.0 + markup)))


# ---------------------------------------------------------------------------
# NullBillingManager — zero-overhead no-op for disabled billing
# ---------------------------------------------------------------------------

class NullBillingManager:
    """A no-op billing manager for use when billing is disabled.

    All methods return sensible defaults without making any network
    calls or maintaining any state.  Drop-in replacement for
    :class:`BillingManager` in local development and test environments.

    Usage::

        billing: BillingManager | NullBillingManager
        if os.environ.get("BILLING_ENABLED", "false").lower() == "true":
            billing = BillingManager()
        else:
            billing = NullBillingManager()
    """

    @property
    def is_stripe_enabled(self) -> bool:
        return False

    async def create_customer(
        self,
        email: str,
        name: str,
        tier: PricingTier = PricingTier.MAKER,
        payment_method_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Customer:
        customer_id = str(uuid.uuid4())
        return Customer(
            id=customer_id,
            stripe_customer_id=f"null_{customer_id}",
            email=email,
            name=name,
            tier=tier,
            created_at=time.time(),
            metadata=metadata or {},
        )

    async def get_customer(self, customer_id: str) -> Customer | None:
        return None

    async def update_tier(self, customer_id: str, new_tier: PricingTier) -> Customer:
        customer_id = customer_id or str(uuid.uuid4())
        return Customer(
            id=customer_id,
            stripe_customer_id=f"null_{customer_id}",
            email="",
            name="",
            tier=new_tier,
        )

    async def cancel_subscription(self, customer_id: str) -> bool:
        return True

    async def record_llm_usage(
        self, customer_id: str, input_tokens: int, output_tokens: int, model: str
    ) -> BillingEvent:
        return self._null_event(customer_id, UsageType.LLM_INPUT_TOKENS, float(input_tokens + output_tokens), model)

    async def record_tool_usage(
        self, customer_id: str, tool_name: str, count: int = 1
    ) -> BillingEvent:
        return self._null_event(customer_id, UsageType.TOOL_CALLS, float(count), tool_name)

    async def record_swarm_spawn(
        self, customer_id: str, agent_id: str, model: str
    ) -> BillingEvent:
        return self._null_event(customer_id, UsageType.SWARM_SPAWNS, 1.0, model)

    async def record_stt_usage(
        self, customer_id: str, duration_seconds: float, backend: str
    ) -> BillingEvent:
        return self._null_event(customer_id, UsageType.STT_SECONDS, duration_seconds, backend)

    async def record_tts_usage(
        self, customer_id: str, text_length: int, backend: str
    ) -> BillingEvent:
        return self._null_event(customer_id, UsageType.TTS_CHARACTERS, float(text_length), backend)

    async def record_memory_usage(
        self, customer_id: str, entries_added: int = 1
    ) -> BillingEvent:
        return self._null_event(customer_id, UsageType.MEMORY_ENTRIES, float(entries_added))

    async def record_code_execution(self, customer_id: str) -> BillingEvent:
        return self._null_event(customer_id, UsageType.CODE_EXECUTIONS, 1.0)

    async def record_browser_action(self, customer_id: str) -> BillingEvent:
        return self._null_event(customer_id, UsageType.BROWSER_ACTIONS, 1.0)

    async def get_usage_summary(
        self,
        customer_id: str,
        period_start: float | None = None,
        period_end: float | None = None,
    ) -> UsageSummary:
        now = time.time()
        return UsageSummary(
            customer_id=customer_id,
            tier=PricingTier.MAKER,
            period_start=period_start or (now - 30 * 86_400),
            period_end=period_end or now,
        )

    async def get_billing_events(
        self,
        customer_id: str,
        limit: int = 100,
        usage_type: UsageType | None = None,
    ) -> list[BillingEvent]:
        return []

    async def estimate_cost(
        self,
        customer_id: str,
        usage_type: UsageType,
        value: float,
        model: str = "",
    ) -> float:
        return 0.0

    def check_model_access(self, tier: PricingTier, model: str) -> tuple[bool, str]:
        return True, ""

    def check_stt_access(self, tier: PricingTier, backend: str) -> tuple[bool, str]:
        return True, ""

    def check_tts_access(self, tier: PricingTier, backend: str) -> tuple[bool, str]:
        return True, ""

    def check_architecture_access(self, tier: PricingTier, arch: str) -> tuple[bool, str]:
        return True, ""

    def check_feature_access(self, tier: PricingTier, feature: str) -> tuple[bool, str]:
        return True, ""

    def get_tier_limits(self, tier: PricingTier) -> TierConfig:
        return TIER_CONFIGS[tier]

    async def setup_stripe_products(self) -> dict[str, str]:
        return {}

    async def setup_stripe_meters(self) -> dict[str, str]:
        return {}

    # Internal helper

    def _null_event(
        self,
        customer_id: str,
        usage_type: UsageType,
        value: float,
        model: str = "",
    ) -> BillingEvent:
        return BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=usage_type,
            value=value,
            unit_cost_cents=0.0,
            total_cost_cents=0.0,
            model=model,
            timestamp=time.time(),
        )
