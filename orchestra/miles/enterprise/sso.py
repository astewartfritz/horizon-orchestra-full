"""MILES Enterprise — SSO / OIDC / SAML / SCIM 2.0.

Adds enterprise identity to MILES:
  - OIDC token validation (Okta, Azure AD, Auth0, Google Workspace, Ping)
  - SAML 2.0 assertion parsing
  - SCIM 2.0 provisioning endpoints (Users + Groups)
  - FastAPI router that mounts at /miles/scim/v2/

Usage::

    from orchestra.miles.enterprise.sso import SSOConfig, SSOEngine, scim_router
    cfg = SSOConfig.from_env()
    engine = SSOEngine(cfg)
    app.include_router(scim_router(engine), prefix="/miles")
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger("orchestra.miles.enterprise.sso")

# ── Optional deps — degrade gracefully ───────────────────────────────────────
try:
    import httpx as _httpx
    _HTTPX = True
except ImportError:
    _HTTPX = False

try:
    from cryptography.hazmat.backends import default_backend as _backend
    from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15 as _PKCS1v15
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers as _RSAPublicNumbers
    from cryptography.hazmat.primitives.asymmetric.ec import (
        EllipticCurvePublicNumbers as _ECPublicNumbers,
        SECP256R1 as _SECP256R1,
        ECDSA as _ECDSA,
    )
    from cryptography.hazmat.primitives.hashes import SHA256 as _SHA256
    _CRYPTO = True
except ImportError:
    _CRYPTO = False

try:
    import xml.etree.ElementTree as ET
    _XML = True
except ImportError:
    _XML = False


# ── Configuration ─────────────────────────────────────────────────────────────

class IdPProvider(str, Enum):
    OKTA       = "okta"
    AZURE_AD   = "azure_ad"
    AUTH0      = "auth0"
    GOOGLE     = "google"
    PING       = "ping"
    GENERIC    = "generic"
    SAML       = "saml"


@dataclass
class OIDCConfig:
    """Configuration for one OIDC identity provider."""
    provider: IdPProvider
    client_id: str
    issuer_url: str
    audience: str | None = None        # defaults to client_id
    jwks_uri: str | None = None        # auto-discovered if None
    # claim name → Orchestra internal field
    claim_map: dict[str, str] = field(default_factory=lambda: {
        "email": "email",
        "name":  "name",
        "groups": "groups",
    })
    enabled: bool = True


@dataclass
class SAMLConfig:
    """Configuration for one SAML 2.0 identity provider."""
    idp_entity_id: str
    idp_sso_url: str
    idp_cert_pem: str          # X.509 cert from IdP metadata
    sp_entity_id: str          # Our entity ID
    acs_url: str               # Assertion Consumer Service URL
    attribute_map: dict[str, str] = field(default_factory=lambda: {
        "email":    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
        "name":     "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
        "groups":   "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups",
    })
    enabled: bool = True


@dataclass
class SCIMConfig:
    """SCIM 2.0 provisioning configuration."""
    enabled: bool = True
    bearer_token: str = ""     # Token IdP uses to call our SCIM endpoints
    base_path: str = "/scim/v2"
    max_results: int = 200
    # Optional: restrict which IdP IPs may call SCIM (empty = any)
    allowed_ips: list[str] = field(default_factory=list)


@dataclass
class SSOConfig:
    """Top-level SSO configuration for MILES enterprise."""
    oidc: list[OIDCConfig] = field(default_factory=list)
    saml: list[SAMLConfig] = field(default_factory=list)
    scim: SCIMConfig = field(default_factory=SCIMConfig)
    # If True, every MILES API request requires a valid SSO token.
    # If False, SSO is optional — fall back to local auth.
    enforce: bool = False
    default_role: str = "analyst"
    default_tier: str = "pro"
    # External group name → Orchestra RBAC role slug
    group_role_map: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> SSOConfig:
        cfg = cls()

        # ── Okta ──────────────────────────────────────────────────────────
        if os.environ.get("OKTA_ISSUER"):
            cfg.oidc.append(OIDCConfig(
                provider=IdPProvider.OKTA,
                client_id=os.environ.get("OKTA_CLIENT_ID", ""),
                issuer_url=os.environ["OKTA_ISSUER"].rstrip("/"),
                audience=os.environ.get("OKTA_AUDIENCE"),
                claim_map={"email": "email", "name": "name",
                           "groups": "groups", "orchestra_roles": "orchestra_roles"},
            ))

        # ── Azure AD ──────────────────────────────────────────────────────
        if os.environ.get("AZURE_AD_TENANT_ID"):
            tenant = os.environ["AZURE_AD_TENANT_ID"]
            cfg.oidc.append(OIDCConfig(
                provider=IdPProvider.AZURE_AD,
                client_id=os.environ.get("AZURE_AD_CLIENT_ID", ""),
                issuer_url=f"https://login.microsoftonline.com/{tenant}/v2.0",
                audience=os.environ.get("AZURE_AD_CLIENT_ID"),
                claim_map={"email": "preferred_username", "name": "name",
                           "groups": "groups", "roles": "roles"},
            ))

        # ── Auth0 ─────────────────────────────────────────────────────────
        if os.environ.get("AUTH0_DOMAIN"):
            domain = os.environ["AUTH0_DOMAIN"]
            cfg.oidc.append(OIDCConfig(
                provider=IdPProvider.AUTH0,
                client_id=os.environ.get("AUTH0_CLIENT_ID", ""),
                issuer_url=f"https://{domain}",
                audience=os.environ.get("AUTH0_AUDIENCE"),
                claim_map={"email": "email", "name": "name",
                           "https://orchestra/roles": "orchestra_roles"},
            ))

        # ── Google Workspace ──────────────────────────────────────────────
        if os.environ.get("GOOGLE_WORKSPACE_DOMAIN"):
            cfg.oidc.append(OIDCConfig(
                provider=IdPProvider.GOOGLE,
                client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
                issuer_url="https://accounts.google.com",
                audience=os.environ.get("GOOGLE_CLIENT_ID"),
                claim_map={"email": "email", "name": "name",
                           "hd": "hd"},  # hosted domain claim
            ))

        # ── SAML (generic — reads cert from env or file) ──────────────────
        if os.environ.get("SAML_IDP_SSO_URL"):
            cert = os.environ.get("SAML_IDP_CERT_PEM", "")
            cert_path = os.environ.get("SAML_IDP_CERT_FILE", "")
            if not cert and cert_path and os.path.isfile(cert_path):
                with open(cert_path) as fh:
                    cert = fh.read()
            cfg.saml.append(SAMLConfig(
                idp_entity_id=os.environ.get("SAML_IDP_ENTITY_ID", ""),
                idp_sso_url=os.environ["SAML_IDP_SSO_URL"],
                idp_cert_pem=cert,
                sp_entity_id=os.environ.get("SAML_SP_ENTITY_ID", "https://orchestra.ai/miles"),
                acs_url=os.environ.get("SAML_ACS_URL", "https://orchestra.ai/miles/saml/acs"),
            ))

        # ── SCIM ──────────────────────────────────────────────────────────
        cfg.scim.bearer_token = os.environ.get("SCIM_BEARER_TOKEN", "")
        cfg.scim.enabled = bool(cfg.scim.bearer_token)

        # ── Group → Role map (comma-separated "group:role" pairs) ─────────
        raw = os.environ.get("ORCHESTRA_GROUP_ROLE_MAP", "")
        for pair in raw.split(","):
            if ":" in pair:
                g, r = pair.split(":", 1)
                cfg.group_role_map[g.strip()] = r.strip()

        cfg.enforce = os.environ.get("MILES_SSO_ENFORCE", "false").lower() == "true"
        return cfg


# ── OIDC Validator ────────────────────────────────────────────────────────────

@dataclass
class OIDCIdentity:
    """Verified identity extracted from an OIDC JWT."""
    sub: str
    email: str
    name: str
    issuer: str
    groups: list[str]
    raw_claims: dict[str, Any]
    provider: IdPProvider
    expires_at: float


class _JWKSCache:
    """In-memory JWKS key cache with TTL."""
    _TTL = 3600.0

    def __init__(self) -> None:
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0

    def stale(self) -> bool:
        return time.time() - self._fetched_at > self._TTL

    def update(self, jwks: dict) -> None:
        self._keys = {k["kid"]: k for k in jwks.get("keys", []) if "kid" in k}
        self._fetched_at = time.time()

    def get(self, kid: str) -> dict | None:
        return self._keys.get(kid) or (next(iter(self._keys.values()), None) if not kid else None)


class OIDCValidator:
    """Validates OIDC JWTs against any configured provider."""

    def __init__(self, configs: list[OIDCConfig]) -> None:
        self._configs = {cfg.issuer_url.rstrip("/"): cfg for cfg in configs if cfg.enabled}
        self._jwks_cache: dict[str, _JWKSCache] = {}
        self._openid_config: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def validate(self, token: str) -> OIDCIdentity:
        """Validate token against all configured providers. Returns first match."""
        header = _jwt_part(token, 0)
        payload = _jwt_part(token, 1)
        iss = payload.get("iss", "").rstrip("/")

        cfg = self._configs.get(iss)
        if cfg is None:
            raise ValueError(f"Unknown OIDC issuer: {iss!r}")

        # Expiry check before hitting JWKS
        if payload.get("exp", 0) < time.time():
            raise ValueError("Token has expired")

        # Audience check
        aud = payload.get("aud", "")
        expected_aud = cfg.audience or cfg.client_id
        if expected_aud and not _aud_matches(aud, expected_aud):
            raise ValueError(f"Audience mismatch — got {aud!r}, expected {expected_aud!r}")

        # Signature
        jwks_uri = cfg.jwks_uri or await self._discovery_jwks_uri(iss, cfg.issuer_url)
        kid = header.get("kid", "")
        alg = header.get("alg", "RS256")
        jwk = await self._fetch_key(iss, jwks_uri, kid)
        if not _verify_signature(token, jwk, alg):
            raise ValueError("JWT signature invalid")

        # Extract identity
        email = self._claim(payload, cfg, "email") or ""
        name  = self._claim(payload, cfg, "name")  or email
        raw_groups = self._claim(payload, cfg, "groups") or []
        if isinstance(raw_groups, str):
            raw_groups = [raw_groups]

        return OIDCIdentity(
            sub=payload.get("sub", ""),
            email=email,
            name=name,
            issuer=iss,
            groups=list(raw_groups),
            raw_claims=payload,
            provider=cfg.provider,
            expires_at=float(payload.get("exp", 0)),
        )

    def _claim(self, payload: dict, cfg: OIDCConfig, key: str) -> Any:
        """Resolve a claim via the provider's claim_map."""
        source_key = cfg.claim_map.get(key, key)
        return payload.get(source_key) or payload.get(key)

    async def _discovery_jwks_uri(self, iss: str, issuer_url: str) -> str:
        if iss not in self._openid_config:
            well_known = issuer_url.rstrip("/") + "/.well-known/openid-configuration"
            async with _http() as client:
                r = await client.get(well_known)
                r.raise_for_status()
                self._openid_config[iss] = r.json()
        return self._openid_config[iss]["jwks_uri"]

    async def _fetch_key(self, iss: str, jwks_uri: str, kid: str) -> dict:
        async with self._lock:
            cache = self._jwks_cache.setdefault(iss, _JWKSCache())
            if cache.stale() or (kid and not cache.get(kid)):
                async with _http() as client:
                    r = await client.get(jwks_uri)
                    r.raise_for_status()
                    cache.update(r.json())
            key = cache.get(kid)
            if not key:
                raise ValueError(f"No JWK found for kid={kid!r} at {jwks_uri}")
            return key


# ── SAML Validator ────────────────────────────────────────────────────────────

@dataclass
class SAMLIdentity:
    """Identity extracted from a validated SAML assertion."""
    name_id: str
    email: str
    name: str
    groups: list[str]
    attributes: dict[str, list[str]]
    session_not_on_or_after: float


class SAMLValidator:
    """Parses and validates SAML 2.0 Responses / Assertions."""

    # XML namespace prefixes
    _NS = {
        "saml":  "urn:oasis:names:tc:SAML:2.0:assertion",
        "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
        "ds":    "http://www.w3.org/2000/09/xmldsig#",
    }

    def __init__(self, configs: list[SAMLConfig]) -> None:
        self._configs = {cfg.idp_entity_id: cfg for cfg in configs if cfg.enabled}

    def validate_response(self, saml_response_b64: str) -> SAMLIdentity:
        """Validate a base64-encoded SAMLResponse. Returns identity or raises."""
        if not _XML:
            raise RuntimeError("xml.etree.ElementTree unavailable — cannot parse SAML")

        xml_bytes = base64.b64decode(saml_response_b64)
        root = ET.fromstring(xml_bytes)

        # Issuer
        issuer_el = root.find("saml:Issuer", self._NS)
        idp_entity_id = issuer_el.text.strip() if issuer_el is not None else ""
        cfg = self._configs.get(idp_entity_id)
        if cfg is None:
            raise ValueError(f"Unknown SAML IdP: {idp_entity_id!r}")

        # Status
        status_code = root.find(".//samlp:StatusCode", self._NS)
        if status_code is not None:
            code = status_code.attrib.get("Value", "")
            if "Success" not in code:
                raise ValueError(f"SAML response status is not Success: {code}")

        # Assertion
        assertion = root.find("saml:Assertion", self._NS)
        if assertion is None:
            raise ValueError("No Assertion element found in SAMLResponse")

        # Signature verification (best-effort — requires cryptography + xmlsec)
        self._verify_signature(root, cfg)

        # Conditions / expiry
        conditions = assertion.find("saml:Conditions", self._NS)
        not_on_or_after = time.time() + 3600
        if conditions is not None:
            val = conditions.attrib.get("NotOnOrAfter", "")
            if val:
                not_on_or_after = _parse_saml_datetime(val)
                if time.time() > not_on_or_after:
                    raise ValueError("SAML Assertion has expired (NotOnOrAfter)")

        # NameID
        name_id_el = assertion.find(".//saml:NameID", self._NS)
        name_id = name_id_el.text.strip() if name_id_el is not None else ""

        # Attributes
        attrs: dict[str, list[str]] = {}
        for attr in assertion.findall(".//saml:Attribute", self._NS):
            attr_name = attr.attrib.get("Name", "")
            values = [
                v.text or ""
                for v in attr.findall("saml:AttributeValue", self._NS)
            ]
            attrs[attr_name] = values

        # Map to identity fields
        email = name_id if "@" in name_id else ""
        for src_key, dest_key in cfg.attribute_map.items():
            if dest_key == "email" and attrs.get(src_key):
                email = attrs[src_key][0]
            elif dest_key == "name" and attrs.get(src_key):
                pass  # handled below

        name_attr_key = next(
            (k for k, v in cfg.attribute_map.items() if v == "name"), ""
        )
        name = (attrs.get(name_attr_key) or [email])[0]

        groups_attr_key = next(
            (k for k, v in cfg.attribute_map.items() if v == "groups"), ""
        )
        groups = attrs.get(groups_attr_key, [])

        return SAMLIdentity(
            name_id=name_id,
            email=email,
            name=name,
            groups=groups,
            attributes=attrs,
            session_not_on_or_after=not_on_or_after,
        )

    def _verify_signature(self, root: Any, cfg: SAMLConfig) -> None:
        """Attempt XML signature verification using available libraries."""
        if not cfg.idp_cert_pem:
            log.warning("SAML: no IdP cert configured — skipping signature verification")
            return
        if not _CRYPTO:
            log.warning("SAML: cryptography not installed — skipping signature verification")
            return
        # Full XML-DSIG verification requires xmlsec1 or lxml-xmlsec bindings.
        # Log a warning when they are absent rather than silently passing.
        try:
            import xmlsec  # type: ignore
        except ImportError:
            log.warning(
                "SAML: xmlsec not installed — XML signature NOT verified. "
                "Install python-xmlsec for production use."
            )
            return
        # If xmlsec is present, perform full verification
        try:
            from lxml import etree as lxml_et  # type: ignore
            xml_tree = lxml_et.fromstring(ET.tostring(root))
            ctx = xmlsec.SignatureContext()
            key = xmlsec.Key.from_memory(
                cfg.idp_cert_pem.encode(), xmlsec.constants.KeyDataFormatCertPem
            )
            ctx.key = key
            sig_node = xmlsec.tree.find_node(xml_tree, xmlsec.constants.NodeSignature)
            ctx.verify(sig_node)
        except Exception as exc:
            raise ValueError(f"SAML signature verification failed: {exc}") from exc


# ── SCIM 2.0 ──────────────────────────────────────────────────────────────────

@dataclass
class SCIMUser:
    """Internal SCIM user record."""
    id: str
    external_id: str
    user_name: str          # Usually email
    display_name: str
    email: str
    active: bool = True
    groups: list[str] = field(default_factory=list)
    orchestra_role: str = "analyst"
    orchestra_tier: str = "pro"
    org_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_scim(self) -> dict:
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "id": self.id,
            "externalId": self.external_id,
            "userName": self.user_name,
            "displayName": self.display_name,
            "active": self.active,
            "emails": [{"value": self.email, "primary": True, "type": "work"}],
            "groups": [{"value": g, "display": g} for g in self.groups],
            "meta": {
                "resourceType": "User",
                "created": _iso(self.created_at),
                "lastModified": _iso(self.updated_at),
                "location": f"/scim/v2/Users/{self.id}",
            },
        }

    @classmethod
    def from_scim(cls, data: dict, org_id: str = "") -> SCIMUser:
        uid = data.get("id") or str(uuid.uuid4())
        emails = data.get("emails", [])
        email = next(
            (e["value"] for e in emails if e.get("primary")),
            emails[0]["value"] if emails else data.get("userName", ""),
        )
        return cls(
            id=uid,
            external_id=data.get("externalId", ""),
            user_name=data.get("userName", email),
            display_name=data.get("displayName", ""),
            email=email,
            active=data.get("active", True),
            org_id=org_id,
        )


class SCIMStore:
    """In-memory SCIM user store (swap for DB adapter in production)."""

    def __init__(self) -> None:
        self._users: dict[str, SCIMUser] = {}          # id → user
        self._by_username: dict[str, str] = {}          # username → id
        self._lock = asyncio.Lock()

    async def list_users(
        self, filter_str: str = "", start_index: int = 1, count: int = 200
    ) -> tuple[list[SCIMUser], int]:
        async with self._lock:
            users = list(self._users.values())
        if filter_str:
            users = _scim_filter(users, filter_str)
        total = len(users)
        return users[start_index - 1 : start_index - 1 + count], total

    async def get_user(self, uid: str) -> SCIMUser | None:
        return self._users.get(uid)

    async def get_by_username(self, username: str) -> SCIMUser | None:
        uid = self._by_username.get(username.lower())
        return self._users.get(uid) if uid else None

    async def create_user(self, user: SCIMUser) -> SCIMUser:
        async with self._lock:
            existing_id = self._by_username.get(user.user_name.lower())
            if existing_id:
                raise ValueError(f"User {user.user_name!r} already exists")
            self._users[user.id] = user
            self._by_username[user.user_name.lower()] = user.id
        log.info("SCIM: created user %s (%s)", user.user_name, user.id)
        return user

    async def replace_user(self, uid: str, user: SCIMUser) -> SCIMUser:
        async with self._lock:
            if uid not in self._users:
                raise KeyError(uid)
            old = self._users[uid]
            if old.user_name.lower() != user.user_name.lower():
                self._by_username.pop(old.user_name.lower(), None)
                self._by_username[user.user_name.lower()] = uid
            user.id = uid
            user.updated_at = time.time()
            self._users[uid] = user
        log.info("SCIM: replaced user %s", uid)
        return user

    async def patch_user(self, uid: str, ops: list[dict]) -> SCIMUser:
        async with self._lock:
            user = self._users.get(uid)
            if not user:
                raise KeyError(uid)
            for op in ops:
                self._apply_patch_op(user, op)
            user.updated_at = time.time()
        log.info("SCIM: patched user %s (%d ops)", uid, len(ops))
        return user

    async def deactivate_user(self, uid: str) -> None:
        async with self._lock:
            user = self._users.get(uid)
            if user:
                user.active = False
                user.updated_at = time.time()
        log.info("SCIM: deactivated user %s", uid)

    @staticmethod
    def _apply_patch_op(user: SCIMUser, op: dict) -> None:
        opname = op.get("op", "").lower()
        path = op.get("path", "")
        value = op.get("value")
        if opname == "replace":
            if path == "active":
                user.active = bool(value)
            elif path == "displayName":
                user.display_name = str(value)
            elif path == "userName":
                user.user_name = str(value)
            elif isinstance(value, dict):
                if "active" in value:
                    user.active = bool(value["active"])
        elif opname == "add" and path == "groups":
            for g in (value if isinstance(value, list) else [value]):
                gval = g.get("value") if isinstance(g, dict) else str(g)
                if gval and gval not in user.groups:
                    user.groups.append(gval)
        elif opname == "remove" and path.startswith("groups"):
            m = re.search(r'\[value eq "([^"]+)"\]', path)
            if m:
                user.groups = [g for g in user.groups if g != m.group(1)]


def scim_router(engine: SSOEngine) -> Any:
    """Return a FastAPI APIRouter with SCIM 2.0 endpoints."""
    try:
        from fastapi import APIRouter, Depends, HTTPException, Request
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError("FastAPI is required for SCIM endpoints: pip install fastapi")

    router = APIRouter(prefix="/scim/v2", tags=["SCIM 2.0"])
    store = engine.scim_store

    async def _auth(request: Request) -> None:
        token = request.headers.get("Authorization", "")
        expected = "Bearer " + engine.cfg.scim.bearer_token
        if not engine.cfg.scim.bearer_token:
            raise HTTPException(503, "SCIM not configured — set SCIM_BEARER_TOKEN")
        if token != expected:
            raise HTTPException(401, "Invalid SCIM bearer token")

    @router.get("/ServiceProviderConfig")
    async def sp_config():
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "documentationUri": "https://docs.orchestra.ai/enterprise/scim",
            "patch": {"supported": True},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": True, "maxResults": 200},
            "changePassword": {"supported": False},
            "sort": {"supported": False},
            "etag": {"supported": False},
            "authenticationSchemes": [{
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Authentication scheme using OAuth bearer tokens",
                "primary": True,
            }],
        }

    @router.get("/Schemas")
    async def schemas():
        return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
                "totalResults": 1, "Resources": [_USER_SCHEMA]}

    @router.get("/Users", dependencies=[Depends(_auth)])
    async def list_users(
        filter: str = "",
        startIndex: int = 1,
        count: int = 100,
    ):
        users, total = await store.list_users(filter, startIndex, min(count, engine.cfg.scim.max_results))
        return {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
            "totalResults": total,
            "startIndex": startIndex,
            "itemsPerPage": len(users),
            "Resources": [u.to_scim() for u in users],
        }

    @router.get("/Users/{uid}", dependencies=[Depends(_auth)])
    async def get_user(uid: str):
        user = await store.get_user(uid)
        if not user:
            raise HTTPException(404, f"User {uid} not found")
        return user.to_scim()

    @router.post("/Users", status_code=201, dependencies=[Depends(_auth)])
    async def create_user(request: Request):
        data = await request.json()
        user = SCIMUser.from_scim(data)
        try:
            created = await store.create_user(user)
        except ValueError as exc:
            # 409 Conflict if user already exists
            raise HTTPException(409, str(exc))
        return JSONResponse(status_code=201, content=created.to_scim())

    @router.put("/Users/{uid}", dependencies=[Depends(_auth)])
    async def replace_user(uid: str, request: Request):
        data = await request.json()
        user = SCIMUser.from_scim(data)
        try:
            updated = await store.replace_user(uid, user)
        except KeyError:
            raise HTTPException(404, f"User {uid} not found")
        return updated.to_scim()

    @router.patch("/Users/{uid}", dependencies=[Depends(_auth)])
    async def patch_user(uid: str, request: Request):
        data = await request.json()
        ops = data.get("Operations", [])
        try:
            updated = await store.patch_user(uid, ops)
        except KeyError:
            raise HTTPException(404, f"User {uid} not found")
        return updated.to_scim()

    @router.delete("/Users/{uid}", status_code=204, dependencies=[Depends(_auth)])
    async def deactivate_user(uid: str):
        await store.deactivate_user(uid)
        return JSONResponse(status_code=204, content=None)

    return router


# ── SSOEngine — top-level facade ──────────────────────────────────────────────

class SSOEngine:
    """Top-level SSO facade used by MILES enterprise middleware."""

    def __init__(self, cfg: SSOConfig) -> None:
        self.cfg = cfg
        self.oidc = OIDCValidator(cfg.oidc)
        self.saml = SAMLValidator(cfg.saml)
        self.scim_store = SCIMStore()

    async def validate_bearer_token(self, token: str) -> OIDCIdentity:
        """Validate an OIDC Bearer token; raises ValueError on failure."""
        return await self.oidc.validate(token)

    def validate_saml_response(self, b64_response: str) -> SAMLIdentity:
        """Validate a SAML response; raises ValueError on failure."""
        return self.saml.validate_response(b64_response)

    def map_groups_to_role(self, groups: list[str]) -> str:
        """Map external IdP groups to an Orchestra RBAC role slug."""
        for group in groups:
            if group in self.cfg.group_role_map:
                return self.cfg.group_role_map[group]
        return self.cfg.default_role

    def extract_bearer(self, auth_header: str) -> str | None:
        """Pull token from 'Bearer <token>' header."""
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return None


# ── FastAPI middleware ─────────────────────────────────────────────────────────

def sso_middleware(engine: SSOEngine, protected_prefix: str = "/miles/api"):
    """Return a FastAPI middleware that validates SSO tokens on protected routes."""
    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse as StarletteJSON
    except ImportError:
        raise ImportError("starlette is required: pip install starlette")

    class _SSOMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next):
            path = request.url.path
            # Only protect specified prefix
            if not path.startswith(protected_prefix):
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            token = engine.extract_bearer(auth_header)

            if not token:
                if engine.cfg.enforce:
                    return StarletteJSON({"error": "Authentication required"}, status_code=401)
                return await call_next(request)

            try:
                identity = await engine.validate_bearer_token(token)
                role = engine.map_groups_to_role(identity.groups)
                request.state.sso_identity = identity
                request.state.sso_role = role
            except ValueError as exc:
                log.warning("SSO token rejected: %s", exc)
                if engine.cfg.enforce:
                    return StarletteJSON({"error": "Invalid token", "detail": str(exc)}, status_code=401)

            return await call_next(request)

    return _SSOMiddleware


# ── Helpers ───────────────────────────────────────────────────────────────────

def _jwt_part(token: str, index: int) -> dict:
    parts = token.split(".")
    raw = parts[index] + "==" * ((4 - len(parts[index]) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(raw))


def _aud_matches(aud: str | list[str], expected: str) -> bool:
    return expected in (aud if isinstance(aud, list) else [aud])


def _verify_signature(token: str, jwk: dict, alg: str) -> bool:
    if not _CRYPTO:
        log.warning("cryptography not installed — JWT signature not verified")
        return True
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        sig = base64.urlsafe_b64decode(sig_b64 + "==")
        kty = jwk.get("kty", "RSA")

        def _b64i(v: str) -> int:
            return int.from_bytes(base64.urlsafe_b64decode(v + "=="), "big")

        if kty == "RSA":
            pub = _RSAPublicNumbers(_b64i(jwk["e"]), _b64i(jwk["n"])).public_key(_backend())
            pub.verify(sig, signing_input, _PKCS1v15(), _SHA256())
            return True
        if kty == "EC":
            x, y = _b64i(jwk["x"]), _b64i(jwk["y"])
            pub = _ECPublicNumbers(x, y, _SECP256R1()).public_key(_backend())
            pub.verify(sig, signing_input, _ECDSA(_SHA256()))
            return True
        log.warning("Unsupported JWK kty=%s", kty)
        return False
    except Exception as exc:
        log.debug("Signature verification failed: %s", exc)
        return False


def _http():
    if not _HTTPX:
        raise ImportError("httpx required for OIDC: pip install httpx")
    return _httpx.AsyncClient(timeout=10)


def _parse_saml_datetime(val: str) -> float:
    import datetime
    try:
        dt = datetime.datetime.strptime(val, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc
        )
        return dt.timestamp()
    except ValueError:
        return time.time() + 3600


def _iso(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scim_filter(users: list[SCIMUser], filter_str: str) -> list[SCIMUser]:
    """Basic SCIM filter: 'userName eq "foo@bar.com"' and 'externalId eq "..."'"""
    m = re.match(r'(\w+)\s+eq\s+"([^"]+)"', filter_str.strip())
    if not m:
        return users
    attr, val = m.group(1), m.group(2).lower()
    attr_map = {
        "username": "user_name",
        "externalid": "external_id",
        "email": "email",
    }
    field_name = attr_map.get(attr.lower(), attr.lower())
    return [u for u in users if getattr(u, field_name, "").lower() == val]


_USER_SCHEMA = {
    "id": "urn:ietf:params:scim:schemas:core:2.0:User",
    "name": "User",
    "description": "User account in Orchestra/MILES",
    "attributes": [
        {"name": "userName", "type": "string", "required": True, "uniqueness": "server"},
        {"name": "displayName", "type": "string"},
        {"name": "emails", "type": "complex", "multiValued": True},
        {"name": "active", "type": "boolean"},
        {"name": "groups", "type": "complex", "multiValued": True, "mutability": "readOnly"},
    ],
}
