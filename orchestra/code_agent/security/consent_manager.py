from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


__all__ = [
    "ConsentPurpose",
    "ConsentRecord",
    "ConsentManager",
]


class ConsentPurpose(enum.Enum):
    ANALYTICS = "analytics"
    PERSONALIZATION = "personalization"
    RESEARCH = "research"
    THIRD_PARTY = "third_party"
    MARKETING = "marketing"
    AGENT_LEARNING = "agent_learning"


@dataclass
class ConsentRecord:
    user_id: str
    purpose: ConsentPurpose
    granted: bool
    granted_at: float
    expires_at: float
    scope: str = "all"


class ConsentManager:
    def __init__(self) -> None:
        self._store: dict[str, list[ConsentRecord]] = {}

    def set_consent(
        self,
        user_id: str,
        purpose: ConsentPurpose,
        granted: bool,
        scope: str = "all",
        ttl: int = 31536000,
    ) -> bool:
        now = time.time()
        record = ConsentRecord(
            user_id=user_id,
            purpose=purpose,
            granted=granted,
            granted_at=now,
            expires_at=now + ttl,
            scope=scope,
        )
        self._store.setdefault(user_id, []).append(record)
        self.audit_log(user_id, "set_consent", f"purpose={purpose.value} granted={granted} scope={scope}")
        return True

    def check_consent(
        self,
        user_id: str,
        purpose: ConsentPurpose,
        data_scope: str = "all",
    ) -> bool:
        records = self._store.get(user_id, [])
        now = time.time()
        for rec in reversed(records):
            if rec.purpose != purpose:
                continue
            if rec.expires_at <= now:
                continue
            if data_scope != "all" and rec.scope != "all" and rec.scope != data_scope:
                continue
            return rec.granted
        return False

    def revoke_consent(self, user_id: str, purpose: ConsentPurpose) -> bool:
        records = self._store.get(user_id, [])
        for rec in records:
            if rec.purpose == purpose:
                rec.granted = False
                rec.expires_at = time.time()
                self.audit_log(user_id, "revoke_consent", f"purpose={purpose.value}")
                return True
        return False

    def get_consent_summary(self, user_id: str) -> dict:
        records = self._store.get(user_id, [])
        return {
            "user_id": user_id,
            "consents": [
                {
                    "purpose": rec.purpose.value,
                    "granted": rec.granted,
                    "granted_at": rec.granted_at,
                    "expires_at": rec.expires_at,
                    "scope": rec.scope,
                }
                for rec in records
            ],
        }

    def purge_expired(self) -> None:
        now = time.time()
        for user_id in list(self._store):
            self._store[user_id] = [
                rec for rec in self._store[user_id] if rec.expires_at > now
            ]
            if not self._store[user_id]:
                del self._store[user_id]

    def audit_log(self, user_id: str, action: str, details: str = "") -> None:
        pass
