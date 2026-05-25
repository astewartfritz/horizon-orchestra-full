"""MILES Enterprise capabilities — SSO, RBAC, and Multi-Tenancy.

These modules add Fortune 500-grade identity, access control, and data
isolation to MILES while keeping the Orchestra main UI simple and clean.

Quick-start::

    from orchestra.miles.enterprise import (
        SSOConfig, SSOEngine, scim_router, sso_middleware,
        RBACEngine, rbac_dependency, Role,
        TenantStore, TenantContext, tenant_middleware,
    )

    # Build from environment variables
    sso_cfg = SSOConfig.from_env()
    sso = SSOEngine(sso_cfg)
    rbac = RBACEngine()
    tenants = TenantStore()

    # Mount on your FastAPI app
    app.add_middleware(sso_middleware(sso, protected_prefix="/miles/api"))
    app.add_middleware(tenant_middleware(tenants))
    app.include_router(scim_router(sso), prefix="/miles")
"""
from __future__ import annotations

__all__ = [
    # SSO / OIDC / SAML / SCIM
    "IdPProvider",
    "OIDCConfig",
    "SAMLConfig",
    "SCIMConfig",
    "SSOConfig",
    "OIDCIdentity",
    "OIDCValidator",
    "SAMLIdentity",
    "SAMLValidator",
    "SCIMUser",
    "SCIMStore",
    "SSOEngine",
    "scim_router",
    "sso_middleware",
    # RBAC
    "Action",
    "Resource",
    "Permission",
    "Role",
    "BUILTIN_ROLES",
    "RBACEngine",
    "RBACAccessLog",
    "AccessEvent",
    "rbac_dependency",
    "rbac_middleware",
    # Multi-tenancy
    "Tenant",
    "TenantLimits",
    "TenantSettings",
    "TenantStore",
    "TenantScopedStore",
    "TenantAuditNamespace",
    "TenantContext",
    "current_tenant",
    "require_tenant",
    "tenant_middleware",
    "tenant_admin_router",
]

from orchestra.miles.enterprise.sso import (
    IdPProvider,
    OIDCConfig,
    OIDCIdentity,
    OIDCValidator,
    SAMLConfig,
    SAMLIdentity,
    SAMLValidator,
    SCIMConfig,
    SCIMStore,
    SCIMUser,
    SSOConfig,
    SSOEngine,
    scim_router,
    sso_middleware,
)
from orchestra.miles.enterprise.rbac import (
    BUILTIN_ROLES,
    AccessEvent,
    Action,
    Permission,
    RBACAccessLog,
    RBACEngine,
    Resource,
    Role,
    rbac_dependency,
    rbac_middleware,
)
from orchestra.miles.enterprise.tenancy import (
    Tenant,
    TenantAuditNamespace,
    TenantContext,
    TenantLimits,
    TenantScopedStore,
    TenantSettings,
    TenantStore,
    current_tenant,
    require_tenant,
    tenant_admin_router,
    tenant_middleware,
)
