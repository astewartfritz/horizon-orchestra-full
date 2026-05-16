from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from code_agent.trace.collector import EventType, TraceCollector


class TraceExporter:
    def __init__(self, collector: TraceCollector | None = None):
        self.collector = collector or TraceCollector()

    def to_chrome_trace(self, trace_id: str, path: str | Path | None = None) -> str:
        events = self.collector.get_events(trace_id)
        trace_events = []
        pid = 1

        for e in events:
            dur_ms = e.duration_ms if e.duration_ms > 0 else 1
            ts_us = int(e.timestamp * 1000000)
            dur_us = int(dur_ms * 1000)
            cat = e.event_type.value
            name = e.name[:100]

            trace_events.append({
                "ph": "B",
                "ts": ts_us,
                "pid": pid,
                "tid": hash(e.parent_id or e.trace_id) % 100,
                "cat": cat,
                "name": name,
                "args": {"input": e.input[:200], "provider": e.provider, "model": e.model},
            })
            trace_events.append({
                "ph": "E",
                "ts": ts_us + dur_us,
                "pid": pid,
                "tid": hash(e.parent_id or e.trace_id) % 100,
                "cat": cat,
                "name": name,
                "args": {"output": e.output[:200], "duration_ms": round(dur_ms, 2), "status": e.status},
            })
            if e.status == "error":
                trace_events.append({
                    "ph": "X",
                    "ts": ts_us,
                    "dur": dur_us,
                    "pid": pid,
                    "tid": 0,
                    "cat": "error",
                    "name": f"ERROR: {e.error[:100]}",
                    "args": {"error": e.error[:200]},
                })

        result = json.dumps({"traceEvents": trace_events, "metadata": {"trace_id": trace_id}}, indent=2)
        if path:
            Path(path).write_text(result, "utf-8")
        return result

    def to_chrome_trace_all(self, path: str | Path = "agent-trace-chrome.json") -> str:
        traces = self.collector.list_traces(limit=100)
        all_events = []
        for t in traces:
            trace_data = json.loads(self.to_chrome_trace(t.trace_id))
            all_events.extend(trace_data["traceEvents"])
        result = json.dumps({"traceEvents": all_events, "metadata": {"exported_at": time.time()}}, indent=2)
        Path(path).write_text(result, "utf-8")
        return result

    def to_markdown(self, trace_id: str, path: str | Path | None = None) -> str:
        trace = self.collector.get_trace(trace_id)
        events = self.collector.get_events(trace_id)
        if not trace and not events:
            return f"Trace not found: {trace_id}"

        lines = [
            f"# Agent Trace: {trace_id}",
            "",
            f"**Task:** {trace.task if trace else '(from db)'}",
            f"**Duration:** {self._fmt_duration(trace.duration if trace else 0)}",
            f"**Status:** {trace.status if trace else 'completed'}",
            f"**Events:** {len(events)}",
            "",
            "## Event Timeline",
            "",
            "| Time | Duration | Type | Name | Status |",
            "|------|----------|------|------|--------|",
        ]
        start = events[0].timestamp if events else time.time()
        for e in events:
            offset = (e.timestamp - start) * 1000
            dur = f"{e.duration_ms:.1f}ms" if e.duration_ms > 0 else "-"
            icon = self._icon(e.event_type)
            lines.append(f"| {offset:.0f}ms | {dur} | {icon} {e.event_type.value} | {e.name} | {e.status} |")

        lines.extend(["", "## Event Details", ""])
        for e in events:
            lines.append(f"### {e.name} ({e.event_id[:6]})")
            if e.input:
                lines.append(f"\n**Input:**\n```\n{e.input[:500]}\n```")
            if e.output:
                lines.append(f"\n**Output:**\n```\n{e.output[:500]}\n```")
            if e.error:
                lines.append(f"\n**Error:** `{e.error[:200]}`")
            if e.tokens_in or e.tokens_out:
                lines.append(f"\n**Tokens:** {e.tokens_in} in / {e.tokens_out} out | ${e.cost:.6f}")
            if e.provider:
                lines.append(f"\n**Provider:** {e.provider}/{e.model}")
            lines.append("")

        result = "\n".join(lines)
        if path:
            Path(path).write_text(result, "utf-8")
        return result

    def export_all(self, output_dir: str | Path = ".agent-trace-export") -> Path:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        traces = self.collector.list_traces(limit=100)

        with open(out / "summary.json", "w") as f:
            json.dump(self.collector.stats(), f, indent=2)

        md_lines = ["# Agent Trace Export", "", f"Exported {len(traces)} traces", "", "| Trace ID | Task | Duration | LLM | Tools | Cost | Status |", "|---|---|---|---|---|---|---|"]
        for t in traces:
            dur = self._fmt_duration(t.duration)
            task = t.task[:60]
            md_lines.append(f"| {t.trace_id} | {task} | {dur} | {t.total_llm_calls} | {t.total_tool_calls} | ${t.total_cost:.4f} | {t.status} |")
        (out / "index.md").write_text("\n".join(md_lines), "utf-8")

        traces_dir = out / "traces"
        traces_dir.mkdir(exist_ok=True)
        for t in traces[:20]:
            md = self.to_markdown(t.trace_id)
            (traces_dir / f"{t.trace_id}.md").write_text(md, "utf-8")

        chrome = self.to_chrome_trace_all(str(out / "chrome-trace.json"))
        return out

    @staticmethod
    def _icon(event_type: EventType) -> str:
        return {
            EventType.TASK_START: "\u25b6",
            EventType.TASK_END: "\u25a0",
            EventType.LLM_CALL: "\u2728",
            EventType.TOOL_CALL: "\u2699",
            EventType.THINKING: "\u25b3",
            EventType.ERROR: "\u2716",
            EventType.REFLECTION: "\u21c9",
            EventType.MEMORY: "\u2601",
            EventType.DECISION: "\u25c6",
        }.get(event_type, "\u2022")

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        if seconds < 1:
            return f"{seconds * 1000:.0f}ms"
        return f"{seconds:.1f}s"
