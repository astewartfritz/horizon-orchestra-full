"""
REST API for Org / Team management.

Auth: Bearer JWT — user_id extracted from the `sub` claim.
All mutating endpoints enforce minimum role requirements.

Org endpoints:
  POST   /api/orgs                                   create org
  GET    /api/orgs                                   list caller's orgs
  GET    /api/orgs/{org_id}                          get org (member only)
  PATCH  /api/orgs/{org_id}                          update org (admin+)
  DELETE /api/orgs/{org_id}                          delete org (owner only)

Member endpoints:
  GET    /api/orgs/{org_id}/members                  list members
  PATCH  /api/orgs/{org_id}/members/{user_id}        update role (admin+)
  DELETE /api/orgs/{org_id}/members/{user_id}        remove member (admin+)

Invite endpoints:
  POST   /api/orgs/{org_id}/invites                  create invite (admin+)
  GET    /api/orgs/{org_id}/invites                  list pending invites (admin+)
  DELETE /api/orgs/{org_id}/invites/{invite_id}      cancel invite (admin+)
  POST   /api/orgs/invites/{token}/accept            accept invite (any authed user)

Team endpoints:
  GET    /api/orgs/{org_id}/teams                    list teams (member+)
  POST   /api/orgs/{org_id}/teams                    create team (admin+)
  DELETE /api/orgs/{org_id}/teams/{team_id}          delete team (admin+)
  GET    /api/orgs/{org_id}/teams/{team_id}/members  list team members (member+)
  POST   /api/orgs/{org_id}/teams/{team_id}/members  add to team (admin+)
  DELETE /api/orgs/{org_id}/teams/{team_id}/members/{user_id}  remove from team (admin+)
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from orchestra.code_agent.orgs import store as _s

_log = logging.getLogger("orchestra.orgs")

_VALID_ORG_ROLES = {"owner", "admin", "member", "viewer"}
_VALID_TEAM_ROLES = {"lead", "member"}


# ── Auth helper ───────────────────────────────────────────────────────────────

def _get_user_id(authorization: str | None) -> str:
    """Extract user_id from Bearer JWT. Raises 401 on failure."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization[7:]
    from orchestra.code_agent.auth.jwt import JWTManager
    from orchestra.code_agent.settings import settings
    mgr = JWTManager(secret=settings.jwt_secret)
    payload = mgr.verify(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    uid = payload.get("sub")
    if not uid:
        raise HTTPException(401, "Token missing sub claim")
    return uid


def _require_org_role(org_id: str, user_id: str, min_role: str) -> None:
    if not _s.is_member(org_id, user_id, min_role):
        raise HTTPException(403, f"Requires org role: {min_role}")


def _org_dict(org) -> dict[str, Any]:
    return asdict(org)


def _member_dict(m) -> dict[str, Any]:
    return asdict(m)


def _invite_dict(inv) -> dict[str, Any]:
    return asdict(inv)


def _team_dict(t) -> dict[str, Any]:
    return asdict(t)


def _tm_dict(tm) -> dict[str, Any]:
    return asdict(tm)


# ── Route registration ────────────────────────────────────────────────────────

def register_org_routes(app: FastAPI) -> None:
    _s.init_db()

    # ── Org CRUD ──────────────────────────────────────────────────────────

    @app.post("/api/orgs", status_code=201)
    async def create_org(
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "name is required")
        plan = body.get("plan", "free")
        if plan not in ("free", "pro", "enterprise"):
            raise HTTPException(400, "plan must be free | pro | enterprise")
        org = _s.create_org(name=name, owner_user_id=user_id, plan=plan)
        return _org_dict(org)

    @app.get("/api/orgs")
    async def list_orgs(
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        orgs = _s.list_orgs_for_user(user_id)
        return [_org_dict(o) for o in orgs]

    @app.get("/api/orgs/{org_id}")
    async def get_org(
        org_id: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "viewer")
        org = _s.get_org(org_id)
        if not org:
            raise HTTPException(404, "Org not found")
        return _org_dict(org)

    @app.patch("/api/orgs/{org_id}")
    async def update_org(
        org_id: str,
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "admin")
        allowed = {"name", "plan", "stripe_customer_id", "stripe_subscription_id", "metadata"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            raise HTTPException(400, f"No valid update fields. Allowed: {sorted(allowed)}")
        if "plan" in updates and updates["plan"] not in ("free", "pro", "enterprise"):
            raise HTTPException(400, "plan must be free | pro | enterprise")
        org = _s.update_org(org_id, **updates)
        if not org:
            raise HTTPException(404, "Org not found")
        return _org_dict(org)

    @app.delete("/api/orgs/{org_id}", status_code=204)
    async def delete_org(
        org_id: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "owner")
        if not _s.delete_org(org_id):
            raise HTTPException(404, "Org not found")

    # ── Members ───────────────────────────────────────────────────────────

    @app.get("/api/orgs/{org_id}/members")
    async def list_members(
        org_id: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "viewer")
        return [_member_dict(m) for m in _s.list_members(org_id)]

    @app.patch("/api/orgs/{org_id}/members/{target_user_id}")
    async def update_member_role(
        org_id: str,
        target_user_id: str,
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "admin")
        new_role = body.get("role", "")
        if new_role not in _VALID_ORG_ROLES:
            raise HTTPException(400, f"role must be one of {sorted(_VALID_ORG_ROLES)}")
        # Prevent demoting owner unless caller is owner
        target = _s.get_member(org_id, target_user_id)
        if not target:
            raise HTTPException(404, "Member not found")
        if target.role == "owner" and not _s.is_member(org_id, user_id, "owner"):
            raise HTTPException(403, "Only owner can change another owner's role")
        m = _s.update_member_role(org_id, target_user_id, new_role)
        return _member_dict(m)

    @app.delete("/api/orgs/{org_id}/members/{target_user_id}", status_code=204)
    async def remove_member(
        org_id: str,
        target_user_id: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        # Members can remove themselves; admins can remove anyone below them
        is_self = user_id == target_user_id
        if not is_self:
            _require_org_role(org_id, user_id, "admin")
        target = _s.get_member(org_id, target_user_id)
        if not target:
            raise HTTPException(404, "Member not found")
        if target.role == "owner" and not is_self:
            raise HTTPException(403, "Cannot remove the org owner")
        if not _s.remove_member(org_id, target_user_id):
            raise HTTPException(404, "Member not found")

    # ── Invites ───────────────────────────────────────────────────────────

    @app.post("/api/orgs/{org_id}/invites", status_code=201)
    async def create_invite(
        org_id: str,
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "admin")
        email = (body.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(400, "email is required")
        role = body.get("role", "member")
        if role not in _VALID_ORG_ROLES - {"owner"}:
            raise HTTPException(400, "role must be admin | member | viewer")
        inv = _s.create_invite(org_id=org_id, email=email, role=role, invited_by=user_id)
        return _invite_dict(inv)

    @app.get("/api/orgs/{org_id}/invites")
    async def list_invites(
        org_id: str,
        status: str = "pending",
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "admin")
        return [_invite_dict(i) for i in _s.list_invites(org_id, status=status)]

    @app.delete("/api/orgs/{org_id}/invites/{invite_id}", status_code=204)
    async def cancel_invite(
        org_id: str,
        invite_id: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "admin")
        if not _s.cancel_invite(invite_id, org_id):
            raise HTTPException(404, "Pending invite not found")

    @app.post("/api/orgs/invites/{token}/accept")
    async def accept_invite(
        token: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        inv = _s.accept_invite(token=token, user_id=user_id)
        if not inv:
            raise HTTPException(400, "Invite not found, already used, or expired")
        return _invite_dict(inv)

    # ── Teams ─────────────────────────────────────────────────────────────

    @app.get("/api/orgs/{org_id}/teams")
    async def list_teams(
        org_id: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "viewer")
        return [_team_dict(t) for t in _s.list_teams(org_id)]

    @app.post("/api/orgs/{org_id}/teams", status_code=201)
    async def create_team(
        org_id: str,
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "admin")
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "name is required")
        description = body.get("description", "")
        try:
            team = _s.create_team(org_id=org_id, name=name, description=description, created_by=user_id)
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, f"A team named '{name}' already exists in this org")
            raise
        return _team_dict(team)

    @app.delete("/api/orgs/{org_id}/teams/{team_id}", status_code=204)
    async def delete_team(
        org_id: str,
        team_id: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "admin")
        if not _s.delete_team(team_id, org_id):
            raise HTTPException(404, "Team not found")

    @app.get("/api/orgs/{org_id}/teams/{team_id}/members")
    async def list_team_members(
        org_id: str,
        team_id: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "viewer")
        if not _s.get_team(team_id):
            raise HTTPException(404, "Team not found")
        return [_tm_dict(m) for m in _s.list_team_members(team_id)]

    @app.post("/api/orgs/{org_id}/teams/{team_id}/members", status_code=201)
    async def add_team_member(
        org_id: str,
        team_id: str,
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_org_role(org_id, user_id, "admin")
        target_user_id = (body.get("user_id") or "").strip()
        if not target_user_id:
            raise HTTPException(400, "user_id is required")
        if not _s.is_member(org_id, target_user_id, "viewer"):
            raise HTTPException(400, "user must be an org member before joining a team")
        role = body.get("role", "member")
        if role not in _VALID_TEAM_ROLES:
            raise HTTPException(400, f"role must be one of {sorted(_VALID_TEAM_ROLES)}")
        tm = _s.add_team_member(
            team_id=team_id, org_id=org_id, user_id=target_user_id,
            role=role, added_by=user_id,
        )
        return _tm_dict(tm)

    @app.delete("/api/orgs/{org_id}/teams/{team_id}/members/{target_user_id}", status_code=204)
    async def remove_team_member(
        org_id: str,
        team_id: str,
        target_user_id: str,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        is_self = user_id == target_user_id
        if not is_self:
            _require_org_role(org_id, user_id, "admin")
        if not _s.remove_team_member(team_id, target_user_id):
            raise HTTPException(404, "Team member not found")
