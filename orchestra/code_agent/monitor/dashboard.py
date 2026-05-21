from __future__ import annotations

import time
from typing import Any

from orchestra.code_agent.cost.tracker import CostTracker
from orchestra.code_agent.monitor.collector import MetricsCollector


class MonitorDashboard:
    """Rich ASCII dashboard for real-time agent monitoring."""

    def __init__(self, collector: MetricsCollector | None = None):
        self.metrics = collector or MetricsCollector()
        self.cost = CostTracker()
        self._last_refresh = 0.0

    def _section_header(self, title: str) -> str:
        return f"\n{'=' * 50}\n  {title}\n{'-' * 50}"

    def _format_value(self, val: float, unit: str = "", threshold_ok: float = 0) -> str:
        if threshold_ok and val > threshold_ok:
            return f"[WARN] {val:.1f}{unit}"
        return f"{val:.1f}{unit}"

    def _bar(self, pct: float, width: int = 30) -> str:
        filled = int(pct * width)
        filled = max(0, min(width, filled))
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {pct * 100:.0f}%"

    def render_overview(self) -> str:
        s = self.metrics.summary()
        return (
            f"  Session:       {s['session_id']}\n"
            f"  Total points:  {s['total_points']:,}\n"
            f"  Session points: {s['session_points']:,}\n"
            f"  Unique metrics: {s['total_metrics']}"
        )

    def render_cost(self) -> str:
        try:
            c = self.cost.summary()
            return f"  {c}"
        except Exception:
            return "  (cost tracker unavailable)"

    def render_metrics_table(self) -> str:
        metrics = self.metrics.list_metrics()
        if not metrics:
            return "  (no metrics recorded)"
        lines = [f"  {'Metric':30} {'Type':12} {'Avg':10} {'Last':10} {'Max':10} {'Count':8}"]
        lines.append("  " + "-" * 80)
        for m in sorted(metrics, key=lambda x: x["name"]):
            lines.append(
                f"  {m['name']:30} {m['type']:12} {m['avg']:<10.2f} {m['last']:<10.2f} {m['max']:<10.2f} {m['count']:<8}"
            )
        return "\n".join(lines)

    def render(self) -> str:
        parts = [
            f"\n{'=' * 50}",
            "  CODE AGENT MONITOR DASHBOARD",
            f"  {time.strftime('%Y-%m-%d %H:%M:%S')}",
            self._section_header("Overview"),
            self.render_overview(),
            self._section_header("Cost"),
            self.render_cost(),
            self._section_header("Metrics"),
            self.render_metrics_table(),
            "\n" + "=" * 50,
        ]
        return "\n".join(parts)

    def close(self) -> None:
        self.metrics.close()
