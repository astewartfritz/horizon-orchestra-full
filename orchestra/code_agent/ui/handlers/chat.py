from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import tempfile
import uuid

_logger = logging.getLogger("orchestra.chat")

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from orchestra.code_agent import Agent, AgentConfig
from orchestra.code_agent.config import LLMConfig
from orchestra.code_agent.context.manager import ContextManager
from orchestra.code_agent.session import Session, SessionManager

_active_tasks: dict[str, dict] = {}
_run_semaphore = asyncio.Semaphore(2)  # max 2 concurrent agent runs


class ChatRequest(BaseModel):
    task: str
    session_id: str = ""
    provider: str = "ollama"
    model: str = "nemotron-mini"
    api_key: str = ""
    use_cache: bool = False
    allow_web: bool = True


class FrontierRequest(BaseModel):
    question: str
    search_query: str | None = None
    include_tabs: bool = True


class PrinceRequest(BaseModel):
    question: str
    search_query: str | None = None


class AgenticChatRequest(BaseModel):
    task: str
    session_id: str = ""
    engine: str = "auto"  # "auto", "claude_code", "opencode", "codex", "openclaw"
    workspace: str = ""  # working directory passed to the agent as cwd
    claude_session_id: str = ""  # resume a previous Claude Code session
    allow_web: bool = True


async def _build_context_prompt(workspace: str) -> str:
    """Build a compact context block to inject via --append-system-prompt.

    Includes top-level directory listing and git status so Claude Code
    understands the project without spending turns on exploration.
    """
    import pathlib as _pl
    lines: list[str] = []
    ws = _pl.Path(workspace)
    if not ws.is_dir():
        return ""

    lines.append(f"## Workspace context\nPath: {ws}")

    # Top-level directory listing (dirs first, then files, capped at 40)
    try:
        entries = sorted(ws.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        visible = [e for e in entries if not e.name.startswith(".")][:40]
        if visible:
            lines.append("\nTop-level contents:")
            for e in visible:
                suffix = "/" if e.is_dir() else ""
                lines.append(f"  {e.name}{suffix}")
    except Exception:
        pass

    # Git info (branch + short status)
    try:
        proc_branch = await asyncio.create_subprocess_exec(
            "git", "-C", str(ws), "rev-parse", "--abbrev-ref", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        b_out, _ = await asyncio.wait_for(proc_branch.communicate(), timeout=5)
        branch = b_out.decode().strip()

        proc_status = await asyncio.create_subprocess_exec(
            "git", "-C", str(ws), "status", "--short",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        s_out, _ = await asyncio.wait_for(proc_status.communicate(), timeout=5)
        status_lines = s_out.decode().strip().splitlines()[:20]

        if branch:
            lines.append(f"\nGit branch: {branch}")
        if status_lines:
            lines.append("Uncommitted changes:")
            for sl in status_lines:
                lines.append(f"  {sl}")
        elif branch:
            lines.append("Git status: clean")
    except Exception:
        pass

    return "\n".join(lines)


def register_chat_routes(
    app: FastAPI,
    sessions: SessionManager,
    ctx_mgr: ContextManager,
    agent_config: AgentConfig | None,
    workspace: str,
) -> None:

    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        try:
            return await _do_chat(req, sessions, ctx_mgr, agent_config, workspace)
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    def _make_enqueue(_tid, _q):
        async def _enqueue(event):
            if event is not None:
                entry = _active_tasks.get(_tid)
                if entry:
                    entry["events"].append(event)
            await _q.put(event)
        return _enqueue

    async def _do_chat(req: ChatRequest, sessions, ctx_mgr, agent_config, workspace):
        cfg = agent_config or AgentConfig(
            llm=LLMConfig(provider=req.provider, model=req.model.lower(), api_key=req.api_key or None),
            memory_type="none",
        )
        cfg.workspace = workspace
        if req.api_key:
            cfg.llm.api_key = req.api_key
        cfg.allow_web = req.allow_web

        _web_tools = {"websearch", "webfetch"}
        tool_filter = None if req.allow_web else (lambda name: name not in _web_tools)

        web_hint = (
            " You have live web search access — use the websearch tool proactively "
            "whenever the task benefits from current or external information."
            if req.allow_web else ""
        )
        if web_hint and cfg.system_prompt:
            cfg.system_prompt += web_hint
        elif web_hint:
            from orchestra.code_agent.agent import DEFAULT_SYSTEM_PROMPT
            cfg.system_prompt = DEFAULT_SYSTEM_PROMPT + web_hint

        agent = Agent(cfg, tool_filter=tool_filter)
        if req.use_cache and req.api_key:
            from orchestra.code_agent.cache.base import DiskCache
            from orchestra.code_agent.cache.patch_llm import CachedLLM
            agent.llm = CachedLLM(agent.llm, DiskCache())

        if req.session_id:
            existing = sessions.load(req.session_id)
            if existing:
                agent.messages = [
                    __import__("code_agent.llm.base", fromlist=[""]).Message(**m)
                    for m in existing.messages
                ]

        session = Session.create(req.task, cfg)
        if req.session_id:
            session.id = req.session_id
        session.add_message(
            __import__("code_agent.llm.base", fromlist=[""]).Message(role="user", content=req.task)
        )
        ctx_mgr.add(req.task, tier="important", source="user")

        task_id = str(uuid.uuid4())
        event_queue: asyncio.Queue = asyncio.Queue()
        agent.set_event_queue(event_queue)
        _enqueue = _make_enqueue(task_id, event_queue)

        async def run_agent():
            try:
                await asyncio.wait_for(_run_semaphore.acquire(), timeout=60)
            except asyncio.TimeoutError:
                await _enqueue({"type": "error", "data": {"message": "Server busy. Try again."}})
                await _enqueue({"type": "done", "data": {"result": "Server busy."}})
                await _enqueue(None)
                return
            try:
                await _enqueue({"type": "task_start", "data": {"task": req.task[:200]}})
                result = await asyncio.wait_for(agent.run(req.task, stream=True), timeout=1800)
            except asyncio.TimeoutError:
                result = "Task timed out."
                await _enqueue({"type": "error", "data": {"message": "Task timed out."}})
            except Exception as e:
                _logger.exception("Agent run failed")
                result = f"Error: {e}"
                await _enqueue({"type": "error", "data": {"message": str(e)}})
            finally:
                _run_semaphore.release()
            # cleanup (runs even if agent run fails)
            try:
                await _enqueue({"type": "done", "data": {"result": result}})
                await _enqueue(None)
                session.add_message(
                    __import__("code_agent.llm.base", fromlist=[""]).Message(role="assistant", content=result)
                )
                # Save full conversation history from agent.messages
                if hasattr(agent, 'messages') and agent.messages:
                    session.messages = [{"role": m.role, "content": m.content} for m in agent.messages]
                session.finished = True
                session.result = result
                sessions.save(session)
                ctx_mgr.add(result[:500], tier="normal", source="assistant")
            except Exception as cleanup_err:
                _logger.exception("Cleanup failed")
            finally:
                entry = _active_tasks.get(task_id)
                if entry:
                    entry["done"] = True
                async def _delayed_cleanup():
                    await asyncio.sleep(60)
                    _active_tasks.pop(task_id, None)
                asyncio.create_task(_delayed_cleanup())

        task_obj = asyncio.create_task(run_agent())
        _active_tasks[task_id] = {
            "queue": event_queue,
            "agent": agent,
            "task": task_obj,
            "events": [],
            "done": False,
        }

        return {"task_id": task_id, "session_id": session.id}

    @app.get("/api/chat/{task_id}/stream")
    async def chat_stream(task_id: str):
        if task_id not in _active_tasks:
            raise HTTPException(status_code=404, detail="Task not found")

        entry = _active_tasks[task_id]

        async def event_generator():
            try:
                # First serve any stored events (for reconnecting clients)
                for ev in entry["events"]:
                    yield f"data: {json.dumps(ev)}\n\n"
                if entry["done"]:
                    return
                while True:
                    event = await entry["queue"].get()
                    if event is None:
                        break
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                pass

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/chat/{task_id}/cancel")
    async def chat_cancel(task_id: str):
        if task_id not in _active_tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        entry = _active_tasks[task_id]
        entry["task"].cancel()
        del _active_tasks[task_id]
        return {"status": "cancelled"}

    @app.get("/v1/run/stream")
    async def v1_run_stream(task: str = "", user_id: str = "default", architecture: str = "A"):
        """SSE bridge for the MILES GUI (gui/orchestra-gui).

        Starts a chat task and streams events translated into the format the
        MILES SPA expects: thinking / tool_call / tool_result / final / error.
        """
        from fastapi.responses import Response as _Response

        if not task.strip():
            return _Response("task query param required", status_code=400)

        # Pick best available provider
        _anth = os.environ.get("ANTHROPIC_API_KEY", "")
        _oai  = os.environ.get("OPENAI_API_KEY", "")
        if _anth:
            _prov, _model = "anthropic", "claude-sonnet-4-6"
        elif _oai:
            _prov, _model = "openai", "gpt-4o"
        else:
            _prov, _model = "ollama", os.environ.get("ORCHESTRA_MODEL", "nemotron-mini")

        req = ChatRequest(task=task.strip(), provider=_prov, model=_model, allow_web=True)
        try:
            info = await _do_chat(req, sessions, ctx_mgr, agent_config, workspace)
        except Exception as exc:
            async def _err_gen():
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(_err_gen(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        task_id = info["task_id"]
        entry = _active_tasks[task_id]

        async def miles_event_gen():
            try:
                # Replay already-buffered events (handles instant completion)
                buffered = list(entry.get("events", []))
                pending = iter(buffered)
                done_seen = False

                async def _next_ev():
                    nonlocal done_seen
                    # Drain buffer first
                    try:
                        return next(pending)
                    except StopIteration:
                        pass
                    if done_seen:
                        return None
                    return await entry["queue"].get()

                while True:
                    ev = await _next_ev()
                    if ev is None:
                        yield "data: [DONE]\n\n"
                        break

                    t = ev.get("type", "")
                    d = ev.get("data", ev)

                    if t == "task_start":
                        yield f"data: {json.dumps({'type': 'thinking', 'content': 'Planning…'})}\n\n"
                    elif t in ("thinking", "thought", "plan"):
                        yield f"data: {json.dumps({'type': 'thinking', 'content': d.get('content') or d.get('text', 'Thinking…')})}\n\n"
                    elif t in ("tool_call", "tool_use"):
                        tool_name = d.get("tool") or d.get("name") or d.get("tool_name", "tool")
                        yield f"data: {json.dumps({'type': 'tool_call', 'tool': tool_name})}\n\n"
                    elif t in ("tool_result", "tool_response"):
                        tool_name = d.get("tool") or d.get("name") or d.get("tool_name", "tool")
                        yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_name, 'success': d.get('success', not d.get('error'))})}\n\n"
                    elif t == "done":
                        done_seen = True
                        result = d.get("result") or d.get("content") or ""
                        yield f"data: {json.dumps({'type': 'final', 'content': str(result)})}\n\n"
                        yield "data: [DONE]\n\n"
                        break
                    elif t == "error":
                        msg = d.get("message") or d.get("error") or "Unknown error"
                        yield f"data: {json.dumps({'type': 'error', 'message': str(msg)})}\n\n"
                        yield "data: [DONE]\n\n"
                        break
                    # skip unknown types (token chunks, metadata, etc.)
            except asyncio.CancelledError:
                yield "data: [DONE]\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            miles_event_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/chat/agentic")
    async def agentic_chat(req: AgenticChatRequest, request: Request = None):
        """Route a task through active agents (Claude Code, Codex, OpenClaw, or auto via Nemotron)."""
        # Gate: require Pro subscription for real code execution
        try:
            from orchestra.code_agent.billing.routes import require_pro
            from orchestra.code_agent.billing.store import SubscriptionStore
            import os
            if os.environ.get("STRIPE_SECRET_KEY"):
                local_id = (request.headers.get("X-Customer-Id", "") if request else "")
                require_pro(local_id)
        except HTTPException:
            raise
        except Exception:
            pass  # billing not configured — allow through

        task_id = str(uuid.uuid4())
        event_queue: asyncio.Queue = asyncio.Queue()
        _active_tasks[task_id] = {"queue": event_queue, "events": [], "done": False}

        async def run_agentic():
            async def enqueue(ev):
                if ev is not None:
                    _active_tasks.get(task_id, {}).get("events", []).append(ev)
                await event_queue.put(ev)

            await enqueue({"type": "task_start", "data": {"task": req.task[:200]}})
            try:
                engine = req.engine
                result_text = ""
                err_text = ""
                agent_used = engine
                agent_meta: dict = {}
                if engine == "auto":
                    try:
                        from orchestra.code_agent.nemotron.routes import _get_dispatch
                        dispatch = _get_dispatch()
                        record = await asyncio.wait_for(
                            dispatch.dispatch(req.task, skip_health_check=False),
                            timeout=300,
                        )
                        result_text = record.result.output if record.result.success else ""
                        err_text = record.result.error if not record.result.success else ""
                        agent_used = record.result.agent_name
                    except Exception as e:
                        result_text = ""
                        err_text = str(e)
                        agent_used = "unknown"
                else:
                    # Direct agent execution — skip Nemotron routing
                    try:
                        from orchestra.code_agent.nemotron.routes import _get_dispatch
                        registry = _get_dispatch()._router._registry
                        agent = registry.get(engine)
                        if agent is None:
                            raise ValueError(f"Agent '{engine}' not registered")

                        # Build context dict with session continuity + scaffolding
                        effective_workspace = req.workspace or workspace or None
                        ctx: dict = {"cwd": effective_workspace}

                        # Web search permission
                        if req.allow_web:
                            ctx["allow_web"] = True

                        # Session continuity — resume previous Claude Code conversation
                        if req.claude_session_id:
                            ctx["claude_session_id"] = req.claude_session_id

                        # Context scaffolding — inject project tree + git status
                        _web_suffix = (
                            "\n\n## Web Search\nYou have live web search access via the WebSearch tool. "
                            "Use it proactively whenever the task benefits from current or external information."
                            if req.allow_web else
                            "\n\n## Web Search\nWeb search is disabled for this task."
                        )
                        if effective_workspace:
                            try:
                                scaffold = await asyncio.wait_for(
                                    _build_context_prompt(effective_workspace),
                                    timeout=8,
                                )
                                if scaffold:
                                    ctx["append_system_prompt"] = scaffold + _web_suffix
                            except Exception:
                                pass  # scaffolding is best-effort
                        else:
                            ctx["append_system_prompt"] = _web_suffix.strip()

                        # Pass event_callback if the agent supports it
                        exec_kwargs: dict = {"context": ctx}
                        sig = inspect.signature(agent.execute)
                        if "event_callback" in sig.parameters:
                            exec_kwargs["event_callback"] = enqueue

                        ag_result = await asyncio.wait_for(
                            agent.execute(req.task, **exec_kwargs),
                            timeout=3660,  # 61 min — matches agent's 1-hour internal limit
                        )
                        result_text = ag_result.output if ag_result.success else ""
                        err_text = ag_result.error if not ag_result.success else ""
                        agent_used = ag_result.agent_name
                        agent_meta = ag_result.metadata or {}
                    except Exception as e:
                        result_text = ""
                        err_text = str(e)
                        agent_used = engine
                        agent_meta = {}

                if err_text:
                    await enqueue({"type": "error", "data": {"message": err_text}})

                _meta = agent_meta
                await enqueue({
                    "type": "done",
                    "data": {
                        "result": result_text or err_text or "Task completed.",
                        "agent": agent_used,
                        "cost_usd": _meta.get("cost_usd"),
                        "turns": _meta.get("turns"),
                        # Return session ID so UI can pass it on the next task
                        "claude_session_id": _meta.get("claude_session_id") or "",
                    },
                })
                try:
                    from orchestra.code_agent.ui.handlers.runs import RunStore
                    RunStore.get().finish(
                        task_id,
                        result=result_text or "",
                        error=err_text or "",
                        cost_usd=float(_meta.get("cost_usd") or 0),
                        turns=int(_meta.get("turns") or 0),
                    )
                except Exception:
                    pass
            except asyncio.TimeoutError:
                await enqueue({"type": "error", "data": {"message": "Agent timed out after 61 minutes"}})
                await enqueue({"type": "done", "data": {"result": "Task timed out."}})
                try:
                    from orchestra.code_agent.ui.handlers.runs import RunStore
                    RunStore.get().finish(task_id, error="Agent timed out")
                except Exception:
                    pass
            except Exception as e:
                _logger.exception("Agentic run failed")
                await enqueue({"type": "error", "data": {"message": str(e)}})
                await enqueue({"type": "done", "data": {"result": f"Error: {e}"}})
                try:
                    from orchestra.code_agent.ui.handlers.runs import RunStore
                    RunStore.get().finish(task_id, error=str(e))
                except Exception:
                    pass
            finally:
                await event_queue.put(None)
                entry = _active_tasks.get(task_id)
                if entry:
                    entry["done"] = True
                async def _cleanup():
                    await asyncio.sleep(60)
                    _active_tasks.pop(task_id, None)
                asyncio.create_task(_cleanup())

        # Record run in history
        try:
            from orchestra.code_agent.ui.handlers.runs import RunStore
            RunStore.get().create(task_id, req.task, engine=req.engine, workspace=req.workspace or workspace or "")
        except Exception:
            pass

        asyncio.create_task(run_agentic())
        session_id = req.session_id or str(uuid.uuid4())
        return {"task_id": task_id, "session_id": session_id}

    @app.post("/api/chat/preview")
    async def preview_changes(body: dict, request: Request = None):
        """Generate a structured change plan (diff preview) without executing.

        Free users call this to see *what* the agent would do. Paying users
        then call /api/chat/agentic to actually apply the changes.
        """
        task = body.get("task", "").strip()
        ws = body.get("workspace", workspace or "")
        provider = body.get("provider", "anthropic")
        model = body.get("model", "claude-opus-4-7")
        api_key = body.get("api_key", "")

        if not task:
            raise HTTPException(status_code=400, detail="task is required")

        # Build workspace context
        ws_context = ""
        if ws:
            try:
                ws_context = await asyncio.wait_for(_build_context_prompt(ws), timeout=8)
            except Exception:
                pass

        system = (
            "You are a senior software engineer planning code changes. "
            "The user describes a task. You must respond with a JSON object describing "
            "the exact changes you would make — without executing anything. "
            "Output ONLY valid JSON, no markdown fences, no explanation outside the JSON.\n\n"
            "Schema:\n"
            "{\n"
            '  "summary": "one sentence summary of the change",\n'
            '  "approach": "2-3 sentence explanation of the approach",\n'
            '  "files": [\n'
            "    {\n"
            '      "path": "relative/file/path.py",\n'
            '      "action": "modify|create|delete",\n'
            '      "description": "what changes in this file",\n'
            '      "diff": "unified diff showing before(-) and after(+) lines, max 60 lines"\n'
            "    }\n"
            "  ],\n"
            '  "risk": "low|medium|high",\n'
            '  "estimated_lines_changed": 42\n'
            "}"
        )

        prompt = f"Task: {task}"
        if ws_context:
            prompt = f"{ws_context}\n\n{prompt}"

        try:
            cfg = AgentConfig(
                llm=LLMConfig(
                    provider=provider,
                    model=model,
                    api_key=api_key or None,
                ),
                memory_type="none",
                max_iterations=1,
            )
            cfg.system_prompt = system
            agent = Agent(cfg)
            result = await asyncio.wait_for(agent.run(prompt), timeout=60)
            raw = result.strip()

            # Parse JSON
            import json as _json
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            try:
                plan = _json.loads(raw)
            except Exception:
                # Fall back — wrap raw text as a single summary
                plan = {
                    "summary": task,
                    "approach": raw[:300] if raw else "Unable to generate preview.",
                    "files": [],
                    "risk": "unknown",
                    "estimated_lines_changed": 0,
                }

            return {"plan": plan, "task": task}

        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    @app.get("/api/queue")
    async def queue_status():
        return {
            "active": len(_active_tasks),
            "running": sum(1 for t in _active_tasks.values() if not t.get("done")),
            "completed": sum(1 for t in _active_tasks.values() if t.get("done")),
            "semaphore_available": _run_semaphore._value if hasattr(_run_semaphore, "_value") else "?",
        }

    @app.post("/api/frontier/ask")
    async def frontier_ask(req: FrontierRequest):
        from orchestra.code_agent.frontier import FrontierEngine
        engine = FrontierEngine()
        result = await engine.research(
            query=req.question,
            search_query=req.search_query,
            include_tabs=req.include_tabs,
        )
        return {
            "answer": result.answer,
            "sources": result.sources,
            "tabs_used": result.tabs_used,
            "safety_level": result.safety_level,
            "latency_ms": result.latency_ms,
        }

    @app.post("/api/prince/ask")
    async def prince_ask(req: PrinceRequest):
        from orchestra.code_agent.prince import PrinceEngine
        engine = PrinceEngine()
        result = await engine.ask(
            question=req.question,
            search_query=req.search_query,
        )
        return result

    @app.get("/api/connectors")
    async def list_connectors():
        from orchestra.code_agent.frontier.connectors import ConnectorRegistry
        reg = ConnectorRegistry()
        return {"connectors": reg.list()}

    @app.get("/api/weather")
    async def weather_endpoint(location: str = "New York", units: str = "celsius"):
        """Real-time weather for any city (Open-Meteo, no API key)."""
        from orchestra.code_agent.tools.weather import _geocode, _WMO
        import httpx
        try:
            geo = await _geocode(location)
            if geo is None:
                raise HTTPException(status_code=404, detail=f"Location not found: {location!r}")
            lat, lon, display = geo
            temp_unit = "fahrenheit" if units.lower().startswith("f") else "celsius"
            wind_unit = "mph" if temp_unit == "fahrenheit" else "kmh"
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat, "longitude": lon,
                        "current_weather": True,
                        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                        "temperature_unit": temp_unit,
                        "windspeed_unit": wind_unit,
                        "timezone": "auto",
                        "forecast_days": 4,
                    },
                )
                d = r.json()
            cur = d.get("current_weather", {})
            daily = d.get("daily", {})
            u = "°F" if temp_unit == "fahrenheit" else "°C"
            wu = "mph" if wind_unit == "mph" else "km/h"
            forecast = []
            dates = daily.get("time", [])
            for i in range(1, min(4, len(dates))):
                forecast.append({
                    "date": dates[i],
                    "high": daily.get("temperature_2m_max", [None] * 4)[i],
                    "low": daily.get("temperature_2m_min", [None] * 4)[i],
                    "precipitation_mm": daily.get("precipitation_sum", [0] * 4)[i],
                    "condition": _WMO.get(daily.get("weathercode", [0] * 4)[i], ""),
                })
            return {
                "location": display,
                "latitude": lat,
                "longitude": lon,
                "current": {
                    "temperature": cur.get("temperature"),
                    "windspeed": cur.get("windspeed"),
                    "condition": _WMO.get(cur.get("weathercode", 0), "Unknown"),
                    "units": {"temp": u, "wind": wu},
                },
                "forecast": forecast,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/news")
    async def news_endpoint(query: str = "", count: int = 10):
        """Real-time news headlines (Google News RSS, no API key)."""
        from orchestra.code_agent.tools.news import _fetch_rss
        count = max(1, min(20, count))
        try:
            if query.strip():
                q = query.strip().replace(" ", "+")
                url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
            else:
                url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
            articles = await _fetch_rss(url, count)
            return {"query": query or None, "count": len(articles), "articles": articles}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/crypto")
    async def crypto_endpoint(coins: str = "", currency: str = "usd", count: int = 10):
        """Live crypto prices via CoinGecko (no key)."""
        import httpx
        try:
            params: dict = {"vs_currency": currency.lower(), "order": "market_cap_desc",
                            "sparkline": False, "price_change_percentage": "24h"}
            if coins.strip():
                params["ids"] = coins.strip()
            else:
                params["per_page"] = min(20, max(1, count))
                params["page"] = 1
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Orchestra/1.0"}) as c:
                r = await c.get("https://api.coingecko.com/api/v3/coins/markets", params=params)
                r.raise_for_status()
            return {"currency": currency.upper(), "coins": r.json()}
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/currency")
    async def currency_endpoint(base: str = "USD", targets: str = ""):
        """Live exchange rates via open.er-api.com (no key)."""
        import httpx
        _MAJORS = ["USD","EUR","GBP","JPY","CAD","AUD","CHF","CNY","INR","MXN",
                   "BRL","KRW","SGD","HKD","NOK","SEK","NZD","ZAR","AED","THB"]
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"https://open.er-api.com/v6/latest/{base.upper()}")
                r.raise_for_status()
                d = r.json()
            rates = d.get("rates", {})
            want = [t.strip().upper() for t in targets.split(",") if t.strip()] or _MAJORS
            filtered = {k: rates[k] for k in want if k in rates and k != base.upper()}
            return {"base": base.upper(), "rates": filtered, "updated": d.get("time_last_update_utc")}
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/wikipedia")
    async def wikipedia_endpoint(topic: str, sentences: int = 5):
        """Wikipedia article summary (no key)."""
        import httpx, re
        try:
            headers = {"User-Agent": "Orchestra/1.0 (https://github.com/orchestra)"}
            async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as c:
                sr = await c.get("https://en.wikipedia.org/w/api.php", params={
                    "action": "query", "list": "search", "srsearch": topic,
                    "srlimit": 1, "format": "json",
                })
                hits = sr.json().get("query", {}).get("search", [])
                if not hits:
                    raise HTTPException(status_code=404, detail=f"No article found for: {topic!r}")
                title = hits[0]["title"]
                slug = title.replace(" ", "_")
                r2 = await c.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}")
                if r2.status_code != 200 or not r2.text.strip():
                    raise HTTPException(status_code=404, detail=f"No summary for: {title!r}")
                data = r2.json()
            extract = data.get("extract") or data.get("description") or ""
            sents = re.split(r'(?<=[.!?])\s+', extract)
            summary = " ".join(sents[:max(1, sentences)])
            return {
                "title": data.get("title", title),
                "description": data.get("description", ""),
                "summary": summary,
                "thumbnail": (data.get("thumbnail") or {}).get("source"),
                "url": (data.get("content_urls") or {}).get("desktop", {}).get("page", ""),
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/github/search")
    async def github_search_endpoint(q: str, count: int = 6, sort: str = "stars"):
        """Search GitHub repos via public API (60 req/hr unauthed)."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15, headers={
                "User-Agent": "Orchestra/1.0", "Accept": "application/vnd.github+json"
            }) as c:
                r = await c.get("https://api.github.com/search/repositories", params={
                    "q": q, "sort": sort, "order": "desc", "per_page": min(10, max(1, count)),
                })
                r.raise_for_status()
                d = r.json()
            return {"query": q, "total": d.get("total_count", 0), "repos": [
                {"name": repo["full_name"], "description": repo.get("description", ""),
                 "stars": repo["stargazers_count"], "language": repo.get("language"),
                 "url": repo["html_url"], "topics": repo.get("topics", [])}
                for repo in d.get("items", [])
            ]}
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/nasa/apod")
    async def nasa_apod_endpoint(date: str = ""):
        """NASA Astronomy Picture of the Day (DEMO key)."""
        import httpx
        try:
            params: dict = {"api_key": "DEMO_KEY"}
            if date:
                params["date"] = date
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://api.nasa.gov/planetary/apod", params=params)
                r.raise_for_status()
            return r.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/api/orchestra/info")
    async def orchestra_info():
        """Return Orchestra's own workspace and source root for self-improvement."""
        import pathlib as _pl
        ws = _pl.Path(workspace).resolve()
        src = ws / "src"
        return {
            "workspace": str(ws),
            "source_root": str(src) if src.exists() else str(ws),
        }

    def _is_safe_path(path) -> bool:
        """Allow paths under user home or the server workspace."""
        import pathlib as _pl
        try:
            resolved = _pl.Path(path).resolve()
            home = _pl.Path.home().resolve()
            ws_resolved = _pl.Path(workspace).resolve()
            return (
                resolved == home or home in resolved.parents or
                resolved == ws_resolved or ws_resolved in resolved.parents or
                ws_resolved == resolved
            )
        except Exception:
            return False

    @app.get("/api/files/browse")
    async def files_browse(path: str = ""):
        """List directory contents — scoped to user home and workspace."""
        import pathlib as _pl, time as _t
        try:
            p = _pl.Path(path).resolve() if path else _pl.Path.home()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid path")
        if not _is_safe_path(p):
            raise HTTPException(status_code=403, detail="Path outside allowed scope")
        if not p.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if not p.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")
        entries = []
        try:
            for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    stat = item.stat()
                    entries.append({
                        "name": item.name,
                        "path": str(item),
                        "is_dir": item.is_dir(),
                        "size": stat.st_size if item.is_file() else None,
                        "modified": stat.st_mtime,
                    })
                except (PermissionError, OSError):
                    continue
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")
        parent = str(p.parent) if str(p.parent) != str(p) else None
        return {"path": str(p), "parent": parent, "entries": entries[:500]}

    @app.get("/api/files/read")
    async def files_read(path: str):
        """Read a file's content — up to 100 KB."""
        import pathlib as _pl
        try:
            p = _pl.Path(path).resolve()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid path")
        if not _is_safe_path(p):
            raise HTTPException(status_code=403, detail="Path outside allowed scope")
        if not p.exists():
            raise HTTPException(status_code=404, detail="Not found")
        if not p.is_file():
            raise HTTPException(status_code=400, detail="Not a file")
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            truncated = len(content) > 100_000
            return {
                "path": str(p),
                "name": p.name,
                "content": content[:100_000],
                "truncated": truncated,
                "size": p.stat().st_size,
                "lines": content[:100_000].count("\n"),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/tools")
    async def list_tools():
        """All registered tools with name, description, and parameters."""
        from orchestra.code_agent.tools import get_all_tools
        tools = []
        for cls in get_all_tools():
            try:
                spec = cls.spec
                tools.append({
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": list(spec.parameters.keys()) if spec.parameters else [],
                })
            except Exception:
                pass
        return {"tools": tools, "count": len(tools)}

    @app.get("/api/health")
    async def health():
        info = {
            "status": "ok",
            "version": "1.0.0",
            "uptime": None,  # could track start time
            "providers": {},
            "gpu": False,
            "memory": {},
        }
        try:
            import psutil
            mem = psutil.virtual_memory()
            info["memory"] = {"total_gb": round(mem.total / 1e9, 1), "available_gb": round(mem.available / 1e9, 1), "percent_used": mem.percent}
        except Exception:
            pass
        try:
            import subprocess
            r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=3)
            info["gpu"] = r.returncode == 0
        except Exception:
            info["gpu"] = False
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get("http://localhost:11434/api/tags")
                if r.status_code == 200:
                    models = [m["name"] for m in r.json().get("models", [])]
                    info["providers"]["ollama"] = {"available": True, "models": models}
                else:
                    info["providers"]["ollama"] = {"available": False}
        except Exception:
            info["providers"]["ollama"] = {"available": False}
        try:
            import vllm as _
            info["providers"]["vllm"] = {"available": True}
        except ImportError:
            info["providers"]["vllm"] = {"available": False}
        return info

    from pydantic import BaseModel as _BM

    class VisionRequest(_BM):
        image: str = ""
        prompt: str = "Describe this image in detail."

    @app.post("/api/vision/describe")
    async def vision_describe(req: VisionRequest):
        if not req.image:
            raise HTTPException(status_code=400, detail="No image provided")
        try:
            import httpx
            vb = {"model": "llava", "prompt": req.prompt, "images": [req.image], "stream": False, "keep_alive": "-1m"}
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post("http://localhost:11434/api/generate", json=vb)
                if r.status_code == 200:
                    return {"description": r.json().get("response", ""), "model": "llava"}
                raise HTTPException(status_code=r.status_code, detail=r.text[:200])
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/scaffold/templates")
    async def scaffold_templates():
        from orchestra.code_agent.scaffold.generator import TEMPLATES
        return {"templates": sorted(TEMPLATES.keys()),
                "count": len(TEMPLATES),
                "groups": {"python": [k for k in TEMPLATES if "python" in k or "fastapi" in k or "web" in k],
                           "rust": [k for k in TEMPLATES if "rust" in k],
                           "typescript": [k for k in TEMPLATES if "typescript" in k or "ts" in k],
                           "mojo": [k for k in TEMPLATES if "mojo" in k]}}

    @app.get("/api/runtimes")
    async def runtimes():
        import subprocess as _sp
        info = {}
        for cmd, key in [(["rustc", "--version"], "rust"), (["node", "--version"], "node"),
                         (["npm.cmd", "--version"], "npm"), (["mojo", "--version"], "mojo"),
                         (["cargo", "--version"], "cargo"), (["python", "--version"], "python")]:
            try:
                r = _sp.run(cmd, capture_output=True, text=True, timeout=5)
                info[key] = r.stdout.strip() if r.returncode == 0 else False
            except Exception:
                info[key] = False
        # Chromium detection
        try:
            from orchestra.code_agent.browser.chromium import ChromiumController
            ctrl = ChromiumController(headless=True)
            browser_path = ctrl.browser_path
            info["chromium"] = os.path.exists(browser_path) if browser_path != "chrome" else False
            info["chromium_path"] = browser_path if os.path.exists(browser_path) else ""
        except Exception:
            info["chromium"] = False
        return info

    @app.get("/api/spaces")
    async def list_spaces():
        from orchestra.code_agent.ui.spaces import SpaceManager
        mgr = SpaceManager()
        return {"spaces": mgr.list()}

    class _CreateSpaceReq(BaseModel):
        name: str = "Untitled"
        description: str = ""

    @app.post("/api/spaces")
    async def create_space(req: _CreateSpaceReq):
        from orchestra.code_agent.ui.spaces import SpaceManager
        mgr = SpaceManager()
        space = mgr.create(req.name, req.description)
        return {"space": space.to_dict()}

    @app.get("/api/artifacts")
    async def list_artifacts():
        from orchestra.code_agent.ui.artifacts import ArtifactManager
        mgr = ArtifactManager()
        return {"artifacts": mgr.list()}

    @app.get("/api/artifacts/{aid}")
    async def get_artifact(aid: str):
        from orchestra.code_agent.ui.artifacts import ArtifactManager
        mgr = ArtifactManager()
        a = mgr.get(aid)
        if not a:
            raise HTTPException(status_code=404)
        return a.to_dict()

    @app.post("/api/browser/navigate")
    async def browser_navigate(body: dict = {}):
        url = body.get("url", "https://example.com")
        try:
            from orchestra.code_agent.browser.chromium import ChromiumController
            ctrl = ChromiumController(headless=True)
            result = await ctrl.navigate(url)
            if result.success and result.data:
                text = await ctrl.extract_text()
                await ctrl.close()
                return {
                    "success": True,
                    "title": result.data.title,
                    "url": result.data.url,
                    "text": text[:2000],
                }
            await ctrl.close()
            return {"success": False, "error": result.error}
        except ImportError as e:
            return {"success": False, "error": f"Playwright not installed: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/api/spaces/{sid}/sessions/{session_id}")
    async def add_session_to_space(sid: str, session_id: str):
        from orchestra.code_agent.ui.spaces import SpaceManager
        mgr = SpaceManager()
        ok = mgr.add_session(sid, session_id)
        return {"ok": ok}

    @app.delete("/api/spaces/{sid}")
    async def delete_space(sid: str):
        from orchestra.code_agent.ui.spaces import SpaceManager
        mgr = SpaceManager()
        ok = mgr.delete(sid)
        return {"deleted": ok}

    @app.post("/api/memory/toggle")
    async def toggle_memory(body: dict = {}):
        enabled = body.get("enabled", False)
        # Store in a simple config file
        try:
            import json as _j
            with open(".agent-memory.json", "w") as _f:
                _j.dump({"enabled": enabled}, _f)
        except Exception:
            pass
        return {"enabled": enabled}

    @app.get("/api/memory/status")
    async def memory_status():
        try:
            import json as _j
            with open(".agent-memory.json") as _f:
                data = _j.load(_f)
                return {"enabled": data.get("enabled", False)}
        except Exception:
            return {"enabled": True}

    @app.get("/api/steps")
    async def list_steps():
        from orchestra.code_agent.human import StepTracker
        tracker = StepTracker(workspace)
        return {"steps": tracker.get_steps(50)}

    @app.post("/api/steps/{step_id}/revert")
    async def revert_step(step_id: int):
        from orchestra.code_agent.human import StepTracker
        tracker = StepTracker(workspace)
        ok = tracker.revert_to(step_id)
        return {"reverted": ok, "step_id": step_id}

    @app.get("/api/approvals/pending")
    async def pending_approvals():
        from orchestra.code_agent.human import ApprovalManager
        mgr = ApprovalManager()
        return {"pending": mgr.pending_requests()}

    @app.get("/api/metrics")
    async def metrics():
        from orchestra.code_agent.telemetry.metrics import metrics_text
        body, content_type = metrics_text()
        from fastapi.responses import Response
        return Response(content=body, media_type=content_type)

    OBSERVABILITY_HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"><meta name="theme-color" content="#0d1117"><title>Orchestra Observability</title><style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#e6edf3;padding:24px;-webkit-font-smoothing:antialiased}
h1{font-size:22px;background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:20px;font-weight:700}
h2{font-size:13px;color:#8b949e;text-transform:uppercase;letter-spacing:.8px;margin:24px 0 10px;font-weight:600}
.metrics-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:20px}
.card{background:#1c2333;border:1px solid #30363d;border-radius:12px;padding:16px;transition:transform .15s,box-shadow .15s}
.card:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.3)}
.card .val{font-size:30px;font-weight:700;background:linear-gradient(135deg,#3fb950,#2ea043);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.card .val.error{-webkit-text-fill-color:#f85149;background:none;color:#f85149}
.card .label{font-size:11px;color:#8b949e;margin-top:6px;letter-spacing:.3px}
.llm-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:10px}
.llm-table th{text-align:left;padding:8px 10px;color:#8b949e;border-bottom:1px solid #30363d;font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:.5px}
.llm-table td{padding:8px 10px;border-bottom:1px solid #21262d}
.llm-table tr:hover{background:rgba(28,33,40,.6)}
.bar{height:6px;border-radius:3px;background:#21262d;overflow:hidden}
.bar-fill{height:100%;background:linear-gradient(90deg,#1f6feb,#58a6ff);border-radius:3px}
.bar-fill.ok{background:linear-gradient(90deg,#238636,#3fb950)}
.bar-fill.err{background:linear-gradient(90deg,#da3633,#f85149)}
</style></head><body><h1>Orchestra Observability</h1>
<div id="summary" style="color:#8b949e;font-size:13px">Loading metrics...</div>
<h2>LLM Calls</h2>
<table class="llm-table"><thead><tr><th>Provider</th><th>Model</th><th>Calls</th><th>Errors</th><th>Avg (s)</th><th>P95 (s)</th><th>Tokens</th></tr></thead><tbody id="llm-rows"></tbody></table>
<h2>Tool Calls</h2>
<table class="llm-table"><thead><tr><th>Tool</th><th>Calls</th><th>Errors</th><th>Avg (s)</th></tr></thead><tbody id="tool-rows"></tbody></table>
<h2>Raw Metrics</h2>
<pre id="raw-metrics" style="background:#1c2333;border:1px solid #30363d;border-radius:12px;padding:16px;font-size:11px;max-height:400px;overflow:auto;color:#8b949e;font-family:'SF Mono','Fira Code',monospace;line-height:1.5"></pre>
<script>
async function load(){
  try{
    const r=await fetch('/api/metrics');
    const text=await r.text();
    document.getElementById('raw-metrics').textContent=text;
    const lines=text.split('\n');
    const help={},data={},types={};
    let current='';
    lines.forEach(l=>{
      if(l.startsWith('# HELP ')){const m=l.match(/# HELP (\S+) (.+)/);if(m)help[m[1]]=m[2]}
      else if(l.startsWith('# TYPE ')){const m=l.match(/# TYPE (\S+) (\S+)/);if(m)types[m[1]]=m[2]}
      else if(l&&!l.startsWith('#')){
        const m=l.match(/^(\w+)\{(.+?)\}\s+([\d.e+]+)/);
        if(m){const key=m[1];if(!data[key])data[key]=[];const attrs=Object.fromEntries(m[2].split(',').map(a=>a.split('=').map((v,i)=>i?v.replace(/"/g,''):v)));attrs._val=parseFloat(m[3]);data[key].push(attrs)}
      }
    });
    renderLLM(data);
    renderTools(data);
    renderSummary(data);
  }catch(e){document.getElementById('summary').textContent='Error: '+e.message}
}
function renderLLM(data){
  const calls=data['llm_calls_total']||[];
  const dur=data['llm_call_duration_seconds_count']||[];
  const durSum=data['llm_call_duration_seconds_sum']||[];
  const toks=data['llm_tokens_total']||[];
  const rows={};
  calls.forEach(c=>{const k=c.provider+'/'+c.model;if(!rows[k])rows[k]={provider:c.provider,model:c.model,calls:0,errors:0,tokens:0};rows[k].calls+=c._val;if(c.status==='error')rows[k].errors+=c._val});
  dur.forEach(d=>{const k=d.provider+'/'+d.model;if(rows[k])rows[k].avg=d._val?durSum.find(s=>s.provider===d.provider&&s.model===d.model)?._val/d._val:0:0});
  toks.forEach(t=>{const k=t.provider+'/'+t.model;if(rows[k])rows[k].tokens+=t._val});
  const tbody=document.getElementById('llm-rows');
  tbody.innerHTML=Object.values(rows).map(r=>'<tr><td>'+r.provider+'</td><td>'+r.model+'</td><td>'+r.calls+'</td><td style="color:'+(r.errors?'#f85149':'#3fb950')+'">'+r.errors+'</td><td>'+(r.avg?r.avg.toFixed(1):'-')+'</td><td>-</td><td>'+r.tokens+'</td></tr>').join('');
}
function renderTools(data){
  const calls=data['tool_calls_total']||[];
  const durCount=data['tool_call_duration_seconds_count']||[];
  const durSum=data['tool_call_duration_seconds_sum']||[];
  const rows={};
  calls.forEach(c=>{const k=c.tool;if(!rows[k])rows[k]={tool:k,calls:0,errors:0};rows[k].calls+=c._val;if(c.status==='error')rows[k].errors+=c._val});
  durCount.forEach(d=>{if(rows[d.tool])rows[d.tool].avg=durSum.find(s=>s.tool===d.tool)?._val/d._val||0});
  document.getElementById('tool-rows').innerHTML=Object.values(rows).map(r=>'<tr><td>'+r.tool+'</td><td>'+r.calls+'</td><td style="color:'+(r.errors?'#f85149':'#3fb950')+'">'+r.errors+'</td><td>'+(r.avg?r.avg.toFixed(1):'-')+'</td></tr>').join('');
}
function renderSummary(data){
  const calls=(data['llm_calls_total']||[]).reduce((s,c)=>s+c._val,0);
  const errs=(data['llm_calls_total']||[]).filter(c=>c.status==='error').reduce((s,c)=>s+c._val,0);
  const toks=(data['llm_tokens_total']||[]).reduce((s,t)=>s+t._val,0);
  const tools=(data['tool_calls_total']||[]).reduce((s,t)=>s+t._val,0);
  document.getElementById('summary').innerHTML='<div class="metrics-grid"><div class="card"><div class="val">'+calls+'</div><div class="label">LLM Calls</div></div><div class="card"><div class="val '+(errs?'error':'')+'">'+errs+'</div><div class="label">Errors</div></div><div class="card"><div class="val">'+toks+'</div><div class="label">Tokens Used</div></div><div class="card"><div class="val">'+tools+'</div><div class="label">Tool Calls</div></div></div>';
}
load();
setInterval(load,5000);
</script></body></html>"""
    from fastapi.responses import HTMLResponse

    @app.get("/observability")
    async def observability():
        return HTMLResponse(OBSERVABILITY_HTML)

    @app.get("/api/langfuse")
    async def langfuse_dashboard():
        from orchestra.code_agent.telemetry.langfuse import LANGFUSE_CONFIGURED
        lf_host = __import__("os").environ.get("LANGFUSE_HOST", "")
        if LANGFUSE_CONFIGURED and lf_host:
            raise __import__("fastapi").responses.RedirectResponse(url=lf_host.rstrip("/"))
        return HTMLResponse("""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>LangFuse - Orchestra</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:32px;max-width:520px;width:90%}
h1{font-size:22px;color:#58a6ff;margin-bottom:8px}
p{color:#8b949e;font-size:14px;line-height:1.6;margin-bottom:16px}
code{background:#1c2128;padding:2px 6px;border-radius:4px;font-size:12px;color:#c9d1d9}
.step{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:12px;margin:10px 0;font-size:13px}
.step .num{display:inline-block;width:20px;height:20px;border-radius:50%;background:#1f6feb;color:#fff;text-align:center;font-size:11px;line-height:20px;margin-right:8px}
.btn{display:inline-block;background:#238636;color:#fff;border:none;border-radius:6px;padding:10px 20px;font-size:13px;cursor:pointer;text-decoration:none;margin-top:8px}
.btn:hover{background:#2ea043}
</style></head><body><div class="card"><h1>LangFuse</h1><p>LangFuse is an open-source LLM observability platform. It traces every LLM call, tracks token usage, latency, and errors, and provides a rich dashboard for debugging and optimization.</p>
<div class="step"><span class="num">1</span>Sign up at <a href="https://cloud.langfuse.com" style="color:#58a6ff" target="_blank">cloud.langfuse.com</a> or self-host</div>
<div class="step"><span class="num">2</span>Set environment variables:<br><code>LANGFUSE_HOST=https://cloud.langfuse.com</code><br><code>LANGFUSE_PUBLIC_KEY=pk-...</code><br><code>LANGFUSE_SECRET_KEY=sk-...</code></div>
<div class="step"><span class="num">3</span>Restart the server. Every LLM call will be traced automatically.</div>
<a class="btn" href="https://langfuse.com/docs" target="_blank">LangFuse Docs</a></div></body></html>""")

