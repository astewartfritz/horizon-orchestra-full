from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class EventType(str, Enum):
    TASK_START = "task_start"
    TASK_END = "task_end"
    LLM_CALL = "llm_call"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    ERROR = "error"
    REFLECTION = "reflection"
    MEMORY = "memory"
    DECISION = "decision"


@dataclass
class TraceEvent:
    event_id: str
    trace_id: str
    event_type: EventType
    name: str
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    parent_id: str = ""
    input: str = ""
    output: str = ""
    provider: str = ""
    model: str = ""
    tool_name: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    status: str = "ok"
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "event_type": self.event_type.value,
            "name": self.name,
            "timestamp": self.timestamp,
            "duration_ms": round(self.duration_ms, 2),
            "parent_id": self.parent_id,
            "input": self.input[:500],
            "output": self.output[:500],
            "provider": self.provider,
            "model": self.model,
            "tool_name": self.tool_name,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost": round(self.cost, 6),
            "status": self.status,
            "error": self.error[:200] if self.error else "",
        }


@dataclass
class AgentTrace:
    trace_id: str
    task: str = ""
    events: list[TraceEvent] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost: float = 0.0
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    total_errors: int = 0
    status: str = "running"

    @property
    def duration(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time


class TraceCollector:
    def __init__(self, db_path: str | Path = ".agent-traces.db", jsonl_path: str | Path = ".agent-traces.jsonl"):
        self.db_path = Path(db_path)
        self.jsonl_path = Path(jsonl_path)
        self._traces: dict[str, AgentTrace] = {}
        self._active_trace_id: str = ""
        self._active_stack: dict[str, str] = {}
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                task TEXT,
                start_time REAL,
                end_time REAL,
                status TEXT,
                total_tokens_in INTEGER DEFAULT 0,
                total_tokens_out INTEGER DEFAULT 0,
                total_cost REAL DEFAULT 0.0,
                total_llm_calls INTEGER DEFAULT 0,
                total_tool_calls INTEGER DEFAULT 0,
                total_errors INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                trace_id TEXT,
                event_type TEXT,
                name TEXT,
                timestamp REAL,
                duration_ms REAL DEFAULT 0.0,
                parent_id TEXT,
                input TEXT,
                output TEXT,
                provider TEXT,
                model TEXT,
                tool_name TEXT,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                cost REAL DEFAULT 0.0,
                status TEXT DEFAULT 'ok',
                error TEXT,
                metadata TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
        """)
        self.conn.commit()

    ## Trace lifecycle

    def start_trace(self, task: str = "") -> str:
        trace_id = str(uuid.uuid4())[:12]
        trace = AgentTrace(trace_id=trace_id, task=task)
        self._traces[trace_id] = trace
        self._active_trace_id = trace_id
        self._active_stack[trace_id] = ""
        self._write_event(TraceEvent(
            event_id=self._eid(),
            trace_id=trace_id,
            event_type=EventType.TASK_START,
            name="task",
            input=task[:500],
        ))
        return trace_id

    def end_trace(self, trace_id: str | None = None, status: str = "ok") -> None:
        tid = trace_id or self._active_trace_id
        trace = self._traces.get(tid)
        if not trace:
            return
        trace.end_time = time.time()
        trace.status = status
        self._write_event(TraceEvent(
            event_id=self._eid(),
            trace_id=tid,
            event_type=EventType.TASK_END,
            name="task",
            status=status,
            duration_ms=trace.duration * 1000,
            output=trace.task,
        ))
        self._persist_trace(tid)

    ## Event recording

    def record_llm_call(self, provider: str, model: str, messages: list[Any], trace_id: str | None = None) -> str:
        tid = trace_id or self._active_trace_id
        eid = self._eid()
        inp = self._summarize_messages(messages)
        self._write_event(TraceEvent(
            event_id=eid, trace_id=tid, event_type=EventType.LLM_CALL,
            name=f"llm.{provider}.{model}", provider=provider, model=model,
            input=inp, parent_id=self._active_stack.get(tid, ""),
        ))
        self._active_stack[tid] = eid
        return eid

    def record_llm_response(self, llm_call_id: str, content: str, tokens_in: int = 0, tokens_out: int = 0, cost: float = 0.0, status: str = "ok", error: str = "", trace_id: str | None = None) -> None:
        tid = trace_id or self._active_trace_id
        trace = self._traces.get(tid)
        if trace:
            trace.total_llm_calls += 1
            trace.total_tokens_in += tokens_in
            trace.total_tokens_out += tokens_out
            trace.total_cost += cost
        event = self._get_event(llm_call_id)
        if event:
            event.output = content[:500]
            event.tokens_in = tokens_in
            event.tokens_out = tokens_out
            event.cost = cost
            event.status = status
            event.error = error[:200] if error else ""
            event.duration_ms = (time.time() - event.timestamp) * 1000
            self._persist_event(event)
        self._active_stack[tid] = self._get_parent(llm_call_id, tid)

    def record_tool_call(self, tool_name: str, args: dict[str, Any], trace_id: str | None = None) -> str:
        tid = trace_id or self._active_trace_id
        eid = self._eid()
        self._write_event(TraceEvent(
            event_id=eid, trace_id=tid, event_type=EventType.TOOL_CALL,
            name=f"tool.{tool_name}", tool_name=tool_name,
            input=json.dumps(args)[:500], parent_id=self._active_stack.get(tid, ""),
        ))
        self._active_stack[tid] = eid
        return eid

    def record_tool_result(self, tool_call_id: str, output: str, status: str = "ok", error: str = "", trace_id: str | None = None) -> None:
        tid = trace_id or self._active_trace_id
        trace = self._traces.get(tid)
        if trace:
            trace.total_tool_calls += 1
            if status == "error":
                trace.total_errors += 1
        event = self._get_event(tool_call_id)
        if event:
            event.output = output[:500]
            event.status = status
            event.error = error[:200] if error else ""
            event.duration_ms = (time.time() - event.timestamp) * 1000
            self._persist_event(event)
        self._active_stack[tid] = self._get_parent(tool_call_id, tid)

    def record_thinking(self, content: str, trace_id: str | None = None) -> str:
        tid = trace_id or self._active_trace_id
        eid = self._eid()
        self._write_event(TraceEvent(
            event_id=eid, trace_id=tid, event_type=EventType.THINKING,
            name="thinking", input=content[:500],
            parent_id=self._active_stack.get(tid, ""),
        ))
        return eid

    def record_error(self, error: str, source: str = "", trace_id: str | None = None) -> str:
        tid = trace_id or self._active_trace_id
        trace = self._traces.get(tid)
        if trace:
            trace.total_errors += 1
            trace.status = "error"
        eid = self._eid()
        self._write_event(TraceEvent(
            event_id=eid, trace_id=tid, event_type=EventType.ERROR,
            name=f"error.{source}", error=error[:500], status="error",
            parent_id=self._active_stack.get(tid, ""),
        ))
        return eid

    def record_decision(self, decision: str, context: str = "", trace_id: str | None = None) -> str:
        tid = trace_id or self._active_trace_id
        eid = self._eid()
        self._write_event(TraceEvent(
            event_id=eid, trace_id=tid, event_type=EventType.DECISION,
            name="decision", input=context[:300], output=decision[:300],
            parent_id=self._active_stack.get(tid, ""),
        ))
        return eid

    ## Query

    def get_trace(self, trace_id: str) -> AgentTrace | None:
        return self._traces.get(trace_id)

    def get_events(self, trace_id: str) -> list[TraceEvent]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE trace_id = ? ORDER BY timestamp", (trace_id,)
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def list_traces(self, limit: int = 20, offset: int = 0) -> list[AgentTrace]:
        rows = self.conn.execute(
            "SELECT * FROM traces ORDER BY start_time DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        return [self._row_to_trace(r) for r in rows]

    def search_events(self, query: str, limit: int = 50) -> list[TraceEvent]:
        q = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM events WHERE name LIKE ? OR input LIKE ? OR output LIKE ? OR error LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (q, q, q, q, limit),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        trace_count = self.conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
        event_count = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        agg = self.conn.execute("""
            SELECT COALESCE(SUM(total_llm_calls),0), COALESCE(SUM(total_tool_calls),0),
                   COALESCE(SUM(total_errors),0), COALESCE(SUM(total_cost),0),
                   COALESCE(SUM(total_tokens_in),0), COALESCE(SUM(total_tokens_out),0)
            FROM traces
        """).fetchone()
        by_type = {}
        for row in self.conn.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type").fetchall():
            by_type[row[0]] = row[1]
        return {
            "total_traces": trace_count,
            "total_events": event_count,
            "total_llm_calls": agg[0],
            "total_tool_calls": agg[1],
            "total_errors": agg[2],
            "total_cost": round(agg[3], 4),
            "total_tokens_in": agg[4],
            "total_tokens_out": agg[5],
            "events_by_type": by_type,
        }

    ## Internal

    def _eid(self) -> str:
        return str(uuid.uuid4())[:8]

    def _write_event(self, event: TraceEvent) -> None:
        trace = self._traces.get(event.trace_id)
        if trace:
            trace.events.append(event)
        self._persist_event(event)
        self._write_jsonl(event)

    def _persist_event(self, event: TraceEvent) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO events (event_id, trace_id, event_type, name, timestamp, duration_ms, "
            "parent_id, input, output, provider, model, tool_name, tokens_in, tokens_out, cost, status, error, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event.event_id, event.trace_id, event.event_type.value, event.name, event.timestamp,
             event.duration_ms, event.parent_id, event.input, event.output, event.provider, event.model,
             event.tool_name, event.tokens_in, event.tokens_out, event.cost, event.status, event.error,
             json.dumps(event.metadata)),
        )
        self.conn.commit()

    def _persist_trace(self, trace_id: str) -> None:
        trace = self._traces.get(trace_id)
        if not trace:
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO traces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trace.trace_id, trace.task, trace.start_time, trace.end_time, trace.status,
             trace.total_tokens_in, trace.total_tokens_out, trace.total_cost,
             trace.total_llm_calls, trace.total_tool_calls, trace.total_errors),
        )
        self.conn.commit()

    def _write_jsonl(self, event: TraceEvent) -> None:
        try:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"trace_id": event.trace_id, **asdict(event)}, default=str) + "\n")
        except OSError:
            pass

    def _get_event(self, event_id: str) -> TraceEvent | None:
        for trace in self._traces.values():
            for e in trace.events:
                if e.event_id == event_id:
                    return e
        row = self.conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return self._row_to_event(row) if row else None

    def _get_parent(self, event_id: str, trace_id: str) -> str:
        for trace in self._traces.values():
            for e in trace.events:
                if e.event_id == event_id:
                    return e.parent_id
        return ""

    @staticmethod
    def _summarize_messages(messages: list[Any]) -> str:
        parts = []
        for m in messages[-4:]:
            role = getattr(m, "role", "unknown")
            content = getattr(m, "content", str(m))
            parts.append(f"[{role}] {str(content)[:200]}")
        return "\n".join(parts)

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> TraceEvent:
        return TraceEvent(
            event_id=row["event_id"], trace_id=row["trace_id"],
            event_type=EventType(row["event_type"]), name=row["name"],
            timestamp=row["timestamp"], duration_ms=row["duration_ms"],
            parent_id=row["parent_id"], input=row["input"] or "",
            output=row["output"] or "", provider=row["provider"] or "",
            model=row["model"] or "", tool_name=row["tool_name"] or "",
            tokens_in=row["tokens_in"] or 0, tokens_out=row["tokens_out"] or 0,
            cost=row["cost"] or 0.0, status=row["status"] or "ok",
            error=row["error"] or "",
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    @staticmethod
    def _row_to_trace(row: sqlite3.Row) -> AgentTrace:
        return AgentTrace(
            trace_id=row["trace_id"], task=row["task"] or "",
            start_time=row["start_time"], end_time=row["end_time"] or 0.0,
            status=row["status"] or "unknown",
            total_tokens_in=row["total_tokens_in"] or 0,
            total_tokens_out=row["total_tokens_out"] or 0,
            total_cost=row["total_cost"] or 0.0,
            total_llm_calls=row["total_llm_calls"] or 0,
            total_tool_calls=row["total_tool_calls"] or 0,
            total_errors=row["total_errors"] or 0,
        )

    def close(self) -> None:
        self.conn.close()
