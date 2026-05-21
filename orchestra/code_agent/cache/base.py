from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Cache(ABC):
    @abstractmethod
    def get(self, key: str) -> str | None:
        ...

    @abstractmethod
    def set(self, key: str, value: str, ttl: int = 3600) -> None:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...

    @abstractmethod
    def invalidate(self, key: str) -> None:
        ...


class NullCache(Cache):
    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, ttl: int = 3600) -> None:
        pass

    def clear(self) -> None:
        pass

    def invalidate(self, key: str) -> None:
        pass


class DiskCache(Cache):
    def __init__(self, path: str | Path = ".code-agent-cache.db", ttl: int = 3600):
        self.path = Path(path)
        self.default_ttl = ttl
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, value TEXT, created_at REAL, ttl INTEGER)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_key ON cache(key)"
        )
        self.conn.commit()

    @staticmethod
    def make_key(messages: list[dict[str, Any]], model: str) -> str:
        raw = json.dumps(messages, sort_keys=True) + model
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value, created_at, ttl FROM cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        value, created_at, ttl = row
        if time.time() - created_at > ttl:
            self.invalidate(key)
            return None
        return value

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, created_at, ttl) VALUES (?, ?, ?, ?)",
            (key, value, time.time(), ttl or self.default_ttl),
        )
        self.conn.commit()

    def clear(self) -> None:
        self.conn.execute("DELETE FROM cache")
        self.conn.commit()

    def invalidate(self, key: str) -> None:
        self.conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        self.conn.commit()

    def clean_expired(self) -> int:
        deleted = self.conn.execute(
            "DELETE FROM cache WHERE created_at + ttl < ?", (time.time(),)
        ).rowcount
        self.conn.commit()
        return deleted

    def close(self) -> None:
        self.conn.close()

    def __len__(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM cache").fetchone()
        return row[0] if row else 0
