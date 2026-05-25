"""RBAC management API — assign professional roles, view permissions."""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request

from orchestra.code_agent.rbac.roles import Role, Perm, permissions_for, role_domain, HEALTHCARE_ROLES, LEGAL_ROLES, FINANCE_ROLES
from orchestra.code_agent.rbac.deps import require_perm


def register_rbac_routes(app: FastAPI) -> None:

    @app.get("/api/rbac/roles")
    async def list_roles():
        """All available roles with their domain and permissions."""
        return [
            {
                "role": r.value,
                "domain": role_domain(r.value),
                "permissions": permissions_for(r.value),
            }
            for r in Role
        ]

    @app.get("/api/rbac/roles/{role}/permissions")
    async def role_permissions(role: str):
        try:
            Role(role)
        except ValueError:
            raise HTTPException(404, f"Unknown role: {role}")
        return {
            "role": role,
            "domain": role_domain(role),
            "permissions": permissions_for(role),
        }

    @app.patch("/api/rbac/users/{user_id}/role")
    async def set_user_role(
        user_id: str,
        body: dict,
        _uid=Depends(require_perm(Perm.USER_MANAGE)),
    ):
        """Assign a professional role to a user (admin only)."""
        new_role = body.get("role", "")
        try:
            Role(new_role)
        except ValueError:
            raise HTTPException(400, f"Invalid role: {new_role}. Valid: {[r.value for r in Role]}")

        from orchestra.code_agent.auth.user_store import UserStore
        store = UserStore.get()
        user = store.get_user_by_id(user_id)
        if not user:
            raise HTTPException(404, "User not found")

        updated = store.update_user(user_id, role=new_role)
        return {
            "user_id": user_id,
            "role": new_role,
            "domain": role_domain(new_role),
            "permissions": permissions_for(new_role),
        }

    @app.get("/api/rbac/me")
    async def my_role(request: Request):
        """Return the caller's current role and permissions."""
        from orchestra.code_agent.rbac.deps import _resolve_role, _resolve_user_id
        role = _resolve_role(request)
        return {
            "user_id": _resolve_user_id(request),
            "role": role,
            "domain": role_domain(role),
            "permissions": permissions_for(role),
        }
