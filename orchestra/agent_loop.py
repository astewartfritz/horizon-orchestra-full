"""Horizon Orchestra — Async Agent Loop with Tool Calling.

Core execution engine: a single agent that calls tools iteratively
until the task is complete.  Designed for Kimi K2.5's 200-300 stable
sequential tool-call capability, but works with any OpenAI-compatible
model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Awaitable

import httpx

from .router import ModelRouter

# ── Parsing integration (lazy — no hard dependency) ──────────────────────────
try:
    from .checkpoint import CheckpointStore as _CheckpointStore, WorkflowCheckpoint as _WorkflowCheckpoint
    _CHECKPOINT_AVAILABLE = True
except Exception:
    _CheckpointStore = _WorkflowCheckpoint = None  # type: ignore
    _CHECKPOINT_AVAILABLE = False

try:
    from .parsing.json_healer import JSONHealer as _JSONHealer
    from .parsing.tool_call_fixer import ToolCallFixer as _ToolCallFixer
    from .parsing.hallucination_scrubber import HallucinationScrubber as _HallucinScrubber
    _PARSING_AVAILABLE = True
    _json_healer = _JSONHealer()
    _tool_fixer   = _ToolCallFixer()
    _hall_scrub   = _HallucinScrubber()
except Exception:
    _PARSING_AVAILABLE = False
    _json_healer = _tool_fixer = _hall_scrub = None  # type: ignore

# ── AuditLedger: record every inference + tool call ─────────────────────────
try:
    from .guardian.audit_ledger import AuditLedger as _AuditLedgerCls
    from .guardian.beyond_guardrails import BeyondGuardrails as _BGCls
    _AUDIT_LEDGER = _AuditLedgerCls()
    _BEYOND_GUARDRAILS = _BGCls()
    _AUDIT_ACTIVE = True
except Exception:
    _AUDIT_LEDGER = _BEYOND_GUARDRAILS = None  # type: ignore
    _AUDIT_ACTIVE = False

# ── Resilience integration (lazy) ────────────────────────────────────────────
try:
    from .resilience.circuit_breaker import CircuitBreaker as _CircuitBreaker
    from .resilience.adaptive_retry import AdaptiveRetryManager as _AdaptiveRetry
    from .resilience.error_taxonomy import ERROR_REGISTRY as _ERR_REG
    _RESILIENCE_AVAILABLE = True
    _circuit_breaker = _CircuitBreaker()
    _retry_mgr       = _AdaptiveRetry()
except Exception:
    _RESILIENCE_AVAILABLE = False
    _circuit_breaker = _retry_mgr = None  # type: ignore

__all__ = [
    "AgentConfig",
    "AgentEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ThinkingEvent",
    "FinalAnswerEvent",
    "ErrorEvent",
    "ToolResult",
    "ToolSpec",
    "ToolRegistry",
    "AgentLoop",
    "create_default_tools",
]

log = logging.getLogger("orchestra.agent_loop")


# ---------------------------------------------------------------------------
# Events emitted by the agent loop
# ---------------------------------------------------------------------------

@dataclass
class ToolCallEvent:
    """The model decided to call a tool."""
    iteration: int
    tool_name: str
    arguments: dict[str, Any]
    tool_call_id: str


@dataclass
class ToolResultEvent:
    """A tool finished executing."""
    iteration: int
    tool_name: str
    result: str
    success: bool
    duration: float


@dataclass
class ThinkingEvent:
    """The model produced intermediate reasoning (no tool calls, not final)."""
    iteration: int
    content: str


@dataclass
class FinalAnswerEvent:
    """The model returned its final answer (no more tool calls)."""
    content: str
    total_iterations: int
    total_tool_calls: int


@dataclass
class ErrorEvent:
    """An error occurred during the loop."""
    message: str
    iteration: int
    recoverable: bool = True


AgentEvent = ToolCallEvent | ToolResultEvent | ThinkingEvent | FinalAnswerEvent | ErrorEvent


# ---------------------------------------------------------------------------
# Tool infrastructure
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    result: str
    success: bool


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[str]]


class ToolRegistry:
    """Register and manage available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Awaitable[str]],
    ) -> None:
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Return tools in OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict[str, Any], call_id: str = "") -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(
                tool_call_id=call_id,
                name=name,
                result=json.dumps({"error": f"Unknown tool: {name}"}),
                success=False,
            )
        try:
            result = await spec.handler(**arguments)
            return ToolResult(tool_call_id=call_id, name=name, result=result, success=True)
        except Exception as exc:
            log.exception("Tool %s raised an exception", name)
            return ToolResult(
                tool_call_id=call_id,
                name=name,
                result=json.dumps({"error": str(exc)}),
                success=False,
            )

    def subset(self, names: list[str]) -> "ToolRegistry":
        """Return a new registry containing only the named tools."""
        sub = ToolRegistry()
        for n in names:
            spec = self._tools.get(n)
            if spec:
                sub._tools[n] = spec
        return sub


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

@dataclass
class AgentConfig:
    model: str = "kimi-k2.5"
    max_iterations: int = 300
    max_tokens: int = 16384
    temperature: float = 0.6
    system_prompt: str = (
        "You are an autonomous agent in Horizon Orchestra. "
        "You have access to tools. Break complex tasks into steps. "
        "Use tools iteratively until the task is fully complete. "
        "When finished, respond with your final answer."
    )
    enable_structured_thinking: bool = False


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

class AgentLoop:
    """Core agent execution loop with tool calling."""

    def __init__(
        self,
        router: ModelRouter,
        tools: ToolRegistry,
        config: AgentConfig | None = None,
        checkpoint_store: Any | None = None,
        job_id: str | None = None,
    ) -> None:
        self.router = router
        self.tools = tools
        self.config = config or AgentConfig()
        # Checkpoint support: persist messages after each iteration so a
        # crashed workflow can resume rather than restarting from scratch.
        self._checkpoint_store = checkpoint_store
        self._job_id = job_id

    async def _structured_think(self, task: str, client: Any, model_id: str) -> str:
        """Make one focused reasoning pass before acting.

        Returns a formatted string: understand / approach / risks.
        Falls back to empty string on any failure so the main loop is unaffected.
        """
        prompt = (
            "Before acting, reason briefly about this task. "
            "Reply with ONLY valid JSON — no markdown, no prose — in this exact shape:\n"
            '{"understand": "one sentence: what is actually being asked", '
            '"approach": "one sentence: how you will tackle it", '
            '"risks": "one sentence: what could go wrong"}\n\n'
            f"Task: {task}"
        )
        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.3,
            )
            raw = (resp.choices[0].message.content or "").strip()
            # strip markdown fences if the model wraps it anyway
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            return (
                f"Understand: {data.get('understand', '')}\n"
                f"Approach:   {data.get('approach', '')}\n"
                f"Risks:      {data.get('risks', '')}"
            )
        except Exception:
            return ""

    async def run(
        self,
        task: str,
        context: str = "",
    ) -> AsyncGenerator[AgentEvent, None]:
        """Run the agent loop, yielding events as it progresses.

        The loop continues until the model responds without tool calls
        (signalling completion) or ``max_iterations`` is reached.
        """
        client, model_id = self.router.get_client(self.config.model)
        openai_tools = self.tools.get_openai_tools() or None

        if self.config.enable_structured_thinking:
            thinking_text = await self._structured_think(task, client, model_id)
            if thinking_text:
                yield ThinkingEvent(iteration=0, content=thinking_text)

        # ── Checkpoint resume ─────────────────────────────────────────────
        start_iteration = 1
        total_tool_calls = 0
        if self._checkpoint_store is not None and self._job_id is not None:
            _cp = self._checkpoint_store.load(self._job_id)
        else:
            _cp = None

        if _cp is not None:
            messages = _cp.messages
            start_iteration = _cp.iteration + 1
            total_tool_calls = _cp.total_tool_calls
            log.info(
                "Resuming job %s from iteration %d (%d tool calls already done)",
                self._job_id, start_iteration, total_tool_calls,
            )
        else:
            messages = [{"role": "system", "content": self.config.system_prompt}]
            if context:
                messages.append({
                    "role": "user",
                    "content": f"Prior context:\n\n{context}\n\nTask: {task}",
                })
            else:
                messages.append({"role": "user", "content": task})

        for iteration in range(start_iteration, self.config.max_iterations + 1):
            # ── Resilience: check circuit breaker before API call ──────────────
            provider = getattr(self.router.models.get(self.config.model), "provider", "unknown")
            if _RESILIENCE_AVAILABLE and _circuit_breaker is not None:
                _cb_result = _circuit_breaker.check(provider, self.config.model, "chat")
                import inspect as _inspect
                if _inspect.iscoroutine(_cb_result):
                    cb_allowed, cb_reason = await _cb_result
                else:
                    cb_allowed, cb_reason = _cb_result
                if not cb_allowed:
                    yield ErrorEvent(
                        message=f"Circuit breaker OPEN for {provider}/{self.config.model}: {cb_reason}",
                        iteration=iteration,
                        recoverable=True,
                    )
                    return

            _t0 = time.monotonic()
            try:
                response = await client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto" if openai_tools else None,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                )
                # ── Record success in circuit breaker ──
                if _RESILIENCE_AVAILABLE and _circuit_breaker is not None:
                    await _circuit_breaker.record_success(
                        provider, self.config.model,
                        int((time.monotonic() - _t0) * 1000)
                    )
            except Exception as exc:
                _latency_ms = int((time.monotonic() - _t0) * 1000)
                # ── Record failure + classify error ──
                if _RESILIENCE_AVAILABLE and _circuit_breaker is not None:
                    _error_type = str(type(exc).__name__)
                    await _circuit_breaker.record_failure(provider, self.config.model, _error_type, _latency_ms)
                # ── Check if we should retry via adaptive retry manager ──
                if _RESILIENCE_AVAILABLE and _retry_mgr is not None:
                    _decision = _retry_mgr.should_retry(iteration, exc, _latency_ms)
                    _should = _decision.should_retry if hasattr(_decision, "should_retry") else _decision[0]
                    _delay = _decision.delay_ms if hasattr(_decision, "delay_ms") else _decision[1]
                    if _should and iteration < self.config.max_iterations:
                        log.debug("Adaptive retry in %.0fms (attempt %d)", _delay, iteration)
                        await asyncio.sleep(_delay / 1000.0)
                        continue  # retry the same iteration
                yield ErrorEvent(
                    message=f"API call failed: {exc}",
                    iteration=iteration,
                    recoverable=False,
                )
                return

            choice = response.choices[0]
            assistant_msg = choice.message

            # Append raw assistant message to history
            msg_dict: dict[str, Any] = {"role": "assistant"}
            if assistant_msg.content:
                msg_dict["content"] = assistant_msg.content
            if assistant_msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ]
            messages.append(msg_dict)

            # ── No tool calls → we're done ────────────────────────────────
            if not assistant_msg.tool_calls:
                content = assistant_msg.content or ""
                # ── Hallucination scrub on final answer ──────────────────
                if _PARSING_AVAILABLE and _hall_scrub is not None and content:
                    try:
                        content, _h_report = _hall_scrub.scrub(content)
                        if _h_report.severity > 0.5:
                            log.warning(
                                "High hallucination score (%.2f) on final answer",
                                _h_report.severity,
                            )
                    except Exception:
                        pass  # never let scrubbing block the answer
                yield FinalAnswerEvent(
                    content=content,
                    total_iterations=iteration,
                    total_tool_calls=total_tool_calls,
                )
                # Clean up checkpoint on successful completion
                if self._checkpoint_store is not None and self._job_id is not None:
                    try:
                        self._checkpoint_store.delete(self._job_id)
                    except Exception:
                        pass
                return

            # ── Parse all tool arguments first (fast, no I/O) ─────────────
            parsed_calls: list[tuple[Any, dict[str, Any]]] = []
            for tc in assistant_msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    # ── JSON healer: repair malformed tool arguments ──────
                    if _PARSING_AVAILABLE and _json_healer is not None:
                        try:
                            args, _repairs = _json_healer.heal(tc.function.arguments)
                            if not isinstance(args, dict):
                                args = {}
                            elif _repairs:
                                log.debug(
                                    "JSONHealer applied %d repairs to tool args",
                                    len(_repairs),
                                )
                        except Exception:
                            args = {}
                    else:
                        args = {}
                parsed_calls.append((tc, args))

            # ── Emit ToolCallEvents before dispatching ─────────────────────
            for tc, args in parsed_calls:
                yield ToolCallEvent(
                    iteration=iteration,
                    tool_name=tc.function.name,
                    arguments=args,
                    tool_call_id=tc.id,
                )

            # ── Execute all tool calls in parallel ─────────────────────────
            _t_tools = time.monotonic()
            tool_results = await asyncio.gather(*[
                self.tools.execute(tc.function.name, args, tc.id)
                for tc, args in parsed_calls
            ])
            _tools_elapsed = time.monotonic() - _t_tools
            total_tool_calls += len(tool_results)

            # ── Emit results and append tool messages ──────────────────────
            for (tc, _args), result in zip(parsed_calls, tool_results):
                yield ToolResultEvent(
                    iteration=iteration,
                    tool_name=tc.function.name,
                    result=result.result[:500],
                    success=result.success,
                    duration=_tools_elapsed,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.result,
                })

            # ── Checkpoint after each iteration ────────────────────────────
            if self._checkpoint_store is not None and self._job_id is not None:
                try:
                    self._checkpoint_store.save(_WorkflowCheckpoint(
                        job_id=self._job_id,
                        task=task,
                        messages=messages,
                        iteration=iteration,
                        total_tool_calls=total_tool_calls,
                    ))
                except Exception as _cp_exc:
                    log.warning("Checkpoint save failed: %s", _cp_exc)

        # Max iterations reached
        yield ErrorEvent(
            message=f"Max iterations ({self.config.max_iterations}) reached.",
            iteration=self.config.max_iterations,
            recoverable=False,
        )


# ---------------------------------------------------------------------------
# Built-in tool implementations
# ---------------------------------------------------------------------------

async def tool_web_search(
    query: str,
    recency: str = "month",
    domains: list[str] | None = None,
) -> str:
    """Search the web using Perplexity Sonar (or return a stub)."""
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        return json.dumps({
            "note": "No PERPLEXITY_API_KEY set. Returning stub.",
            "query": query,
            "results": [],
        })

    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url="https://api.perplexity.ai", api_key=api_key)
    kwargs: dict[str, Any] = {
        "model": "sonar",
        "messages": [{"role": "user", "content": query}],
    }
    # Sonar-specific params (passed as extra_body)
    extra: dict[str, Any] = {}
    if recency:
        extra["search_recency_filter"] = recency
    if domains:
        extra["search_domain_filter"] = domains
    if extra:
        kwargs["extra_body"] = extra

    try:
        resp = await client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        citations = getattr(resp, "citations", []) or []
        return json.dumps({"content": content, "citations": citations})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def tool_fetch_url(url: str, extract_prompt: str | None = None) -> str:
    """Fetch and extract content from a URL."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url, headers={"User-Agent": "HorizonOrchestra/1.0"})
            resp.raise_for_status()
            text = resp.text[:50_000]
        return json.dumps({"url": url, "length": len(text), "content": text})
    except Exception as exc:
        return json.dumps({"error": str(exc), "url": url})


async def tool_execute_code(
    code: str,
    language: str = "python",
    timeout: int = 30,
) -> str:
    """Execute code in a subprocess sandbox."""
    if language not in ("python", "bash"):
        return json.dumps({"error": f"Unsupported language: {language}"})

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py" if language == "python" else ".sh",
        delete=False,
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        cmd = ["python3", tmp_path] if language == "python" else ["bash", tmp_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return json.dumps({"error": "Execution timed out", "timeout": timeout})

        return json.dumps({
            "exit_code": proc.returncode,
            "stdout": stdout.decode(errors="replace")[:20_000],
            "stderr": stderr.decode(errors="replace")[:5_000],
        })
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def tool_file_read(path: str) -> str:
    """Read a workspace file."""
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return json.dumps({"path": path, "length": len(content), "content": content[:50_000]})
    except Exception as exc:
        return json.dumps({"error": str(exc), "path": path})


async def tool_file_write(path: str, content: str) -> str:
    """Write to a workspace file."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return json.dumps({"path": path, "bytes_written": len(content)})
    except Exception as exc:
        return json.dumps({"error": str(exc), "path": path})


async def tool_browser_action(
    url: str,
    action: str = "navigate",
    selector: str = "",
    value: str = "",
) -> str:
    """Browser automation placeholder (implement with Playwright)."""
    return json.dumps({
        "note": "Browser automation not yet wired. Implement with Playwright.",
        "url": url,
        "action": action,
    })


# ---------------------------------------------------------------------------
# OpenCode tool
# ---------------------------------------------------------------------------


async def tool_opencode_task(prompt: str) -> str:
    """Delegate a software-engineering task to the OpenCode agent.

    OpenCode is a specialised tool-use agent for coding tasks. It has
    full access to the workspace filesystem, shell commands, and git.

    This tool runs OpenCode's CLI as a subprocess and returns the
    result as a JSON string.
    """
    try:
        from .opencode_provider import OpenCodeConfig, OpenCodeProvider

        provider = OpenCodeProvider(
            config=OpenCodeConfig(working_dir=os.getcwd()),
        )
        result = await provider.run_task(prompt)
        return json.dumps({
            "success": result.success,
            "summary": result.summary,
            "files_changed": result.files_changed,
            "commands_run": result.commands_run,
            "error": result.error,
            "output": result.output[:20_000],
        })
    except ImportError:
        return json.dumps({
            "success": False,
            "error": "OpenCode provider not available (opencode_provider.py missing)",
        })
    except Exception as exc:
        log.exception("OpenCode task failed")
        return json.dumps({
            "success": False,
            "error": str(exc),
        })


# ---------------------------------------------------------------------------
# Default tool factory
# ---------------------------------------------------------------------------

def create_default_tools(router: ModelRouter | None = None) -> ToolRegistry:
    """Create a :class:`ToolRegistry` populated with all built-in tools."""
    reg = ToolRegistry()

    reg.register(
        name="web_search",
        description=(
            "Search the web for current information. Returns content and citations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "recency": {
                    "type": "string",
                    "enum": ["day", "week", "month", "year"],
                    "description": "Filter results by recency",
                },
                "domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Limit search to specific domains",
                },
            },
            "required": ["query"],
        },
        handler=tool_web_search,
    )

    reg.register(
        name="fetch_url",
        description="Fetch and extract content from a specific URL.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "extract_prompt": {
                    "type": "string",
                    "description": "Optional: what specific info to extract",
                },
            },
            "required": ["url"],
        },
        handler=tool_fetch_url,
    )

    reg.register(
        name="execute_code",
        description="Execute Python or Bash code in a sandboxed subprocess. Returns stdout/stderr.",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to execute"},
                "language": {
                    "type": "string",
                    "enum": ["python", "bash"],
                    "description": "Language (default: python)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30)",
                },
            },
            "required": ["code"],
        },
        handler=tool_execute_code,
    )

    reg.register(
        name="file_read",
        description="Read a file from the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        },
        handler=tool_file_read,
    )

    reg.register(
        name="file_write",
        description="Write content to a workspace file. Creates directories as needed.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        handler=tool_file_write,
    )

    reg.register(
        name="browser_action",
        description="Perform browser automation: navigate, click, fill forms, screenshot.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["navigate", "click", "fill", "screenshot", "extract"],
                },
                "selector": {"type": "string", "description": "CSS selector"},
                "value": {"type": "string", "description": "Value for fill actions"},
            },
            "required": ["url", "action"],
        },
        handler=tool_browser_action,
    )

    reg.register(
        name="opencode_task",
        description=(
            "Delegate a software-engineering task (coding, refactoring, "
            "debugging, testing) to the OpenCode specialist agent. "
            "Use this for any task that requires reading, writing, or "
            "editing source code files in the workspace."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Natural-language description of the coding task",
                },
            },
            "required": ["prompt"],
        },
        handler=tool_opencode_task,
    )

    # ── Science tools ─────────────────────────────────────────────────────────

    async def tool_science_analyze(description: str, data: str = "{}") -> str:
        """Analyze scientific data using OpenCode and orchestra_science."""
        try:
            import json
            from orchestra_science.engine import ScienceEngine, ScienceTask, ScienceTaskType
            engine = ScienceEngine()
            task = ScienceTask(
                task_type=ScienceTaskType.ANALYSIS,
                description=description,
                context=json.loads(data) if isinstance(data, str) else data,
            )
            result = await engine.run(task)
            return result.content or result.error or "No output"
        except Exception as e:
            return f"Science analysis error: {e}"

    async def tool_science_pubchem(query: str, namespace: str = "name") -> str:
        """Search PubChem for chemical compounds."""
        try:
            import json
            from orchestra_science.ingestion.pubchem import PubChemClient
            async with PubChemClient() as client:
                compounds = await client.search_compound(query, namespace, max_results=5)
            return json.dumps([c.to_dict() for c in compounds], indent=2)
        except Exception as e:
            return f"PubChem search error: {e}"

    async def tool_science_literature(topic: str) -> str:
        """Conduct a literature review on a scientific topic."""
        try:
            from orchestra_science.workflows.literature_review import LitReviewWorkflow
            from orchestra_science.engine import ScienceEngine
            engine = ScienceEngine()
            wf = LitReviewWorkflow()
            result = await wf.run(topic, engine)
            return result.summary or "No results"
        except Exception as e:
            return f"Literature review error: {e}"

    async def tool_science_docking(protein_pdb: str, ligand_smiles: str) -> str:
        """Run molecular docking analysis."""
        try:
            from orchestra_science.workflows.molecular_docking import DockingWorkflow
            from orchestra_science.engine import ScienceEngine
            engine = ScienceEngine()
            wf = DockingWorkflow()
            result = await wf.run(protein_pdb, ligand_smiles, engine)
            return result.analysis or result.error or "No output"
        except Exception as e:
            return f"Docking analysis error: {e}"

    async def tool_science_report(title: str, objective: str, methods: str = "", results: str = "") -> str:
        """Generate a scientific lab report."""
        try:
            from orchestra_science.reporting.report_generator import ScienceReportGenerator
            from orchestra_science.engine import ScienceEngine
            engine = ScienceEngine()
            reporter = ScienceReportGenerator()
            content = await reporter.generate_lab_report(
                title=title, objective=objective,
                methods=methods, results=results,
                discussion="", conclusion="",
                engine=engine,
            )
            return content
        except Exception as e:
            return f"Report generation error: {e}"

    reg.register(
        name="science_analyze",
        description="Analyze scientific data (chemistry, biology, physics) using OpenCode. Provide the analysis description and optional data as JSON.",
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Analysis task description"},
                "data": {"type": "string", "description": "Optional JSON data"},
            },
            "required": ["description"],
        },
        handler=tool_science_analyze,
    )
    reg.register(
        name="science_pubchem_search",
        description="Search PubChem for chemical compounds by name, SMILES, or formula.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Compound name or identifier"},
                "namespace": {"type": "string", "enum": ["name", "smiles", "cid", "formula"]},
            },
            "required": ["query"],
        },
        handler=tool_science_pubchem,
    )
    reg.register(
        name="science_literature_review",
        description="Conduct a literature review on any scientific topic using multi-perspective research and synthesis.",
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Research topic"},
            },
            "required": ["topic"],
        },
        handler=tool_science_literature,
    )
    reg.register(
        name="science_docking",
        description="Run molecular docking analysis for a protein and ligand.",
        parameters={
            "type": "object",
            "properties": {
                "protein_pdb": {"type": "string", "description": "PDB code (e.g. 1ake)"},
                "ligand_smiles": {"type": "string", "description": "Ligand SMILES string"},
            },
            "required": ["protein_pdb", "ligand_smiles"],
        },
        handler=tool_science_docking,
    )
    reg.register(
        name="science_generate_report",
        description="Generate a formatted scientific lab report.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "objective": {"type": "string"},
                "methods": {"type": "string"},
                "results": {"type": "string"},
            },
            "required": ["title", "objective"],
        },
        handler=tool_science_report,
    )

    return reg
