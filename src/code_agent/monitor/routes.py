from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from code_agent.monitor.collector import MetricsCollector, MetricPoint
from code_agent.monitor.alerts import AlertManager, AlertRule, AlertCondition


_collector: MetricsCollector | None = None
_alert_mgr: AlertManager | None = None


def get_collector() -> MetricsCollector:
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector


def get_alert_mgr() -> AlertManager:
    global _alert_mgr
    if _alert_mgr is None:
        _alert_mgr = AlertManager()
    return _alert_mgr


def register_monitor_routes(app, prefix: str = "/api/monitor"):
    router = APIRouter(prefix=prefix)
    collector = get_collector()
    alerts = get_alert_mgr()

    # ── Metrics ──────────────────────────────────────────────────────────────

    @router.post("/metrics")
    async def record_metric(body: dict):
        name = body.get("name", "")
        if not name:
            raise HTTPException(400, "name is required")
        value = float(body.get("value", 1.0))
        metric_type = body.get("type", "counter")
        labels = {k: str(v) for k, v in body.get("labels", {}).items()}

        if metric_type == "gauge":
            collector.gauge(name, value, **labels)
        elif metric_type == "histogram":
            collector.observe(name, value, **labels)
        else:
            collector.increment(name, value, **labels)

        return {"name": name, "value": value, "type": metric_type, "recorded": True}

    @router.post("/metrics/batch")
    async def record_metrics_batch(body: dict):
        points = body.get("metrics", [])
        count = 0
        for p in points:
            name = p.get("name", "")
            if not name:
                continue
            value = float(p.get("value", 1.0))
            labels = {k: str(v) for k, v in p.get("labels", {}).items()}
            metric_type = p.get("type", "counter")
            if metric_type == "gauge":
                collector.gauge(name, value, **labels)
            elif metric_type == "histogram":
                collector.observe(name, value, **labels)
            else:
                collector.increment(name, value, **labels)
            count += 1
        return {"recorded": count}

    @router.get("/metrics")
    async def list_metrics():
        metrics = collector.list_metrics()
        return {"metrics": metrics, "count": len(metrics)}

    @router.get("/metrics/{name}")
    async def query_metric(name: str, since: float = 0, limit: int = 100):
        points = collector.query(name, since=since, limit=limit)
        agg = collector.aggregate(name)
        return {
            "name": name,
            "aggregate": agg,
            "points": [
                {
                    "timestamp": p.timestamp,
                    "value": p.value,
                    "type": p.metric_type,
                    "labels": p.labels,
                }
                for p in points
            ],
            "count": len(points),
        }

    @router.get("/metrics/{name}/aggregate")
    async def get_metric_aggregate(name: str):
        agg = collector.aggregate(name)
        return {"name": name, **agg}

    @router.get("/summary")
    async def get_summary():
        s = collector.summary()
        metrics = collector.list_metrics()
        return {
            **s,
            "top_metrics": metrics[:10],
        }

    @router.post("/prune")
    async def prune_metrics(body: dict):
        older_than = body.get("older_than_seconds", 86400)
        cutoff = time.time() - float(older_than)
        deleted = collector.prune(cutoff)
        return {"deleted": deleted, "cutoff": cutoff}

    # ── Alerts ───────────────────────────────────────────────────────────────

    @router.post("/alerts/rules")
    async def add_alert_rule(body: dict):
        name = body.get("name", "")
        metric_name = body.get("metric_name", "")
        if not name or not metric_name:
            raise HTTPException(400, "name and metric_name are required")
        condition_str = body.get("condition", "gt")
        try:
            condition = AlertCondition(condition_str)
        except ValueError:
            raise HTTPException(400, f"Invalid condition: {condition_str}. Valid: gt, lt, gte, lte")
        rule = AlertRule(
            name=name,
            metric_name=metric_name,
            condition=condition,
            threshold=float(body.get("threshold", 0)),
            cooldown_seconds=float(body.get("cooldown_seconds", 300)),
            channels=body.get("channels", ["log"]),
            enabled=body.get("enabled", True),
        )
        alerts.add_rule(rule)
        return {"name": rule.name, "status": "created"}

    @router.get("/alerts/rules")
    async def list_alert_rules():
        rules = alerts.list_rules()
        return {
            "rules": [
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
            ],
            "count": len(rules),
        }

    @router.delete("/alerts/rules/{name}")
    async def delete_alert_rule(name: str):
        ok = alerts.remove_rule(name)
        if not ok:
            raise HTTPException(404, "Rule not found")
        return {"name": name, "status": "deleted"}

    @router.post("/alerts/check")
    async def check_alerts():
        fired = alerts.check(collector)
        return {
            "fired": [
                {
                    "rule_name": e.rule_name,
                    "state": e.state.value,
                    "metric_value": e.metric_value,
                    "threshold": e.threshold,
                    "message": e.message,
                    "timestamp": e.timestamp,
                }
                for e in fired
            ],
            "count": len(fired),
        }

    @router.get("/alerts/history")
    async def get_alert_history(rule_name: str | None = None, limit: int = 100):
        history = alerts.get_history(rule_name=rule_name, limit=limit)
        return {
            "events": [
                {
                    "rule_name": e.rule_name,
                    "state": e.state.value,
                    "metric_value": e.metric_value,
                    "threshold": e.threshold,
                    "message": e.message,
                    "timestamp": e.timestamp,
                }
                for e in history
            ],
            "count": len(history),
        }

    app.include_router(router)
