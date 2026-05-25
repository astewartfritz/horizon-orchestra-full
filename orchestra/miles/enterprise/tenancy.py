"""MILES Enterprise — Multi-Tenancy and Org Isolation.

Hard per-org data separation for MILES enterprise deployments.
Each tenant gets:
  - Isolated conversation and memory storage
  - Separate audit log namespace
  - Per-tenant rate limits
  - Per-tenant model/tool policy
  - Per-tenant RBAC role overrides

Usage::

    from orchestra.miles.enterprise.tenancy import TenantStore, TenantContext
    store = TenantStore()
    tenant = store.get_or_create("acme-corp", display_name="Acme Corporation")
    async with TenantContext(tenant):
        ...  # all storage ops scoped to this tenant
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

log = logging.getLogger("orchestra.miles.enterprise.tenancy")

# Request-scoped tenant (set by middleware, read by storage layer)
_current_tenant: ContextVar[Tenant | None] = ContextVar("current_tenant", default=None)


# ── Tenant model ──────────────────────────────────────────────────────────────

@dataclass
class TenantLimits:
    max_users: int                 = 500
    max_concurrent_tasks: int      = 20
    requests_per_minute: int       = 300
    requests_per_hour: int         = 5_000
    max_storage_mb: int            = 10_000
    max_conversation_history: int  = 10_000
    allowed_models: list[str]      = field(default_factory=list)   # empty = all
    allowed_tools: list[str]       = field(default_factory=list)   # empty = all


@dataclass
class TenantSettings:
    # SSO
    sso_enforced: bool             = False
    allowed_email_domains: list[str] = field(default_factory=list)
    # Data residency
    data_region: str               = "us-east-1"
    # Audit
    audit_retention_days: int      = 365
    # Branding
    display_name: str              = ""
    logo_url: str                  = ""
    custom_domain: str             = ""
    # RBAC
    default_user_role: str         = "analyst"
    custom_roles: list[dict]       = field(default_factory=list)
    # Model policy
    default_model: str             = "claude-sonnet-4-6"
    # Feature flags
    features: dict[str, bool]      = field(default_factory=lambda: {
        "voice":            True,
        "channels":         True,
        "workflows":        True,
        "red_team":         False,
        "multimodel":       True,
        "custom_tools":     False,
    })


@dataclass
class Tenant:
    id: str                                   # Slug, e.g. "acme-corp"
    display_name: str
    owner_user_id: str                        = ""
    plan: str                                 = "enterprise"   # free|pro|enterprise
    limits: TenantLimits                      = field(default_factory=TenantLimits)
    settings: TenantSettings                  = field(default_factory=TenantSettings)
    member_ids: list[str]                     = field(default_factory=list)
    created_at: float                         = field(default_factory=time.time)
    active: bool                              = True
    metadata: dict[str, Any]                  = field(default_factory=dict)

    @property
    def storage_prefix(self) -> str:
        """Unique filesystem / key prefix for this tenant."""
        return f"tenant_{self.id}"

    @property
    def audit_namespace(self) -> str:
        return f"audit/{self.id}"

    def is_member(self, user_id: str) -> bool:
        return user_id in self.member_ids

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "owner_user_id": self.owner_user_id,
            "plan": self.plan,
            "active": self.active,
            "member_count": len(self.member_ids),
            "created_at": self.created_at,
            "data_region": self.settings.data_region,
            "features": self.settings.features,
        }


# ── Tenant store ──────────────────────────────────────────────────────────────

class TenantStore:
    """
    Registry of all tenants.

    In production, back this with Postgres or Redis.
    The interface is async to make that swap transparent.
    """

    def __init__(self, persistence_path: str | None = None) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._lock = asyncio.Lock()
        self._path = (
            Path(persistence_path)
            if persistence_path
            else Path(os.environ.get("MILES_DATA_DIR", ".miles")) / "tenants.json"
        )
        self._load()

    # ── CRUD ──────────────────────────────────────────────────────────────

    async def create(
        self,
        tenant_id: str,
        display_name: str,
        owner_user_id: str = "",
        plan: str = "enterprise",
        **kwargs: Any,
    ) -> Tenant:
        async with self._lock:
            if tenant_id in self._tenants:
                raise ValueError(f"Tenant '{tenant_id}' already exists")
            tenant = Tenant(
                id=tenant_id,
                display_name=display_name,
                owner_user_id=owner_user_id,
                plan=plan,
                **kwargs,
            )
            self._tenants[tenant_id] = tenant
            await self._persist()
        log.info("Tenant created: %s (%s)", tenant_id, display_name)
        return tenant

    async def get(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    async def get_or_create(self, tenant_id: str, **kwargs: Any) -> Tenant:
        existing = await self.get(tenant_id)
        if existing:
            return existing
        return await self.create(tenant_id, **kwargs)

    async def update(self, tenant_id: str, **fields: Any) -> Tenant:
        async with self._lock:
            tenant = self._tenants.get(tenant_id)
            if not tenant:
                raise KeyError(f"Tenant '{tenant_id}' not found")
            for k, v in fields.items():
                if hasattr(tenant, k):
                    setattr(tenant, k, v)
                elif hasattr(tenant.settings, k):
                    setattr(tenant.settings, k, v)
                elif hasattr(tenant.limits, k):
                    setattr(tenant.limits, k, v)
            await self._persist()
        return tenant

    async def deactivate(self, tenant_id: str) -> None:
        await self.update(tenant_id, active=False)
        log.info("Tenant deactivated: %s", tenant_id)

    async def add_member(self, tenant_id: str, user_id: str) -> bool:
        async with self._lock:
            tenant = self._tenants.get(tenant_id)
            if not tenant or user_id in tenant.member_ids:
                return False
            if len(tenant.member_ids) >= tenant.limits.max_users:
                raise ValueError(
                    f"Tenant '{tenant_id}' has reached user limit ({tenant.limits.max_users})"
                )
            tenant.member_ids.append(user_id)
            await self._persist()
        return True

    async def remove_member(self, tenant_id: str, user_id: str) -> bool:
        async with self._lock:
            tenant = self._tenants.get(tenant_id)
            if not tenant or user_id not in tenant.member_ids:
                return False
            tenant.member_ids.remove(user_id)
            await self._persist()
        return True

    async def list_all(self, include_inactive: bool = False) -> list[Tenant]:
        tenants = list(self._tenants.values())
        if not include_inactive:
            tenants = [t for t in tenants if t.active]
        return tenants

    async def find_by_email_domain(self, domain: str) -> list[Tenant]:
        return [
            t for t in self._tenants.values()
            if t.active and domain in t.settings.allowed_email_domains
        ]

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                for d in raw:
                    t = _tenant_from_dict(d)
                    self._tenants[t.id] = t
                log.info("Loaded %d tenants from %s", len(self._tenants), self._path)
            except Exception as exc:
                log.warning("Could not load tenant store: %s", exc)

    async def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = [_tenant_to_dict(t) for t in self._tenants.values()]
            self._path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            log.warning("Could not persist tenant store: %s", exc)


# ── Namespaced storage wrappers ───────────────────────────────────────────────

class TenantScopedStore:
    """
    Wraps any key-value store to namespace all keys by tenant ID.

    Pass this to MILES memory, session, and audit layers in place of the
    global store to achieve hard data isolation between tenants.
    """

    def __init__(self, backing_store: Any, tenant_id: str) -> None:
        self._store = backing_store
        self._prefix = f"{tenant_id}/"

    def _key(self, k: str) -> str:
        return self._prefix + k

    def _strip(self, k: str) -> str:
        return k[len(self._prefix):] if k.startswith(self._prefix) else k

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(self._key(key), default)

    def set(self, key: str, value: Any) -> None:
        self._store.set(self._key(key), value)

    def delete(self, key: str) -> None:
        self._store.delete(self._key(key))

    def keys(self, pattern: str = "*") -> list[str]:
        raw = self._store.keys(self._prefix + pattern)
        return [self._strip(k) for k in raw]

    def exists(self, key: str) -> bool:
        return self._store.exists(self._key(key))


class TenantAuditNamespace:
    """
    Routes audit events to a per-tenant ledger namespace.
    Wraps the existing AuditLedger by injecting tenant_id into every event.
    """

    def __init__(self, ledger: Any, tenant_id: str) -> None:
        self._ledger = ledger
        self._tenant_id = tenant_id

    def record(self, event_type: str, **kwargs: Any) -> None:
        kwargs.setdefault("metadata", {})["tenant_id"] = self._tenant_id
        if hasattr(self._ledger, "record"):
            self._ledger.record(event_type, **kwargs)

    def get_events(self, **filters: Any) -> list[Any]:
        events = self._ledger.get_events(**filters) if hasattr(self._ledger, "get_events") else []
        return [
            e for e in events
            if (e.get("metadata") or {}).get("tenant_id") == self._tenant_id
        ]

    def export(self, format: str = "jsonl") -> str:
        events = self.get_events()
        if format == "jsonl":
            return "\n".join(json.dumps(e) for e in events)
        return json.dumps(events, indent=2)


# ── Context manager ───────────────────────────────────────────────────────────

@asynccontextmanager
async def TenantContext(tenant: Tenant) -> AsyncIterator[Tenant]:
    """Async context manager that sets the current tenant for a request."""
    token = _current_tenant.set(tenant)
    try:
        yield tenant
    finally:
        _current_tenant.reset(token)


def current_tenant() -> Tenant | None:
    """Return the tenant for the current async context (set by middleware)."""
    return _current_tenant.get()


def require_tenant() -> Tenant:
    """Return the current tenant or raise RuntimeError."""
    t = _current_tenant.get()
    if t is None:
        raise RuntimeError("No tenant in current context — did the middleware run?")
    return t


# ── FastAPI middleware ────────────────────────────────────────────────────────

def tenant_middleware(store: TenantStore, header: str = "X-Orchestra-Tenant-ID"):
    """
    Starlette middleware that reads the tenant ID from a header (or JWT claim)
    and injects it into request state + context var.

    Supports three resolution strategies (tried in order):
      1. ``X-Orchestra-Tenant-ID`` request header
      2. ``tenant_id`` claim in the SSO identity already set by SSOMiddleware
      3. Email domain → tenant lookup (for implicit tenant routing)
    """
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse
    except ImportError:
        raise ImportError("starlette required: pip install starlette")

    class _TenantMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Strategy 1: explicit header
            tenant_id = request.headers.get(header, "")

            # Strategy 2: tenant_id in SSO identity
            if not tenant_id:
                identity = getattr(request.state, "sso_identity", None)
                if identity:
                    tenant_id = (
                        getattr(identity, "raw_claims", {}).get("orchestra_tenant")
                        or getattr(identity, "org_id", "")
                    )

            # Strategy 3: email domain
            if not tenant_id:
                identity = getattr(request.state, "sso_identity", None)
                email = getattr(identity, "email", "") if identity else ""
                if "@" in email:
                    domain = email.split("@")[1]
                    matches = await store.find_by_email_domain(domain)
                    if matches:
                        tenant_id = matches[0].id

            tenant = None
            if tenant_id:
                tenant = await store.get(tenant_id)
                if tenant and not tenant.active:
                    return JSONResponse(
                        {"error": f"Tenant '{tenant_id}' is inactive"},
                        status_code=403,
                    )

            request.state.tenant = tenant
            ctx_token = _current_tenant.set(tenant)
            try:
                response = await call_next(request)
            finally:
                _current_tenant.reset(ctx_token)
            return response

    return _TenantMiddleware


# ── Admin API routes ──────────────────────────────────────────────────────────

def tenant_admin_router(store: TenantStore, rbac_check=None) -> Any:
    """FastAPI router for tenant CRUD — mount at /miles/admin/tenants."""
    try:
        from fastapi import APIRouter, HTTPException, Request
    except ImportError:
        raise ImportError("FastAPI required: pip install fastapi")

    router = APIRouter(prefix="/admin/tenants", tags=["Tenant Admin"])

    @router.get("")
    async def list_tenants(include_inactive: bool = False):
        tenants = await store.list_all(include_inactive)
        return {"tenants": [t.to_dict() for t in tenants], "total": len(tenants)}

    @router.get("/{tenant_id}")
    async def get_tenant(tenant_id: str):
        t = await store.get(tenant_id)
        if not t:
            raise HTTPException(404, f"Tenant '{tenant_id}' not found")
        return t.to_dict()

    @router.post("", status_code=201)
    async def create_tenant(request: Request):
        body = await request.json()
        try:
            t = await store.create(
                tenant_id=body["id"],
                display_name=body.get("display_name", body["id"]),
                owner_user_id=body.get("owner_user_id", ""),
                plan=body.get("plan", "enterprise"),
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc))
        return t.to_dict()

    @router.patch("/{tenant_id}")
    async def update_tenant(tenant_id: str, request: Request):
        body = await request.json()
        try:
            t = await store.update(tenant_id, **body)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return t.to_dict()

    @router.delete("/{tenant_id}", status_code=204)
    async def deactivate_tenant(tenant_id: str):
        await store.deactivate(tenant_id)

    @router.post("/{tenant_id}/members/{user_id}")
    async def add_member(tenant_id: str, user_id: str):
        try:
            ok = await store.add_member(tenant_id, user_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": ok}

    @router.delete("/{tenant_id}/members/{user_id}")
    async def remove_member(tenant_id: str, user_id: str):
        ok = await store.remove_member(tenant_id, user_id)
        return {"ok": ok}

    return router


# ── Serialization helpers ─────────────────────────────────────────────────────

def _tenant_to_dict(t: Tenant) -> dict:
    return {
        "id": t.id,
        "display_name": t.display_name,
        "owner_user_id": t.owner_user_id,
        "plan": t.plan,
        "active": t.active,
        "member_ids": t.member_ids,
        "created_at": t.created_at,
        "metadata": t.metadata,
        "settings": vars(t.settings),
        "limits": vars(t.limits),
    }


def _tenant_from_dict(d: dict) -> Tenant:
    settings_raw = d.pop("settings", {})
    limits_raw = d.pop("limits", {})
    settings = TenantSettings(**{k: v for k, v in settings_raw.items()
                                 if k in TenantSettings.__dataclass_fields__})
    limits = TenantLimits(**{k: v for k, v in limits_raw.items()
                              if k in TenantLimits.__dataclass_fields__})
    return Tenant(settings=settings, limits=limits, **{
        k: v for k, v in d.items() if k in Tenant.__dataclass_fields__
    })
