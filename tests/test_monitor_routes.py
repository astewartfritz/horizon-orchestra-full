import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from orchestra.code_agent.monitor.routes import register_monitor_routes
from orchestra.code_agent.monitor.collector import MetricsCollector
from orchestra.code_agent.monitor.alerts import AlertManager


@pytest.fixture
def app(tmp_path):
    import orchestra.code_agent.monitor.routes as r
    db = str(tmp_path / "test.db")
    r._collector = MetricsCollector(db_path=db)
    r._alert_mgr = AlertManager(db_path=db)
    a = FastAPI()
    register_monitor_routes(a)
    yield a
    r._collector = None
    r._alert_mgr = None


@pytest.fixture
def client(app):
    return TestClient(app)


class TestMetricsEndpoints:
    def test_record_counter(self, client):
        r = client.post("/api/monitor/metrics", json={"name": "test.counter", "value": 1, "type": "counter"})
        assert r.status_code == 200
        data = r.json()
        assert data["recorded"] is True
        assert data["name"] == "test.counter"

    def test_record_gauge(self, client):
        r = client.post("/api/monitor/metrics", json={"name": "test.gauge", "value": 42.5, "type": "gauge"})
        assert r.status_code == 200

    def test_record_histogram(self, client):
        r = client.post("/api/monitor/metrics", json={"name": "test.hist", "value": 150.0, "type": "histogram"})
        assert r.status_code == 200

    def test_record_with_labels(self, client):
        r = client.post("/api/monitor/metrics", json={
            "name": "test.labeled", "value": 1, "type": "counter",
            "labels": {"service": "api", "region": "us-east"}
        })
        assert r.status_code == 200

    def test_missing_name_returns_400(self, client):
        r = client.post("/api/monitor/metrics", json={"value": 1})
        assert r.status_code == 400

    def test_list_metrics_after_record(self, client):
        client.post("/api/monitor/metrics", json={"name": "list.test", "value": 5})
        r = client.get("/api/monitor/metrics")
        assert r.status_code == 200
        data = r.json()
        assert "metrics" in data
        assert "count" in data
        names = [m["name"] for m in data["metrics"]]
        assert "list.test" in names

    def test_query_specific_metric(self, client):
        client.post("/api/monitor/metrics", json={"name": "query.me", "value": 99})
        r = client.get("/api/monitor/metrics/query.me")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "query.me"
        assert "aggregate" in data
        assert data["aggregate"]["count"] >= 1
        assert "points" in data

    def test_aggregate_endpoint(self, client):
        client.post("/api/monitor/metrics", json={"name": "agg.test", "value": 10})
        client.post("/api/monitor/metrics", json={"name": "agg.test", "value": 20})
        r = client.get("/api/monitor/metrics/agg.test/aggregate")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 2
        assert data["sum"] == 30
        assert data["min"] == 10
        assert data["max"] == 20
        assert data["avg"] == 15

    def test_batch_record(self, client):
        r = client.post("/api/monitor/metrics/batch", json={
            "metrics": [
                {"name": "batch.a", "value": 1},
                {"name": "batch.b", "value": 2, "type": "gauge"},
                {"name": "batch.c", "value": 3},
            ]
        })
        assert r.status_code == 200
        assert r.json()["recorded"] == 3

    def test_summary(self, client):
        client.post("/api/monitor/metrics", json={"name": "summary.test", "value": 1})
        r = client.get("/api/monitor/summary")
        assert r.status_code == 200
        data = r.json()
        assert "total_points" in data
        assert "total_metrics" in data

    def test_prune_metrics(self, client):
        r = client.post("/api/monitor/prune", json={"older_than_seconds": 0})
        assert r.status_code == 200
        assert "deleted" in r.json()


class TestAlertEndpoints:
    def test_add_alert_rule(self, client):
        r = client.post("/api/monitor/alerts/rules", json={
            "name": "high-cpu",
            "metric_name": "cpu.usage",
            "condition": "gt",
            "threshold": 90.0,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "high-cpu"
        assert data["status"] == "created"

    def test_add_rule_missing_fields(self, client):
        r = client.post("/api/monitor/alerts/rules", json={"name": "incomplete"})
        assert r.status_code == 400

    def test_add_rule_invalid_condition(self, client):
        r = client.post("/api/monitor/alerts/rules", json={
            "name": "bad-rule",
            "metric_name": "some.metric",
            "condition": "invalid",
            "threshold": 50.0,
        })
        assert r.status_code == 400

    def test_list_alert_rules(self, client):
        client.post("/api/monitor/alerts/rules", json={
            "name": "list-rule",
            "metric_name": "test.metric",
            "condition": "gt",
            "threshold": 100,
        })
        r = client.get("/api/monitor/alerts/rules")
        assert r.status_code == 200
        data = r.json()
        assert "rules" in data
        assert "count" in data
        names = [rule["name"] for rule in data["rules"]]
        assert "list-rule" in names

    def test_delete_alert_rule(self, client):
        client.post("/api/monitor/alerts/rules", json={
            "name": "del-me",
            "metric_name": "x",
            "condition": "gt",
            "threshold": 0,
        })
        r = client.delete("/api/monitor/alerts/rules/del-me")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

    def test_delete_nonexistent_rule(self, client):
        r = client.delete("/api/monitor/alerts/rules/ghost")
        assert r.status_code == 404

    def test_check_alerts_no_rules(self, client):
        r = client.post("/api/monitor/alerts/check")
        assert r.status_code == 200
        data = r.json()
        assert "fired" in data
        assert data["count"] == 0

    def test_check_alerts_fires(self, client):
        client.post("/api/monitor/metrics", json={"name": "fire.me", "value": 150})
        client.post("/api/monitor/alerts/rules", json={
            "name": "fire-rule",
            "metric_name": "fire.me",
            "condition": "gt",
            "threshold": 100,
            "cooldown_seconds": 0,
        })
        r = client.post("/api/monitor/alerts/check")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 1

    def test_alert_history(self, client):
        r = client.get("/api/monitor/alerts/history")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data

    def test_alert_conditions(self, client):
        for cond in ("gt", "lt", "gte", "lte"):
            r = client.post("/api/monitor/alerts/rules", json={
                "name": f"rule-{cond}",
                "metric_name": "x.metric",
                "condition": cond,
                "threshold": 50,
            })
            assert r.status_code == 200
