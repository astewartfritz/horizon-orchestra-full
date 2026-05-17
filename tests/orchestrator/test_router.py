"""Tests for the router orchestrator — exact state-diagram implementation."""
from __future__ import annotations

import pytest

from code_agent.orchestrator.router.models import (
    ModelLane, TaskIntent, TaskStep, StepStatus, TaskStatus,
    RouterPlan, StepResult, TaskState, RouterConfig,
    choose_model_lane,
)
from code_agent.orchestrator.router.agent_router import AgentRouter
from code_agent.orchestrator.router.agent_pool import AgentPool
from code_agent.orchestrator.router.planner import RouterPlanner
from code_agent.orchestrator.router.state import StateGraph
from code_agent.orchestrator.router.engine import Engine


class TestModels:
    def test_model_lane_values(self):
        assert ModelLane.CODER_7B.value == "coder_7b"
        assert ModelLane.MASTER_PLANNER_7B.value == "master_planner_7b"
        assert ModelLane.FALLBACK_3B.value == "fallback_3b"

    def test_task_step_defaults(self):
        step = TaskStep(step=1, lane=ModelLane.CODER_7B, goal="test")
        assert step.status == StepStatus.PENDING
        assert step.retries == 0
        assert step.max_retries == 2

    def test_step_status_values(self):
        assert StepStatus.DISPATCHED.value == "dispatched"
        assert StepStatus.RUNNING.value == "running"
        assert StepStatus.SUCCESS.value == "success"
        assert StepStatus.NEEDS_REPLAN.value == "needs_replan"

    def test_task_status_values(self):
        assert TaskStatus.INGESTED.value == "ingested"
        assert TaskStatus.PLANNED.value == "planned"
        assert TaskStatus.ENQUEUED.value == "enqueued"

    def test_router_plan_defaults(self):
        plan = RouterPlan()
        assert plan.steps == []
        assert plan.intent == TaskIntent.GENERAL

    def test_router_config_defaults(self):
        config = RouterConfig()
        assert config.planner_model == "qwen2.5:7b"
        assert config.max_steps == 5

    def test_choose_model_lane_plan(self):
        assert choose_model_lane("plan") == ModelLane.MASTER_PLANNER_7B

    def test_choose_model_lane_code(self):
        assert choose_model_lane("code") == ModelLane.CODER_7B

    def test_choose_model_lane_reasoning(self):
        assert choose_model_lane("reasoning") == ModelLane.REASONER_7B

    def test_choose_model_lane_summary(self):
        assert choose_model_lane("summary") == ModelLane.SUMMARIZER_3B

    def test_choose_model_lane_scratch(self):
        assert choose_model_lane("scratch") == ModelLane.SCRATCH_3B

    def test_choose_model_lane_validate(self):
        assert choose_model_lane("validate") == ModelLane.VALIDATOR_7B

    def test_choose_model_lane_search(self):
        assert choose_model_lane("search") == ModelLane.SEARCHER_3B

    def test_choose_model_lane_extract(self):
        assert choose_model_lane("extract") == ModelLane.EXTRACTOR_3B

    def test_choose_model_lane_fallback(self):
        assert choose_model_lane("unknown") == ModelLane.FALLBACK_3B

    def test_choose_model_lane_long_input(self):
        assert choose_model_lane("general", {"input_length": 5000}) == ModelLane.SUMMARIZER_3B
        assert choose_model_lane("reasoning", {"input_length": 100}) == ModelLane.REASONER_7B


class TestAgentRouter:
    def test_route_plan(self):
        router = AgentRouter()
        lane, model = router.route("plan")
        assert lane == ModelLane.MASTER_PLANNER_7B

    def test_route_code(self):
        router = AgentRouter()
        lane, model = router.route("code")
        assert lane == ModelLane.CODER_7B

    def test_route_reasoning(self):
        router = AgentRouter()
        lane, model = router.route("reasoning")
        assert lane == ModelLane.REASONER_7B

    def test_route_summary(self):
        router = AgentRouter()
        lane, model = router.route("summary")
        assert lane == ModelLane.SUMMARIZER_3B

    def test_route_fallback(self):
        router = AgentRouter()
        lane, model = router.route("bogus")
        assert lane == ModelLane.FALLBACK_3B

    def test_list_lanes(self):
        router = AgentRouter()
        lanes = router.list_lanes()
        assert len(lanes) == 9
        assert any(l["task_type"] == "code" for l in lanes)
        assert any(l["task_type"] == "plan" for l in lanes)

    def test_route_with_context(self):
        router = AgentRouter()
        lane, model = router.route("summary", {"input_length": 99})
        assert lane == ModelLane.SUMMARIZER_3B

    def test_route_long_input(self):
        router = AgentRouter()
        lane, _ = router.route("reasoning", {"input_length": 5000})
        assert lane == ModelLane.SUMMARIZER_3B

    def test_route_short_input(self):
        router = AgentRouter()
        lane, _ = router.route("reasoning", {"input_length": 100})
        assert lane == ModelLane.REASONER_7B

    def test_route_scratch(self):
        router = AgentRouter()
        lane, model = router.route("scratch")
        assert lane == ModelLane.SCRATCH_3B

    def test_static_choose_model_lane(self):
        assert AgentRouter.choose_model_lane("code") == ModelLane.CODER_7B


class TestAgentPool:
    def test_get_default_spec(self):
        pool = AgentPool()
        spec = pool.get(ModelLane.CODER_7B)
        assert spec.model is not None

    def test_select_model(self):
        pool = AgentPool()
        model = pool.select_model(ModelLane.CODER_7B)
        assert isinstance(model, str)

    def test_build_prompt_from_lane(self):
        pool = AgentPool()
        prompt = pool.build_prompt_from_lane(ModelLane.CODER_7B, "write a function", context="needs sorting")
        assert "write a function" in prompt
        assert "needs sorting" in prompt

    def test_build_prompt_summarizer(self):
        pool = AgentPool()
        prompt = pool.build_prompt_from_lane(ModelLane.SUMMARIZER_3B, "summarize this")
        assert "summarize this" in prompt

    def test_register(self):
        pool = AgentPool()
        spec = pool.get(ModelLane.CODER_7B)
        pool.register(ModelLane.CODER_7B, spec)
        assert pool.list_agents() == [spec]


class TestStateGraph:
    def test_create_state(self):
        graph = StateGraph()
        state = graph.create_state("test")
        assert state.user_input == "test"
        assert state.task_id is not None

    def test_get_state(self):
        graph = StateGraph()
        state = graph.create_state("hello")
        assert graph.get_state(state.task_id) is state

    def test_add_step_result(self):
        graph = StateGraph()
        state = graph.create_state("test")
        result = StepResult(step=1, lane=ModelLane.CODER_7B, agent_role="coder", status=StepStatus.SUCCESS, output="ok")
        graph.add_step_result(state.task_id, result)
        assert len(graph.get_state(state.task_id).history) == 1

    def test_set_status(self):
        graph = StateGraph()
        state = graph.create_state("test")
        graph.set_status(state.task_id, TaskStatus.RUNNING)
        assert graph.get_state(state.task_id).status == TaskStatus.RUNNING

    def test_list_states(self):
        graph = StateGraph()
        graph.create_state("a")
        graph.create_state("b")
        assert len(graph.list_states()) == 2

    def test_delete_state(self):
        graph = StateGraph()
        state = graph.create_state("test")
        assert graph.delete_state(state.task_id) is True
        assert graph.get_state(state.task_id) is None

    def test_get_trace(self):
        graph = StateGraph()
        state = graph.create_state("test")
        trace = graph.get_trace(state.task_id)
        assert len(trace) == 1
        assert trace[0]["event"] == "created"

    def test_export_trace(self):
        graph = StateGraph()
        state = graph.create_state("test")
        exported = graph.export_trace(state.task_id)
        assert exported is not None
        assert exported["task_id"] == state.task_id


class TestEngine:
    @pytest.mark.asyncio
    async def test_ingest_creates_state(self):
        engine = Engine(llm_call=_mock_llm)
        state = engine.ingest("write code")
        assert state.status == TaskStatus.INGESTED
        assert state.user_input == "write code"

    @pytest.mark.asyncio
    async def test_plan_task(self):
        engine = Engine(llm_call=_mock_llm)
        state = engine.ingest("write a python function")
        plan = await engine.plan(state.task_id)
        assert len(plan.steps) > 0

    @pytest.mark.asyncio
    async def test_enqueue_steps(self):
        engine = Engine(llm_call=_mock_llm)
        state = engine.ingest("write code")
        await engine.plan(state.task_id)
        state = engine.enqueue(state.task_id)
        assert state.status == TaskStatus.ENQUEUED
        for s in state.plan.steps:
            assert s.lane is not None
            assert s.lane in ModelLane
            assert len(s.input_prompt) > 0

    @pytest.mark.asyncio
    async def test_execute_general(self):
        engine = Engine(llm_call=_mock_llm)
        state = await engine.run("hello world")
        assert state.status == TaskStatus.COMPLETED
        assert state.final_output is not None

    @pytest.mark.asyncio
    async def test_execute_code_intent(self):
        engine = Engine(llm_call=_mock_llm)
        state = await engine.run("write a sort function", TaskIntent.CODE)
        assert state.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_summary_intent(self):
        engine = Engine(llm_call=_mock_llm)
        state = await engine.run("summarize this text", TaskIntent.SUMMARY)
        assert state.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_full_lifecycle_trace(self):
        engine = Engine(llm_call=_mock_llm)
        state = await engine.run("write code")
        trace = engine.state_graph.get_trace(state.task_id)
        events = [t["event"] for t in trace]
        assert "ingested" in events
        assert "planned" in events
        assert "enqueued" in events
        assert "dispatched" in events
        assert "running" in events
        assert "collected" in events
        assert "responded" in events

    @pytest.mark.asyncio
    async def test_ingest_plan_enqueue_execute_stages(self):
        engine = Engine(llm_call=_mock_llm)
        s1 = engine.ingest("analyze this data")
        assert s1.status == TaskStatus.INGESTED
        await engine.plan(s1.task_id)
        assert engine.state_graph.get_state(s1.task_id).status == TaskStatus.PLANNED
        engine.enqueue(s1.task_id)
        assert engine.state_graph.get_state(s1.task_id).status == TaskStatus.ENQUEUED
        await engine.execute(s1.task_id)
        assert engine.state_graph.get_state(s1.task_id).status == TaskStatus.COMPLETED


async def _mock_llm(model: str, prompt: str) -> str:
    if "system" in prompt.lower() or "planner" in model:
        return '{"steps": [{"step": 1, "agent": "reasoner", "goal": "analyze"}, {"step": 2, "agent": "summarizer", "goal": "summarize"}]}'
    return f"Mocked response from {model}"
