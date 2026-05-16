from __future__ import annotations

import datetime
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    timestamp: str = ""
    level: str = "INFO"
    message: str = ""
    module: str = ""
    agent_id: str = ""
    session_id: str = ""
    tool: str = ""
    duration_ms: float = 0.0
    tokens: int = 0
    cost: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class AgentLogger:
    _instance: AgentLogger | None = None

    def __init__(self, log_dir: str = ".agent-logs", json_output: bool = True):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.json_output = json_output
        self._entries: list[LogEntry] = []
        self._file = self.log_dir / f"agent-{datetime.datetime.now():%Y%m%d-%H%M%S}.jsonl"

    @classmethod
    def get(cls) -> AgentLogger:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def log(
        self,
        level: str | LogLevel = "INFO",
        message: str = "",
        module: str = "",
        agent_id: str = "",
        session_id: str = "",
        tool: str = "",
        duration_ms: float = 0.0,
        tokens: int = 0,
        cost: float = 0.0,
        **extra: Any,
    ) -> LogEntry:
        entry = LogEntry(
            timestamp=datetime.datetime.utcnow().isoformat() + "Z",
            level=level.value if isinstance(level, LogLevel) else level,
            message=message,
            module=module,
            agent_id=agent_id,
            session_id=session_id,
            tool=tool,
            duration_ms=duration_ms,
            tokens=tokens,
            cost=cost,
            extra=extra,
        )
        self._entries.append(entry)
        if self.json_output:
            self._write_json(entry)
        return entry

    def _write_json(self, entry: LogEntry) -> None:
        try:
            with open(self._file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        except OSError:
            pass

    def info(self, message: str, **kw: Any) -> LogEntry:
        return self.log("INFO", message, **kw)

    def warn(self, message: str, **kw: Any) -> LogEntry:
        return self.log("WARNING", message, **kw)

    def error(self, message: str, **kw: Any) -> LogEntry:
        return self.log("ERROR", message, **kw)

    def debug(self, message: str, **kw: Any) -> LogEntry:
        return self.log("DEBUG", message, **kw)

    def recent(self, n: int = 50) -> list[LogEntry]:
        return self._entries[-n:]

    def search(self, query: str, max_results: int = 100) -> list[LogEntry]:
        q = query.lower()
        results = []
        for entry in self._entries:
            if q in entry.message.lower() or q in entry.module.lower() or q in entry.tool.lower():
                results.append(entry)
                if len(results) >= max_results:
                    break
        return results

    def get_log_file(self) -> str:
        return str(self._file)

    def stats(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for e in self._entries:
            counts[e.level] = counts.get(e.level, 0) + 1
        return {
            "total_entries": len(self._entries),
            "levels": counts,
            "log_file": str(self._file),
        }

    def flush(self) -> None:
        self._entries.clear()
