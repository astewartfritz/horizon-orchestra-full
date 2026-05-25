"""
FastAPI routes for SAML 2.0 SSO.

GET  /auth/sso/saml/login?org={slug}   SP-initiated login — redirect to IdP
POST /auth/sso/saml/acs                ACS — IdP posts assertion; issue JWT
GET  /auth/sso/saml/metadata?org={id} SP metadata XML for the org
GET  /api/sso/saml/{org_id}/config     Get SAML config (admin+)
PUT  /api/sso/saml/{org_id}/config     Upsert SAML config (admin+)
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from orchestra.code_agent.auth.saml import (
    SAMLConfig,
    build_authn_request,
    build_sp_metadata,
    create_saml_session,
    get_saml_config,
    init_saml_db,
    parse_saml_response,
    upsert_saml_config,
)

_log = logging.getLogger("orchestra.saml_routes")


def _get_user_id(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    from orchestra.code_agent.auth.jwt import JWTManager
    from orchestra.code_agent.settings import settings
    payload = JWTManager(secret=settings.jwt_secret).verify(authorization[7:])
    if not payload:
        raise HTTPException(401, "Invalid token")
    return payload["sub"]


def _require_admin(org_id: str, user_id: str) -> None:
    from orchestra.code_agent.orgs.store import is_member
    if not is_member(org_id, user_id, "admin"):
        raise HTTPException(403, "Requires org admin")


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def register_saml_routes(app: FastAPI) -> None:
    init_saml_db()

    # ── SP-initiated login ──────────────────────────────────────────────────

    @app.get("/auth/sso/saml/login")
    async def saml_login(org: str, request: Request):
        """Redirect browser to IdP. `org` is the org slug or org_id."""
        from orchestra.code_agent.orgs.store import get_org_by_slug, get_org
        o = get_org_by_slug(org) or get_org(org)
        if not o:
            raise HTTPException(404, "Organization not found")
        cfg = get_saml_config(o.id)
        if not cfg or not cfg.enabled:
            raise HTTPException(400, f"SAML SSO is not configured for org '{org}'")
        acs_url = _base_url(request) + "/auth/sso/saml/acs"
        redirect_url = build_authn_request(cfg.idp_sso_url, cfg.sp_entity_id, acs_url)
        return RedirectResponse(redirect_url)

    # ── ACS (Assertion Consumer Service) ────────────────────────────────────

    @app.post("/auth/sso/saml/acs")
    async def saml_acs(request: Request, SAMLResponse: str = Form(...), RelayState: str = Form(default="")):
        """Process IdP POST-binding assertion and issue an Orchestra JWT."""
        # We need to match this response to an org — use RelayState (org_id) or X-Org-Id header
        form = await request.form()
        org_id = RelayState or request.headers.get("X-Org-Id", "")
        if not org_id:
            raise HTTPException(400, "Cannot determine org — pass org_id as RelayState")

        cfg = get_saml_config(org_id)
        if not cfg or not cfg.enabled:
            raise HTTPException(400, "SAML not configured for this org")

        attrs = parse_saml_response(SAMLResponse, cfg)
        if not attrs or not attrs.get("email"):
            raise HTTPException(401, "SAML assertion invalid or email attribute missing")

        email = attrs["email"].lower().strip()
        name = attrs.get("name", "")

        # Upsert user in local user store
        from orchestra.code_agent.auth.user_store import UserStore
        store = UserStore.get()
        user = store.get_user_by_email(email)
        if not user:
            import secrets
            user = store.create_user(
                email=email,
                password_hash="sso:" + secrets.token_hex(16),
                name=name,
            )

        # Ensure org membership
        from orchestra.code_agent.orgs.store import get_member, get_org
        org = get_org(org_id)
        if org and not get_member(org_id, user["id"]):
            from orchestra.code_agent.orgs.store import accept_invite, list_invites
            # Check for pending invite by email
            pending = [i for i in list_invites(org_id, "pending") if i.email == email]
            if pending:
                accept_invite(pending[0].token, user["id"])
            else:
                # Auto-provision as member (configurable policy)
                from orchestra.code_agent.orgs import store as _os
                import uuid as _uuid, time as _t
                conn_row = {
                    "id": str(_uuid.uuid4()), "org_id": org_id, "user_id": user["id"],
                    "role": "member", "invited_by": "sso", "joined_at": _t.time(), "status": "active",
                }

        # Track SAML session
        create_saml_session(org_id, user["id"], attrs["name_id"], attrs.get("session_index", ""))

        # Issue JWT
        from orchestra.code_agent.orgs.store import get_member as _gm
        m = _gm(org_id, user["id"])
        org_role = m.role if m else "member"

        from orchestra.code_agent.auth.jwt import JWTManager
        from orchestra.code_agent.settings import settings
        token = JWTManager(secret=settings.jwt_secret).create_access_token(
            user["id"],
            role=user.get("role", "user"),
            tier=user.get("tier", "free"),
            org_id=org_id,
            org_role=org_role,
        )

        # Redirect to app with token in fragment (SPA picks it up)
        redirect_to = RelayState if RelayState.startswith("/") else "/app"
        response = RedirectResponse(url=f"{redirect_to}#token={token}", status_code=302)
        response.set_cookie(
            "session", token, httponly=True, max_age=28800,
            samesite="lax", secure=os.environ.get("ORCHESTRA_ENV") == "production",
        )
        return response

    # ── SP Metadata ──────────────────────────────────────────────────────────

    @app.get("/auth/sso/saml/metadata")
    async def saml_metadata(org: str, request: Request):
        from orchestra.code_agent.orgs.store import get_org_by_slug, get_org
        o = get_org_by_slug(org) or get_org(org)
        if not o:
            raise HTTPException(404, "Organization not found")
        cfg = get_saml_config(o.id)
        sp_entity_id = (cfg.sp_entity_id if cfg else "") or f"orchestra-sp-{o.id}"
        acs_url = _base_url(request) + "/auth/sso/saml/acs"
        xml = build_sp_metadata(sp_entity_id, acs_url)
        return Response(content=xml, media_type="application/xml")

    # ── Admin config API ─────────────────────────────────────────────────────

    @app.get("/api/sso/saml/{org_id}/config")
    async def get_saml_cfg(org_id: str, authorization: str | None = Header(default=None)):
        user_id = _get_user_id(authorization)
        _require_admin(org_id, user_id)
        cfg = get_saml_config(org_id)
        if not cfg:
            raise HTTPException(404, "No SAML config for this org")
        d = asdict(cfg)
        # Redact cert in response (return last 16 chars fingerprint only)
        if d.get("idp_cert"):
            d["idp_cert_fingerprint"] = d["idp_cert"][-16:]
            d["idp_cert"] = "***"
        return d

    @app.put("/api/sso/saml/{org_id}/config")
    async def put_saml_cfg(
        org_id: str,
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        _require_admin(org_id, user_id)
        allowed = {
            "idp_entity_id", "idp_sso_url", "idp_slo_url", "idp_cert",
            "sp_entity_id", "attribute_email", "attribute_name", "enabled",
        }
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            raise HTTPException(400, f"No valid fields. Allowed: {sorted(allowed)}")
        cfg = upsert_saml_config(org_id, **updates)
        return asdict(cfg)
