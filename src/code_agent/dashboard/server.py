from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import click

from code_agent.cost.tracker import CostTracker
from code_agent.knowledge.base import KnowledgeBase


@dataclass
class DashboardData:
    sessions: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    tool_calls: int = 0
    knowledge_entries: int = 0
    cache_hits: int = 0
    uptime_seconds: float = 0.0
    recent_logs: list[str] = field(default_factory=list)


class DashboardServer:
    def __init__(self):
        self._start_time = time.time()
        self._data = DashboardData()

    def refresh(self) -> DashboardData:
        try:
            logger = AgentLogger.get()
            stats = logger.stats()
            self._data.recent_logs = [f"[{e.level}] {e.module}: {e.message[:80]}" for e in logger.recent(10)]
        except Exception:
            pass

        try:
            kb = KnowledgeBase()
            kstats = kb.stats()
            self._data.knowledge_entries = kstats.get("entries", 0)
        except Exception:
            pass

        try:
            tracker = CostTracker()
            summary = tracker.summary()
            self._data.total_cost = summary.get("total_cost", 0)
            self._data.total_tokens = summary.get("total_tokens", 0)
        except Exception:
            pass

        self._data.uptime_seconds = time.time() - self._start_time

        return self._data

    def get_html(self) -> str:
        d = self.refresh()
        uptime_m = int(d.uptime_seconds / 60)
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Code Agent Dashboard</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0d1117; color: #c9d1d9; }}
h1 {{ color: #58a6ff; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; margin: 1rem 0; }}
.metric {{ display: inline-block; margin: 1rem 2rem 1rem 0; }}
.metric .value {{ font-size: 2rem; font-weight: bold; color: #58a6ff; }}
.metric .label {{ font-size: 0.8rem; color: #8b949e; }}
.log {{ font-family: monospace; font-size: 0.85rem; color: #8b949e; margin: 0.25rem 0; }}
</style></head><body>
<h1>Code Agent Dashboard</h1>
<div class="card">
<div class="metric"><div class="value">{d.sessions}</div><div class="label">Sessions</div></div>
<div class="metric"><div class="value">{d.total_tokens:,}</div><div class="label">Total Tokens</div></div>
<div class="metric"><div class="value">${d.total_cost:.4f}</div><div class="label">Total Cost</div></div>
<div class="metric"><div class="value">{d.tool_calls}</div><div class="label">Tool Calls</div></div>
<div class="metric"><div class="value">{d.knowledge_entries}</div><div class="label">Knowledge Entries</div></div>
<div class="metric"><div class="value">{uptime_m}m</div><div class="label">Uptime</div></div>
</div>
<div class="card"><h3>Recent Activity</h3>
{"".join(f'<div class="log">{log}</div>' for log in d.recent_logs)}
</div></body></html>"""

    async def run_server(self, host: str = "127.0.0.1", port: int = 9090) -> None:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse
        import uvicorn

        app = FastAPI(title="Code Agent Dashboard")

        @app.get("/")
        async def root():
            return HTMLResponse(self.get_html())

        @app.get("/api/metrics")
        async def api_metrics():
            d = self.refresh()
            return {
                "sessions": d.sessions,
                "total_tokens": d.total_tokens,
                "total_cost": d.total_cost,
                "tool_calls": d.tool_calls,
                "knowledge_entries": d.knowledge_entries,
                "uptime_seconds": d.uptime_seconds,
            }

        click.echo(f"Dashboard: http://{host}:{port}")
        uvicorn.run(app, host=host, port=port)
