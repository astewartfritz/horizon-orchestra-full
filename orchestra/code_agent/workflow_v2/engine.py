from __future__ import annotations

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from orchestra.code_agent.workflow_v2.models import (
    BaseStep, AgentStep, ToolStep, TransformStep,
    ParallelStep, ConditionStep, SwitchStep, LoopStep,
    HumanHandoffStep, SubWorkflowStep,
    DAGWorkflow, DAGResult, WorkflowContext,
    StepStatus, WorkflowStatus,
)

logger = logging.getLogger(__name__)


class _AttrDict(dict):
    def __getattribute__(self, key):
        if key in self:
            v = self[key]
            if isinstance(v, dict):
                return _AttrDict(v)
            return v
        return dict.__getattribute__(self, key)

class DAGEngine:
    def __init__(self, tool_registry: dict[str, Callable] | None = None,
                 agent_factory: Callable | None = None,
                 handoff_callback: Callable | None = None):
        self._tool_registry = tool_registry or {}
        self._agent_factory = agent_factory
        self._handoff_callback = handoff_callback
        self._sub_engines: dict[str, DAGEngine] = {}
        self._on_step_start: list[Callable] = []
        self._on_step_complete: list[Callable] = []
        self._handoff_events: dict[str, asyncio.Event] = {}
        self._handoff_responses: dict[str, str] = {}
        self._active_contexts: dict[str, WorkflowContext] = {}

    def on_step_start(self, cb: Callable):
        self._on_step_start.append(cb)

    def on_step_complete(self, cb: Callable):
        self._on_step_complete.append(cb)

    async def run(self, workflow: DAGWorkflow, vars: dict[str, Any] | None = None) -> WorkflowContext:
        ctx = WorkflowContext(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            status=WorkflowStatus.RUNNING,
            vars=dict(workflow.vars),
        )
        if vars:
            ctx.vars.update(vars)
        ctx.workflow = workflow

        self._active_contexts[workflow.id] = ctx
        start = time.time()
        try:
            await self._execute_dag(workflow, ctx)
        except Exception as e:
            ctx.status = WorkflowStatus.FAILED
            ctx.error = str(e)
            logger.exception(f"Workflow {workflow.name} failed")

        ctx.completed_at = time.time()
        ctx.total_duration_ms = (ctx.completed_at - start) * 1000
        if ctx.status == WorkflowStatus.RUNNING:
            ctx.status = WorkflowStatus.COMPLETED
        if ctx.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
            self._active_contexts.pop(workflow.id, None)
        return ctx

    async def _execute_dag(self, workflow: DAGWorkflow, ctx: WorkflowContext):
        step_map = {s.id: s for s in workflow.all_steps_flat()}
        pending: set[str] = {s.id for s in workflow.steps}
        running: set[str] = set()

        while pending or running:
            if ctx.status == WorkflowStatus.PAUSED:
                break

            ready = [
                s for s in workflow.steps
                if s.id in pending
                and s.id not in ctx.results
                and self._deps_met(s, ctx, step_map)
                and (not s.condition or self._evaluate_condition(s.condition, ctx))
            ]

            if not ready and not running:
                if pending:
                    blocked = [s.id for s in workflow.steps if s.id in pending]
                    failed = [s.id for s in workflow.steps if s.id in pending
                              and any(ctx.results.get(d, DAGResult()).status == StepStatus.FAILED for d in s.depends_on)]
                    if failed:
                        for fid in failed:
                            s = step_map.get(fid)
                            if s:
                                s.status = StepStatus.SKIPPED
                                ctx.results[fid] = DAGResult(
                                    step_id=fid, step_type=s.step_type,
                                    status=StepStatus.SKIPPED,
                                    error="Dependency failed",
                                )
                                pending.discard(fid)
                        continue
                break

            for step in ready:
                pending.discard(step.id)
                running.add(step.id)
                asyncio.create_task(self._execute_step(step, ctx, running, pending))

            await asyncio.sleep(0.05)

    async def _execute_step(self, step: BaseStep, ctx: WorkflowContext,
                            running: set[str] | None = None,
                            pending: set[str] | None = None):
        for cb in self._on_step_start:
            cb(step, ctx)
        ctx.current_step_id = step.id
        step.status = StepStatus.RUNNING

        try:
            result = await asyncio.wait_for(
                self._dispatch_step(step, ctx),
                timeout=step.timeout,
            )
        except asyncio.TimeoutError:
            result = DAGResult(
                step_id=step.id, step_type=step.step_type,
                step_name=step.name, status=StepStatus.FAILED,
                error=f"Timed out after {step.timeout}s",
            )
        except Exception as e:
            result = DAGResult(
                step_id=step.id, step_type=step.step_type,
                step_name=step.name, status=StepStatus.FAILED,
                error=str(e),
            )

        step.status = result.status
        ctx.results[step.id] = result

        if result.status == StepStatus.FAILED and step.on_failure == "skip":
            result.status = StepStatus.SKIPPED
            step.status = StepStatus.SKIPPED

        for cb in self._on_step_complete:
            cb(step, ctx, result)

        if running:
            running.discard(step.id)

    async def _dispatch_step(self, step: BaseStep, ctx: WorkflowContext) -> DAGResult:
        dispatchers = {
            "agent": self._run_agent_step,
            "tool": self._run_tool_step,
            "transform": self._run_transform_step,
            "parallel": self._run_parallel_step,
            "condition": self._run_condition_step,
            "switch": self._run_switch_step,
            "loop": self._run_loop_step,
            "human_handoff": self._run_human_handoff_step,
            "subworkflow": self._run_subworkflow_step,
        }
        handler = dispatchers.get(step.step_type, self._run_default_step)
        result = await handler(step, ctx)
        result.step_id = step.id
        result.step_type = step.step_type
        result.step_name = step.name
        return result

    def _deps_met(self, step: BaseStep, ctx: WorkflowContext,
                  step_map: dict[str, BaseStep]) -> bool:
        deps = step.depends_on
        for dep_id in deps:
            dep_result = ctx.results.get(dep_id)
            if not dep_result or dep_result.status not in (StepStatus.COMPLETED, StepStatus.SKIPPED):
                return False
            if dep_result.status == StepStatus.FAILED:
                return False
        return True

    def _evaluate_condition(self, condition: str, ctx: WorkflowContext) -> bool:
        try:
            import json, re
            eval_globals = {"__builtins__": {}, "json": json, "str": str, "int": int,
                            "float": float, "list": list, "dict": dict, "len": len}
            attr_vars = _AttrDict(ctx.vars)
            eval_locals = dict(ctx.vars, vars=attr_vars)
            m = re.match(r'\$\{\{\s*(.+?)\s*\}\}', condition)
            if m:
                expr = m.group(1)
            else:
                expr = ctx.resolve_variables(condition)
            result = eval(expr, eval_globals, eval_locals)
            return bool(result)
        except Exception as e:
            logger.warning(f"Condition eval failed: {condition} -> {e}")
            return False

    async def _run_agent_step(self, step: AgentStep, ctx: WorkflowContext) -> DAGResult:
        prompt = ctx.resolve_variables(step.prompt)
        if self._agent_factory:
            agent = self._agent_factory(step.agent_config)
            output = await agent.run(prompt)
            return DAGResult(status=StepStatus.COMPLETED, output=str(output))
        return DAGResult(status=StepStatus.COMPLETED, output=f"[mock-agent:{step.name}] {prompt[:100]}...")

    async def _run_tool_step(self, step: ToolStep, ctx: WorkflowContext) -> DAGResult:
        params = ctx.resolve_in_dict(step.tool_params)
        handler = self._tool_registry.get(step.tool_name)
        if handler:
            result = handler(**params)
            if asyncio.iscoroutine(result):
                result = await result
            return DAGResult(status=StepStatus.COMPLETED, output=str(result))
        return DAGResult(status=StepStatus.FAILED, error=f"Tool '{step.tool_name}' not found")

    async def _run_transform_step(self, step: TransformStep, ctx: WorkflowContext) -> DAGResult:
        try:
            import json, re
            eval_globals = {"__builtins__": {}, "json": json, "str": str, "int": int,
                            "float": float, "list": list, "dict": dict, "len": len}
            attr_vars = _AttrDict(ctx.vars)
            eval_locals = dict(ctx.vars, vars=attr_vars)
            if step.expression:
                expr = step.expression
                m = re.match(r'\$\{\{\s*(.+?)\s*\}\}', expr)
                if m:
                    expr = m.group(1)
                else:
                    expr = ctx.resolve_variables(expr)
                result = eval(expr, eval_globals, eval_locals)
                return DAGResult(status=StepStatus.COMPLETED, output=str(result))
            if step.output_template:
                output = ctx.resolve_variables(step.output_template)
                return DAGResult(status=StepStatus.COMPLETED, output=output)
        except Exception as e:
            return DAGResult(status=StepStatus.FAILED, error=str(e))
        return DAGResult(status=StepStatus.COMPLETED, output="")

    async def _run_parallel_step(self, step: ParallelStep, ctx: WorkflowContext) -> DAGResult:
        sem = asyncio.Semaphore(step.max_concurrency)
        all_results: list[DAGResult] = []
        branch_tasks = []

        async def run_branch(branch: list[BaseStep], branch_idx: int):
            async with sem:
                branch_results: list[DAGResult] = []
                for s in branch:
                    s.status = StepStatus.RUNNING
                    r = await self._dispatch_step(s, ctx)
                    s.status = r.status
                    ctx.results[s.id] = r
                    branch_results.append(r)
                    if r.status == StepStatus.FAILED:
                        break
                all_results.extend(branch_results)

        for i, branch in enumerate(step.branches):
            branch_tasks.append(run_branch(branch, i))

        await asyncio.gather(*branch_tasks, return_exceptions=True)

        if step.aggregator == "join":
            output = "\n".join(
                r.output for r in all_results if r.status == StepStatus.COMPLETED
            )
        elif step.aggregator == "first":
            output = next(
                (r.output for r in all_results if r.status == StepStatus.COMPLETED), ""
            )
        elif step.aggregator == "merge_json":
            import json
            merged = {}
            for r in all_results:
                if r.status == StepStatus.COMPLETED and r.output:
                    try:
                        data = json.loads(r.output)
                        if isinstance(data, dict):
                            merged.update(data)
                    except json.JSONDecodeError:
                        pass
            output = json.dumps(merged)
        else:
            output = "\n".join(r.output for r in all_results if r.status == StepStatus.COMPLETED)

        overall = StepStatus.COMPLETED
        errors = [r.error for r in all_results if r.status == StepStatus.FAILED]
        if errors:
            overall = StepStatus.COMPLETED if any(r.success for r in all_results) else StepStatus.FAILED

        return DAGResult(
            status=overall,
            output=output,
            error="; ".join(errors) if errors else "",
            child_results=all_results,
        )

    async def _run_condition_step(self, step: ConditionStep, ctx: WorkflowContext) -> DAGResult:
        import json
        eval_globals = {"__builtins__": {}, "json": json, "str": str, "int": int,
                        "float": float, "list": list, "dict": dict, "len": len}
        resolved = ctx.resolve_variables(step.condition_expression)
        condition_met = False
        try:
            condition_met = bool(eval(resolved, eval_globals, dict(ctx.vars)))
        except Exception as e:
            return DAGResult(status=StepStatus.FAILED, error=f"Condition error: {e}")

        chosen = step.if_steps if condition_met else step.else_steps
        child_results = []
        for s in chosen:
            s.status = StepStatus.RUNNING
            r = await self._dispatch_step(s, ctx)
            s.status = r.status
            ctx.results[s.id] = r
            child_results.append(r)

        output = f"{'IF' if condition_met else 'ELSE'} branch executed: " + "; ".join(
            r.output[:100] for r in child_results if r.status == StepStatus.COMPLETED
        )
        overall = StepStatus.COMPLETED if all(r.success for r in child_results) else StepStatus.FAILED
        return DAGResult(status=overall, output=output, child_results=child_results)

    async def _run_switch_step(self, step: SwitchStep, ctx: WorkflowContext) -> DAGResult:
        import json
        raw = step.switch_expression
        if "${{" in raw:
            value = ctx.resolve_variables(raw)
        else:
            eval_globals = {"__builtins__": {}, "json": json, "str": str, "int": int,
                            "float": float, "list": list, "dict": dict, "len": len}
            try:
                resolved = ctx.resolve_variables(raw)
                value = str(eval(resolved, eval_globals, dict(ctx.vars)))
            except Exception as e:
                return DAGResult(status=StepStatus.FAILED, error=f"Switch error: {e}")

        chosen = step.cases.get(value, step.default_steps)
        child_results = []
        for s in chosen:
            s.status = StepStatus.RUNNING
            r = await self._dispatch_step(s, ctx)
            s.status = r.status
            ctx.results[s.id] = r
            child_results.append(r)

        output = f"Case '{value}' executed: " + "; ".join(
            r.output[:100] for r in child_results if r.status == StepStatus.COMPLETED
        )
        overall = StepStatus.COMPLETED if all(r.success for r in child_results) else StepStatus.FAILED
        return DAGResult(status=overall, output=output, child_results=child_results)

    async def _run_loop_step(self, step: LoopStep, ctx: WorkflowContext) -> DAGResult:
        iterations = 0
        all_results: list[DAGResult] = []

        import json, re
        eval_globals = {"__builtins__": {}, "json": json, "str": str, "int": int,
                        "float": float, "list": list, "dict": dict, "len": len}
        attr_vars = _AttrDict(ctx.vars)
        eval_locals = dict(ctx.vars, vars=attr_vars)

        def _resolve_expr(raw: str) -> str:
            m = re.match(r'\$\{\{\s*(.+?)\s*\}\}', raw)
            if m:
                return m.group(1)
            return ctx.resolve_variables(raw)

        items = []
        if step.for_items:
            expr = _resolve_expr(step.for_items)
            try:
                items = list(eval(expr, eval_globals, eval_locals))
            except Exception:
                items = []

        for iteration in range(step.max_iterations):
            if step.for_items:
                if iteration >= len(items):
                    break
                ctx.vars[step.item_variable] = items[iteration]
                eval_locals = dict(ctx.vars, vars=_AttrDict(ctx.vars))
            elif step.while_condition:
                expr = _resolve_expr(step.while_condition)
                try:
                    if not eval(expr, eval_globals, eval_locals):
                        break
                except Exception:
                    break

            for s in step.loop_body:
                s.status = StepStatus.RUNNING
                r = await self._dispatch_step(s, ctx)
                s.status = r.status
                ctx.results[s.id] = r
                r.metadata["iteration"] = iteration
                all_results.append(r)

            iterations += 1
            if iterations >= step.max_iterations:
                break

        output = f"Loop executed {iterations} iterations"
        overall = StepStatus.COMPLETED
        errors = [r.error for r in all_results if r.status == StepStatus.FAILED]
        if errors:
            overall = StepStatus.COMPLETED if any(r.success for r in all_results) else StepStatus.FAILED
        return DAGResult(status=overall, output=output, error="; ".join(errors) if errors else "",
                         child_results=all_results)

    async def _run_human_handoff_step(self, step: HumanHandoffStep, ctx: WorkflowContext) -> DAGResult:
        message = ctx.resolve_variables(step.message)
        prompt = ctx.resolve_variables(step.prompt)

        ctx.status = WorkflowStatus.PAUSED
        step.status = StepStatus.WAITING_HUMAN

        event_id = f"{ctx.workflow_id}:{step.id}"
        event = asyncio.Event()
        self._handoff_events[event_id] = event

        if self._handoff_callback:
            await self._handoff_callback({
                "step_id": step.id,
                "workflow_id": ctx.workflow_id,
                "message": message,
                "prompt": prompt,
                "channel": step.channel,
                "event": event,
            })

        return DAGResult(status=StepStatus.WAITING_HUMAN, output=f"Awaiting human input for step '{step.id}'")

    async def _run_subworkflow_step(self, step: SubWorkflowStep, ctx: WorkflowContext) -> DAGResult:
        if step.workflow_name and step.workflow_name in self._sub_engines:
            sub_engine = self._sub_engines[step.workflow_name]
            sub_ctx = await sub_engine.run(
                DAGWorkflow(name=step.workflow_name),
                vars={**ctx.vars, **step.workflow_vars},
            )
            return DAGResult(
                status=StepStatus.COMPLETED if sub_ctx.status == WorkflowStatus.COMPLETED else StepStatus.FAILED,
                output=sub_ctx.error if sub_ctx.status == WorkflowStatus.FAILED else f"Sub-workflow completed",
                child_results=list(sub_ctx.results.values()),
            )
        return DAGResult(status=StepStatus.FAILED, error=f"Sub-workflow '{step.workflow_name}' not found")

    async def _run_default_step(self, step: BaseStep, ctx: WorkflowContext) -> DAGResult:
        return DAGResult(status=StepStatus.COMPLETED, output=f"[{step.step_type}:{step.name}]")

    def register_sub_engine(self, name: str, engine: DAGEngine):
        self._sub_engines[name] = engine

    async def resume_handoff(self, workflow_id: str, step_id: str, response: str) -> bool:
        ctx = self._active_contexts.get(workflow_id)
        if not ctx:
            return False
        ctx.status = WorkflowStatus.RUNNING
        ctx.results[step_id] = DAGResult(status=StepStatus.COMPLETED, output=response)
        step = next((s for s in ctx.workflow.all_steps_flat() if s.id == step_id), None)
        if step:
            step.status = StepStatus.COMPLETED
        await self._execute_dag(ctx.workflow, ctx)
        return True


@dataclass
class WorkflowInstance:
    workflow: DAGWorkflow
    context: WorkflowContext
    engine: DAGEngine
    created_at: float = field(default_factory=time.time)


class WorkflowManager:
    def __init__(self, engine: DAGEngine | None = None):
        self._engine = engine or DAGEngine()
        self._workflows: dict[str, DAGWorkflow] = {}
        self._instances: dict[str, WorkflowInstance] = {}

    @property
    def engine(self) -> DAGEngine:
        return self._engine

    def register_workflow(self, workflow: DAGWorkflow):
        self._workflows[workflow.id] = workflow
        self._workflows[workflow.name] = workflow

    def get_workflow(self, identifier: str) -> DAGWorkflow | None:
        return self._workflows.get(identifier)

    def list_workflows(self) -> list[DAGWorkflow]:
        return list(self._workflows.values())

    async def run_workflow(self, workflow_id: str, vars: dict[str, Any] | None = None) -> WorkflowContext:
        wf = self.get_workflow(workflow_id)
        if not wf:
            raise ValueError(f"Workflow '{workflow_id}' not found")
        ctx = await self._engine.run(wf, vars)
        inst = WorkflowInstance(workflow=wf, context=ctx, engine=self._engine)
        self._instances[ctx.workflow_id] = inst
        return ctx

    async def run_workflow_direct(self, workflow: DAGWorkflow,
                                  vars: dict[str, Any] | None = None) -> WorkflowContext:
        ctx = await self._engine.run(workflow, vars)
        inst = WorkflowInstance(workflow=workflow, context=ctx, engine=self._engine)
        self._instances[ctx.workflow_id] = inst
        return ctx

    def get_instance(self, instance_id: str) -> WorkflowInstance | None:
        return self._instances.get(instance_id)

    def list_instances(self) -> list[WorkflowInstance]:
        return list(self._instances.values())

    async def resume_handoff(self, instance_id: str, step_id: str, response: str) -> bool:
        return await self._engine.resume_handoff(instance_id, step_id, response)
