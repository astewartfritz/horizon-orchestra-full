from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid

_logger = logging.getLogger("orchestra.chat")

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from code_agent import Agent, AgentConfig
from code_agent.config import LLMConfig
from code_agent.context.manager import ContextManager
from code_agent.session import Session, SessionManager

_active_tasks: dict[str, dict] = {}
_run_semaphore = asyncio.Semaphore(2)  # max 2 concurrent agent runs


class ChatRequest(BaseModel):
    task: str
    session_id: str = ""
    provider: str = "ollama"
    model: str = "nemotron-mini"
    api_key: str = ""
    use_cache: bool = False


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

        agent = Agent(cfg)
        if req.use_cache and req.api_key:
            from code_agent.cache.base import DiskCache
            from code_agent.cache.patch_llm import CachedLLM
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

    @app.get("/api/queue")
    async def queue_status():
        return {
            "active": len(_active_tasks),
            "running": sum(1 for t in _active_tasks.values() if not t.get("done")),
            "completed": sum(1 for t in _active_tasks.values() if t.get("done")),
            "semaphore_available": _run_semaphore._value if hasattr(_run_semaphore, "_value") else "?",
        }

    @app.post("/api/frontier/ask")
    async def frontier_ask():
        from pydantic import BaseModel
        class FrontierRequest(BaseModel):
            question: str
            search_query: str | None = None
            include_tabs: bool = True
        import json as _j
        raw = await __import__("asyncio").to_thread(lambda: _j.loads("{}"))
        # Read body
        body_raw = await __import__("fastapi").requests.Request.body()
        try:
            req_data = _j.loads(body_raw) if body_raw else {}
        except Exception:
            req_data = {}
        from code_agent.frontier import FrontierEngine
        engine = FrontierEngine()
        result = await engine.research(
            query=req_data.get("question", ""),
            search_query=req_data.get("search_query"),
            include_tabs=req_data.get("include_tabs", True),
        )
        return {
            "answer": result.answer,
            "sources": result.sources,
            "tabs_used": result.tabs_used,
            "safety_level": result.safety_level,
            "latency_ms": result.latency_ms,
        }

    @app.post("/api/prince/ask")
    async def prince_ask():
        import json as _j
        body_raw = await __import__("fastapi").requests.Request.body()
        try:
            req_data = _j.loads(body_raw) if body_raw else {}
        except Exception:
            req_data = {}
        from code_agent.prince import PrinceEngine
        engine = PrinceEngine()
        result = await engine.ask(
            question=req_data.get("question", ""),
            search_query=req_data.get("search_query"),
        )
        return result

    @app.get("/api/connectors")
    async def list_connectors():
        from code_agent.frontier.connectors import ConnectorRegistry
        reg = ConnectorRegistry()
        return {"connectors": reg.list()}

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
        from code_agent.scaffold.generator import TEMPLATES
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
            from code_agent.browser.chromium import ChromiumController
            ctrl = ChromiumController(headless=True)
            browser_path = ctrl.browser_path
            info["chromium"] = os.path.exists(browser_path) if browser_path != "chrome" else False
            info["chromium_path"] = browser_path if os.path.exists(browser_path) else ""
        except Exception:
            info["chromium"] = False
        return info

    @app.get("/api/spaces")
    async def list_spaces():
        from code_agent.ui.spaces import SpaceManager
        mgr = SpaceManager()
        return {"spaces": mgr.list()}

    class _CreateSpaceReq(BaseModel):
        name: str = "Untitled"
        description: str = ""

    @app.post("/api/spaces")
    async def create_space(req: _CreateSpaceReq):
        from code_agent.ui.spaces import SpaceManager
        mgr = SpaceManager()
        space = mgr.create(req.name, req.description)
        return {"space": space.to_dict()}

    @app.get("/api/artifacts")
    async def list_artifacts():
        from code_agent.ui.artifacts import ArtifactManager
        mgr = ArtifactManager()
        return {"artifacts": mgr.list()}

    @app.get("/api/artifacts/{aid}")
    async def get_artifact(aid: str):
        from code_agent.ui.artifacts import ArtifactManager
        mgr = ArtifactManager()
        a = mgr.get(aid)
        if not a:
            raise HTTPException(status_code=404)
        return a.to_dict()

    @app.post("/api/browser/navigate")
    async def browser_navigate(body: dict = {}):
        url = body.get("url", "https://example.com")
        try:
            from code_agent.browser.chromium import ChromiumController
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
        from code_agent.ui.spaces import SpaceManager
        mgr = SpaceManager()
        ok = mgr.add_session(sid, session_id)
        return {"ok": ok}

    @app.delete("/api/spaces/{sid}")
    async def delete_space(sid: str):
        from code_agent.ui.spaces import SpaceManager
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
        from code_agent.human import StepTracker
        tracker = StepTracker(workspace)
        return {"steps": tracker.get_steps(50)}

    @app.post("/api/steps/{step_id}/revert")
    async def revert_step(step_id: int):
        from code_agent.human import StepTracker
        tracker = StepTracker(workspace)
        ok = tracker.revert_to(step_id)
        return {"reverted": ok, "step_id": step_id}

    @app.get("/api/approvals/pending")
    async def pending_approvals():
        from code_agent.human import ApprovalManager
        mgr = ApprovalManager()
        return {"pending": mgr.pending_requests()}

    @app.get("/api/metrics")
    async def metrics():
        from code_agent.telemetry.metrics import metrics_text
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
        from code_agent.telemetry.langfuse import LANGFUSE_CONFIGURED
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

