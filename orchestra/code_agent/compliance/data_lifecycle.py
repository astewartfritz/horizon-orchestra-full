from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetentionPolicy:
    id: str = ""
    name: str = ""
    data_category: str = ""
    retention_days: int = 365
    auto_delete: bool = True
    requires_legal_hold_override: bool = True


@dataclass
class LegalHold:
    id: str = ""
    case_name: str = ""
    data_categories: list[str] = field(default_factory=list)
    created_at: float = 0.0
    expires_at: float = 0.0
    created_by: str = ""
    notes: str = ""
    active: bool = True


DEFAULT_RETENTION_POLICIES: list[RetentionPolicy] = [
    RetentionPolicy(name="phi_medical_records", data_category="phi", retention_days=2555, auto_delete=False),
    RetentionPolicy(name="phi_financial", data_category="financial_phi", retention_days=2190),
    RetentionPolicy(name="legal_documents", data_category="legal_document", retention_days=2555),
    RetentionPolicy(name="financial_transactions", data_category="transaction", retention_days=2190),
    RetentionPolicy(name="audit_logs", data_category="audit_log", retention_days=2190),
    RetentionPolicy(name="user_sessions", data_category="session", retention_days=90),
    RetentionPolicy(name="chat_history", data_category="chat", retention_days=730),
    RetentionPolicy(name="consent_records", data_category="consent", retention_days=3650),
    RetentionPolicy(name="billing_records", data_category="billing", retention_days=2555),
]


class DataLifecycleManager:
    """Manages data retention, deletion, and legal holds across categories.

    Supports:
    - Per-category retention policies
    - Legal holds that override automatic deletion
    - Soft-delete with grace period
    - Expiration checking for scheduled cleanup
    """

    def __init__(self) -> None:
        self._policies: dict[str, RetentionPolicy] = {}
        self._legal_holds: dict[str, LegalHold] = {}
        self._holds_by_category: dict[str, list[str]] = {}
        for p in DEFAULT_RETENTION_POLICIES:
            self._policies[p.data_category] = p

    def register_policy(self, policy: RetentionPolicy) -> None:
        self._policies[policy.data_category] = policy

    def get_policy(self, data_category: str) -> RetentionPolicy | None:
        return self._policies.get(data_category)

    def list_policies(self) -> list[RetentionPolicy]:
        return list(self._policies.values())

    def is_expired(self, data_category: str, created_at: float) -> bool:
        policy = self._policies.get(data_category)
        if policy is None:
            return False
        if self._has_active_hold(data_category):
            return False
        return (time.time() - created_at) > (policy.retention_days * 86400)

    def create_legal_hold(
        self, case_name: str, data_categories: list[str],
        created_by: str = "", duration_days: int = 3650,
    ) -> LegalHold:
        hold = LegalHold(
            id=str(uuid.uuid4()),
            case_name=case_name,
            data_categories=data_categories,
            created_at=time.time(),
            expires_at=time.time() + duration_days * 86400,
            created_by=created_by,
        )
        self._legal_holds[hold.id] = hold
        for cat in data_categories:
            self._holds_by_category.setdefault(cat, []).append(hold.id)
        return hold

    def release_legal_hold(self, hold_id: str) -> bool:
        hold = self._legal_holds.get(hold_id)
        if hold is None:
            return False
        hold.active = False
        return True

    def get_legal_hold(self, hold_id: str) -> LegalHold | None:
        return self._legal_holds.get(hold_id)

    def list_legal_holds(self) -> list[LegalHold]:
        return list(self._legal_holds.values())

    def _has_active_hold(self, data_category: str) -> bool:
        hold_ids = self._holds_by_category.get(data_category, [])
        now = time.time()
        for hid in hold_ids:
            hold = self._legal_holds.get(hid)
            if hold and hold.active and now < hold.expires_at:
                return True
        return False
