"""
Professional role hierarchy for Orchestra.

Three domains (healthcare, legal, finance) each have their own role ladder.
Cross-domain access requires explicit SUPER_ADMIN or ADMIN grant.

Role ladder (highest → lowest):
  Platform:    super_admin > admin > user
  Healthcare:  physician > nurse > healthcare_admin
  Legal:       partner > associate > paralegal
  Finance:     portfolio_manager > trader > analyst

Permissions are additive — a physician also has all nurse permissions, etc.
"""
from __future__ import annotations

from enum import Enum
from typing import FrozenSet


class Role(str, Enum):
    # ── Platform ─────────────────────────────────────────────
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"

    # ── Healthcare ───────────────────────────────────────────
    PHYSICIAN = "physician"        # MD/DO — full PHI access + break-glass
    NURSE = "nurse"                # RN/NP — patient records, no admin ops
    HEALTHCARE_ADMIN = "healthcare_admin"  # billing, scheduling, no PHI

    # ── Legal ────────────────────────────────────────────────
    PARTNER = "partner"            # all firm matters, rate setting, billing
    ASSOCIATE = "associate"        # own matters + assigned matters
    PARALEGAL = "paralegal"        # read-only on assigned matters

    # ── Finance ──────────────────────────────────────────────
    PORTFOLIO_MANAGER = "portfolio_manager"  # all portfolios + trading
    TRADER = "trader"              # execute trades on assigned portfolios
    ANALYST = "analyst"            # read-only analytics + report generation

    # ── General ──────────────────────────────────────────────
    USER = "user"                  # default — app access, own data only


# ── Domain membership ─────────────────────────────────────────────────────────

HEALTHCARE_ROLES: FrozenSet[Role] = frozenset({
    Role.PHYSICIAN, Role.NURSE, Role.HEALTHCARE_ADMIN,
})

LEGAL_ROLES: FrozenSet[Role] = frozenset({
    Role.PARTNER, Role.ASSOCIATE, Role.PARALEGAL,
})

FINANCE_ROLES: FrozenSet[Role] = frozenset({
    Role.PORTFOLIO_MANAGER, Role.TRADER, Role.ANALYST,
})

PLATFORM_ROLES: FrozenSet[Role] = frozenset({
    Role.SUPER_ADMIN, Role.ADMIN, Role.USER,
})

PRIVILEGED_ROLES: FrozenSet[Role] = frozenset({
    Role.SUPER_ADMIN, Role.ADMIN,
    Role.PHYSICIAN, Role.PARTNER, Role.PORTFOLIO_MANAGER,
})


# ── Permission constants ──────────────────────────────────────────────────────

class Perm(str, Enum):
    # PHI / sensitive data
    PHI_READ           = "phi:read"
    PHI_WRITE          = "phi:write"
    BREAK_GLASS        = "phi:break_glass"

    # Legal privilege
    MATTER_READ_ALL    = "matter:read_all"
    MATTER_WRITE_ALL   = "matter:write_all"
    MATTER_READ_OWN    = "matter:read_own"
    MATTER_WRITE_OWN   = "matter:write_own"
    INVOICE_MANAGE     = "invoice:manage"

    # Finance
    PORTFOLIO_READ_ALL = "portfolio:read_all"
    PORTFOLIO_WRITE    = "portfolio:write"
    TRADE_EXECUTE      = "trade:execute"
    ANALYTICS_READ     = "analytics:read"

    # Admin
    USER_MANAGE        = "user:manage"
    AUDIT_READ         = "audit:read"
    COMPLIANCE_REPORT  = "compliance:report"
    CONSENT_MANAGE     = "consent:manage"
    LIFECYCLE_MANAGE   = "lifecycle:manage"

    # General
    AI_QUERY           = "ai:query"
    SETTINGS_READ      = "settings:read"
    SETTINGS_WRITE     = "settings:write"


# ── Role → permission mapping ─────────────────────────────────────────────────

_ROLE_PERMS: dict[Role, FrozenSet[Perm]] = {

    Role.SUPER_ADMIN: frozenset(Perm),  # all permissions

    Role.ADMIN: frozenset({
        Perm.PHI_READ, Perm.PHI_WRITE,
        Perm.MATTER_READ_ALL, Perm.MATTER_WRITE_ALL, Perm.INVOICE_MANAGE,
        Perm.PORTFOLIO_READ_ALL, Perm.PORTFOLIO_WRITE, Perm.ANALYTICS_READ,
        Perm.USER_MANAGE, Perm.AUDIT_READ, Perm.COMPLIANCE_REPORT,
        Perm.CONSENT_MANAGE, Perm.LIFECYCLE_MANAGE,
        Perm.AI_QUERY, Perm.SETTINGS_READ, Perm.SETTINGS_WRITE,
    }),

    Role.PHYSICIAN: frozenset({
        Perm.PHI_READ, Perm.PHI_WRITE, Perm.BREAK_GLASS,
        Perm.AUDIT_READ, Perm.CONSENT_MANAGE,
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),

    Role.NURSE: frozenset({
        Perm.PHI_READ, Perm.PHI_WRITE,
        Perm.CONSENT_MANAGE,
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),

    Role.HEALTHCARE_ADMIN: frozenset({
        Perm.CONSENT_MANAGE,
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),

    Role.PARTNER: frozenset({
        Perm.MATTER_READ_ALL, Perm.MATTER_WRITE_ALL, Perm.INVOICE_MANAGE,
        Perm.AUDIT_READ, Perm.CONSENT_MANAGE,
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),

    Role.ASSOCIATE: frozenset({
        Perm.MATTER_READ_OWN, Perm.MATTER_WRITE_OWN,
        Perm.CONSENT_MANAGE,
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),

    Role.PARALEGAL: frozenset({
        Perm.MATTER_READ_OWN,
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),

    Role.PORTFOLIO_MANAGER: frozenset({
        Perm.PORTFOLIO_READ_ALL, Perm.PORTFOLIO_WRITE,
        Perm.TRADE_EXECUTE, Perm.ANALYTICS_READ,
        Perm.AUDIT_READ, Perm.COMPLIANCE_REPORT,
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),

    Role.TRADER: frozenset({
        Perm.PORTFOLIO_READ_ALL, Perm.TRADE_EXECUTE, Perm.ANALYTICS_READ,
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),

    Role.ANALYST: frozenset({
        Perm.PORTFOLIO_READ_ALL, Perm.ANALYTICS_READ,
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),

    Role.USER: frozenset({
        Perm.AI_QUERY, Perm.SETTINGS_READ,
    }),
}


def has_permission(role: str, perm: Perm) -> bool:
    """Return True if the given role string grants perm."""
    try:
        r = Role(role)
    except ValueError:
        r = Role.USER
    return perm in _ROLE_PERMS.get(r, frozenset())


def permissions_for(role: str) -> list[str]:
    """Return list of permission strings for a role."""
    try:
        r = Role(role)
    except ValueError:
        r = Role.USER
    return sorted(p.value for p in _ROLE_PERMS.get(r, frozenset()))


def role_domain(role: str) -> str | None:
    """Return 'healthcare' | 'legal' | 'finance' | None for a role string."""
    try:
        r = Role(role)
    except ValueError:
        return None
    if r in HEALTHCARE_ROLES:
        return "healthcare"
    if r in LEGAL_ROLES:
        return "legal"
    if r in FINANCE_ROLES:
        return "finance"
    return None
