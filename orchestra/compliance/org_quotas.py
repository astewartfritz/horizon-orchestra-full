"""
Per-Org Rate Limits & Quotas.

Every Fortune 500 org gets isolated resource controls with per-tier
defaults, usage tracking, utilization monitoring, and automatic
reset scheduling. Provides both programmatic API and FastAPI route
registration for admin endpoints.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

__all__ = [
    "OrgQuota",
    "QuotaUsage",
    "OrgQuotaManager",
    "QuotaTier",
    "TIER_QUOTAS",
]


# ---------------------------------------------------------------------------
# Quota Tier Enum
# ---------------------------------------------------------------------------

class QuotaTier(str, Enum):
    """Subscription tiers with associated quota defaults."""
    FREE = "free"
    PRO = "pro"
    TEAM = "team"
    MAX = "max"
    ENTERPRISE = "enterprise"


# ---------------------------------------------------------------------------
# Tier-based quota defaults (aligned with billing tiers)
# ---------------------------------------------------------------------------

TIER_QUOTAS: Dict[str, Dict[str, Any]] = {
    QuotaTier.FREE.value: {
        "requests_per_min": 10,
        "requests_per_day": 200,
        "tokens_per_month": 500_000,
        "agents_concurrent": 1,
        "storage_gb": 1,
        "teams_max": 1,
        "specialists_max": 3,
        "api_keys_max": 1,
        "file_upload_mb": 10,
        "memory_entries_max": 100,
        "connectors_max": 3,
    },
    QuotaTier.PRO.value: {
        "requests_per_min": 60,
        "requests_per_day": 5_000,
        "tokens_per_month": 10_000_000,
        "agents_concurrent": 5,
        "storage_gb": 50,
        "teams_max": 5,
        "specialists_max": 20,
        "api_keys_max": 10,
        "file_upload_mb": 100,
        "memory_entries_max": 10_000,
        "connectors_max": 20,
    },
    QuotaTier.TEAM.value: {
        "requests_per_min": 200,
        "requests_per_day": 50_000,
        "tokens_per_month": 100_000_000,
        "agents_concurrent": 20,
        "storage_gb": 500,
        "teams_max": 50,
        "specialists_max": 100,
        "api_keys_max": 50,
        "file_upload_mb": 500,
        "memory_entries_max": 100_000,
        "connectors_max": 100,
    },
    QuotaTier.MAX.value: {
        "requests_per_min": 1_000,
        "requests_per_day": 500_000,
        "tokens_per_month": 1_000_000_000,
        "agents_concurrent": 100,
        "storage_gb": 5_000,
        "teams_max": 500,
        "specialists_max": 1_000,
        "api_keys_max": 200,
        "file_upload_mb": 2_000,
        "memory_entries_max": 1_000_000,
        "connectors_max": 500,
    },
    QuotaTier.ENTERPRISE.value: {
        "requests_per_min": 10_000,
        "requests_per_day": 5_000_000,
        "tokens_per_month": 10_000_000_000,
        "agents_concurrent": 1_000,
        "storage_gb": 50_000,
        "teams_max": 5_000,
        "specialists_max": 10_000,
        "api_keys_max": 1_000,
        "file_upload_mb": 10_000,
        "memory_entries_max": 10_000_000,
        "connectors_max": 5_000,
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OrgQuota:
    """
    Quota limits for an organization.

    Defines maximum resource consumption across all quota dimensions.
    """
    org_id: str = ""
    tier: str = QuotaTier.FREE.value
    requests_per_min: int = 10
    requests_per_day: int = 200
    tokens_per_month: int = 500_000
    agents_concurrent: int = 1
    storage_gb: int = 1
    teams_max: int = 1
    specialists_max: int = 3
    api_keys_max: int = 1
    file_upload_mb: int = 10
    memory_entries_max: int = 100
    connectors_max: int = 3
    custom_overrides: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "tier": self.tier,
            "requests_per_min": self.requests_per_min,
            "requests_per_day": self.requests_per_day,
            "tokens_per_month": self.tokens_per_month,
            "agents_concurrent": self.agents_concurrent,
            "storage_gb": self.storage_gb,
            "teams_max": self.teams_max,
            "specialists_max": self.specialists_max,
            "api_keys_max": self.api_keys_max,
            "file_upload_mb": self.file_upload_mb,
            "memory_entries_max": self.memory_entries_max,
            "connectors_max": self.connectors_max,
            "custom_overrides": self.custom_overrides,
        }

    def get_limit(self, resource: str) -> int:
        """Get the limit for a specific resource, checking custom overrides first."""
        if resource in self.custom_overrides:
            return self.custom_overrides[resource]
        return getattr(self, resource, 0)


@dataclass
class QuotaUsage:
    """
    Current usage counters for an organization.

    Tracks usage across all quota dimensions with reset timestamps.
    """
    org_id: str = ""
    # Current counts
    requests_this_min: int = 0
    requests_today: int = 0
    tokens_this_month: int = 0
    agents_active: int = 0
    storage_used_gb: float = 0.0
    teams_count: int = 0
    specialists_count: int = 0
    api_keys_count: int = 0
    memory_entries_count: int = 0
    connectors_count: int = 0
    # Reset timestamps
    minute_reset_at: float = 0.0
    daily_reset_at: float = 0.0
    monthly_reset_at: float = 0.0
    # Tracking
    last_request_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "requests_this_min": self.requests_this_min,
            "requests_today": self.requests_today,
            "tokens_this_month": self.tokens_this_month,
            "agents_active": self.agents_active,
            "storage_used_gb": self.storage_used_gb,
            "teams_count": self.teams_count,
            "specialists_count": self.specialists_count,
            "api_keys_count": self.api_keys_count,
            "memory_entries_count": self.memory_entries_count,
            "connectors_count": self.connectors_count,
            "minute_reset_at": self.minute_reset_at,
            "daily_reset_at": self.daily_reset_at,
            "monthly_reset_at": self.monthly_reset_at,
            "last_request_at": self.last_request_at,
        }


# ---------------------------------------------------------------------------
# Resource-to-field mappings
# ---------------------------------------------------------------------------

_RESOURCE_TO_QUOTA_FIELD: Dict[str, str] = {
    "requests": "requests_per_min",
    "requests_per_min": "requests_per_min",
    "requests_daily": "requests_per_day",
    "requests_per_day": "requests_per_day",
    "tokens": "tokens_per_month",
    "tokens_per_month": "tokens_per_month",
    "agents": "agents_concurrent",
    "agents_concurrent": "agents_concurrent",
    "storage": "storage_gb",
    "storage_gb": "storage_gb",
    "teams": "teams_max",
    "teams_max": "teams_max",
    "specialists": "specialists_max",
    "specialists_max": "specialists_max",
    "api_keys": "api_keys_max",
    "api_keys_max": "api_keys_max",
    "memory": "memory_entries_max",
    "memory_entries_max": "memory_entries_max",
    "connectors": "connectors_max",
    "connectors_max": "connectors_max",
}

_RESOURCE_TO_USAGE_FIELD: Dict[str, str] = {
    "requests": "requests_this_min",
    "requests_per_min": "requests_this_min",
    "requests_daily": "requests_today",
    "requests_per_day": "requests_today",
    "tokens": "tokens_this_month",
    "tokens_per_month": "tokens_this_month",
    "agents": "agents_active",
    "agents_concurrent": "agents_active",
    "storage": "storage_used_gb",
    "storage_gb": "storage_used_gb",
    "teams": "teams_count",
    "teams_max": "teams_count",
    "specialists": "specialists_count",
    "specialists_max": "specialists_count",
    "api_keys": "api_keys_count",
    "api_keys_max": "api_keys_count",
    "memory": "memory_entries_count",
    "memory_entries_max": "memory_entries_count",
    "connectors": "connectors_count",
    "connectors_max": "connectors_count",
}


# ---------------------------------------------------------------------------
# Org Quota Manager
# ---------------------------------------------------------------------------

class OrgQuotaManager:
    """
    Per-org rate limits and quota enforcement.

    Manages quota allocation, usage tracking, utilization monitoring,
    and provides admin API endpoints.
    """

    def __init__(self) -> None:
        self._quotas: Dict[str, OrgQuota] = {}
        self._usage: Dict[str, QuotaUsage] = {}

    # -- Quota management ---------------------------------------------------

    def set_quota(self, org_id: str, quota: OrgQuota) -> None:
        """Set or update the quota for an organization."""
        quota.org_id = org_id
        self._quotas[org_id] = quota
        # Initialize usage if not exists
        if org_id not in self._usage:
            now = time.time()
            self._usage[org_id] = QuotaUsage(
                org_id=org_id,
                minute_reset_at=now + 60,
                daily_reset_at=now + 86400,
                monthly_reset_at=now + 2592000,
            )

    def get_quota(self, org_id: str) -> OrgQuota:
        """Get the quota for an organization. Returns free-tier defaults if unset."""
        if org_id in self._quotas:
            return self._quotas[org_id]
        return self.default_quota(QuotaTier.FREE.value)

    def default_quota(self, tier: str) -> OrgQuota:
        """Create a default OrgQuota for a given tier."""
        tier_lower = tier.lower()
        defaults = TIER_QUOTAS.get(tier_lower, TIER_QUOTAS[QuotaTier.FREE.value])
        return OrgQuota(
            tier=tier_lower,
            requests_per_min=defaults["requests_per_min"],
            requests_per_day=defaults["requests_per_day"],
            tokens_per_month=defaults["tokens_per_month"],
            agents_concurrent=defaults["agents_concurrent"],
            storage_gb=defaults["storage_gb"],
            teams_max=defaults["teams_max"],
            specialists_max=defaults["specialists_max"],
            api_keys_max=defaults["api_keys_max"],
            file_upload_mb=defaults.get("file_upload_mb", 10),
            memory_entries_max=defaults.get("memory_entries_max", 100),
            connectors_max=defaults.get("connectors_max", 3),
        )

    # -- Usage checking & recording -----------------------------------------

    async def check(
        self,
        org_id: str,
        resource: str,
        amount: int = 1,
    ) -> Tuple[bool, str, int]:
        """
        Check if a resource consumption is within quota.

        Args:
            org_id: Organization identifier.
            resource: Resource type (e.g., 'requests', 'tokens', 'agents').
            amount: Amount of resource to consume.

        Returns:
            Tuple of (allowed, reason, retry_after_seconds).
        """
        quota = self.get_quota(org_id)
        usage = self._get_or_create_usage(org_id)

        # Auto-reset expired windows
        self._auto_reset(usage)

        quota_field = _RESOURCE_TO_QUOTA_FIELD.get(resource, resource)
        usage_field = _RESOURCE_TO_USAGE_FIELD.get(resource, "")

        limit = quota.get_limit(quota_field)
        if limit <= 0:
            return (True, "No limit configured", 0)

        if not usage_field:
            return (True, f"Unknown resource '{resource}'", 0)

        current = getattr(usage, usage_field, 0)
        if isinstance(current, float):
            current = int(current)

        if current + amount > limit:
            # Calculate retry_after for time-windowed resources
            retry_after = 0
            now = time.time()
            if resource in ("requests", "requests_per_min"):
                retry_after = max(0, int(usage.minute_reset_at - now))
            elif resource in ("requests_daily", "requests_per_day"):
                retry_after = max(0, int(usage.daily_reset_at - now))
            elif resource in ("tokens", "tokens_per_month"):
                retry_after = max(0, int(usage.monthly_reset_at - now))

            return (
                False,
                f"Quota exceeded for '{resource}': {current}/{limit} "
                f"(requested {amount})",
                retry_after,
            )

        return (True, "Within quota", 0)

    async def record_usage(
        self,
        org_id: str,
        resource: str,
        amount: int = 1,
    ) -> None:
        """
        Record resource usage for an organization.

        Args:
            org_id: Organization identifier.
            resource: Resource type.
            amount: Amount consumed.
        """
        usage = self._get_or_create_usage(org_id)
        self._auto_reset(usage)

        usage_field = _RESOURCE_TO_USAGE_FIELD.get(resource, "")
        if not usage_field:
            return

        current = getattr(usage, usage_field, 0)
        setattr(usage, usage_field, current + amount)
        usage.last_request_at = time.time()

    async def get_usage(self, org_id: str) -> QuotaUsage:
        """Get current usage for an organization."""
        usage = self._get_or_create_usage(org_id)
        self._auto_reset(usage)
        return usage

    async def get_utilization(self, org_id: str) -> Dict[str, float]:
        """
        Get utilization percentages for each quota dimension.

        Returns a dict mapping resource names to utilization percentages (0.0 - 1.0+).
        """
        quota = self.get_quota(org_id)
        usage = self._get_or_create_usage(org_id)
        self._auto_reset(usage)

        utilization: Dict[str, float] = {}

        for resource, quota_field in _RESOURCE_TO_QUOTA_FIELD.items():
            # Skip aliases
            if resource != quota_field:
                continue

            limit = quota.get_limit(quota_field)
            if limit <= 0:
                utilization[quota_field] = 0.0
                continue

            usage_field = _RESOURCE_TO_USAGE_FIELD.get(resource, "")
            if not usage_field:
                continue

            current = getattr(usage, usage_field, 0)
            utilization[quota_field] = round(float(current) / float(limit), 4)

        return utilization

    # -- Reset operations ---------------------------------------------------

    async def reset_daily(self, org_id: str) -> None:
        """Reset daily usage counters for an organization."""
        usage = self._get_or_create_usage(org_id)
        usage.requests_today = 0
        usage.daily_reset_at = time.time() + 86400

    async def reset_monthly(self, org_id: str) -> None:
        """Reset monthly usage counters for an organization."""
        usage = self._get_or_create_usage(org_id)
        usage.tokens_this_month = 0
        usage.monthly_reset_at = time.time() + 2592000  # ~30 days

    def _auto_reset(self, usage: QuotaUsage) -> None:
        """Auto-reset expired time windows."""
        now = time.time()
        if now >= usage.minute_reset_at:
            usage.requests_this_min = 0
            usage.minute_reset_at = now + 60
        if now >= usage.daily_reset_at:
            usage.requests_today = 0
            usage.daily_reset_at = now + 86400
        if now >= usage.monthly_reset_at:
            usage.tokens_this_month = 0
            usage.monthly_reset_at = now + 2592000

    # -- Monitoring ---------------------------------------------------------

    async def list_near_limit(self, threshold: float = 0.8) -> List[Dict[str, Any]]:
        """
        List organizations approaching their quota limits.

        Args:
            threshold: Utilization threshold (0.0 to 1.0). Default 0.8 (80%).

        Returns:
            List of dicts with org_id, resource, utilization, and limit details.
        """
        alerts: List[Dict[str, Any]] = []

        for org_id in self._quotas:
            utilization = await self.get_utilization(org_id)
            quota = self.get_quota(org_id)

            for resource, pct in utilization.items():
                if pct >= threshold:
                    limit = quota.get_limit(resource)
                    usage_field = _RESOURCE_TO_USAGE_FIELD.get(resource, "")
                    current = 0
                    if usage_field:
                        usage = self._get_or_create_usage(org_id)
                        current = getattr(usage, usage_field, 0)

                    alerts.append({
                        "org_id": org_id,
                        "tier": quota.tier,
                        "resource": resource,
                        "utilization": pct,
                        "current": current,
                        "limit": limit,
                        "severity": "critical" if pct >= 1.0 else "warning",
                    })

        # Sort by utilization descending
        alerts.sort(key=lambda x: x["utilization"], reverse=True)
        return alerts

    # -- Admin stats --------------------------------------------------------

    async def get_all_org_stats(self) -> List[Dict[str, Any]]:
        """Get usage statistics for all tracked organizations."""
        stats = []
        for org_id in self._quotas:
            quota = self.get_quota(org_id)
            usage = await self.get_usage(org_id)
            utilization = await self.get_utilization(org_id)
            stats.append({
                "org_id": org_id,
                "tier": quota.tier,
                "usage": usage.to_dict(),
                "utilization": utilization,
            })
        return stats

    # -- Route registration -------------------------------------------------

    def register_routes(self, app: Any) -> None:
        """
        Mount /v1/admin/quotas endpoints on a FastAPI app.

        Endpoints:
          GET  /v1/admin/quotas/{org_id}         — get org quota
          PUT  /v1/admin/quotas/{org_id}         — set org quota
          GET  /v1/admin/quotas/{org_id}/usage   — get usage
          GET  /v1/admin/quotas/{org_id}/util    — get utilization
          POST /v1/admin/quotas/{org_id}/reset   — reset counters
          GET  /v1/admin/quotas/alerts            — near-limit orgs
          GET  /v1/admin/quotas/stats             — all org stats
        """
        try:
            from fastapi import Request
            from fastapi.responses import JSONResponse
        except ImportError:
            raise RuntimeError("FastAPI is required for quota route registration")

        prefix = "/v1/admin/quotas"

        @app.get(f"{prefix}/alerts")
        async def quota_alerts(request: Request):
            threshold = float(request.query_params.get("threshold", "0.8"))
            alerts = await self.list_near_limit(threshold)
            return JSONResponse({"alerts": alerts})

        @app.get(f"{prefix}/stats")
        async def quota_stats():
            stats = await self.get_all_org_stats()
            return JSONResponse({"organizations": stats})

        @app.get(f"{prefix}/{{org_id}}")
        async def get_quota(org_id: str):
            quota = self.get_quota(org_id)
            return JSONResponse(quota.to_dict())

        @app.put(f"{prefix}/{{org_id}}")
        async def set_quota_endpoint(org_id: str, request: Request):
            data = await request.json()
            tier = data.get("tier", "free")
            quota = self.default_quota(tier)

            # Apply custom overrides
            for key in [
                "requests_per_min", "requests_per_day", "tokens_per_month",
                "agents_concurrent", "storage_gb", "teams_max",
                "specialists_max", "api_keys_max",
            ]:
                if key in data:
                    setattr(quota, key, data[key])

            self.set_quota(org_id, quota)
            return JSONResponse(quota.to_dict())

        @app.get(f"{prefix}/{{org_id}}/usage")
        async def get_usage_endpoint(org_id: str):
            usage = await self.get_usage(org_id)
            return JSONResponse(usage.to_dict())

        @app.get(f"{prefix}/{{org_id}}/util")
        async def get_utilization_endpoint(org_id: str):
            utilization = await self.get_utilization(org_id)
            return JSONResponse(utilization)

        @app.post(f"{prefix}/{{org_id}}/reset")
        async def reset_quota(org_id: str, request: Request):
            data = await request.json()
            scope = data.get("scope", "daily")
            if scope == "daily":
                await self.reset_daily(org_id)
            elif scope == "monthly":
                await self.reset_monthly(org_id)
            elif scope == "all":
                await self.reset_daily(org_id)
                await self.reset_monthly(org_id)
            return JSONResponse({"status": "reset", "scope": scope, "org_id": org_id})

    # -- Internal helpers ---------------------------------------------------

    def _get_or_create_usage(self, org_id: str) -> QuotaUsage:
        """Get or create a usage tracker for an organization."""
        if org_id not in self._usage:
            now = time.time()
            self._usage[org_id] = QuotaUsage(
                org_id=org_id,
                minute_reset_at=now + 60,
                daily_reset_at=now + 86400,
                monthly_reset_at=now + 2592000,
            )
        return self._usage[org_id]
