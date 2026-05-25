from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionPolicy:
    idle_timeout_seconds: float = 1800.0
    max_concurrent_sessions: int = 3
    absolute_max_lifetime_seconds: float = 43200.0
    require_reauthentication_on_idle: bool = True


@dataclass
class SessionRecord:
    session_id: str = ""
    user_id: str = ""
    created_at: float = 0.0
    last_activity: float = 0.0
    ip_address: str = ""
    user_agent: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionHardener:
    """Enforces session security policies.

    - Idle timeout: terminates sessions inactive beyond threshold
    - Concurrent session limits: prevents session proliferation
    - Absolute max lifetime: forces periodic re-authentication
    """

    def __init__(self, policy: SessionPolicy | None = None) -> None:
        self._policy = policy or SessionPolicy()
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = threading.Lock()

    def set_policy(self, policy: SessionPolicy) -> None:
        self._policy = policy

    def register_session(self, record: SessionRecord) -> bool:
        with self._lock:
            user_sessions = [s for s in self._sessions.values() if s.user_id == record.user_id]
            active_count = sum(1 for s in user_sessions if not self._is_expired(s))
            if active_count >= self._policy.max_concurrent_sessions:
                oldest = sorted(user_sessions, key=lambda s: s.last_activity)[0]
                del self._sessions[oldest.session_id]
            self._sessions[record.session_id] = record
            return True

    def touch(self, session_id: str) -> bool:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return False
            if self._is_expired(record):
                del self._sessions[session_id]
                return False
            record.last_activity = time.time()
            return True

    def is_valid(self, session_id: str) -> bool:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return False
            if self._is_expired(record):
                del self._sessions[session_id]
                return False
            return True

    def revoke(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def revoke_all_for_user(self, user_id: str) -> int:
        with self._lock:
            to_remove = [sid for sid, s in self._sessions.items() if s.user_id == user_id]
            for sid in to_remove:
                del self._sessions[sid]
            return len(to_remove)

    def get_active_sessions(self, user_id: str) -> list[SessionRecord]:
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.user_id == user_id and not self._is_expired(s)
            ]

    def count_active(self) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values() if not self._is_expired(s))

    def cleanup_expired(self) -> int:
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if self._is_expired(s)]
            for sid in expired:
                del self._sessions[sid]
            return len(expired)

    def _is_expired(self, record: SessionRecord) -> bool:
        now = time.time()
        if now - record.last_activity > self._policy.idle_timeout_seconds:
            return True
        if now - record.created_at > self._policy.absolute_max_lifetime_seconds:
            return True
        return False
