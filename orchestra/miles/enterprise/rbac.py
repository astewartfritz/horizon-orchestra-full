"""MILES Enterprise — Role-Based Access Control (RBAC).

Fine-grained permission system for enterprise MILES deployments.
Goes beyond the basic user/admin/org_admin model in orchestra/auth.py.

Built-in roles (can be extended or overridden per org):
  viewer          — read-only across all MILES features
  analyst         — read + run queries + view dashboards
  builder         — analyst + create workflows + manage integrations
  admin           — builder + user management + org settings
  org_admin       — admin + billing + SSO config + audit export
  security_auditor — read audit logs + run red-team + no data modification
  integration_mgr  — manage connectors + webhooks, no user/org changes

Usage::

    from orchestra.miles.enterprise.rbac import RBACEngine, rbac_dependency
    engine = RBACEngine()
    engine.check(user_role="analyst", resource="workflow", action="create")
    # → raises PermissionError
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger("orchestra.miles.enterprise.rbac")


# ── Permission model ──────────────────────────────────────────────────────────

class Action(str, Enum):
    READ    = "read"
    CREATE  = "create"
    UPDATE  = "update"
    DELETE  = "delete"
    EXECUTE = "execute"
    EXPORT  = "export"
    MANAGE  = "manage"    # super-action: implies all others on that resource
    ANY     = "*"


class Resource(str, Enum):
    # Data / content
    CONVERSATION   = "conversation"
    MEMORY         = "memory"
    DOCUMENT       = "document"
    FILE           = "file"
    ARTIFACT       = "artifact"
    # Agentic
    TASK           = "task"
    WORKFLOW       = "workflow"
    AGENT          = "agent"
    TOOL           = "tool"
    # Integrations
    CONNECTOR      = "connector"
    WEBHOOK        = "webhook"
    CHANNEL        = "channel"
    # Identity
    USER           = "user"
    ROLE           = "role"
    ORG            = "org"
    # Security / compliance
    AUDIT_LOG      = "audit_log"
    SECURITY_SCAN  = "security_scan"
    RED_TEAM       = "red_team"
    # Billing / config
    BILLING        = "billing"
    SSO_CONFIG     = "sso_config"
    ORG_SETTINGS   = "org_settings"
    ANY            = "*"


@dataclass(frozen=True)
class Permission:
    resource: str    # Resource enum value or "*"
    action: str      # Action enum value or "*"

    def matches(self, resource: str, action: str) -> bool:
        res_ok  = self.resource == Resource.ANY or self.resource == resource
        act_ok  = (self.action  == Action.ANY
                   or self.action == action
                   or self.action == Action.MANAGE)
        return res_ok and act_ok

    def __str__(self) -> str:
        return f"{self.resource}:{self.action}"


# ── Role definitions ──────────────────────────────────────────────────────────

@dataclass
class Role:
    slug: str
    display_name: str
    description: str
    permissions: list[Permission]
    inherits: list[str] = field(default_factory=list)   # slugs of parent roles
    is_custom: bool = False

    def __hash__(self) -> int:
        return hash(self.slug)


def _p(resource: str, *actions: str) -> list[Permission]:
    return [Permission(resource, a) for a in actions]


def _all(resource: str) -> list[Permission]:
    return [Permission(resource, Action.MANAGE)]


# ── Built-in role library ─────────────────────────────────────────────────────

BUILTIN_ROLES: dict[str, Role] = {

    "viewer": Role(
        slug="viewer",
        display_name="Viewer",
        description="Read-only access across all MILES features.",
        permissions=(
            _p(Resource.CONVERSATION,  Action.READ) +
            _p(Resource.MEMORY,        Action.READ) +
            _p(Resource.DOCUMENT,      Action.READ) +
            _p(Resource.FILE,          Action.READ) +
            _p(Resource.ARTIFACT,      Action.READ) +
            _p(Resource.TASK,          Action.READ) +
            _p(Resource.WORKFLOW,      Action.READ) +
            _p(Resource.AGENT,         Action.READ) +
            _p(Resource.TOOL,          Action.READ) +
            _p(Resource.CONNECTOR,     Action.READ) +
            _p(Resource.CHANNEL,       Action.READ)
        ),
    ),

    "analyst": Role(
        slug="analyst",
        display_name="Analyst",
        description="Read everything + execute tasks and queries.",
        inherits=["viewer"],
        permissions=(
            _p(Resource.TASK,          Action.CREATE, Action.EXECUTE) +
            _p(Resource.MEMORY,        Action.CREATE) +
            _p(Resource.DOCUMENT,      Action.CREATE) +
            _p(Resource.ARTIFACT,      Action.CREATE) +
            _p(Resource.FILE,          Action.CREATE)
        ),
    ),

    "builder": Role(
        slug="builder",
        display_name="Builder",
        description="Analyst + create and manage workflows, agents, and integrations.",
        inherits=["analyst"],
        permissions=(
            _p(Resource.WORKFLOW,  Action.CREATE, Action.UPDATE, Action.DELETE, Action.EXECUTE) +
            _p(Resource.AGENT,     Action.CREATE, Action.UPDATE, Action.DELETE) +
            _p(Resource.CONNECTOR, Action.CREATE, Action.UPDATE) +
            _p(Resource.WEBHOOK,   Action.CREATE, Action.UPDATE, Action.DELETE) +
            _p(Resource.CHANNEL,   Action.CREATE, Action.UPDATE)
        ),
    ),

    "integration_manager": Role(
        slug="integration_manager",
        display_name="Integration Manager",
        description="Full control over connectors, webhooks, and channels. No user/org changes.",
        inherits=["viewer"],
        permissions=(
            _all(Resource.CONNECTOR) +
            _all(Resource.WEBHOOK)   +
            _all(Resource.CHANNEL)
        ),
    ),

    "security_auditor": Role(
        slug="security_auditor",
        display_name="Security Auditor",
        description="Read audit logs, run security scans and red-team. No data modification.",
        inherits=["viewer"],
        permissions=(
            _p(Resource.AUDIT_LOG,    Action.READ, Action.EXPORT) +
            _p(Resource.SECURITY_SCAN,Action.READ, Action.EXECUTE) +
            _p(Resource.RED_TEAM,     Action.READ, Action.EXECUTE)
        ),
    ),

    "admin": Role(
        slug="admin",
        display_name="Admin",
        description="Builder + user management and org settings. No billing or SSO.",
        inherits=["builder"],
        permissions=(
            _all(Resource.USER)         +
            _all(Resource.ROLE)         +
            _p(Resource.ORG_SETTINGS, Action.READ, Action.UPDATE) +
            _p(Resource.AUDIT_LOG,    Action.READ, Action.EXPORT)
        ),
    ),

    "org_admin": Role(
        slug="org_admin",
        display_name="Org Admin",
        description="Full control including billing, SSO configuration, and audit export.",
        inherits=["admin"],
        permissions=(
            _all(Resource.BILLING)      +
            _all(Resource.SSO_CONFIG)   +
            _all(Resource.ORG)          +
            _all(Resource.ORG_SETTINGS) +
            _all(Resource.AUDIT_LOG)    +
            _all(Resource.RED_TEAM)
        ),
    ),
}


# ── RBAC Engine ───────────────────────────────────────────────────────────────

class RBACEngine:
    """Evaluates permissions for a user given their role."""

    def __init__(self, custom_roles: list[Role] | None = None) -> None:
        self._roles: dict[str, Role] = {**BUILTIN_ROLES}
        for role in (custom_roles or []):
            self._roles[role.slug] = role
        # Flatten inheritance chains once
        self._flat_perms: dict[str, list[Permission]] = {}
        for slug in self._roles:
            self._flat_perms[slug] = list(self._resolve_permissions(slug, set()))

    def check(self, user_role: str, resource: str, action: str) -> bool:
        """Return True if the role grants resource:action."""
        for perm in self._flat_perms.get(user_role, []):
            if perm.matches(resource, action):
                return True
        return False

    def require(self, user_role: str, resource: str, action: str) -> None:
        """Raise PermissionError if the role lacks the permission."""
        if not self.check(user_role, resource, action):
            raise PermissionError(
                f"Role '{user_role}' lacks permission '{resource}:{action}'"
            )

    def all_permissions(self, user_role: str) -> list[str]:
        """Return all permission strings for a role (for display/audit)."""
        return [str(p) for p in self._flat_perms.get(user_role, [])]

    def role_info(self, slug: str) -> Role | None:
        return self._roles.get(slug)

    def list_roles(self) -> list[Role]:
        return list(self._roles.values())

    def add_custom_role(self, role: Role) -> None:
        """Dynamically add or replace a role (custom org role)."""
        self._roles[role.slug] = role
        self._flat_perms[role.slug] = list(self._resolve_permissions(role.slug, set()))
        log.info("RBAC: registered custom role '%s'", role.slug)

    def _resolve_permissions(self, slug: str, seen: set[str]) -> list[Permission]:
        if slug in seen:
            return []
        seen.add(slug)
        role = self._roles.get(slug)
        if not role:
            return []
        perms = list(role.permissions)
        for parent_slug in role.inherits:
            perms.extend(self._resolve_permissions(parent_slug, seen))
        return perms


# ── FastAPI dependency helpers ────────────────────────────────────────────────

def rbac_dependency(engine: RBACEngine, resource: str, action: str):
    """
    FastAPI dependency factory.

    Usage::

        @router.post("/workflow")
        async def create_wf(user=Depends(rbac_dependency(rbac, "workflow", "create"))):
            ...
    """
    try:
        from fastapi import Depends, HTTPException, Request
    except ImportError:
        raise ImportError("FastAPI required: pip install fastapi")

    async def _check(request: Request):
        role = getattr(request.state, "sso_role", None) or getattr(request.state, "user_role", "viewer")
        if not engine.check(role, resource, action):
            raise HTTPException(
                403,
                detail=f"Role '{role}' does not have permission to {action} {resource}",
            )
        return role

    return Depends(_check)


def rbac_middleware(engine: RBACEngine, route_permissions: dict[str, tuple[str, str]]):
    """
    Starlette middleware that checks permissions on route patterns.

    ``route_permissions``: mapping of path prefix → (resource, action).

    Example::

        rbac_middleware(engine, {
            "/miles/api/workflow": ("workflow", "read"),
            "/miles/api/users":    ("user", "manage"),
        })
    """
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse
    except ImportError:
        raise ImportError("starlette required: pip install starlette")

    class _RBACMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            method = request.method

            for prefix, (resource, action) in route_permissions.items():
                if path.startswith(prefix):
                    role = (
                        getattr(request.state, "sso_role", None)
                        or getattr(request.state, "user_role", "viewer")
                    )
                    if not engine.check(role, resource, action):
                        return JSONResponse(
                            {"error": f"Forbidden — '{role}' cannot {action} {resource}"},
                            status_code=403,
                        )
                    break

            return await call_next(request)

    return _RBACMiddleware


# ── Audit helpers ─────────────────────────────────────────────────────────────

@dataclass
class AccessEvent:
    user_id: str
    role: str
    resource: str
    action: str
    allowed: bool
    path: str = ""
    reason: str = ""


class RBACAccessLog:
    """In-memory access event log (wire to AuditLedger in production)."""

    def __init__(self, max_events: int = 10_000) -> None:
        self._events: list[AccessEvent] = []
        self._max = max_events

    def record(self, event: AccessEvent) -> None:
        if len(self._events) >= self._max:
            self._events.pop(0)
        self._events.append(event)
        if not event.allowed:
            log.warning(
                "RBAC denied: user=%s role=%s resource=%s action=%s path=%s",
                event.user_id, event.role, event.resource, event.action, event.path,
            )

    def denied_events(self) -> list[AccessEvent]:
        return [e for e in self._events if not e.allowed]

    def events_for_user(self, user_id: str) -> list[AccessEvent]:
        return [e for e in self._events if e.user_id == user_id]

    def to_dict_list(self) -> list[dict]:
        return [vars(e) for e in self._events]
