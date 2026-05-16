"""OpenJarvis — Stripe Billing Integration.

Manages subscription plans, usage metering, customer lifecycle, and
billing for OpenJarvis's multi-model agentic platform.

Pricing is designed around OpenJarvis's unique capabilities:
- Multi-model backbone access (Gemma 4, Claude, Kimi, Sonar)
- Speech/audio pipeline (STT/TTS with 12 backends)
- Architecture tiers (Monolithic, Swarm, Production)
- Security policy levels
- Domain-aware routing

Uses Stripe's meter events API for real-time usage tracking and
graduated pricing for compute-intensive overages.

Usage::

    from openjarvis.billing.stripe import BillingManager, PricingTier

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
    "PricingTier",
    "UsageType",
    "TierConfig",
    "Customer",
    "UsageRecord",
    "UsageSummary",
    "BillingEvent",
    "BillingManager",
    "NullBillingManager",
    "MODEL_COSTS",
    "STT_COSTS",
    "TTS_COSTS",
    "TIER_CONFIGS",
    "STRIPE_METERS",
]

log = logging.getLogger("openjarvis.billing.stripe")


class PricingTier(str, Enum):
    MAKER = "maker"
    BUILDER = "builder"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class UsageType(str, Enum):
    LLM_INPUT_TOKENS = "llm_input_tokens"
    LLM_OUTPUT_TOKENS = "llm_output_tokens"
    TOOL_CALLS = "tool_calls"
    SWARM_SPAWNS = "swarm_spawns"
    STT_SECONDS = "stt_seconds"
    TTS_CHARACTERS = "tts_characters"
    MEMORY_ENTRIES = "memory_entries"
    CODE_EXECUTIONS = "code_executions"
    BROWSER_ACTIONS = "browser_actions"


MODEL_COSTS: dict[str, tuple[float, float]] = {
    "kimi-k2.5": (0.60, 2.50),
    "gemma-4-31b": (0.15, 0.60),
    "gemma-4-26b-moe": (0.10, 0.40),
    "gemma-4-e4b": (0.0, 0.0),
    "gemma-4-e2b": (0.0, 0.0),
    "claude-opus-4.6": (5.00, 25.00),
    "claude-sonnet-4.6": (3.00, 15.00),
    "claude-haiku-4.5": (1.00, 5.00),
    "claude-opus-4.6-openrouter": (5.00, 25.00),
    "claude-sonnet-4.6-openrouter": (3.00, 15.00),
    "claude-haiku-4.5-openrouter": (1.00, 5.00),
    "gpt-5.4": (2.00, 10.00),
    "grok-3": (0.30, 1.50),
    "sonar": (1.00, 1.00),
    "sonar-pro": (3.00, 15.00),
    "sonar-reasoning-pro": (3.00, 15.00),
    "kimi-k2.5-local": (0.0, 0.0),
    "gemma-4-31b-local": (0.0, 0.0),
    "gemma-4-ollama": (0.0, 0.0),
    "ollama-local": (0.0, 0.0),
}

STT_COSTS: dict[str, float] = {
    "whisper_api": 0.006,
    "deepgram_nova3": 0.0077,
    "groq_whisper": 0.04 / 60.0,
    "elevenlabs_scribe": 0.40 / 60.0,
    "whisper_local": 0.0,
    "faster_whisper": 0.0,
}

TTS_COSTS: dict[str, float] = {
    "openai_tts": 15.0 / 1_000,
    "elevenlabs": 0.10,
    "deepgram_aura": 30.0 / 1_000,
    "kokoro": 0.0,
    "fish_speech": 0.0,
    "chatterbox": 0.0,
}

STRIPE_METERS: dict[str, str] = {
    "llm_input_tokens": "openjarvis_llm_input_tokens",
    "llm_output_tokens": "openjarvis_llm_output_tokens",
    "tool_calls": "openjarvis_tool_calls",
    "swarm_spawns": "openjarvis_swarm_spawns",
    "stt_seconds": "openjarvis_stt_seconds",
    "tts_characters": "openjarvis_tts_characters",
    "memory_entries": "openjarvis_memory_entries",
    "code_executions": "openjarvis_code_executions",
    "browser_actions": "openjarvis_browser_actions",
}


@dataclass
class TierConfig:
    name: str
    display_name: str
    price_monthly: int
    stripe_price_id: str = ""
    allowed_models: set[str] = field(default_factory=set)
    allowed_stt_backends: set[str] = field(default_factory=set)
    allowed_tts_backends: set[str] = field(default_factory=set)
    allowed_architectures: set[str] = field(default_factory=set)
    allowed_security_policies: set[str] = field(default_factory=set)
    enable_domain_router: bool = False
    enable_voice_cloning: bool = False
    max_tool_calls_monthly: int = 0
    max_sessions_daily: int = 0
    max_swarm_agents: int = 0
    max_memory_entries: int = 0
    included_stt_minutes: int = 0
    included_tts_minutes: int = 0
    included_model_credit_cents: int = 0
    overage_tool_call_cents: int = 0
    markup_percentage: float = 0.30


@dataclass
class Customer:
    id: str
    stripe_customer_id: str
    email: str
    name: str
    tier: PricingTier
    stripe_subscription_id: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageRecord:
    customer_id: str
    usage_type: UsageType
    value: float
    model: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageSummary:
    customer_id: str
    tier: PricingTier
    period_start: float
    period_end: float
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cost_cents: int = 0
    tool_calls: int = 0
    swarm_spawns: int = 0
    stt_seconds: float = 0.0
    stt_cost_cents: int = 0
    tts_characters: int = 0
    tts_cost_cents: int = 0
    memory_entries: int = 0
    code_executions: int = 0
    browser_actions: int = 0
    total_cost_cents: int = 0
    model_credit_remaining_cents: int = 0
    overages: dict[str, int] = field(default_factory=dict)


@dataclass
class BillingEvent:
    event_id: str
    customer_id: str
    usage_type: UsageType
    value: float
    unit_cost_cents: float
    total_cost_cents: float
    model: str = ""
    timestamp: float = field(default_factory=time.time)
    stripe_meter_event_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


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

_ENTERPRISE_MODELS: set[str] = _PRO_MODELS

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
        max_swarm_agents=0,
        max_memory_entries=100,
        included_stt_minutes=60,
        included_tts_minutes=30,
        included_model_credit_cents=0,
        overage_tool_call_cents=1,
        markup_percentage=0.30,
    ),
    PricingTier.BUILDER: TierConfig(
        name="builder",
        display_name="Builder",
        price_monthly=2_900,
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
        included_model_credit_cents=1_000,
        overage_tool_call_cents=1,
        markup_percentage=0.30,
    ),
    PricingTier.PRO: TierConfig(
        name="pro",
        display_name="Pro",
        price_monthly=9_900,
        allowed_models=_PRO_MODELS,
        allowed_stt_backends=_PRO_STT,
        allowed_tts_backends=_PRO_TTS,
        allowed_architectures={"A", "C", "E"},
        allowed_security_policies={"standard", "strict", "safety_critical"},
        enable_domain_router=True,
        enable_voice_cloning=False,
        max_tool_calls_monthly=500_000,
        max_sessions_daily=0,
        max_swarm_agents=100,
        max_memory_entries=50_000,
        included_stt_minutes=6_000,
        included_tts_minutes=1_200,
        included_model_credit_cents=5_000,
        overage_tool_call_cents=1,
        markup_percentage=0.25,
    ),
    PricingTier.ENTERPRISE: TierConfig(
        name="enterprise",
        display_name="Enterprise",
        price_monthly=49_900,
        allowed_models=_ENTERPRISE_MODELS,
        allowed_stt_backends=_ENTERPRISE_STT,
        allowed_tts_backends=_ENTERPRISE_TTS,
        allowed_architectures={"A", "C", "E", "custom"},
        allowed_security_policies={"standard", "strict", "safety_critical", "custom"},
        enable_domain_router=True,
        enable_voice_cloning=True,
        max_tool_calls_monthly=0,
        max_sessions_daily=0,
        max_swarm_agents=0,
        max_memory_entries=0,
        included_stt_minutes=0,
        included_tts_minutes=0,
        included_model_credit_cents=20_000,
        overage_tool_call_cents=1,
        markup_percentage=0.20,
    ),
}


class BillingManager:
    def __init__(self, stripe_api_key: str = "") -> None:
        self._api_key: str = stripe_api_key or os.environ.get("STRIPE_SECRET_KEY", "")
        self._webhook_secret: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        self._stripe_client: Any = None

        self._customers: dict[str, Customer] = {}
        self._customers_by_stripe: dict[str, Customer] = {}
        self._events: dict[str, list[BillingEvent]] = defaultdict(list)
        self._meter_ids: dict[str, str] = {}
        self._product_ids: dict[str, str] = {}
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

    @property
    def is_stripe_enabled(self) -> bool:
        return self._stripe_client is not None

    async def create_customer(
        self,
        email: str,
        name: str,
        tier: PricingTier = PricingTier.MAKER,
        payment_method_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Customer:
        metadata = metadata or {}
        customer_id = str(uuid.uuid4())
        stripe_customer_id = ""
        stripe_subscription_id = ""

        tier_cfg = TIER_CONFIGS[tier]

        if self.is_stripe_enabled:
            try:
                stripe_meta = {
                    "openjarvis_customer_id": customer_id,
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
        if customer_id in self._customers:
            return self._customers[customer_id]

        if self.is_stripe_enabled:
            try:
                results = await asyncio.to_thread(
                    self._stripe_client.customers.search,
                    {"query": f"metadata['openjarvis_customer_id']:'{customer_id}'"},
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

    async def update_tier(self, customer_id: str, new_tier: PricingTier) -> Customer:
        customer = await self.get_customer(customer_id)
        if customer is None:
            raise ValueError(f"Customer not found: {customer_id}")

        new_cfg = TIER_CONFIGS[new_tier]
        old_tier = customer.tier
        customer.tier = new_tier

        if self.is_stripe_enabled:
            try:
                await asyncio.to_thread(
                    self._stripe_client.customers.update,
                    customer.stripe_customer_id,
                    {"metadata": {"tier": new_tier.value}},
                )

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

        customer.tier = PricingTier.MAKER
        return True

    async def record_llm_usage(
        self,
        customer_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> BillingEvent:
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
        customer = await self.get_customer(customer_id)
        tier = customer.tier if customer else PricingTier.MAKER
        cfg = TIER_CONFIGS[tier]
        unit_cost = cfg.overage_tool_call_cents / 1_000.0
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
        _SWARM_SPAWN_COST_CENTS = 1.0

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
        raw_cost = self._calculate_stt_cost(backend, duration_seconds)
        customer = await self.get_customer(customer_id)
        final_cost = self._apply_markup(raw_cost, customer.tier if customer else PricingTier.MAKER)

        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.STT_SECONDS,
            value=duration_seconds,
            unit_cost_cents=STT_COSTS.get(backend, 0.0) * 100 / 60,
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
        raw_cost = self._calculate_tts_cost(backend, text_length)
        customer = await self.get_customer(customer_id)
        final_cost = self._apply_markup(raw_cost, customer.tier if customer else PricingTier.MAKER)

        per_char_cents = (TTS_COSTS.get(backend, 0.0) * 100) / 1_000
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
        _MEMORY_ENTRY_OVERAGE_CENTS = 0.1

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
        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.CODE_EXECUTIONS,
            value=1.0,
            unit_cost_cents=0.0,
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
        event = BillingEvent(
            event_id=str(uuid.uuid4()),
            customer_id=customer_id,
            usage_type=UsageType.BROWSER_ACTIONS,
            value=1.0,
            unit_cost_cents=0.0,
            total_cost_cents=0.0,
            timestamp=time.time(),
        )
        event.stripe_meter_event_id = await self._send_meter_event(
            STRIPE_METERS["browser_actions"], customer_id, 1
        )

        self._events[customer_id].append(event)
        log.debug("Browser action: customer=%s", customer_id)
        return event

    async def get_usage_summary(
        self,
        customer_id: str,
        period_start: float | None = None,
        period_end: float | None = None,
    ) -> UsageSummary:
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

                included_secs = cfg.included_stt_minutes * 60
                if summary.stt_seconds > included_secs and included_secs > 0:
                    summary.total_cost_cents += int(event.total_cost_cents)
                    summary.overages["stt"] = summary.overages.get("stt", 0) + int(event.total_cost_cents)

            elif ut == UsageType.TTS_CHARACTERS:
                summary.tts_characters += int(event.value)
                summary.tts_cost_cents += int(event.total_cost_cents)
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
            return value * 1.0
        elif usage_type == UsageType.MEMORY_ENTRIES:
            return value * 0.1
        else:
            return 0.0

    def check_model_access(self, tier: PricingTier, model: str) -> tuple[bool, str]:
        cfg = TIER_CONFIGS[tier]
        if model in cfg.allowed_models:
            return True, ""
        for upgrade_tier in (PricingTier.BUILDER, PricingTier.PRO, PricingTier.ENTERPRISE):
            if model in TIER_CONFIGS[upgrade_tier].allowed_models:
                return False, (
                    f"Model '{model}' requires {TIER_CONFIGS[upgrade_tier].display_name} tier "
                    f"or above. Current tier: {cfg.display_name}."
                )
        return False, f"Model '{model}' is not available on any OpenJarvis tier."

    def check_stt_access(self, tier: PricingTier, backend: str) -> tuple[bool, str]:
        cfg = TIER_CONFIGS[tier]
        if backend in cfg.allowed_stt_backends:
            return True, ""
        for upgrade_tier in (PricingTier.BUILDER, PricingTier.PRO, PricingTier.ENTERPRISE):
            if backend in TIER_CONFIGS[upgrade_tier].allowed_stt_backends:
                return False, (
                    f"STT backend '{backend}' requires {TIER_CONFIGS[upgrade_tier].display_name} "
                    f"tier or above. Current tier: {cfg.display_name}."
                )
        return False, f"STT backend '{backend}' is not available on any OpenJarvis tier."

    def check_tts_access(self, tier: PricingTier, backend: str) -> tuple[bool, str]:
        cfg = TIER_CONFIGS[tier]
        if backend in cfg.allowed_tts_backends:
            return True, ""
        for upgrade_tier in (PricingTier.BUILDER, PricingTier.PRO, PricingTier.ENTERPRISE):
            if backend in TIER_CONFIGS[upgrade_tier].allowed_tts_backends:
                return False, (
                    f"TTS backend '{backend}' requires {TIER_CONFIGS[upgrade_tier].display_name} "
                    f"tier or above. Current tier: {cfg.display_name}."
                )
        return False, f"TTS backend '{backend}' is not available on any OpenJarvis tier."

    def check_architecture_access(self, tier: PricingTier, arch: str) -> tuple[bool, str]:
        cfg = TIER_CONFIGS[tier]
        if arch in cfg.allowed_architectures:
            return True, ""
        for upgrade_tier in (PricingTier.BUILDER, PricingTier.PRO, PricingTier.ENTERPRISE):
            if arch in TIER_CONFIGS[upgrade_tier].allowed_architectures:
                return False, (
                    f"Architecture '{arch}' requires {TIER_CONFIGS[upgrade_tier].display_name} "
                    f"tier or above. Current tier: {cfg.display_name}."
                )
        return False, f"Architecture '{arch}' is not available on any OpenJarvis tier."

    def check_feature_access(self, tier: PricingTier, feature: str) -> tuple[bool, str]:
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
                f"Agent swarm requires Builder tier or above. Current: {cfg.display_name}.",
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
        return TIER_CONFIGS[tier]

    async def setup_stripe_products(self) -> dict[str, str]:
        if not self.is_stripe_enabled:
            log.warning("setup_stripe_products called in offline mode — no-op")
            return {}

        created: dict[str, str] = {}

        for tier, cfg in TIER_CONFIGS.items():
            if cfg.price_monthly == 0:
                log.info("Skipping free tier %s (no Stripe product needed)", tier.value)
                continue

            try:
                product = await asyncio.to_thread(
                    self._stripe_client.products.create,
                    {
                        "name": f"OpenJarvis — {cfg.display_name}",
                        "description": (
                            f"OpenJarvis {cfg.display_name} plan: "
                            f"${cfg.price_monthly // 100}/mo with ${cfg.included_model_credit_cents // 100} "
                            f"model credit included."
                        ),
                        "metadata": {"tier": tier.value},
                    },
                )
                self._product_ids[tier.value] = product.id
                log.info("Created Stripe product %s for tier %s", product.id, tier.value)

                price = await asyncio.to_thread(
                    self._stripe_client.prices.create,
                    {
                        "product": product.id,
                        "unit_amount": cfg.price_monthly,
                        "currency": "usd",
                        "recurring": {"interval": "month"},
                        "nickname": f"OpenJarvis {cfg.display_name} Monthly",
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
        if not self.is_stripe_enabled:
            log.warning("setup_stripe_meters called in offline mode — no-op")
            return {}

        created: dict[str, str] = {}
        meter_definitions = [
            ("llm_input_tokens",  "OpenJarvis LLM Input Tokens",   "sum"),
            ("llm_output_tokens", "OpenJarvis LLM Output Tokens",  "sum"),
            ("tool_calls",        "OpenJarvis Tool Calls",          "sum"),
            ("swarm_spawns",      "OpenJarvis Swarm Agent Spawns",  "sum"),
            ("stt_seconds",       "OpenJarvis STT Seconds",         "sum"),
            ("tts_characters",    "OpenJarvis TTS Characters",      "sum"),
            ("memory_entries",    "OpenJarvis Memory Entries",      "sum"),
            ("code_executions",   "OpenJarvis Code Executions",     "sum"),
            ("browser_actions",   "OpenJarvis Browser Actions",     "sum"),
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

    async def _send_meter_event(
        self,
        event_name: str,
        customer_id: str,
        value: float,
    ) -> str:
        if not self.is_stripe_enabled:
            return ""

        customer = self._customers.get(customer_id)
        if customer is None:
            log.warning("_send_meter_event: unknown customer %s", customer_id)
            return ""

        stripe_customer_id = customer.stripe_customer_id
        if stripe_customer_id.startswith("offline_"):
            return ""

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

    def _calculate_llm_cost(self, model: str, input_tokens: int, output_tokens: int) -> int:
        costs = MODEL_COSTS.get(model)
        if costs is None:
            log.warning("Unknown model '%s' in _calculate_llm_cost; using $0 cost", model)
            return 0

        input_cost_usd, output_cost_usd = costs
        total_usd = (
            (input_tokens / 1_000_000) * input_cost_usd
            + (output_tokens / 1_000_000) * output_cost_usd
        )
        return int(round(total_usd * 100))

    def _calculate_stt_cost(self, backend: str, duration_seconds: float) -> int:
        cost_per_min_usd = STT_COSTS.get(backend)
        if cost_per_min_usd is None:
            log.warning("Unknown STT backend '%s'; using $0 cost", backend)
            return 0

        duration_minutes = duration_seconds / 60.0
        total_usd = duration_minutes * cost_per_min_usd
        return int(round(total_usd * 100))

    def _calculate_tts_cost(self, backend: str, characters: int) -> int:
        cost_per_1k_usd = TTS_COSTS.get(backend)
        if cost_per_1k_usd is None:
            log.warning("Unknown TTS backend '%s'; using $0 cost", backend)
            return 0

        total_usd = (characters / 1_000.0) * cost_per_1k_usd
        return int(round(total_usd * 100))

    def _apply_markup(self, cost_cents: int, tier: PricingTier) -> int:
        cfg = TIER_CONFIGS[tier]
        markup = cfg.markup_percentage
        return int(round(cost_cents * (1.0 + markup)))


class NullBillingManager:
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
