import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from orchestra.code_agent.telemetry.routes import register_telemetry_routes
from orchestra.code_agent.telemetry.tracer import AgentTracer


@pytest.fixture(autouse=True)
def reset_tracer():
    tracer = AgentTracer.get()
    tracer._contexts.clear()
    yield
    tracer._contexts.clear()


@pytest.fixture
def app():
    a = FastAPI()
    register_telemetry_routes(a)
    return a


@pytest.fixture
def client(app):
    return TestClient(app)


class TestTraceLifecycle:
    def test_start_trace(self, client):
        r = client.post("/api/telemetry/traces")
        assert r.status_code == 200
        data = r.json()
        assert "trace_id" in data
        assert len(data["trace_id"]) > 0

    def test_get_trace(self, client):
        r = client.post("/api/telemetry/traces")
        trace_id = r.json()["trace_id"]
        r2 = client.get(f"/api/telemetry/traces/{trace_id}")
        assert r2.status_code == 200
        data = r2.json()
        assert data["trace_id"] == trace_id
        assert "spans" in data

    def test_get_nonexistent_trace(self, client):
        r = client.get("/api/telemetry/traces/nonexistent")
        assert r.status_code == 404

    def test_list_traces(self, client):
        client.post("/api/telemetry/traces")
        client.post("/api/telemetry/traces")
        r = client.get("/api/telemetry/traces")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 2
        assert "traces" in data

    def test_delete_trace(self, client):
        r = client.post("/api/telemetry/traces")
        trace_id = r.json()["trace_id"]
        r2 = client.delete(f"/api/telemetry/traces/{trace_id}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "deleted"
        r3 = client.get(f"/api/telemetry/traces/{trace_id}")
        assert r3.status_code == 404

    def test_delete_nonexistent_trace(self, client):
        r = client.delete("/api/telemetry/traces/ghost")
        assert r.status_code == 404


class TestSpanLifecycle:
    def test_start_span(self, client):
        trace_id = client.post("/api/telemetry/traces").json()["trace_id"]
        r = client.post(f"/api/telemetry/traces/{trace_id}/spans", json={"name": "my-span"})
        assert r.status_code == 200
        data = r.json()
        assert "span_id" in data
        assert data["trace_id"] == trace_id

    def test_start_span_missing_name(self, client):
        trace_id = client.post("/api/telemetry/traces").json()["trace_id"]
        r = client.post(f"/api/telemetry/traces/{trace_id}/spans", json={})
        assert r.status_code == 400

    def test_start_span_nonexistent_trace(self, client):
        r = client.post("/api/telemetry/traces/ghost/spans", json={"name": "s"})
        assert r.status_code == 404

    def test_end_span(self, client):
        trace_id = client.post("/api/telemetry/traces").json()["trace_id"]
        span_id = client.post(f"/api/telemetry/traces/{trace_id}/spans", json={"name": "s1"}).json()["span_id"]
        r = client.put(f"/api/telemetry/traces/{trace_id}/spans/{span_id}", json={"status": "ok"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_end_span_error_status(self, client):
        trace_id = client.post("/api/telemetry/traces").json()["trace_id"]
        span_id = client.post(f"/api/telemetry/traces/{trace_id}/spans", json={"name": "fail-span"}).json()["span_id"]
        r = client.put(f"/api/telemetry/traces/{trace_id}/spans/{span_id}", json={"status": "error"})
        assert r.status_code == 200
        assert r.json()["status"] == "error"

    def test_end_span_nonexistent_trace(self, client):
        r = client.put("/api/telemetry/traces/ghost/spans/s1", json={})
        assert r.status_code == 404

    def test_span_with_attributes(self, client):
        trace_id = client.post("/api/telemetry/traces").json()["trace_id"]
        r = client.post(f"/api/telemetry/traces/{trace_id}/spans", json={
            "name": "llm.call",
            "attributes": {"model": "kimi-k2.5", "tokens": 512},
        })
        assert r.status_code == 200

    def test_nested_spans(self, client):
        trace_id = client.post("/api/telemetry/traces").json()["trace_id"]
        parent_id = client.post(f"/api/telemetry/traces/{trace_id}/spans", json={"name": "parent"}).json()["span_id"]
        r = client.post(f"/api/telemetry/traces/{trace_id}/spans", json={"name": "child", "parent_id": parent_id})
        assert r.status_code == 200

    def test_trace_summary_after_spans(self, client):
        trace_id = client.post("/api/telemetry/traces").json()["trace_id"]
        span_id = client.post(f"/api/telemetry/traces/{trace_id}/spans", json={"name": "s"}).json()["span_id"]
        client.put(f"/api/telemetry/traces/{trace_id}/spans/{span_id}", json={"status": "ok"})
        r = client.get(f"/api/telemetry/traces/{trace_id}/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["trace_id"] == trace_id
        assert "total_duration_ms" in data
        assert "spans" in data

    def test_trace_detail_shows_spans(self, client):
        trace_id = client.post("/api/telemetry/traces").json()["trace_id"]
        client.post(f"/api/telemetry/traces/{trace_id}/spans", json={"name": "span-a"})
        client.post(f"/api/telemetry/traces/{trace_id}/spans", json={"name": "span-b"})
        r = client.get(f"/api/telemetry/traces/{trace_id}")
        assert r.status_code == 200
        data = r.json()
        assert len(data["spans"]) == 2
        span_names = [s["name"] for s in data["spans"]]
        assert "span-a" in span_names
        assert "span-b" in span_names


class TestTelemetryHealth:
    def test_health(self, client):
        r = client.get("/api/telemetry/health")
        assert r.status_code == 200
        data = r.json()
        assert "active_traces" in data
        assert "output_path" in data
        assert "output_exists" in data
