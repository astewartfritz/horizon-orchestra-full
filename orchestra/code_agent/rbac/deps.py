"""
FastAPI dependency factories for role-based access control.

Usage::

    from orchestra.code_agent.rbac.deps import require_perm, require_role
    from orchestra.code_agent.rbac.roles import Perm, Role

    @app.get("/api/healthcare/patients")
    async def list_patients(uid=Depends(require_perm(Perm.PHI_READ))):
        ...

    @app.delete("/api/admin/users/{uid}")
    async def delete_user(uid=Depends(require_role(Role.SUPER_ADMIN))):
        ...
"""
from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request

from orchestra.code_agent.rbac.roles import Perm, Role, has_permission


def _resolve_role(request: Request) -> str:
    """Extract role from JWT session cookie or Authorization header."""
    from orchestra.code_agent.ui.handlers.v1_compat import _decode_local_token, _jwt

    token = (
        request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.cookies.get("session", "")
    )
    if not token:
        return Role.USER.value

    payload = _jwt().verify(token)
    if not payload or payload.get("type") != "access":
        return Role.USER.value

    # JWT carries both the platform role (admin/user) and professional role
    # Professional role takes precedence for domain checks
    return payload.get("prof_role") or payload.get("role") or Role.USER.value


def _resolve_user_id(request: Request) -> str | None:
    from orchestra.code_agent.ui.handlers.v1_compat import _decode_local_token
    token = (
        request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.cookies.get("session", "")
    )
    return _decode_local_token(token) if token else None


def require_perm(perm: Perm) -> Callable:
    """Return a FastAPI dependency that enforces a permission, raising 403 if denied."""
    async def _check(request: Request):
        role = _resolve_role(request)
        if not has_permission(role, perm):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: '{perm.value}' required. Your role: '{role}'.",
            )
        return _resolve_user_id(request)
    return _check


def require_role(*roles: Role) -> Callable:
    """Return a dependency that requires any one of the specified roles."""
    role_values = {r.value for r in roles}

    async def _check(request: Request):
        role = _resolve_role(request)
        if role not in role_values and role != Role.SUPER_ADMIN.value:
            raise HTTPException(
                status_code=403,
                detail=f"Role required: one of {sorted(role_values)}. Your role: '{role}'.",
            )
        return _resolve_user_id(request)
    return _check


def current_role(request: Request) -> str:
    """Non-raising dependency — returns the role string (defaults to 'user')."""
    return _resolve_role(request)


def optional_user_with_role(request: Request) -> tuple[str | None, str]:
    """Return (user_id | None, role_string) — never raises."""
    return _resolve_user_id(request), _resolve_role(request)
