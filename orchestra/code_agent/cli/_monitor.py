"""CLI commands — monitor."""
from __future__ import annotations

import click

from ._core import main


@main.group()
def monitor():
    """Monitor agent metrics, alerts, and dashboards."""


@monitor.command("dashboard")
def monitor_dashboard():
    """Show ASCII metrics dashboard."""
    from orchestra.code_agent.monitor import MonitorDashboard
    dash = MonitorDashboard()
    safe_echo(dash.render())
    dash.close()


@monitor.command("metrics")
@click.option("--name", "-n", default="", help="Filter by metric name")
@click.option("--since", type=float, default=0, help="Show metrics since timestamp")
def monitor_metrics(name, since):
    """List collected metrics with aggregates."""
    from orchestra.code_agent.monitor import MetricsCollector
    collector = MetricsCollector()
    if name:
        pts = collector.query(name, since=since, limit=50)
        if not pts:
            safe_echo(f"No points for '{name}'")
            return
        agg = collector.aggregate(name)
        safe_echo(f"Metric: {name}")
        safe_echo(f"  Type:  {pts[0].metric_type if pts else '?'}")
        safe_echo(f"  Count: {agg['count']}")
        safe_echo(f"  Sum:   {agg['sum']:.2f}")
        safe_echo(f"  Avg:   {agg['avg']:.2f}")
        safe_echo(f"  Min:   {agg['min']:.2f}")
        safe_echo(f"  Max:   {agg['max']:.2f}")
        safe_echo(f"  Last:  {agg['last']:.2f}")
    else:
        metrics = collector.list_metrics()
        if not metrics:
            safe_echo("No metrics recorded.")
            return
        safe_echo(f"{'Metric':30} {'Type':12} {'Last':10} {'Avg':10} {'Max':10} {'Count':8}")
        safe_echo("-" * 80)
        for m in sorted(metrics, key=lambda x: x["name"]):
            safe_echo(f"{m['name']:30} {m['type']:12} {m['last']:<10.2f} {m['avg']:<10.2f} {m['max']:<10.2f} {m['count']:<8}")
    collector.close()


@monitor.command("alerts")
@click.option("--history", is_flag=True, help="Show alert history")
def monitor_alerts(history):
    """List alert rules or show alert history."""
    from orchestra.code_agent.monitor import AlertManager
    mgr = AlertManager()
    if history:
        events = mgr.get_history(limit=50)
        if not events:
            safe_echo("No alert events.")
            return
        for ev in events:
            safe_echo(f"  [{ev.state.value:8}] {ev.message} @ {time.strftime('%H:%M:%S', time.localtime(ev.timestamp))}")
    else:
        rules = mgr.list_rules()
        if not rules:
            safe_echo("No alert rules defined.")
            safe_echo("Use 'code-agent monitor alert-add' to create one.")
            return
        safe_echo(f"{'Name':25} {'Metric':25} {'Condition':10} {'Threshold':10} {'Cooldown':10} {'Enabled':8}")
        safe_echo("-" * 90)
        for r in rules:
            safe_echo(f"{r.name:25} {r.metric_name:25} {r.condition.value:10} {r.threshold:<10.2f} {r.cooldown_seconds:<10.0f} {'Yes' if r.enabled else 'No':8}")


@monitor.command("alert-add")
@click.argument("name")
@click.argument("metric_name")
@click.argument("condition", type=click.Choice(["gt", "lt", "gte", "lte"]))
@click.argument("threshold", type=float)
@click.option("--cooldown", default=300, type=float, help="Cooldown in seconds")
def monitor_alert_add(name, metric_name, condition, threshold, cooldown):
    """Add an alert rule. Condition: gt/lt/gte/lte."""
    from orchestra.code_agent.monitor import AlertManager, AlertRule, AlertCondition
    mgr = AlertManager()
    rule = AlertRule(
        name=name,
        metric_name=metric_name,
        condition=AlertCondition(condition),
        threshold=threshold,
        cooldown_seconds=cooldown,
    )
    mgr.add_rule(rule)
    safe_echo(f"Alert rule added: {name}")


@monitor.command("alert-remove")
@click.argument("name")
def monitor_alert_remove(name):
    """Remove an alert rule."""
    from orchestra.code_agent.monitor import AlertManager
    mgr = AlertManager()
    if mgr.remove_rule(name):
        safe_echo(f"Removed alert rule: {name}")
    else:
        safe_echo(f"Alert rule not found: {name}")


@monitor.command("server")
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind")
@click.option("-p", "--port", default=9090, type=int, help="Port to bind")
def monitor_server(host, port):
    """Start the monitoring web server (dashboard + Prometheus + SSE)."""
    from orchestra.code_agent.monitor import MonitorServer
    server = MonitorServer()
    server.run(host=host, port=port)


@monitor.command("prometheus")
@click.option("-p", "--port", default=9091, type=int, help="Prometheus metrics port")
@click.option("--interval", default=5, type=int, help="Sync interval in seconds")
def monitor_prometheus(port, interval):
    """Start a standalone Prometheus HTTP metrics server."""
    from orchestra.code_agent.monitor import MetricsCollector
    from orchestra.code_agent.monitor.prometheus import PrometheusExporter
    import time
    collector = MetricsCollector()
    exporter = PrometheusExporter(collector)
    from prometheus_client import start_http_server
    start_http_server(port)
    safe_echo(f"Prometheus metrics: http://127.0.0.1:{port}/metrics")
    try:
        while True:
            time.sleep(interval)
            exporter.generate()
    except KeyboardInterrupt:
        safe_echo("Stopped")


@monitor.command("prune")
@click.option("--older-than", default=86400, type=int, help="Prune metrics older than N seconds (default 24h)")
def monitor_prune(older_than):
    """Prune old metrics from the database."""
    from orchestra.code_agent.monitor import MetricsCollector
    import time
    collector = MetricsCollector()
    cutoff = time.time() - older_than
    deleted = collector.prune(cutoff)
    safe_echo(f"Pruned {deleted} metric points older than {older_than}s")
    collector.close()


