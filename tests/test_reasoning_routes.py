import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from code_agent.reasoning.routes import register_reasoning_routes


@pytest.fixture
def app():
    a = FastAPI()
    register_reasoning_routes(a)
    return a


@pytest.fixture
def client(app):
    return TestClient(app)


class TestStrategiesEndpoint:
    def test_list_strategies(self, client):
        r = client.get("/api/reasoning/strategies")
        assert r.status_code == 200
        data = r.json()
        assert "strategies" in data
        assert data["count"] >= 5
        keys = {s["key"] for s in data["strategies"]}
        assert "cot" in keys
        assert "plan" in keys
        assert "tot" in keys
        assert "reflect" in keys

    def test_get_strategy_cot(self, client):
        r = client.get("/api/reasoning/strategies/cot")
        assert r.status_code == 200
        data = r.json()
        assert data["key"] == "cot"
        assert "system_prompt" in data
        assert len(data["system_prompt"]) > 20

    def test_get_strategy_plan(self, client):
        r = client.get("/api/reasoning/strategies/plan")
        assert r.status_code == 200
        data = r.json()
        assert data["key"] == "plan"

    def test_get_strategy_not_found(self, client):
        r = client.get("/api/reasoning/strategies/nonexistent")
        assert r.status_code == 404

    def test_get_strategy_auto(self, client):
        r = client.get("/api/reasoning/strategies/auto")
        assert r.status_code == 200


class TestSelectStrategy:
    def test_selects_plan_for_long_task(self, client):
        long_task = (
            "Design and implement a comprehensive full stack microservice platform with "
            "multi region authentication adaptive rate limiting service mesh with "
            "circuit breakers distributed tracing across all services end to end "
            "encryption zero downtime deployment pipeline automated canary releases "
            "comprehensive observability with alerting and cost optimization layer "
            "plus full test coverage including chaos engineering scenarios across every "
            "single service in the entire distributed system architecture."
        )
        assert len(long_task.split()) > 50, f"Need >50 words, got {len(long_task.split())}"
        r = client.post("/api/reasoning/select-strategy", json={"task": long_task})
        assert r.status_code == 200
        data = r.json()
        assert data["selected_strategy"] == "plan"
        assert "system_prompt" in data

    def test_selects_reflect_for_error(self, client):
        r = client.post("/api/reasoning/select-strategy", json={"task": "fix this error in the code"})
        assert r.status_code == 200
        data = r.json()
        assert data["selected_strategy"] == "reflect"

    def test_selects_converse_for_greeting(self, client):
        r = client.post("/api/reasoning/select-strategy", json={"task": "hello there"})
        assert r.status_code == 200
        data = r.json()
        assert data["selected_strategy"] in ("converse", "cot")

    def test_selects_cot_for_short_task(self, client):
        r = client.post("/api/reasoning/select-strategy", json={"task": "read the config file"})
        assert r.status_code == 200
        data = r.json()
        assert data["selected_strategy"] in ("cot", "reflect")

    def test_missing_task_returns_400(self, client):
        r = client.post("/api/reasoning/select-strategy", json={})
        assert r.status_code == 400

    def test_returns_reason(self, client):
        r = client.post("/api/reasoning/select-strategy", json={"task": "build something"})
        assert r.status_code == 200
        data = r.json()
        assert "reason" in data
        assert "task_preview" in data


class TestAnalyzeTask:
    def test_analyze_returns_signals(self, client):
        r = client.post("/api/reasoning/analyze", json={"task": "fix the broken import error"})
        assert r.status_code == 200
        data = r.json()
        assert "signals" in data
        assert "has_error_keywords" in data["signals"]
        assert data["signals"]["has_error_keywords"] is True
        assert "word_count" in data
        assert "recommended_strategy" in data

    def test_analyze_long_task(self, client):
        words = " ".join(["word"] * 60)
        r = client.post("/api/reasoning/analyze", json={"task": words})
        assert r.status_code == 200
        data = r.json()
        assert data["signals"]["is_long_task"] is True

    def test_analyze_short_task(self, client):
        r = client.post("/api/reasoning/analyze", json={"task": "hi"})
        assert r.status_code == 200
        data = r.json()
        assert data["signals"]["is_short_input"] is True

    def test_analyze_missing_task(self, client):
        r = client.post("/api/reasoning/analyze", json={})
        assert r.status_code == 400


class TestSession:
    def test_start_session_cot(self, client):
        r = client.post("/api/reasoning/session", json={"task": "write a sort function", "strategy": "cot"})
        assert r.status_code == 200
        data = r.json()
        assert data["strategy"] == "cot"
        assert "system_prompt" in data
        assert "created_at" in data

    def test_start_session_auto(self, client):
        r = client.post("/api/reasoning/session", json={"task": "fix this bug in the parser"})
        assert r.status_code == 200
        data = r.json()
        assert data["strategy"] in ("cot", "reflect", "plan", "tot", "converse")

    def test_start_session_invalid_strategy(self, client):
        r = client.post("/api/reasoning/session", json={"task": "do something", "strategy": "quantum"})
        assert r.status_code == 400

    def test_start_session_missing_task(self, client):
        r = client.post("/api/reasoning/session", json={"strategy": "cot"})
        assert r.status_code == 400


class TestTraces:
    def test_list_traces_returns_list(self, client):
        r = client.get("/api/reasoning/traces")
        assert r.status_code == 200
        data = r.json()
        assert "traces" in data
        assert "count" in data
        assert isinstance(data["traces"], list)

    def test_get_nonexistent_trace(self, client):
        r = client.get("/api/reasoning/traces/nonexistent_trace_xyz")
        assert r.status_code == 404
