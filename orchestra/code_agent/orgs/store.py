"""
Org / Team data store.

Hierarchy: Org → Teams → Members
Every user belongs to at least one org. Billing is at the org level.
Roles:
  org:   owner | admin | member | viewer
  team:  lead | member
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_DB_PATH = Path.home() / ".orchestra_orgs.db"
_lock = threading.Lock()

_INVITE_TTL = 7 * 24 * 3600  # 7 days


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class Org:
    id: str
    name: str
    slug: str
    plan: str            # free | pro | enterprise
    owner_user_id: str
    stripe_customer_id: str
    stripe_subscription_id: str
    created_at: float
    metadata: str        # JSON


@dataclass
class OrgMember:
    id: str
    org_id: str
    user_id: str
    role: str            # owner | admin | member | viewer
    invited_by: str
    joined_at: float
    status: str          # active | suspended


@dataclass
class OrgInvite:
    id: str
    org_id: str
    email: str
    role: str
    token: str
    invited_by: str
    created_at: float
    expires_at: float
    accepted_at: float | None
    status: str          # pending | accepted | cancelled | expired


@dataclass
class Team:
    id: str
    org_id: str
    name: str
    description: str
    created_by: str
    created_at: float


@dataclass
class TeamMember:
    id: str
    team_id: str
    org_id: str
    user_id: str
    role: str            # lead | member
    added_by: str
    added_at: float


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orgs (
                id                      TEXT PRIMARY KEY,
                name                    TEXT NOT NULL,
                slug                    TEXT UNIQUE NOT NULL,
                plan                    TEXT NOT NULL DEFAULT 'free',
                owner_user_id           TEXT NOT NULL,
                stripe_customer_id      TEXT NOT NULL DEFAULT '',
                stripe_subscription_id  TEXT NOT NULL DEFAULT '',
                created_at              REAL NOT NULL,
                metadata                TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_orgs_owner ON orgs(owner_user_id);
            CREATE INDEX IF NOT EXISTS idx_orgs_slug  ON orgs(slug);

            CREATE TABLE IF NOT EXISTS org_members (
                id          TEXT PRIMARY KEY,
                org_id      TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
                user_id     TEXT NOT NULL,
                role        TEXT NOT NULL DEFAULT 'member',
                invited_by  TEXT NOT NULL DEFAULT '',
                joined_at   REAL NOT NULL,
                status      TEXT NOT NULL DEFAULT 'active',
                UNIQUE(org_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_om_org  ON org_members(org_id);
            CREATE INDEX IF NOT EXISTS idx_om_user ON org_members(user_id);

            CREATE TABLE IF NOT EXISTS org_invites (
                id          TEXT PRIMARY KEY,
                org_id      TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
                email       TEXT NOT NULL,
                role        TEXT NOT NULL DEFAULT 'member',
                token       TEXT UNIQUE NOT NULL,
                invited_by  TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL,
                expires_at  REAL NOT NULL,
                accepted_at REAL,
                status      TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE INDEX IF NOT EXISTS idx_inv_org   ON org_invites(org_id);
            CREATE INDEX IF NOT EXISTS idx_inv_token ON org_invites(token);
            CREATE INDEX IF NOT EXISTS idx_inv_email ON org_invites(email);

            CREATE TABLE IF NOT EXISTS teams (
                id          TEXT PRIMARY KEY,
                org_id      TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_by  TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL,
                UNIQUE(org_id, name)
            );
            CREATE INDEX IF NOT EXISTS idx_teams_org ON teams(org_id);

            CREATE TABLE IF NOT EXISTS team_members (
                id       TEXT PRIMARY KEY,
                team_id  TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                org_id   TEXT NOT NULL,
                user_id  TEXT NOT NULL,
                role     TEXT NOT NULL DEFAULT 'member',
                added_by TEXT NOT NULL DEFAULT '',
                added_at REAL NOT NULL,
                UNIQUE(team_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_tm_team ON team_members(team_id);
            CREATE INDEX IF NOT EXISTS idx_tm_user ON team_members(user_id);
        """)


# ── Row → dataclass ───────────────────────────────────────────────────────────

def _org(r) -> Org:
    return Org(**{k: r[k] for k in Org.__dataclass_fields__})

def _member(r) -> OrgMember:
    return OrgMember(**{k: r[k] for k in OrgMember.__dataclass_fields__})

def _invite(r) -> OrgInvite:
    return OrgInvite(**{k: r[k] for k in OrgInvite.__dataclass_fields__})

def _team(r) -> Team:
    return Team(**{k: r[k] for k in Team.__dataclass_fields__})

def _tm(r) -> TeamMember:
    return TeamMember(**{k: r[k] for k in TeamMember.__dataclass_fields__})


# ── Org CRUD ──────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    return slug or "org"


def create_org(name: str, owner_user_id: str, plan: str = "free") -> Org:
    base_slug = _slugify(name)
    now = time.time()
    org_id = str(uuid.uuid4())

    with _lock, _db() as conn:
        # Ensure unique slug
        slug = base_slug
        suffix = 1
        while conn.execute("SELECT id FROM orgs WHERE slug=?", (slug,)).fetchone():
            slug = f"{base_slug}-{suffix}"; suffix += 1

        conn.execute(
            "INSERT INTO orgs(id,name,slug,plan,owner_user_id,stripe_customer_id,"
            "stripe_subscription_id,created_at,metadata) VALUES(?,?,?,?,?,?,?,?,?)",
            (org_id, name.strip(), slug, plan, owner_user_id, "", "", now, "{}"),
        )
        # Auto-add owner as owner-role member
        conn.execute(
            "INSERT INTO org_members(id,org_id,user_id,role,invited_by,joined_at,status) "
            "VALUES(?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), org_id, owner_user_id, "owner", "", now, "active"),
        )
        row = conn.execute("SELECT * FROM orgs WHERE id=?", (org_id,)).fetchone()
    return _org(row)


def get_org(org_id: str) -> Org | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM orgs WHERE id=?", (org_id,)).fetchone()
    return _org(row) if row else None


def get_org_by_slug(slug: str) -> Org | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM orgs WHERE slug=?", (slug,)).fetchone()
    return _org(row) if row else None


def list_orgs_for_user(user_id: str) -> list[Org]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT o.* FROM orgs o JOIN org_members m ON o.id=m.org_id "
            "WHERE m.user_id=? AND m.status='active' ORDER BY o.created_at",
            (user_id,),
        ).fetchall()
    return [_org(r) for r in rows]


def update_org(org_id: str, **kwargs: Any) -> Org | None:
    allowed = {"name", "plan", "stripe_customer_id", "stripe_subscription_id", "metadata"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_org(org_id)
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with _lock, _db() as conn:
        conn.execute(f"UPDATE orgs SET {set_clause} WHERE id=?", (*updates.values(), org_id))
        row = conn.execute("SELECT * FROM orgs WHERE id=?", (org_id,)).fetchone()
    return _org(row) if row else None


def delete_org(org_id: str) -> bool:
    with _lock, _db() as conn:
        c = conn.execute("DELETE FROM orgs WHERE id=?", (org_id,))
    return c.rowcount > 0


# ── Membership ────────────────────────────────────────────────────────────────

def get_member(org_id: str, user_id: str) -> OrgMember | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM org_members WHERE org_id=? AND user_id=?", (org_id, user_id)
        ).fetchone()
    return _member(row) if row else None


def list_members(org_id: str) -> list[OrgMember]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM org_members WHERE org_id=? ORDER BY joined_at", (org_id,)
        ).fetchall()
    return [_member(r) for r in rows]


def update_member_role(org_id: str, user_id: str, role: str) -> OrgMember | None:
    with _lock, _db() as conn:
        conn.execute(
            "UPDATE org_members SET role=? WHERE org_id=? AND user_id=?",
            (role, org_id, user_id),
        )
        row = conn.execute(
            "SELECT * FROM org_members WHERE org_id=? AND user_id=?", (org_id, user_id)
        ).fetchone()
    return _member(row) if row else None


def remove_member(org_id: str, user_id: str) -> bool:
    with _lock, _db() as conn:
        c = conn.execute(
            "DELETE FROM org_members WHERE org_id=? AND user_id=?", (org_id, user_id)
        )
    return c.rowcount > 0


def is_member(org_id: str, user_id: str, min_role: str = "viewer") -> bool:
    role_rank = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
    m = get_member(org_id, user_id)
    if not m or m.status != "active":
        return False
    return role_rank.get(m.role, -1) >= role_rank.get(min_role, 0)


# ── Invites ───────────────────────────────────────────────────────────────────

def create_invite(org_id: str, email: str, role: str, invited_by: str) -> OrgInvite:
    now = time.time()
    invite = OrgInvite(
        id=str(uuid.uuid4()),
        org_id=org_id,
        email=email.lower().strip(),
        role=role,
        token=secrets.token_urlsafe(32),
        invited_by=invited_by,
        created_at=now,
        expires_at=now + _INVITE_TTL,
        accepted_at=None,
        status="pending",
    )
    with _lock, _db() as conn:
        # Cancel any existing pending invite for this email+org
        conn.execute(
            "UPDATE org_invites SET status='cancelled' WHERE org_id=? AND email=? AND status='pending'",
            (org_id, invite.email),
        )
        conn.execute(
            "INSERT INTO org_invites(id,org_id,email,role,token,invited_by,"
            "created_at,expires_at,accepted_at,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (invite.id, invite.org_id, invite.email, invite.role, invite.token,
             invite.invited_by, invite.created_at, invite.expires_at,
             invite.accepted_at, invite.status),
        )
    return invite


def get_invite_by_token(token: str) -> OrgInvite | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM org_invites WHERE token=?", (token,)).fetchone()
    return _invite(row) if row else None


def list_invites(org_id: str, status: str = "pending") -> list[OrgInvite]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM org_invites WHERE org_id=? AND status=? ORDER BY created_at DESC",
            (org_id, status),
        ).fetchall()
    return [_invite(r) for r in rows]


def accept_invite(token: str, user_id: str) -> OrgInvite | None:
    now = time.time()
    with _lock, _db() as conn:
        row = conn.execute(
            "SELECT * FROM org_invites WHERE token=? AND status='pending' AND expires_at>?",
            (token, now),
        ).fetchone()
        if not row:
            return None
        inv = _invite(row)
        conn.execute(
            "UPDATE org_invites SET status='accepted', accepted_at=? WHERE id=?",
            (now, inv.id),
        )
        # Upsert member record
        existing = conn.execute(
            "SELECT id FROM org_members WHERE org_id=? AND user_id=?", (inv.org_id, user_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE org_members SET role=?, status='active' WHERE org_id=? AND user_id=?",
                (inv.role, inv.org_id, user_id),
            )
        else:
            conn.execute(
                "INSERT INTO org_members(id,org_id,user_id,role,invited_by,joined_at,status) "
                "VALUES(?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), inv.org_id, user_id, inv.role, inv.invited_by, now, "active"),
            )
        row2 = conn.execute("SELECT * FROM org_invites WHERE id=?", (inv.id,)).fetchone()
    return _invite(row2)


def cancel_invite(invite_id: str, org_id: str) -> bool:
    with _lock, _db() as conn:
        c = conn.execute(
            "UPDATE org_invites SET status='cancelled' WHERE id=? AND org_id=? AND status='pending'",
            (invite_id, org_id),
        )
    return c.rowcount > 0


# ── Teams ─────────────────────────────────────────────────────────────────────

def create_team(org_id: str, name: str, description: str = "", created_by: str = "") -> Team:
    now = time.time()
    team_id = str(uuid.uuid4())
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO teams(id,org_id,name,description,created_by,created_at) VALUES(?,?,?,?,?,?)",
            (team_id, org_id, name.strip(), description, created_by, now),
        )
        row = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    return _team(row)


def get_team(team_id: str) -> Team | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    return _team(row) if row else None


def list_teams(org_id: str) -> list[Team]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM teams WHERE org_id=? ORDER BY name", (org_id,)
        ).fetchall()
    return [_team(r) for r in rows]


def delete_team(team_id: str, org_id: str) -> bool:
    with _lock, _db() as conn:
        c = conn.execute("DELETE FROM teams WHERE id=? AND org_id=?", (team_id, org_id))
    return c.rowcount > 0


def add_team_member(team_id: str, org_id: str, user_id: str,
                    role: str = "member", added_by: str = "") -> TeamMember:
    now = time.time()
    tm_id = str(uuid.uuid4())
    with _lock, _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO team_members(id,team_id,org_id,user_id,role,added_by,added_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (tm_id, team_id, org_id, user_id, role, added_by, now),
        )
        row = conn.execute(
            "SELECT * FROM team_members WHERE team_id=? AND user_id=?", (team_id, user_id)
        ).fetchone()
    return _tm(row)


def remove_team_member(team_id: str, user_id: str) -> bool:
    with _lock, _db() as conn:
        c = conn.execute(
            "DELETE FROM team_members WHERE team_id=? AND user_id=?", (team_id, user_id)
        )
    return c.rowcount > 0


def list_team_members(team_id: str) -> list[TeamMember]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM team_members WHERE team_id=? ORDER BY added_at", (team_id,)
        ).fetchall()
    return [_tm(r) for r in rows]
