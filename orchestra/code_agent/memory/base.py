from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class MemoryEntry:
    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None


class Memory(ABC):
    @abstractmethod
    async def save(self, entry: MemoryEntry) -> None:
        ...

    @abstractmethod
    async def load_recent(self, limit: int = 50) -> list[MemoryEntry]:
        ...

    @abstractmethod
    async def clear(self) -> None:
        ...


class NullMemory(Memory):
    async def save(self, entry: MemoryEntry) -> None:
        pass

    async def load_recent(self, limit: int = 50) -> list[MemoryEntry]:
        return []

    async def clear(self) -> None:
        pass


class JSONMemory(Memory):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._entries: list[dict[str, Any]] = []
        if self.path.exists():
            self._entries = json.loads(self.path.read_text("utf-8"))

    async def save(self, entry: MemoryEntry) -> None:
        d = asdict(entry)
        if d.get("metadata") is None:
            d["metadata"] = {}
        d["metadata"]["timestamp"] = __import__("time").time()
        self._entries.append(d)
        self.path.write_text(json.dumps(self._entries, indent=2), "utf-8")

    async def load_recent(self, limit: int = 50) -> list[MemoryEntry]:
        recent = self._entries[-limit:]
        return [MemoryEntry(**d) for d in recent]

    async def clear(self) -> None:
        self._entries = []
        if self.path.exists():
            self.path.unlink()


class SQLiteMemory(Memory):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS memory "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            " role TEXT, content TEXT, tool_call_id TEXT, "
            " name TEXT, metadata TEXT, created_at REAL)"
        )
        self.conn.commit()

    async def save(self, entry: MemoryEntry) -> None:
        import time
        self.conn.execute(
            "INSERT INTO memory (role, content, tool_call_id, name, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry.role,
                entry.content,
                entry.tool_call_id,
                entry.name,
                json.dumps(entry.metadata or {}),
                time.time(),
            ),
        )
        self.conn.commit()

    async def load_recent(self, limit: int = 50) -> list[MemoryEntry]:
        rows = self.conn.execute(
            "SELECT role, content, tool_call_id, name, metadata FROM memory "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            MemoryEntry(
                role=r[0],
                content=r[1],
                tool_call_id=r[2],
                name=r[3],
                metadata=json.loads(r[4]) if r[4] else {},
            )
            for r in reversed(rows)
        ]

    async def clear(self) -> None:
        self.conn.execute("DELETE FROM memory")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
