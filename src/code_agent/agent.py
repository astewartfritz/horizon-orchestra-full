from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from code_agent.config import AgentConfig
from code_agent.llm.base import LLM, Message, LLMError
from code_agent.memory.base import Memory, NullMemory, JSONMemory, SQLiteMemory
from code_agent.memory.manager import MemoryManager
from code_agent.memory.tool import MemoryTool
from code_agent.tools.base import Tool, ToolResult
from code_agent.tools import CORE_TOOLS
from code_agent.reasoning.engine import ReasoningEngine
from code_agent.reasoning.saver import ModuleSaver
from code_agent.mdconfig.loader import MarkdownConfigLoader, AgentMdConventions
from code_agent.guardrails.policy import Guardrails, CheckResult
from code_agent.guardrails.nemoclaw import Nemoclaw, NemoclawConfig
from code_agent.trace.collector import TraceCollector, EventType
from code_agent.skills.base import SkillLibrary
from code_agent.skills.manager import SkillManager, Embedder
from code_agent.skills.tool import SkillTool
from code_agent.skills.v2 import SkillManagerV2, PersistentTrainer, CreditStore, SkillEvaluator, EvalStore

DEFAULT_SYSTEM_PROMPT = """You are an autonomous code agent. Use tools to accomplish tasks — do not just describe what to do. Start immediately, use one tool per turn, read before modifying, verify results, finish with a summary. If a tool errors, fix and retry. Keep arguments precise."""


@dataclass
class AgentState:
    iterations: int = 0
    tool_rounds: int = 0
    last_error: str | None = None
    finished: bool = False
    result: str | None = None


class Agent:
    def __init__(
        self,
        config: AgentConfig,
        tools: list[Tool] | None = None,
        custom_tools: list[Tool] | None = None,
        tool_filter: Callable[[str], bool] | None = None,
    ):
        self.config = config
        self.state = AgentState()
        self.llm = LLM(
            provider=config.llm.provider,
            model=config.llm.model,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
            timeout=config.llm.timeout,
        )

        self.memory_manager = MemoryManager()
        self.trace_collector = TraceCollector()
        self.guardrails = Guardrails() if config.enable_guardrails else None
        self.nemoclaw = Nemoclaw(NemoclawConfig(enabled=config.enable_nemoclaw)) if config.enable_nemoclaw else None
        self._guardrails_warnings: list[str] = []
        self._event_queue: asyncio.Queue | None = None

        if config.enable_skills:
            sk_lib = SkillLibrary(db_path=getattr(config.skills, 'library_path', '.agent-skills.db'))
            sk_embed = Embedder()
            self.skill_manager = SkillManager(library=sk_lib, embedder=sk_embed)
            skill_tool = SkillTool(self.skill_manager)

            from code_agent.llm.base import LLM as _LLM
            from code_agent.skills.v2 import SkillLibraryV2
            self.skill_manager_v2 = SkillManagerV2(
                library=SkillLibraryV2(".agent-skills-v2.db"),
                llm=_LLM(provider=config.llm.provider, model=config.llm.model, timeout=config.llm.timeout),
            )
            self.credit_store = CreditStore()
            self.persistent_trainer = PersistentTrainer(store=self.credit_store)
            self.eval_store = EvalStore()
            self._skillv2_step = 0
        else:
            self.skill_manager = None
            skill_tool = None
            self.skill_manager_v2 = None
            self.credit_store = None
            self.persistent_trainer = None

        memory_tool = MemoryTool(self.memory_manager)
        extra_tools = [memory_tool]
        if skill_tool:
            extra_tools.append(skill_tool)
        all_tools = (tools or CORE_TOOLS) + extra_tools + (custom_tools or [])
        self.tools: dict[str, Tool] = {}
        for t_cls in all_tools:
            if isinstance(t_cls, Tool):
                inst = t_cls
            else:
                inst = t_cls()
            if tool_filter is None or tool_filter(inst.spec.name):
                self.tools[inst.spec.name] = inst

        self.tool_specs = [t.spec for t in self.tools.values()]
        self.tool_filter = tool_filter

        self.memory = self._init_memory()
        self.messages: list[Message] = []
        self.reasoning = ReasoningEngine(self.llm, config.reasoning)
        self.module_saver = ModuleSaver()
        self.context_manager = (
            getattr(config, "context_manager", None)
            or __import__("code_agent.context.manager", fromlist=[""]).ContextManager()
        )

    def _init_memory(self) -> Memory:
        mt = self.config.memory_type
        if mt == "none":
            return NullMemory()
        mp = self.config.memory_path or str(
            Path.cwd() / ".code-agent-memory.json"
        )
        if mt == "json":
            return JSONMemory(mp)
        if mt == "sqlite":
            return SQLiteMemory(Path(mp).with_suffix(".db"))
        return NullMemory()

    def set_event_queue(self, queue: asyncio.Queue) -> None:
        self._event_queue = queue

    async def _emit(self, event_type: str, data: Any) -> None:
        if self._event_queue:
            await self._event_queue.put({"type": event_type, "data": data})

    def _build_tool_defs(self) -> list[dict[str, Any]]:
        defs = []
        for spec in self.tool_specs:
            props: dict[str, Any] = {}
            required: list[str] = []
            for pname, pinfo in spec.parameters.items():
                ptype = pinfo.get("type", "string")
                props[pname] = {
                    "type": ptype,
                    "description": pinfo.get("description", ""),
                }
                if "default" not in pinfo:
                    required.append(pname)
            defs.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            })
        return defs

    async def run(self, task: str, stream: bool = False) -> str:
        if stream:
            return await self._run_stream(task)
        return await self._run_loop(task)

    async def _run_stream(self, task: str) -> str:
        tokens: list[str] = []

        def on_token(tok: str) -> None:
            tokens.append(tok)
            try:
                print(tok, end="", flush=True)
            except OSError:
                pass  # stdout may be invalid in background jobs

        self.llm.on_token(on_token)
        result = await self._run_loop(task)
        print()
        self.llm.on_token(None)
        return result

    async def _run_loop(self, task: str) -> str:
        self.state = AgentState()
        # Preserve conversation history set before run() (from chat handler session loading)
        _prior_messages = list(getattr(self, 'messages', []))
        self.messages = await self._build_context(task)
        # Append prior conversation history so answers build on earlier turns
        if _prior_messages:
            # Filter: include non-system messages from prior history (system prompt already in _build_context)
            _prior_content = [m for m in _prior_messages if m.role != "system"]
            self.messages.extend(_prior_content)
        trace_id = self.trace_collector.start_trace(task=task)
        trajectory: list[dict] = []

        # Wire token streaming to event queue when present
        _saved_on_token = self.llm._on_token
        if self._event_queue:
            async def _stream_to_queue(tok: str):
                await self._emit("token", tok)
            async def _stream_both(tok: str):
                await _stream_to_queue(tok)
                cb = _saved_on_token
                if cb:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(tok)
                    else:
                        cb(tok)
            self.llm.on_token(lambda t: asyncio.ensure_future(_stream_both(t)))

        # Phase 1: Thinking / Planning
        await self._emit("move", {"type": "plan", "description": "Analyzing task..."})
        thought = await self.reasoning.think(task, context=self.messages)
        await self._emit("thinking", thought)
        await self._emit("move", {"type": "plan", "description": thought[:300] if thought else "Planning..."})
        self.context_manager.add(thought, tier="critical", source="reasoning")
        if thought and self.config.reasoning.show_thinking:
            self.messages.append(Message(
                role="assistant",
                content=f"[Thinking]\n{thought[:800]}",
            ))
        self.trace_collector.record_thinking(thought[:500] if thought else "", trace_id)

        # GPU-aware mode selection (cached to avoid repeated slow imports)
        _has_gpu = getattr(self, '_gpu_cached', None)
        if _has_gpu is None:
            _has_gpu = False
            try:
                import subprocess
                r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=3)
                _has_gpu = r.returncode == 0
            except Exception:
                _has_gpu = False
            self._gpu_cached = _has_gpu

        if not _has_gpu and thought:
            # Strip thinking formatting for clean answers
            result = thought
            for prefix in ["## Plan", "## plan", "## Summary", "## summary"]:
                if result.startswith(prefix):
                    result = result[len(prefix):].strip()
                    if result.startswith("\n"):
                        result = result[1:].strip()
            self.state.finished = True
            self.state.result = result
            self.reasoning.finish(result)
            # Result already streamed via tokens — no duplicate emit
            self._event_queue = None
            self.llm.on_token(_saved_on_token)
            self.trace_collector.end_trace(trace_id, status="ok")
            return result

        # Phase 2: Execute (tool-calling loop)
        # Enabled automatically when GPU is detected.
        error_count = 0
        iteration = 0
        while iteration < self.config.max_iterations:
            self.state.iterations = iteration
            iteration += 1

            llm_call_id = self.trace_collector.record_llm_call(
                self.llm.provider, self.llm.model, self.messages, trace_id
            )
            await self._emit("move", {"type": "prompt", "iteration": iteration, "description": "Calling LLM..."})
            try:
                response = await self.llm.chat(
                    messages=self.messages,
                    tools=self._build_tool_defs(),
                )
                self.trace_collector.record_llm_response(
                    llm_call_id, response.content or "", trace_id=trace_id,
                )
                if self._event_queue and response.content and not response.tool_calls:
                    await self._emit("token", response.content)
            except LLMError as e:
                self.state.last_error = str(e)
                self.reasoning.record_error(str(e))
                self.trace_collector.record_llm_response(
                    llm_call_id, "", status="error", error=str(e), trace_id=trace_id,
                )
                self.trace_collector.record_error(str(e), "llm", trace_id)
                await self._emit("error", {"message": f"LLM error: {e}"})
                await self._emit("error_llm", {"message": str(e), "iteration": iteration})
                self.memory_manager.remember(
                    content=f"LLM Error: {e}",
                    role="system",
                    tier="important",
                    source="error",
                    importance=0.8,
                )
                self._event_queue = None
                self.llm.on_token(_saved_on_token)
                self.trace_collector.end_trace(trace_id, status="error")
                return f"Error: {e}"

            self.messages.append(response)
            await self._emit("move", {"type": "response", "description": response.content[:300] if response.content else ""})

            if not response.tool_calls:
                content = (response.content or "").strip()
                # If the LLM just produced a long monologue without doing anything,
                # and the task wasn't actually completed, push it to use tools.
                if content and iteration < 3 and not _looks_final(content):
                    self.messages.append(Message(
                        role="user",
                        content="Do not just describe what to do. Call a tool function NOW. "
                                "Pick the most relevant tool and call it with the right arguments.",
                    ))
                    continue
                self.state.finished = True
                self.state.result = content
                self.reasoning.finish(content)
                await self._emit("result", {"content": content[:500]})
                self.memory_manager.remember(
                    content=f"Completed task. Result: {content[:500]}",
                    role="assistant",
                    tier="important",
                    source="completion",
                    importance=0.9,
                )
                if self.reasoning.current_session:
                    self.module_saver.save_from_session(
                        self.reasoning.current_session.to_dict()
                    )
                self.context_manager.add(
                    content=f"Completed: {content[:300]}",
                    tier="important", source="completion",
                )
                self._event_queue = None
                self.llm.on_token(_saved_on_token)
                self.trace_collector.end_trace(trace_id, status="ok")
                if self.skill_manager and self.config.skills.distill_on_completion and trajectory:
                    try:
                        outcome = 1.0 if len(trajectory) > 0 else 0.0
                        await self.skill_manager.distill(task, trajectory, outcome)
                    except Exception:
                        pass
                if self.skill_manager_v2 and trajectory:
                    try:
                        from code_agent.skills.v2 import TaskSpec, SkillV2, Trajectory as V2Traj
                        tspec = TaskSpec(instruction=task, environment="code_agent")
                        v2_traj_steps = [{"tool": s.get("tool", "unknown"), "args": s.get("args", {}), "output": s.get("output", "")[:200]} for s in trajectory]
                        v2_traj = V2Traj(task=tspec, skill_id=0)
                        for step in v2_traj_steps:
                            v2_traj.add_step(obs="", action=step["tool"], reward=1.0 if step["output"] else 0.0, done=False)
                        v2_traj.final_reward = 1.0 if len(trajectory) > 0 else 0.0
                        v2_traj.success = len(trajectory) > 0
                        summary = v2_traj.summarize()
                        policy = self.skill_manager_v2.ensure_policy()
                        distill_out = await policy.distill(task, summary, v2_traj.final_reward, v2_traj.success)
                        new_body = distill_out.content.strip()
                        if new_body and len(new_body) > 20:
                            new_skill = SkillV2(body=new_body, tags=["code_agent"], creation_step=self._skillv2_step)
                            new_skill.id = self.skill_manager_v2.library.add(new_skill)
                            self._skillv2_step += 1
                        credit = self.persistent_trainer.record_episode(
                            outcome=v2_traj.final_reward, utilization_lp=0.5, selection_lp=0.0, distillation_lp=0.5,
                        )
                    except Exception:
                        pass
                return content

            self.state.tool_rounds += 1
            if self.state.tool_rounds > self.config.max_tool_rounds:
                self.reasoning.finish("Max tool rounds reached")
                self._event_queue = None
                self.llm.on_token(_saved_on_token)
                self.trace_collector.end_trace(trace_id, status="cancelled")
                return "Max tool rounds reached."

            for tc in response.tool_calls:
                tool_name = tc["function"]["name"]
                args_raw = tc["function"].get("arguments", "{}")
                try:
                    args = json.loads(args_raw)
                except json.JSONDecodeError:
                    args = {"raw": args_raw[:200]}
                tool_call_id = self.trace_collector.record_tool_call(tool_name, args, trace_id)
                action_type = _classify_tool(tool_name)
                await self._emit("tool_call", {
                    "name": tool_name, "arguments": args, "id": tc["id"],
                    "action_type": action_type,
                })
                await self._emit("move", {"type": f"tool:{action_type}", "tool": tool_name,
                    "description": _summarize_tool_call(tool_name, args)})
                result = await self._execute_tool(tool_name, tc)
                if self._guardrails_warnings and result and not result.error:
                    warning_text = "\n[Guardrails]\n" + "\n".join(self._guardrails_warnings)
                    result.output = (result.output or "") + warning_text
                await self._emit("tool_result", {
                    "name": tool_name, "id": tc["id"],
                    "output": result.output if result else "",
                    "error": result.error if result else "",
                })
                self.trace_collector.record_tool_result(
                    tool_call_id, result.output if result else "",
                    status="error" if (result and result.error) else "ok",
                    error=result.error if result else "",
                    trace_id=trace_id,
                )

                trajectory.append({"tool": tool_name, "args": args, "output": result.output[:200] if result else ""})

                tool_msg = Message(
                    role="tool",
                    content=result.output if result else "",
                    tool_call_id=tc["id"],
                    name=tool_name,
                )

                # Phase 3: Reflect on errors
                if result and result.error:
                    error_count += 1
                    self.trace_collector.record_error(result.error, tool_name, trace_id)
                    msg = f"Error executing {tool_name}: {result.error}"
                    if result.output:
                        msg += f"\nOutput: {result.output}"
                    tool_msg.content = msg[:10000]
                    tool_msg.role = "tool"
                    self.reasoning.record_error(result.error)
                    self.context_manager.add(result.error, tier="important", source="error")

                    # Reflect after repeated errors
                    if error_count >= 2 and error_count % 2 == 0:
                        reflection = await self.reasoning.reflect_on_error(
                            result.error,
                            context=f"Tool: {tool_name}\nArgs: {args}",
                        )
                        self.context_manager.add(reflection, tier="important", source="reflection")
                        self.trace_collector.record_thinking(f"Reflection: {reflection[:300]}", trace_id)
                        self.messages.append(Message(
                            role="assistant",
                            content=f"[Reflection]\n{reflection}",
                        ))

                self.messages.append(tool_msg)
                self.context_manager.add(
                    tool_msg.content[:200], tier="normal", source=tool_name
                )
                await self.memory.save(
                    __import__("code_agent.memory.base", fromlist=[""]).MemoryEntry(
                        role="tool",
                        content=tool_msg.content or "",
                        tool_call_id=tc["id"],
                        name=tool_name,
                    )
                )
                self.memory_manager.remember(
                    content=tool_msg.content[:1000] or "",
                    role="tool",
                    tier="normal" if not result.error else "important",
                    source=tool_name,
                    importance=0.9 if result.error else 0.5,
                )

            # Phase 4: Periodically verify progress
            if self.config.reasoning.verify_steps and iteration > 0 and iteration % 5 == 0:
                self.messages.append(Message(
                    role="user",
                    content="[Progress Check] What have you accomplished so far? "
                            "Are you still on track? If stuck, what's blocking you?",
                ))

        self.reasoning.finish("Max iterations reached")
        self._event_queue = None
        self.llm.on_token(_saved_on_token)
        self.trace_collector.end_trace(trace_id, status="cancelled")
        return "Max iterations reached without completing the task."

    async def _execute_tool(self, tool_name: str, tc: dict) -> ToolResult:
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    if attempt < max_retries:
                        error_msg = f"Invalid JSON arguments: {tc['function']['arguments'][:200]}"
                        error_fix_msg = Message(
                            role="tool",
                            content=error_msg,
                            tool_call_id=tc["id"],
                            name=tool_name,
                        )
                        self.messages.append(error_fix_msg)
                        correction = await self.llm.chat(
                            messages=self.messages[:-1] + [Message(
                                role="assistant",
                                content=f"The tool call had invalid JSON arguments. Please retry with valid JSON for {tool_name}.",
                                tool_calls=[tc],
                            )],
                        )
                        if correction.tool_calls:
                            tc = correction.tool_calls[0]
                            continue
                    return ToolResult(error=f"Invalid JSON args: {tc['function']['arguments'][:200]}")

                self._guardrails_warnings = []
                if self.guardrails:
                    results = self.guardrails.check_tool_call(tool_name, args)
                    if results:
                        summary = self.guardrails.summary(results)
                        if self.guardrails.has_blocks(results):
                            return ToolResult(error=f"Guardrails blocked: {summary}")
                        self._guardrails_warnings = [r.message for r in results if not r.passed]
                        self.memory_manager.remember(
                            content=f"Guardrails warning for {tool_name}: {summary}",
                            role="system", tier="normal", source="guardrails", importance=0.3,
                        )
                if self.nemoclaw:
                    ncheck = await self.nemoclaw.check_tool_call(tool_name, args)
                    if ncheck.severity == "block":
                        return ToolResult(error=f"Nemoclaw blocked: {ncheck.reasoning}")
                    if ncheck.severity == "warning":
                        self._guardrails_warnings.append(f"Nemoclaw: {ncheck.reasoning}")
                        self.context_manager.add(
                            content=f"Nemoclaw: {tool_name} - {ncheck.reasoning}",
                            tier="important", source="nemoclaw",
                        )

                tool = self.tools.get(tool_name)
                if not tool:
                    return ToolResult(error=f"Unknown tool: {tool_name}")

                if self.config.confirm_commands and tool.spec.requires_confirmation:
                    print(f"[CONFIRM] {tool_name}({args})? (y/N)")
                    confirm = input().strip().lower()
                    if confirm != "y":
                        return ToolResult(error="Cancelled by user")

                result = await tool(**args)
                self.context_manager.add(
                    content=f"{tool_name}: {result.output[:200] if result.output else '(no output)'}",
                    tier="normal", source=f"tool:{tool_name}",
                )
                return result

            except Exception as e:
                if attempt < max_retries:
                    await asyncio.sleep(0.5)
                    continue
                return ToolResult(error=str(e))

        return ToolResult(error="Max retries exceeded")

    async def _build_context(self, task: str) -> list[Message]:
        system = self.config.system_prompt or self.reasoning._get_prompt() or DEFAULT_SYSTEM_PROMPT
        ws = self.config.workspace or str(Path.cwd())
        system += f"\n\nWorkspace: {ws}"

        messages = [Message(role="system", content=system)]

        # Load structured markdown configs
        try:
            conventions = AgentMdConventions()
            ctx_parts = conventions.format_for_context()
            if ctx_parts:
                messages.append(
                    Message(role="user", content=f"Project Configuration:\n{ctx_parts[:800]}")
                )
        except Exception:
            # Fallback to raw file reads
            ws_path = Path(ws)
            for fname in ["CLAUDE.md", "AGENTS.md"]:
                p = ws_path / fname
                if p.exists():
                    tag = "conventions" if fname == "CLAUDE.md" else "instructions"
                    messages.append(
                        Message(
                            role="user",
                            content=f"Project {tag} ({fname}):\n{p.read_text('utf-8')[:500]}",
                        )
                    )

        # Load .md config files from .agent-mdconfig/ directory
        mdconfig_dir = Path(ws) / ".agent-mdconfig"
        if mdconfig_dir.exists():
            for f in sorted(mdconfig_dir.glob("*.md")):
                try:
                    from code_agent.mdconfig.parser import extract_frontmatter
                    fm = extract_frontmatter(f)
                    dtype = fm.get("type", fm.get("prompt", fm.get("tool", "config")))
                    messages.append(
                        Message(
                            role="user",
                            content=f"[{dtype}: {f.stem}]\n{f.read_text('utf-8')[:400]}",
                        )
                    )
                except Exception:
                    pass

        # Retrieve relevant memories for context
        try:
            memory_context = self.memory_manager.get_context(task, max_tokens=800)
            if memory_context:
                messages.append(Message(
                    role="user",
                    content=f"[Relevant Past Memories]\n{memory_context}",
                ))
        except Exception:
            pass

        # Retrieve relevant skills for context
        if self.skill_manager:
            try:
                skills = await self.skill_manager.retrieve(task, top_k=self.config.skills.retrieval_top_k)
                if skills:
                    sk_lines = []
                    for s in skills:
                        sk_lines.append(f"## {s.name}\n{s.description}\n\nProcedure:\n{s.procedure[:500]}")
                    messages.append(Message(
                        role="user",
                        content=f"[Relevant Skills]\n{chr(10).join(sk_lines)}",
                    ))
            except Exception:
                pass

        # v2 skill retrieval
        if self.skill_manager_v2:
            try:
                v2_results = self.skill_manager_v2.library.search(task, top_k=2)
                if v2_results:
                    v2_lines = []
                    for score, sv2 in v2_results:
                        v2_lines.append(f"- [{sv2.id}] (score={score:.2f}) {sv2.body[:200]}")
                    messages.append(Message(
                        role="user",
                        content=f"[Skill Library v2]\n{chr(10).join(v2_lines)}",
                    ))
            except Exception:
                pass

        # Inject capability awareness — tell the agent what tools and capabilities are available
        try:
            from code_agent.agentic.navigator import CapabilityRegistry
            caps = CapabilityRegistry()
            cap_text = caps.format_for_prompt()
            messages.append(Message(role="user", content=cap_text[:1200]))
        except Exception:
            pass

        # Inject project structure summary
        try:
            from code_agent.agentic.navigator import ProjectNavigator
            navigator = ProjectNavigator(ws)
            summary = navigator.summarize()
            project_info = f"[Project]\nRoot: {summary['root']}\nFiles: {summary['total_files']}\nLines: {summary['total_lines']}\nTypes: {', '.join(f'{ext}: {count}' for ext, count in list(summary['file_types'].items())[:8])}"
            messages.append(Message(role="user", content=project_info[:600]))
        except Exception:
            pass

        # Inject language-specific context (build/test/lint commands for detected project)
        try:
            from code_agent.scaffold.context import LanguageDetector
            detector = LanguageDetector(ws)
            lang = detector.detect()
            if lang:
                lctx = LanguageDetector.format_context(lang)
                messages.append(
                    Message(role="user", content=lctx,
                ))
        except Exception:
            pass

        # Layered retrieval: query web + skills + knowledge base for relevant evidence
        try:
            from code_agent.context.retrieval import RetrievalPipeline
            pipeline = RetrievalPipeline()
            evidence = await pipeline.retrieve_and_format(task, max_tokens=1200)
            if evidence and len(evidence) > 50:
                messages.append(Message(
                    role="user",
                    content=f"[Retrieved Evidence]\n{evidence}",
                ))
        except Exception:
            pass

        # Store task in memory
        try:
            self.memory_manager.remember(
                content=f"Task: {task}",
                role="user",
                tier="important",
                source="task",
                importance=0.9,
            )
        except Exception:
            pass

        messages.append(Message(role="user", content=task))
        return messages

    def get_tools_summary(self) -> str:
        lines = ["Available tools:"]
        for spec in self.tool_specs:
            lines.append(f"  {spec.name}: {spec.description}")
        return "\n".join(lines)


def _looks_final(content: str) -> bool:
    c = content.lower().strip()
    if len(c) < 20:
        return True
    if "## plan" in c or "## summary" in c or "## done" in c:
        return True
    final_phrases = [
        "task is complete", "task complete", "all done", "finished",
        "here's a summary", "here is a summary", "here's what i did",
        "here is what i did", "successfully", "completed the task",
    ]
    for p in final_phrases:
        if p in c:
            return True
    return False


def _classify_tool(name: str) -> str:
    name_l = name.lower()
    if name_l in ("write", "edit", "apply_edit", "patch"):
        return "edit"
    if name_l in ("read",):
        return "read"
    if name_l in ("glob", "grep", "index", "semsearch", "search"):
        return "search"
    if name_l in ("bash", "sandbox", "command"):
        return "command"
    if name_l in ("git", "commit", "push"):
        return "git"
    if name_l in ("webfetch", "websearch"):
        return "web"
    if name_l in ("task",):
        return "agent"
    if name_l in ("diff",):
        return "diff"
    if name_l in ("knowledge", "memory", "memsearch"):
        return "knowledge"
    return "tool"


def _summarize_tool_call(name: str, args: dict) -> str:
    name_l = name.lower()
    if name_l == "write":
        fp = args.get("file_path", "")
        return f"Write {fp}" if fp else "Write file"
    if name_l == "edit":
        fp = args.get("file_path", "")
        return f"Edit {fp}" if fp else "Edit file"
    if name_l == "read":
        fp = args.get("file_path", "")
        return f"Read {fp}" if fp else "Read file"
    if name_l == "bash":
        cmd = args.get("command", "")
        return f"Run: {cmd[:80]}" if cmd else "Run command"
    if name_l == "glob":
        pat = args.get("pattern", "")
        return f"Glob {pat}" if pat else "Find files"
    if name_l == "grep":
        pat = args.get("pattern", "")
        return f"Search {pat[:60]}" if pat else "Search files"
    if name_l == "git":
        action = args.get("action", args.get("command", ""))
        return f"Git: {action[:60]}" if action else "Git operation"
    if name_l == "webfetch":
        url = args.get("url", "")
        return f"Fetch {url[:60]}" if url else "Web fetch"
    if name_l == "websearch":
        q = args.get("query", "")
        return f"Search: {q[:60]}" if q else "Web search"
    return f"{name}(...)"
