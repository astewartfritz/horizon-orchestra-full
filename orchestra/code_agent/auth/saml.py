"""
SAML 2.0 SSO integration for enterprise customers.

Supports SP-initiated login flow:
  1. GET  /auth/sso/saml/login?org={slug}     → redirect to IdP
  2. POST /auth/sso/saml/acs                  → IdP posts assertion here
  3. GET  /auth/sso/saml/metadata             → SP metadata XML

Requires python3-saml or pysaml2. Falls back to stub mode if neither is
installed (useful for dev — returns 501 with a clear message).

IdP config is stored per-org in the saml_configs table (SQLite).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger("orchestra.saml")
_DB_PATH = Path.home() / ".orchestra_saml.db"
_lock = threading.Lock()

# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class SAMLConfig:
    id: str
    org_id: str
    idp_entity_id: str
    idp_sso_url: str
    idp_slo_url: str
    idp_cert: str           # PEM public cert (without header/footer)
    sp_entity_id: str
    attribute_email: str    # IdP attribute name that maps to email
    attribute_name: str     # IdP attribute name for display name
    enabled: bool
    created_at: float
    updated_at: float


@dataclass
class SAMLSession:
    id: str
    org_id: str
    user_id: str
    name_id: str
    session_index: str
    created_at: float
    expires_at: float


# ── DB ────────────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_saml_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS saml_configs (
                id              TEXT PRIMARY KEY,
                org_id          TEXT UNIQUE NOT NULL,
                idp_entity_id   TEXT NOT NULL DEFAULT '',
                idp_sso_url     TEXT NOT NULL DEFAULT '',
                idp_slo_url     TEXT NOT NULL DEFAULT '',
                idp_cert        TEXT NOT NULL DEFAULT '',
                sp_entity_id    TEXT NOT NULL DEFAULT '',
                attribute_email TEXT NOT NULL DEFAULT 'email',
                attribute_name  TEXT NOT NULL DEFAULT 'displayName',
                enabled         INTEGER NOT NULL DEFAULT 0,
                created_at      REAL NOT NULL,
                updated_at      REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_saml_org ON saml_configs(org_id);

            CREATE TABLE IF NOT EXISTS saml_sessions (
                id            TEXT PRIMARY KEY,
                org_id        TEXT NOT NULL,
                user_id       TEXT NOT NULL,
                name_id       TEXT NOT NULL,
                session_index TEXT NOT NULL DEFAULT '',
                created_at    REAL NOT NULL,
                expires_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ssaml_user ON saml_sessions(user_id);
        """)


# ── Config CRUD ───────────────────────────────────────────────────────────────

def _cfg(r) -> SAMLConfig:
    d = dict(r)
    d["enabled"] = bool(d["enabled"])
    return SAMLConfig(**d)


def upsert_saml_config(org_id: str, **fields: Any) -> SAMLConfig:
    now = time.time()
    allowed = {
        "idp_entity_id", "idp_sso_url", "idp_slo_url", "idp_cert",
        "sp_entity_id", "attribute_email", "attribute_name", "enabled",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    with _lock, _db() as conn:
        row = conn.execute("SELECT * FROM saml_configs WHERE org_id=?", (org_id,)).fetchone()
        if row:
            set_clause = ", ".join(f"{k}=?" for k in updates) + ", updated_at=?"
            conn.execute(
                f"UPDATE saml_configs SET {set_clause} WHERE org_id=?",
                (*updates.values(), now, org_id),
            )
        else:
            cfg_id = str(uuid.uuid4())
            base = {
                "id": cfg_id, "org_id": org_id,
                "idp_entity_id": "", "idp_sso_url": "", "idp_slo_url": "",
                "idp_cert": "", "sp_entity_id": f"orchestra-sp-{org_id}",
                "attribute_email": "email", "attribute_name": "displayName",
                "enabled": 0, "created_at": now, "updated_at": now,
            }
            base.update(updates)
            if "enabled" in base:
                base["enabled"] = int(base["enabled"])
            conn.execute(
                "INSERT INTO saml_configs(id,org_id,idp_entity_id,idp_sso_url,idp_slo_url,"
                "idp_cert,sp_entity_id,attribute_email,attribute_name,enabled,created_at,updated_at) "
                "VALUES(:id,:org_id,:idp_entity_id,:idp_sso_url,:idp_slo_url,:idp_cert,"
                ":sp_entity_id,:attribute_email,:attribute_name,:enabled,:created_at,:updated_at)",
                base,
            )
        row = conn.execute("SELECT * FROM saml_configs WHERE org_id=?", (org_id,)).fetchone()
    return _cfg(row)


def get_saml_config(org_id: str) -> SAMLConfig | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM saml_configs WHERE org_id=?", (org_id,)).fetchone()
    return _cfg(row) if row else None


# ── SP Metadata ───────────────────────────────────────────────────────────────

def build_sp_metadata(sp_entity_id: str, acs_url: str) -> str:
    return f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
    entityID="{sp_entity_id}">
  <md:SPSSODescriptor
      AuthnRequestsSigned="false"
      WantAssertionsSigned="true"
      protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:AssertionConsumerService
        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        Location="{acs_url}"
        index="1"/>
  </md:SPSSODescriptor>
</md:EntityDescriptor>"""


# ── AuthnRequest builder (redirect binding) ───────────────────────────────────

def build_authn_request(idp_sso_url: str, sp_entity_id: str, acs_url: str) -> str:
    """
    Build a minimal SAML AuthnRequest and return the full redirect URL.
    In production, use python3-saml for proper signing. This is a stub.
    """
    import base64
    import zlib

    request_id = "_" + uuid.uuid4().hex
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        f'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{request_id}" Version="2.0" IssueInstant="{now}" '
        f'AssertionConsumerServiceURL="{acs_url}" '
        f'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f'<saml:Issuer>{sp_entity_id}</saml:Issuer>'
        f'</samlp:AuthnRequest>'
    )
    compressed = zlib.compress(xml.encode())[2:-4]  # strip zlib header/trailer
    encoded = base64.b64encode(compressed).decode()
    import urllib.parse
    return f"{idp_sso_url}?SAMLRequest={urllib.parse.quote(encoded)}"


# ── Assertion parsing ─────────────────────────────────────────────────────────

def parse_saml_response(saml_response_b64: str, cfg: SAMLConfig) -> dict[str, str] | None:
    """
    Parse and validate a SAML Response (base64-encoded).
    Returns {email, name, name_id, session_index} or None if invalid.

    Tries python3-saml first; falls back to bare XML parsing (dev only).
    """
    import base64
    try:
        xml = base64.b64decode(saml_response_b64).decode("utf-8", errors="replace")
    except Exception:
        return None

    # Attempt python3-saml
    try:
        from onelogin.saml2.response import OneLogin_Saml2_Response  # type: ignore
        settings_dict = {
            "sp": {"entityId": cfg.sp_entity_id, "assertionConsumerService": {"url": ""}},
            "idp": {
                "entityId": cfg.idp_entity_id,
                "singleSignOnService": {"url": cfg.idp_sso_url},
                "x509cert": cfg.idp_cert,
            },
        }
        resp = OneLogin_Saml2_Response(settings_dict, saml_response_b64)
        if not resp.is_valid({}):
            return None
        attrs = resp.get_attributes()
        email = (attrs.get(cfg.attribute_email) or [""])[0]
        name = (attrs.get(cfg.attribute_name) or [""])[0]
        return {
            "email": email, "name": name,
            "name_id": resp.get_nameid() or "",
            "session_index": resp.get_session_index() or "",
        }
    except ImportError:
        pass

    # Bare XML fallback (dev / testing — no signature verification)
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        ns = {
            "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
            "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
        }
        name_id_el = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
        name_id = name_id_el.text if name_id_el is not None else ""
        attrs: dict[str, str] = {}
        for attr in root.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Attribute"):
            attr_name = attr.get("Name", "")
            val_el = attr.find("{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue")
            attrs[attr_name] = val_el.text if val_el is not None else ""
        email = attrs.get(cfg.attribute_email, name_id)
        display_name = attrs.get(cfg.attribute_name, "")
        return {
            "email": email, "name": display_name,
            "name_id": name_id, "session_index": "",
        }
    except Exception as exc:
        _log.warning("SAML response parsing failed: %s", exc)
        return None


# ── Session tracking ──────────────────────────────────────────────────────────

def create_saml_session(org_id: str, user_id: str, name_id: str, session_index: str = "") -> SAMLSession:
    now = time.time()
    s = SAMLSession(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        name_id=name_id,
        session_index=session_index,
        created_at=now,
        expires_at=now + 28800,  # 8h
    )
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO saml_sessions(id,org_id,user_id,name_id,session_index,created_at,expires_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (s.id, s.org_id, s.user_id, s.name_id, s.session_index, s.created_at, s.expires_at),
        )
    return s
