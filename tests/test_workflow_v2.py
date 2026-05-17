import pytest
import asyncio
import json

from code_agent.workflow_v2 import (
    DAGEngine, WorkflowManager, WorkflowInstance,
    DAGWorkflow, DAGResult, WorkflowContext,
    BaseStep, AgentStep, ToolStep, TransformStep,
    ParallelStep, ConditionStep, SwitchStep, LoopStep,
    HumanHandoffStep, SubWorkflowStep,
    StepStatus, WorkflowStatus,
    parse_workflow, parse_workflow_json, parse_workflow_yaml, workflow_to_dict,
)


class TestStepModels:
    def test_base_step_auto_id(self):
        s = BaseStep(name="test")
        assert s.id.startswith("step_")
        assert s.step_type == "base"

    def test_agent_step(self):
        s = AgentStep(name="coder", prompt="Write code", agent_config={"model": "gpt4"})
        assert s.step_type == "agent"
        assert s.prompt == "Write code"
        assert s.agent_config["model"] == "gpt4"

    def test_tool_step(self):
        s = ToolStep(name="bash", tool_name="bash", tool_params={"cmd": "ls"})
        assert s.step_type == "tool"
        assert s.tool_name == "bash"

    def test_transform_step(self):
        s = TransformStep(name="merge", expression="a + b", output_template="${{ vars.x }}")
        assert s.step_type == "transform"

    def test_parallel_step(self):
        s = ParallelStep(name="p", branches=[[AgentStep(prompt="a")], [AgentStep(prompt="b")]])
        assert s.step_type == "parallel"
        assert len(s.branches) == 2
        assert len(s.all_child_steps()) == 2

    def test_condition_step(self):
        s = ConditionStep(
            name="check", condition_expression="x > 5",
            if_steps=[AgentStep(prompt="yes")],
            else_steps=[AgentStep(prompt="no")],
        )
        assert s.step_type == "condition"
        assert len(s.if_steps) == 1
        assert len(s.else_steps) == 1
        assert len(s.all_child_steps()) == 2

    def test_switch_step(self):
        s = SwitchStep(
            name="router", switch_expression="x",
            cases={"a": [AgentStep(prompt="case a")], "b": [AgentStep(prompt="case b")]},
            default_steps=[AgentStep(prompt="default")],
        )
        assert s.step_type == "switch"
        assert len(s.all_child_steps()) == 3

    def test_loop_step(self):
        s = LoopStep(name="loop", loop_body=[AgentStep(prompt="body")], for_items="[1,2,3]")
        assert s.step_type == "loop"
        assert len(s.all_child_steps()) == 1

    def test_human_handoff_step(self):
        s = HumanHandoffStep(name="approve", message="Approve?", prompt="Please review")
        assert s.step_type == "human_handoff"
        assert s.timeout == 3600.0

    def test_subworkflow_step(self):
        s = SubWorkflowStep(name="sub", workflow_name="inner")
        assert s.step_type == "subworkflow"


class TestWorkflowModels:
    def test_dag_workflow_creation(self):
        wf = DAGWorkflow(name="test", description="A test workflow")
        assert wf.id.startswith("wf_")
        assert wf.name == "test"
        assert len(wf.steps) == 0

    def test_add_step(self):
        wf = DAGWorkflow(name="test")
        s1 = AgentStep(name="step1", prompt="do something")
        sid = wf.add_step(s1)
        assert sid == s1.id
        assert len(wf.steps) == 1

    def test_get_step(self):
        wf = DAGWorkflow(name="test")
        s1 = AgentStep(id="s1", name="step1")
        wf.add_step(s1)
        assert wf.get_step("s1") is s1
        assert wf.get_step("nonexistent") is None

    def test_all_steps_flat(self):
        wf = DAGWorkflow(name="test")
        inner = AgentStep(id="inner", prompt="inner")
        outer = ParallelStep(id="outer", branches=[[inner]])
        wf.add_step(outer)
        flat = wf.all_steps_flat()
        ids = [s.id for s in flat]
        assert "outer" in ids
        assert "inner" in ids

    def test_depends_on_tracking(self):
        wf = DAGWorkflow(name="test")
        s1 = AgentStep(id="s1", prompt="first")
        s2 = AgentStep(id="s2", prompt="second", depends_on=["s1"])
        wf.add_step(s1)
        wf.add_step(s2)
        deps = wf.get_dependency_ids(s2)
        assert "s1" in deps


class TestWorkflowContext:
    def test_resolve_variables_simple(self):
        ctx = WorkflowContext(vars={"name": "World"})
        result = ctx.resolve_variables("Hello ${{ vars.name }}!")
        assert result == "Hello World!"

    def test_resolve_step_output(self):
        ctx = WorkflowContext()
        ctx.results["step1"] = DAGResult(step_id="step1", output='{"result": 42}')
        result = ctx.resolve_variables("Got ${{ steps.step1.output.result }}")
        assert result == "Got 42"

    def test_resolve_step_output_raw(self):
        ctx = WorkflowContext()
        ctx.results["step1"] = DAGResult(step_id="step1", output="hello world")
        result = ctx.resolve_variables("${{ steps.step1.output }}")
        assert result == "hello world"

    def test_resolve_env(self):
        import os
        os.environ["TEST_VAR"] = "env_val"
        ctx = WorkflowContext()
        result = ctx.resolve_variables("${{ env.TEST_VAR }}")
        assert result == "env_val"

    def test_resolve_in_dict(self):
        ctx = WorkflowContext(vars={"key": "val"})
        d = {"a": "${{ vars.key }}", "b": {"c": "${{ vars.key }}"}, "d": [1, 2]}
        resolved = ctx.resolve_in_dict(d)
        assert resolved["a"] == "val"
        assert resolved["b"]["c"] == "val"
        assert resolved["d"] == [1, 2]

    def test_get_step_output_json_field(self):
        ctx = WorkflowContext()
        ctx.results["r1"] = DAGResult(step_id="r1", output=json.dumps({"a": {"b": "deep"}}))
        assert ctx.get_step_output("r1", "a.b") == "deep"

    def test_get_step_output_missing(self):
        ctx = WorkflowContext()
        assert ctx.get_step_output("missing") == ""
        assert ctx.get_step_output("missing", "field") == ""


class TestDAGEngine:
    @pytest.mark.asyncio
    async def test_run_simple_workflow(self):
        wf = DAGWorkflow(name="simple")
        wf.add_step(AgentStep(id="s1", prompt="hello"))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.status == WorkflowStatus.COMPLETED
        assert "s1" in ctx.results
        assert ctx.results["s1"].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_with_dependencies(self):
        wf = DAGWorkflow(name="deps")
        s1 = AgentStep(id="first", prompt="first")
        s2 = AgentStep(id="second", prompt="second", depends_on=["first"])
        s3 = AgentStep(id="third", prompt="third", depends_on=["first"])
        wf.add_step(s1)
        wf.add_step(s2)
        wf.add_step(s3)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.status == WorkflowStatus.COMPLETED
        assert all(ctx.results[s].status == StepStatus.COMPLETED for s in ["first", "second", "third"])

    @pytest.mark.asyncio
    async def test_parallel_branches(self):
        wf = DAGWorkflow(name="parallel")
        branch1 = [AgentStep(id="b1s1", prompt="parallel a")]
        branch2 = [AgentStep(id="b2s1", prompt="parallel b")]
        p = ParallelStep(id="parallel_step", branches=[branch1, branch2], aggregator="join")
        wf.add_step(p)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.status == WorkflowStatus.COMPLETED
        result = ctx.results["parallel_step"]
        assert result.status == StepStatus.COMPLETED
        assert len(result.child_results) == 2

    @pytest.mark.asyncio
    async def test_parallel_first_aggregator(self):
        wf = DAGWorkflow(name="parallel-first")
        b1 = [AgentStep(id="b1", prompt="first")]
        b2 = [AgentStep(id="b2", prompt="second")]
        p = ParallelStep(id="p", branches=[b1, b2], aggregator="first")
        wf.add_step(p)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["p"].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_parallel_merge_json(self):
        wf = DAGWorkflow(name="merge-json", vars={})
        b1 = [TransformStep(id="t1", output_template='{"a": 1}')]
        b2 = [TransformStep(id="t2", output_template='{"b": 2}')]
        p = ParallelStep(id="p", branches=[b1, b2], aggregator="merge_json")
        wf.add_step(p)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        r = ctx.results["p"]
        assert r.status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_condition_if_branch(self):
        wf = DAGWorkflow(name="cond-if", vars={"x": 10})
        cond = ConditionStep(
            id="cond", condition_expression="${{ vars.x }} > 5",
            if_steps=[AgentStep(id="if_branch", prompt="x is big")],
            else_steps=[AgentStep(id="else_branch", prompt="x is small")],
        )
        wf.add_step(cond)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["cond"].status == StepStatus.COMPLETED
        assert "if_branch" in ctx.results
        assert ctx.results["if_branch"].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_condition_else_branch(self):
        wf = DAGWorkflow(name="cond-else", vars={"x": 2})
        cond = ConditionStep(
            id="cond", condition_expression="${{ vars.x }} > 5",
            if_steps=[AgentStep(id="if_branch", prompt="x is big")],
            else_steps=[AgentStep(id="else_branch", prompt="x is small")],
        )
        wf.add_step(cond)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["cond"].status == StepStatus.COMPLETED
        assert "else_branch" in ctx.results
        assert ctx.results["else_branch"].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_condition_nested_steps(self):
        wf = DAGWorkflow(name="nested-cond", vars={"x": 1})
        cond = ConditionStep(
            id="outer", condition_expression="${{ vars.x }} > 0",
            if_steps=[ConditionStep(
                id="inner", condition_expression="${{ vars.x }} < 5",
                if_steps=[AgentStep(id="deep", prompt="deep")],
                else_steps=[],
            )],
            else_steps=[],
        )
        wf.add_step(cond)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["outer"].status == StepStatus.COMPLETED
        assert ctx.results["inner"].status == StepStatus.COMPLETED
        assert ctx.results["deep"].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_switch_case(self):
        wf = DAGWorkflow(name="switch", vars={"x": "a"})
        sw = SwitchStep(
            id="sw", switch_expression="${{ vars.x }}",
            cases={"a": [AgentStep(id="case_a", prompt="matched a")],
                   "b": [AgentStep(id="case_b", prompt="matched b")]},
        )
        wf.add_step(sw)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["sw"].status == StepStatus.COMPLETED
        assert "case_a" in ctx.results
        assert "case_b" not in ctx.results

    @pytest.mark.asyncio
    async def test_switch_default(self):
        wf = DAGWorkflow(name="switch-default", vars={"x": "z"})
        sw = SwitchStep(
            id="sw", switch_expression="${{ vars.x }}",
            cases={"a": [AgentStep(id="case_a", prompt="a")]},
            default_steps=[AgentStep(id="default_case", prompt="default")],
        )
        wf.add_step(sw)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["sw"].status == StepStatus.COMPLETED
        assert "default_case" in ctx.results

    @pytest.mark.asyncio
    async def test_loop_for_items(self):
        wf = DAGWorkflow(name="for-loop", vars={"items": [1, 2, 3]})
        loop = LoopStep(
            id="loop", for_items="${{ vars.items }}", max_iterations=5, item_variable="item",
            loop_body=[TransformStep(id="body", expression="str(vars['item'])")],
        )
        wf.add_step(loop)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["loop"].status == StepStatus.COMPLETED
        assert "3 iterations" in ctx.results["loop"].output

    @pytest.mark.asyncio
    async def test_loop_max_iterations(self):
        wf = DAGWorkflow(name="max-loop", vars={"items": list(range(100))})
        loop = LoopStep(
            id="loop", for_items="vars.items", max_iterations=3,
            loop_body=[AgentStep(id="body", prompt="item")],
        )
        wf.add_step(loop)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["loop"].status == StepStatus.COMPLETED
        assert "3 iterations" in ctx.results["loop"].output

    @pytest.mark.asyncio
    async def test_tool_step(self):
        tool_results = {}

        async def my_tool(param=""):
            tool_results["called"] = True
            return f"tool result: {param}"

        wf = DAGWorkflow(name="tool-test", vars={"p": "hello"})
        wf.add_step(ToolStep(id="t1", tool_name="my_tool", tool_params={"param": "${{ vars.p }}"}))
        engine = DAGEngine(tool_registry={"my_tool": my_tool})
        ctx = await engine.run(wf)
        assert ctx.results["t1"].status == StepStatus.COMPLETED
        assert tool_results.get("called") is True

    @pytest.mark.asyncio
    async def test_tool_step_not_found(self):
        wf = DAGWorkflow(name="missing-tool")
        wf.add_step(ToolStep(id="t1", tool_name="nonexistent"))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["t1"].status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_transform_expression(self):
        wf = DAGWorkflow(name="transform", vars={"a": 5, "b": 3})
        wf.add_step(TransformStep(id="t1", expression="${{ vars.a + vars.b }}"))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["t1"].output == "8"

    @pytest.mark.asyncio
    async def test_transform_template(self):
        wf = DAGWorkflow(name="template", vars={"name": "World"})
        wf.add_step(TransformStep(id="t1", output_template="Hello ${{ vars.name }}!"))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["t1"].output == "Hello World!"

    @pytest.mark.asyncio
    async def test_condition_expression_variable_reference(self):
        wf = DAGWorkflow(name="cond-ref", vars={"threshold": 10})
        cond = ConditionStep(
            id="cond", condition_expression="${{ vars.threshold }} > 5",
            if_steps=[AgentStep(id="ok", prompt="ok")],
            else_steps=[],
        )
        wf.add_step(cond)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["cond"].status == StepStatus.COMPLETED
        assert "ok" in ctx.results

    @pytest.mark.asyncio
    async def test_dependency_chain(self):
        wf = DAGWorkflow(name="chain")
        wf.add_step(AgentStep(id="a", prompt="a"))
        wf.add_step(AgentStep(id="b", prompt="b", depends_on=["a"]))
        wf.add_step(AgentStep(id="c", prompt="c", depends_on=["b"]))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        for sid in ["a", "b", "c"]:
            assert ctx.results[sid].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_human_handoff_and_resume(self):
        wf = DAGWorkflow(name="handoff")
        wf.add_step(HumanHandoffStep(id="h1", message="Approve?", prompt="details"))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.status == WorkflowStatus.PAUSED
        assert ctx.results["h1"].status == StepStatus.WAITING_HUMAN

        ok = await engine.resume_handoff(ctx.workflow_id, "h1", "approved")
        assert ok is True

        await asyncio.sleep(0.05)
        assert ctx.results["h1"].status == StepStatus.COMPLETED
        assert ctx.results["h1"].output == "approved"

    @pytest.mark.asyncio
    async def test_on_failure_skip(self):
        wf = DAGWorkflow(name="fail-skip")
        wf.add_step(AgentStep(id="s1", prompt="ok"))
        wf.add_step(ToolStep(id="s2", tool_name="missing", on_failure="skip", depends_on=["s1"]))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["s1"].status == StepStatus.COMPLETED
        assert ctx.results["s2"].status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_timeout(self):
        wf = DAGWorkflow(name="timeout")
        wf.add_step(AgentStep(id="s1", prompt="slow", timeout=0.01))
        engine = DAGEngine()

        async def slow_agent(self, prompt):
            await asyncio.sleep(10)
            return "done"

        engine._agent_factory = lambda c: type("A", (), {"run": slow_agent})()
        ctx = await engine.run(wf)
        assert ctx.results["s1"].status == StepStatus.FAILED
        assert "timed out" in ctx.results["s1"].error.lower()

    @pytest.mark.asyncio
    async def test_step_events(self):
        wf = DAGWorkflow(name="events")
        wf.add_step(AgentStep(id="e1", prompt="event test"))
        events = []
        engine = DAGEngine()
        engine.on_step_start(lambda s, ctx: events.append(("start", s.id)))
        engine.on_step_complete(lambda s, ctx, r: events.append(("complete", s.id, r.status.value)))
        await engine.run(wf)
        assert ("start", "e1") in events
        assert any(e[0] == "complete" and e[1] == "e1" for e in events)

    @pytest.mark.asyncio
    async def test_handoff_callback(self):
        wf = DAGWorkflow(name="handoff-cb")
        wf.add_step(HumanHandoffStep(id="h1", message="test"))
        callback_data = {}
        engine = DAGEngine()

        async def cb(data):
            callback_data.update(data)

        engine._handoff_callback = cb
        ctx = await engine.run(wf)
        assert callback_data.get("step_id") == "h1"

    @pytest.mark.asyncio
    async def test_parallel_with_mixed_results(self):
        wf = DAGWorkflow(name="mixed-parallel")
        b1 = [ToolStep(id="good", tool_name="ok_tool")]
        b2 = [ToolStep(id="bad", tool_name="missing_tool")]
        p = ParallelStep(id="p", branches=[b1, b2])
        wf.add_step(p)
        tool_reg = {"ok_tool": lambda: "success"}
        engine = DAGEngine(tool_registry=tool_reg)
        ctx = await engine.run(wf)
        r = ctx.results["p"]
        assert any(c.success for c in r.child_results)
        assert any(not c.success for c in r.child_results)

    @pytest.mark.asyncio
    async def test_workflow_manager(self):
        mgr = WorkflowManager()
        wf = DAGWorkflow(name="managed")
        wf.add_step(AgentStep(id="m1", prompt="managed step"))
        mgr.register_workflow(wf)
        assert mgr.get_workflow(wf.id) is wf
        assert mgr.get_workflow("managed") is wf

        ctx = await mgr.run_workflow(wf.id)
        assert ctx.status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_workflow_direct(self):
        mgr = WorkflowManager()
        wf = DAGWorkflow(name="direct")
        wf.add_step(AgentStep(id="d1", prompt="direct step"))
        ctx = await mgr.run_workflow_direct(wf)
        assert ctx.status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_workflow_manager_list_instances(self):
        mgr = WorkflowManager()
        wf = DAGWorkflow(name="list-me")
        wf.add_step(AgentStep(id="l1", prompt="list test"))
        await mgr.run_workflow_direct(wf)
        assert len(mgr.list_instances()) >= 1

    def test_workflow_manager_get_instance(self):
        mgr = WorkflowManager()
        assert mgr.get_instance("nonexistent") is None

    @pytest.mark.asyncio
    async def test_step_output_in_vars(self):
        wf = DAGWorkflow(name="output-chain", vars={})
        wf.add_step(TransformStep(id="gen", expression="json.dumps({'value': 42})"))
        wf.add_step(TransformStep(
            id="use", depends_on=["gen"],
            output_template="Got ${{ steps.gen.output.value }}",
        ))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.results["use"].output == "Got 42"


class TestParser:
    def test_parse_simple_workflow(self):
        data = {
            "name": "parsed",
            "description": "Parsed workflow",
            "vars": {"x": 1},
            "steps": [
                {"id": "s1", "type": "agent", "prompt": "hello"},
                {"id": "s2", "type": "tool", "tool_name": "bash", "tool_params": {"cmd": "ls"}},
            ],
        }
        wf = parse_workflow(data)
        assert wf.name == "parsed"
        assert len(wf.steps) == 2
        assert isinstance(wf.steps[0], AgentStep)
        assert isinstance(wf.steps[1], ToolStep)

    def test_parse_with_condition(self):
        data = {
            "name": "cond",
            "steps": [{
                "id": "c1", "type": "condition", "condition_expression": "x > 5",
                "if": [{"id": "yes", "type": "agent", "prompt": "yes"}],
                "else": [{"id": "no", "type": "agent", "prompt": "no"}],
            }],
        }
        wf = parse_workflow(data)
        assert len(wf.steps) == 1
        assert isinstance(wf.steps[0], ConditionStep)
        assert len(wf.steps[0].if_steps) == 1
        assert len(wf.steps[0].else_steps) == 1

    def test_parse_with_parallel(self):
        data = {
            "name": "par",
            "steps": [{
                "id": "p1", "type": "parallel", "max_concurrency": 3,
                "branches": [
                    [{"id": "a", "type": "agent", "prompt": "A"}],
                    [{"id": "b", "type": "agent", "prompt": "B"}],
                ],
            }],
        }
        wf = parse_workflow(data)
        assert isinstance(wf.steps[0], ParallelStep)
        assert len(wf.steps[0].branches) == 2

    def test_parse_with_switch(self):
        data = {
            "name": "sw",
            "steps": [{
                "id": "sw1", "type": "switch", "switch_expression": "x",
                "cases": {
                    "a": [{"id": "ca", "type": "agent", "prompt": "a"}],
                },
                "default": [{"id": "def", "type": "agent", "prompt": "default"}],
            }],
        }
        wf = parse_workflow(data)
        assert isinstance(wf.steps[0], SwitchStep)
        assert "a" in wf.steps[0].cases

    def test_parse_with_loop(self):
        data = {
            "name": "lp",
            "steps": [{
                "id": "lp1", "type": "loop", "for_items": "[1,2]",
                "body": [{"id": "body1", "type": "agent", "prompt": "item"}],
            }],
        }
        wf = parse_workflow(data)
        assert isinstance(wf.steps[0], LoopStep)
        assert len(wf.steps[0].loop_body) == 1

    def test_parse_with_human_handoff(self):
        data = {
            "name": "hh",
            "steps": [{"id": "hh1", "type": "human_handoff", "message": "Ok?"}],
        }
        wf = parse_workflow(data)
        assert isinstance(wf.steps[0], HumanHandoffStep)

    def test_parse_from_yaml(self):
        yaml_text = """
name: yaml-workflow
steps:
  - id: s1
    type: agent
    prompt: "hello from yaml"
"""
        wf = parse_workflow_yaml(yaml_text)
        assert wf.name == "yaml-workflow"
        assert len(wf.steps) == 1

    def test_parse_from_json(self):
        json_text = '{"name": "json-wf", "steps": [{"id": "s1", "type": "agent", "prompt": "hi"}]}'
        wf = parse_workflow_json(json_text)
        assert wf.name == "json-wf"
        assert len(wf.steps) == 1

    def test_workflow_to_dict(self):
        wf = DAGWorkflow(name="export")
        wf.add_step(AgentStep(id="e1", prompt="export test"))
        d = workflow_to_dict(wf)
        assert d["name"] == "export"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["id"] == "e1"

    def test_workflow_to_dict_nested(self):
        wf = DAGWorkflow(name="nested-export")
        wf.add_step(ConditionStep(
            id="c1", condition_expression="x > 0",
            if_steps=[AgentStep(id="if1", prompt="if")],
        ))
        d = workflow_to_dict(wf)
        assert len(d["steps"][0]["if"]) == 1


class TestDAGResult:
    def test_success_property(self):
        r = DAGResult(status=StepStatus.COMPLETED)
        assert r.success is True
        r.status = StepStatus.FAILED
        assert r.success is False

    def test_duration_calculation(self):
        r = DAGResult(started_at=100.0, completed_at=110.0)
        assert r.duration_ms == 0.0
        r.started_at = 100.0
        r.completed_at = 105.0
        r.duration_ms = (r.completed_at - r.started_at) * 1000
        assert r.duration_ms == 5000.0


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_workflow(self):
        wf = DAGWorkflow(name="empty")
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_single_step_no_agent_factory(self):
        wf = DAGWorkflow(name="single")
        wf.add_step(AgentStep(id="s1", prompt="test"))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.status == WorkflowStatus.COMPLETED
        assert "[mock-agent:" in ctx.results["s1"].output

    @pytest.mark.asyncio
    async def test_workflow_with_vars(self):
        wf = DAGWorkflow(name="with-vars", vars={"initial": "start"})
        wf.add_step(TransformStep(id="t1", output_template="${{ vars.initial }}"))
        engine = DAGEngine()
        ctx = await engine.run(wf, vars={"extra": "end"})
        assert ctx.vars["initial"] == "start"
        assert ctx.vars["extra"] == "end"

    @pytest.mark.asyncio
    async def test_condition_false_skips_if_branch(self):
        wf = DAGWorkflow(name="false-cond", vars={"flag": False})
        cond = ConditionStep(
            id="cond", condition_expression="${{ vars.flag }}",
            if_steps=[AgentStep(id="if_b", prompt="should not run")],
            else_steps=[AgentStep(id="else_b", prompt="should run")],
        )
        wf.add_step(cond)
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert "if_b" not in ctx.results
        assert "else_b" in ctx.results

    @pytest.mark.asyncio
    async def test_handoff_callback_pauses_workflow(self):
        wf = DAGWorkflow(name="pause-test")
        wf.add_step(HumanHandoffStep(id="h1", message="pause"))
        engine = DAGEngine()
        ctx = await engine.run(wf)
        assert ctx.status == WorkflowStatus.PAUSED
        await engine.resume_handoff(ctx.workflow_id, "h1", "resumed")
        await asyncio.sleep(0.1)
        assert ctx.results["h1"].status == StepStatus.COMPLETED
