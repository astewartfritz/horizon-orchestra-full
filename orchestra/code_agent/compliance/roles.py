from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class ProfessionalRole(str, enum.Enum):
    """Domain-specific professional roles with granular permissions."""

    # Healthcare
    DOCTOR = "doctor"
    NURSE = "nurse"
    PHARMACIST = "pharmacist"
    MEDICAL_RESIDENT = "medical_resident"
    PATIENT = "patient"

    # Legal
    ATTORNEY = "attorney"
    PARALEGAL = "paralegal"
    JUDGE = "judge"
    LEGAL_SECRETARY = "legal_secretary"
    CLIENT = "client"

    # Financial
    BANKER = "banker"
    FINANCIAL_ADVISOR = "financial_advisor"
    AUDITOR = "auditor"
    COMPLIANCE_OFFICER = "compliance_officer"
    TRADER = "trader"

    # Cross-domain
    ADMIN = "admin"
    SYSTEM = "system"
    AUDIT_VIEWER = "audit_viewer"


@dataclass
class RolePermission:
    domain: str = ""
    resource: str = ""
    action: str = "read"


DOMAIN_PERMISSIONS: dict[str, dict[str, list[str]]] = {
    "healthcare": {
        "view_phi": ["doctor", "nurse", "pharmacist", "medical_resident"],
        "write_phi": ["doctor", "nurse", "pharmacist"],
        "delete_phi": ["doctor", "admin"],
        "manage_consent": ["doctor", "admin", "patient"],
        "emergency_access": ["doctor", "admin"],
        "view_financial": ["admin", "auditor"],
    },
    "legal": {
        "view_confidential": ["attorney", "paralegal", "judge", "client"],
        "write_confidential": ["attorney", "paralegal"],
        "delete_confidential": ["attorney", "admin"],
        "manage_engagement": ["attorney", "admin"],
        "billing_access": ["attorney", "legal_secretary", "admin"],
    },
    "financial": {
        "view_transactions": ["banker", "financial_advisor", "auditor", "compliance_officer"],
        "authorize_transaction": ["banker", "trader"],
        "approve_large_transaction": ["banker", "compliance_officer", "admin"],
        "view_balances": ["banker", "financial_advisor", "auditor"],
        "fraud_alert_access": ["compliance_officer", "auditor", "admin"],
    },
}


class RoleManager:
    """Manages professional role assignments and permission checks."""

    def __init__(self) -> None:
        self._user_roles: dict[str, list[ProfessionalRole]] = {}

    def assign(self, user_id: str, role: ProfessionalRole) -> None:
        self._user_roles.setdefault(user_id, [])
        if role not in self._user_roles[user_id]:
            self._user_roles[user_id].append(role)

    def remove(self, user_id: str, role: ProfessionalRole) -> bool:
        if user_id in self._user_roles and role in self._user_roles[user_id]:
            self._user_roles[user_id].remove(role)
            return True
        return False

    def get_roles(self, user_id: str) -> list[ProfessionalRole]:
        return self._user_roles.get(user_id, [])

    def has_role(self, user_id: str, role: ProfessionalRole) -> bool:
        return role in self._user_roles.get(user_id, [])

    def has_any_role(self, user_id: str, roles: list[ProfessionalRole]) -> bool:
        user_roles = self._user_roles.get(user_id, [])
        return any(r in user_roles for r in roles)

    def check_permission(self, user_id: str, domain: str, permission: str) -> bool:
        user_roles = self._user_roles.get(user_id, [])
        perm_map = DOMAIN_PERMISSIONS.get(domain, {})
        allowed_roles = perm_map.get(permission, [])
        return any(r.value in allowed_roles for r in user_roles)

    def has_emergency_capability(self, user_id: str) -> bool:
        emergency_roles = {ProfessionalRole.DOCTOR, ProfessionalRole.ADMIN}
        return any(r in emergency_roles for r in self._user_roles.get(user_id, []))
