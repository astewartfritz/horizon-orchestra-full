from __future__ import annotations

import time
from typing import Any

from code_agent.trace.collector import AgentTrace, EventType, TraceCollector, TraceEvent


class TraceViewer:
    def __init__(self, collector: TraceCollector | None = None):
        self.collector = collector or TraceCollector()

    def list_traces(self, limit: int = 20) -> str:
        traces = self.collector.list_traces(limit=limit)
        if not traces:
            return "No traces found."
        lines = [
            f"{'Trace ID':14} {'Task':40} {'Duration':10} {'LLM':6} {'Tools':6} {'Errors':7} {'Cost':10} {'Status':10}",
            "-" * 103,
        ]
        for t in traces:
            dur = self._fmt_duration(t.duration)
            task = t.task[:38] + ".." if len(t.task) > 38 else t.task
            lines.append(
                f"{t.trace_id:14} {task:40} {dur:>10} {t.total_llm_calls:>4} "
                f"{t.total_tool_calls:>4} {t.total_errors:>5} ${t.total_cost:<7.4f} {t.status:10}"
            )
        return "\n".join(lines)

    def show_trace(self, trace_id: str) -> str:
        trace = self.collector.get_trace(trace_id)
        if not trace:
            events = self.collector.get_events(trace_id)
            if not events:
                return f"Trace not found: {trace_id}"
        else:
            events = trace.events

        lines = [
            f"Trace: {trace_id}",
            f"Task:  {trace.task[:100] if trace else '(from db)'}",
            f"Duration: {self._fmt_duration((trace.duration if trace else 0))}",
            f"Status: {trace.status if trace else 'completed'}",
            f"Events: {len(events)}",
            "",
            "Timeline:",
            "-" * 80,
        ]

        start_time = events[0].timestamp if events else time.time()
        indent_map: dict[str, int] = {}
        for e in events:
            depth = 0
            if e.parent_id:
                depth = indent_map.get(e.parent_id, 0) + 1
            indent_map[e.event_id] = depth
            indent = "  " * depth
            offset = (e.timestamp - start_time) * 1000
            icon = self._icon(e.event_type)
            dur = f"{e.duration_ms:>7.1f}ms" if e.duration_ms > 0 else "       -"
            status = self._status_str(e.status)
            name = e.name[:40]
            lines.append(f"  {offset:>8.0f}ms {dur} {icon} {indent}{name:40} {status}")

        lines.extend([
            "",
            "Details:",
            "-" * 80,
        ])
        for e in events:
            if e.input or e.output:
                lines.append(f"  [{e.event_id[:6]}] {e.name}")
                if e.input:
                    lines.append(f"    In:  {e.input[:100]}")
                if e.output:
                    lines.append(f"    Out: {e.output[:100]}")
                if e.error:
                    lines.append(f"    Err: {e.error[:100]}")

        return "\n".join(lines)

    def waterfall(self, trace_id: str, max_events: int = 100) -> str:
        events = self.collector.get_events(trace_id)
        if not events:
            return f"No events for trace: {trace_id}"
        events = events[:max_events]
        if not events:
            return ""

        start = events[0].timestamp
        max_offset = max((e.timestamp - start) * 1000 + max(e.duration_ms, 10) for e in events)
        scale = 50 / max_offset if max_offset > 0 else 1

        lines = [f"Waterfall: {trace_id}  ({max_offset:.0f}ms total)", ""]
        indent_map: dict[str, int] = {}
        for e in events:
            depth = 0
            if e.parent_id:
                depth = indent_map.get(e.parent_id, 0) + 1
            indent_map[e.event_id] = depth
            offset = (e.timestamp - start) * 1000
            bar_start = int(offset * scale)
            bar_width = max(1, int(max(e.duration_ms, 5) * scale))
            bar = "█" * bar_width
            indent = "  " * depth
            icon = self._icon(e.event_type)
            name = e.name[:30]
            label = f"{offset:>8.0f}ms [{icon}] {indent}{name}"
            timeline = " " * bar_start + bar
            lines.append(f"{label:55} |{timeline}")

        return "\n".join(lines)

    def search(self, query: str, limit: int = 50) -> str:
        results = self.collector.search_events(query, limit=limit)
        if not results:
            return f"No events matching: {query}"
        lines = [f"Found {len(results)} events for '{query}':", ""]
        for e in results[:limit]:
            icon = self._icon(e.event_type)
            lines.append(f"  [{e.trace_id[:8]}] {icon} {e.name:35} {e.input[:80]}")
        return "\n".join(lines)

    def summary(self) -> str:
        stats = self.collector.stats()
        lines = [
            "Trace Collection Summary",
            "=" * 40,
            f"Total traces:     {stats['total_traces']}",
            f"Total events:     {stats['total_events']}",
            f"LLM calls:        {stats['total_llm_calls']}",
            f"Tool calls:       {stats['total_tool_calls']}",
            f"Errors:           {stats['total_errors']}",
            f"Total cost:       ${stats['total_cost']:.4f}",
            f"Tokens (in/out):  {stats['total_tokens_in']} / {stats['total_tokens_out']}",
            "",
            "Events by type:",
        ]
        for etype, count in sorted(stats.get("events_by_type", {}).items()):
            lines.append(f"  {etype:20} {count}")
        return "\n".join(lines)

    @staticmethod
    def _icon(event_type: EventType) -> str:
        return {
            EventType.TASK_START: "\u25b6",
            EventType.TASK_END: "\u25a0",
            EventType.LLM_CALL: "\u2728",
            EventType.LLM_RESPONSE: "\u2728",
            EventType.TOOL_CALL: "\u2699",
            EventType.TOOL_RESULT: "\u2699",
            EventType.THINKING: "\u25b3",
            EventType.ERROR: "\u2716",
            EventType.REFLECTION: "\u21c9",
            EventType.MEMORY: "\u2601",
            EventType.DECISION: "\u25c6",
        }.get(event_type, "\u2022")

    @staticmethod
    def _status_str(status: str) -> str:
        if status == "ok":
            return ""
        if status == "error":
            return "\u2716 ERROR"
        return status

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        if seconds < 1:
            return f"{seconds * 1000:.0f}ms"
        if seconds < 60:
            return f"{seconds:.1f}s"
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s}s"
