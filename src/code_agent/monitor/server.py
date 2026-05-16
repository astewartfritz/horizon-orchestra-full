from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import click
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from code_agent.cost.tracker import CostTracker
from code_agent.monitor.alerts import AlertCondition, AlertEvent, AlertManager, AlertRule
from code_agent.monitor.collector import MetricsCollector
from code_agent.monitor.prometheus import PrometheusExporter


MONITOR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Code Agent Monitor</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; background: #0d1117; color: #c9d1d9; }
  h1 { color: #58a6ff; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1rem; margin: 0.5rem 0; }
  .card h3 { margin: 0 0 0.5rem 0; color: #58a6ff; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 0.3rem 0.5rem; border-bottom: 1px solid #30363d; }
  th { color: #8b949e; font-size: 0.8rem; text-transform: uppercase; }
  .ok { color: #3fb950; }
  .warn { color: #d29922; }
  .crit { color: #f85149; }
  .metric-value { font-size: 1.5rem; font-weight: bold; color: #58a6ff; }
  .metric-label { font-size: 0.75rem; color: #8b949e; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }
  .stat { text-align: center; padding: 1rem; background: #161b22; border-radius: 8px; border: 1px solid #30363d; }
</style>
</head>
<body>
<h1>Code Agent Monitor</h1>
<div id="status">Connecting...</div>
<div class="grid" id="summary"></div>
<h2>Metrics</h2>
<div class="card"><table><thead><tr><th>Metric</th><th>Type</th><th>Last</th><th>Avg</th><th>Max</th><th>Count</th></tr></thead><tbody id="metrics-body"></tbody></table></div>
<h2>Alerts</h2>
<div class="card"><table><thead><tr><th>Rule</th><th>State</th><th>Value</th><th>Threshold</th><th>Time</th></tr></thead><tbody id="alerts-body"></tbody></table></div>
<script>
  const evt = new EventSource('/stream');
  evt.onmessage = (e) => {
    const data = JSON.parse(e.data);
    document.getElementById('status').textContent = 'Last update: ' + new Date(data.timestamp * 1000).toLocaleTimeString();

    // Summary grid
    const summary = data.summary;
    document.getElementById('summary').innerHTML = Object.entries(summary).map(([k,v]) =>
      `<div class="stat"><div class="metric-value">${v}</div><div class="metric-label">${k}</div></div>`
    ).join('');

    // Metrics table
    const metrics = data.metrics;
    document.getElementById('metrics-body').innerHTML = metrics.map(m =>
      `<tr><td>${m.name}</td><td>${m.type}</td><td>${m.last.toFixed(2)}</td><td>${m.avg.toFixed(2)}</td><td>${m.max.toFixed(2)}</td><td>${m.count}</td></tr>`
    ).join('');

    // Alerts table
    const alerts = data.alerts || [];
    document.getElementById('alerts-body').innerHTML = alerts.map(a =>
      `<tr><td>${a.rule_name}</td><td class="${a.state}">${a.state}</td><td>${a.metric_value.toFixed(2)}</td><td>${a.threshold.toFixed(2)}</td><td>${new Date(a.timestamp*1000).toLocaleTimeString()}</td></tr>`
    ).join('');
  };
  evt.onerror = () => document.getElementById('status').textContent = 'Disconnected';
</script>
</body>
</html>"""


class MonitorServer:
    def __init__(self, collector: MetricsCollector | None = None, alert_mgr: AlertManager | None = None):
        self.collector = collector or MetricsCollector()
        self.alert_mgr = alert_mgr or AlertManager()
        self.cost = CostTracker()
        self.prometheus = PrometheusExporter(self.collector)
        self._subscribers: list[asyncio.Queue] = []
        self._last_broadcast = 0.0

    def _collect_snapshot(self) -> dict[str, Any]:
        metrics = self.collector.list_metrics()
        alerts = self.alert_mgr.get_history(limit=20)
        try:
            cost_str = self.cost.summary()
        except Exception:
            cost_str = "N/A"
        s = self.collector.summary()
        return {
            "timestamp": time.time(),
            "summary": {
                "points": s["total_points"],
                "metrics": s["total_metrics"],
                "session_points": s["session_points"],
            },
            "metrics": metrics,
            "alerts": [asdict(a) for a in alerts],
            "cost": cost_str,
        }

    def _broadcast(self) -> None:
        data = self._collect_snapshot()
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def build_app(self) -> FastAPI:
        app = FastAPI(title="Code Agent Monitor")

        @app.get("/")
        async def root():
            return HTMLResponse(MONITOR_HTML)

        @app.get("/metrics")
        async def prometheus_metrics():
            return PlainTextResponse(
                self.prometheus.generate(),
                media_type=self.prometheus.content_type(),
            )

        @app.get("/health")
        async def health():
            return {
                "status": "ok",
                "timestamp": time.time(),
                "metrics": self.collector.summary(),
            }

        @app.get("/stats")
        async def stats():
            return self._collect_snapshot()

        @app.get("/stream")
        async def stream(request: Request):
            q: asyncio.Queue = asyncio.Queue(maxsize=50)
            self._subscribers.append(q)

            async def event_generator():
                try:
                    while True:
                        if await request.is_disconnected():
                            break
                        data = await asyncio.wait_for(q.get(), timeout=30)
                        yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'keepalive': True})}\n\n"
                except Exception:
                    pass
                finally:
                    if q in self._subscribers:
                        self._subscribers.remove(q)

            from fastapi.responses import StreamingResponse
            return StreamingResponse(event_generator(), media_type="text/event-stream")

        @app.post("/alerts")
        async def create_alert(rule: dict[str, Any]):
            required = ["name", "metric_name", "condition", "threshold"]
            for r in required:
                if r not in rule:
                    raise HTTPException(400, f"Missing required field: {r}")
            if rule["condition"] not in ("gt", "lt", "gte", "lte"):
                raise HTTPException(400, f"Invalid condition: {rule['condition']}")
            alert_rule = AlertRule(
                name=rule["name"],
                metric_name=rule["metric_name"],
                condition=AlertCondition(rule["condition"]),
                threshold=rule["threshold"],
                cooldown_seconds=rule.get("cooldown_seconds", 300),
                channels=rule.get("channels", ["log"]),
                enabled=rule.get("enabled", True),
            )
            self.alert_mgr.add_rule(alert_rule)
            return {"status": "created", "rule": rule["name"]}

        @app.get("/alerts")
        async def list_alerts():
            rules = self.alert_mgr.list_rules()
            return [
                {
                    "name": r.name,
                    "metric_name": r.metric_name,
                    "condition": r.condition.value,
                    "threshold": r.threshold,
                    "cooldown_seconds": r.cooldown_seconds,
                    "channels": r.channels,
                    "enabled": r.enabled,
                }
                for r in rules
            ]

        @app.delete("/alerts/{name}")
        async def delete_alert(name: str):
            if self.alert_mgr.remove_rule(name):
                return {"status": "deleted"}
            raise HTTPException(404, f"Alert rule not found: {name}")

        return app

    def run(self, host: str = "127.0.0.1", port: int = 9090) -> None:
        import uvicorn
        app = self.build_app()

        async def broadcast_loop():
            while True:
                self._broadcast()
                await asyncio.sleep(5)

        @app.on_event("startup")
        async def startup():
            asyncio.create_task(broadcast_loop())

        click.echo(f"Monitor: http://{host}:{port}")
        click.echo(f"Metrics: http://{host}:{port}/metrics")
        click.echo(f"Stream:  http://{host}:{port}/stream")
        uvicorn.run(app, host=host, port=port)
