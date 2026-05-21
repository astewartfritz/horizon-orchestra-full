from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from orchestra.code_agent.agent_headers.models import ContextRecord

__all__ = [
    "ContextManager",
    "ContextRecord",
    "generate_context_id",
]

_CONTEXT_HEADER = "X-Agent-Context-Id"


def generate_context_id() -> str:
    return str(uuid.uuid4())


class ContextManager:
    """Tracks ongoing agent interactions across multiple API calls.

    Stores conversation context keyed by a ``X-Agent-Context-Id`` header
    so agents can resume multi-turn workflows without redundant queries.
    """

    def __init__(self, default_ttl: float = 3600.0) -> None:
        self._store: dict[str, ContextRecord] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl

    def create_context(self, initial_data: dict[str, Any] | None = None) -> str:
        ctx_id = generate_context_id()
        record = ContextRecord(
            context_id=ctx_id,
            expires_at=time.time() + self._default_ttl,
            data=initial_data or {},
        )
        with self._lock:
            self._store[ctx_id] = record
        return ctx_id

    def get_context(self, ctx_id: str) -> ContextRecord | None:
        self._evict_expired()
        with self._lock:
            record = self._store.get(ctx_id)
            if record is None:
                return None
            if time.time() > record.expires_at:
                del self._store[ctx_id]
                return None
            return record

    def update_context(self, ctx_id: str, data: dict[str, Any]) -> bool:
        self._evict_expired()
        with self._lock:
            record = self._store.get(ctx_id)
            if record is None:
                return False
            if time.time() > record.expires_at:
                del self._store[ctx_id]
                return False
            record.data.update(data)
            record.updated_at = time.time()
            record.turn_count += 1
            return True

    def delete_context(self, ctx_id: str) -> bool:
        with self._lock:
            if ctx_id in self._store:
                del self._store[ctx_id]
                return True
            return False

    def extract_from_headers(self, headers: dict[str, str]) -> str | None:
        ctx_id = headers.get(_CONTEXT_HEADER) or headers.get(_CONTEXT_HEADER.lower())
        if ctx_id and self.get_context(ctx_id):
            return ctx_id
        return None

    @staticmethod
    def header_name() -> str:
        return _CONTEXT_HEADER

    def _evict_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._store.items() if now > v.expires_at]
            for k in expired:
                del self._store[k]
