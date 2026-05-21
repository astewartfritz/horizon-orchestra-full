from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
except ImportError:
    HTTPServer = None  # type: ignore


_TOOL_NAMES = [
    "read", "write", "edit", "glob", "bash", "grep",
    "webfetch", "websearch", "git", "diff", "patch", "apply_edit",
    "analyze", "scaffold", "knowledge",
]

_TOOL_HELP = {
    "read": "read <path>",
    "write": "write <path> <content>",
    "edit": "edit <path> <old_string> <new_string>",
    "glob": 'glob <pattern> [path="."]',
    "bash": "bash <command> [timeout=30]",
    "grep": "grep <pattern> [path=\".\"]",
    "webfetch": "webfetch <url>",
    "websearch": 'websearch <query> [count=5]',
    "git": "git <args...>",
    "analyze": "analyze <path>",
    "scaffold": "scaffold <type> <name>",
    "knowledge": 'knowledge <action> <query>',
}


@dataclass
class PlaygroundSession:
    history: list[dict] = field(default_factory=list)
    tools: dict[str, Any] = field(default_factory=dict)


_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Code Agent Playground</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1b26; color: #c0caf5; height: 100vh; display: flex; }}
  .sidebar {{ width: 260px; background: #1f2335; border-right: 1px solid #2f3346; padding: 16px; overflow-y: auto; flex-shrink: 0; }}
  .sidebar h2 {{ font-size: 14px; color: #565f89; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; }}
  .tool-btn {{ display: block; width: 100%; padding: 8px 12px; background: #292e42; border: 1px solid #2f3346; color: #c0caf5; border-radius: 6px; margin-bottom: 4px; cursor: pointer; font-size: 13px; text-align: left; }}
  .tool-btn:hover {{ background: #33467c; border-color: #4f8cf7; }}
  .main {{ flex: 1; display: flex; flex-direction: column; }}
  .toolbar {{ padding: 12px 20px; background: #1f2335; border-bottom: 1px solid #2f3346; display: flex; align-items: center; gap: 12px; }}
  .toolbar h1 {{ font-size: 18px; flex: 1; }}
  .toolbar select, .toolbar input {{ background: #292e42; border: 1px solid #2f3346; color: #c0caf5; padding: 6px 10px; border-radius: 6px; font-size: 13px; }}
  .content {{ flex: 1; display: flex; overflow: hidden; }}
  .config-panel {{ width: 280px; background: #1f2335; border-left: 1px solid #2f3346; padding: 16px; overflow-y: auto; flex-shrink: 0; }}
  .config-panel h3 {{ font-size: 13px; color: #565f89; margin-bottom: 8px; }}
  .config-panel label {{ display: block; font-size: 12px; color: #737aa2; margin: 8px 0 4px; }}
  .config-panel input, .config-panel textarea {{ width: 100%; background: #292e42; border: 1px solid #2f3346; color: #c0caf5; padding: 6px 8px; border-radius: 4px; font-size: 12px; font-family: monospace; }}
  .config-panel textarea {{ height: 80px; resize: vertical; }}
  .config-panel button {{ width: 100%; padding: 8px; background: #4f8cf7; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; margin-top: 12px; }}
  .config-panel button:hover {{ background: #3d7be0; }}
  .result-area {{ flex: 1; padding: 20px; overflow-y: auto; }}
  .prompt-area {{ padding: 12px 20px; background: #1f2335; border-top: 1px solid #2f3346; display: flex; gap: 8px; }}
  .prompt-area input {{ flex: 1; background: #292e42; border: 1px solid #2f3346; color: #c0caf5; padding: 10px 14px; border-radius: 8px; font-size: 14px; outline: none; }}
  .prompt-area input:focus {{ border-color: #4f8cf7; }}
  .prompt-area button {{ padding: 10px 24px; background: #4f8cf7; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; }}
  .prompt-area button:hover {{ background: #3d7be0; }}
  .result-box {{ background: #1f2335; border: 1px solid #2f3346; border-radius: 8px; padding: 16px; margin-bottom: 12px; white-space: pre-wrap; font-family: 'Fira Code', 'Cascadia Code', monospace; font-size: 13px; line-height: 1.5; }}
  .result-box .tool-label {{ color: #4f8cf7; font-weight: 600; margin-bottom: 8px; }}
  .result-box .output {{ color: #9ece6a; }}
  .result-box .error {{ color: #f7768e; }}
  .result-box .meta {{ color: #565f89; font-size: 11px; margin-top: 4px; }}
  .history-item {{ padding: 6px 8px; cursor: pointer; border-radius: 4px; font-size: 12px; color: #737aa2; }}
  .history-item:hover {{ background: #292e42; }}
  ::-webkit-scrollbar {{ width: 6px; }}
  ::-webkit-scrollbar-track {{ background: #1a1b26; }}
  ::-webkit-scrollbar-thumb {{ background: #2f3346; border-radius: 3px; }}
</style>
</head>
<body>
<div class="sidebar">
  <h2>Tools</h2>
  <div id="tool-list"></div>
  <h2 style="margin-top:20px">History</h2>
  <div id="history-list"></div>
</div>
<div class="main">
  <div class="toolbar">
    <h1>Agent Playground</h1>
    <select id="model-select"><option>auto</option><option>gpt-4o</option><option>claude-3-opus</option><option>ollama</option></select>
    <input id="workspace-input" placeholder="Workspace path..." value="." style="width:200px">
  </div>
  <div class="content">
    <div class="result-area" id="result-area">
      <div class="result-box" style="color:#565f89;text-align:center;padding:40px">
        Select a tool or type a command to test.<br><br>
        <span style="font-size:11px">Example: <code style="background:#292e42;padding:2px 6px;border-radius:3px">read src/code_agent/__init__.py</code></span>
      </div>
    </div>
    <div class="config-panel">
      <h3>Tool Config</h3>
      <label>Tool</label>
      <select id="tool-select" style="width:100%;background:#292e42;border:1px solid #2f3346;color:#c0caf5;padding:6px;border-radius:4px;font-size:12px">
        <option value="bash">bash</option>
        <option value="read">read</option>
        <option value="write">write</option>
        <option value="edit">edit</option>
        <option value="grep">grep</option>
        <option value="glob">glob</option>
        <option value="webfetch">webfetch</option>
      </select>
      <label>Arguments (one per line)</label>
      <textarea id="args-input" placeholder="arg1&#10;arg2&#10;key=value"></textarea>
      <button onclick="runTool()">Run Tool</button>
      <h3 style="margin-top:20px">Help</h3>
      <div style="font-size:11px;color:#737aa2;line-height:1.6" id="help-text">
        <div><strong style="color:#c0caf5">bash</strong> — Run shell command</div>
        <div><strong style="color:#c0caf5">read</strong> — Read file</div>
        <div><strong style="color:#c0caf5">write</strong> — Write file</div>
        <div><strong style="color:#c0caf5">edit</strong> — Edit file</div>
        <div><strong style="color:#c0caf5">grep</strong> — Search contents</div>
        <div><strong style="color:#c0caf5">glob</strong> — Find files</div>
      </div>
    </div>
  </div>
  <div class="prompt-area">
    <input id="prompt-input" placeholder="Type a command or natural language task..." onkeydown="if(event.key==='Enter') submitPrompt()">
    <button onclick="submitPrompt()">Send</button>
  </div>
</div>
<script>
let history = [];

async function callAPI(endpoint, data) {{
  try {{
    const r = await fetch(endpoint, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(data),
    }});
    return await r.json();
  }} catch(e) {{
    return {{error: e.message}};
  }}
}}

async function runTool() {{
  const tool = document.getElementById('tool-select').value;
  const argsText = document.getElementById('args-input').value;
  const args = argsText.split('\\n').filter(a => a.trim());
  addResult('bash', 'Running ' + tool + ' ' + args.join(' '), 'pending');
  const result = await callAPI('/api/run-tool', {{tool, args}});
  displayResult(result);
}}

async function submitPrompt() {{
  const input = document.getElementById('prompt-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addResult('prompt', text, 'user');
  const result = await callAPI('/api/run-task', {{task: text, model: document.getElementById('model-select').value, workspace: document.getElementById('workspace-input').value}});
  displayResult(result);
}}

function displayResult(result) {{
  const area = document.getElementById('result-area');
  const box = document.createElement('div');
  box.className = 'result-box';
  if (result.error) {{
    box.innerHTML = '<div class="tool-label">Error</div><div class="error">' + escapeHtml(result.error) + '</div>';
  }} else if (result.output) {{
    box.innerHTML = '<div class="tool-label">Output</div><div class="output">' + escapeHtml(result.output) + '</div>';
  }} else {{
    box.innerHTML = '<div class="tool-label">Result</div><div class="output">' + escapeHtml(JSON.stringify(result, null, 2)) + '</div>';
  }}
  box.innerHTML += '<div class="meta">' + new Date().toLocaleTimeString() + '</div>';
  area.insertBefore(box, area.firstChild);
}}

function addResult(type, text, cls) {{
  const area = document.getElementById('result-area');
  const box = document.createElement('div');
  box.className = 'result-box';
  box.innerHTML = '<div class="tool-label">' + type + '</div><div class="' + cls + '">' + escapeHtml(text) + '</div>';
  area.insertBefore(box, area.firstChild);
  const hl = document.getElementById('history-list');
  const item = document.createElement('div');
  item.className = 'history-item';
  item.textContent = text.slice(0, 60) + (text.length > 60 ? '...' : '');
  hl.insertBefore(item, hl.firstChild);
}}

function escapeHtml(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

document.querySelectorAll('.tool-btn').forEach(b => b.addEventListener('click', function() {{
  document.getElementById('tool-select').value = this.dataset.tool;
  const help = {{}};
  document.getElementById('help-text').innerHTML = '<div><strong style=\\"color:#c0caf5\\">' + this.dataset.tool + '</strong> — ' + (help[this.dataset.tool] || '') + '</div>';
}}));
</script>
</body>
</html>"""


class _Handler(BaseHTTPRequestHandler):
    playground: Optional[PlaygroundServer] = None

    def do_GET(self):
        if self.path == "/":
            self._send_html()
        elif self.path == "/api/tools":
            self._send_json({"tools": _TOOL_NAMES})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"
        data = json.loads(body) if body else {}

        if self.path == "/api/run-tool":
            result = self._run_tool(data)
            self._send_json(result)
        elif self.path == "/api/run-task":
            result = self._run_task(data)
            self._send_json(result)
        else:
            self._send_json({"error": "Unknown endpoint"})

    def _send_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_HTML.encode("utf-8"))

    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _run_tool(self, data):
        tool = data.get("tool", "bash")
        args = data.get("args", [])
        try:
            if tool == "bash":
                cmd = " ".join(args) if args else "echo hello"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                output = result.stdout
                if result.stderr:
                    output += "\n" + result.stderr
                return {"output": output.strip()}
            elif tool == "read":
                path = args[0] if args else "."
                try:
                    content = Path(path).read_text(encoding="utf-8")
                    return {"output": content[:5000]}
                except Exception as e:
                    return {"error": str(e)}
            elif tool == "glob":
                pattern = args[0] if args else "*"
                p = Path(args[1]) if len(args) > 1 else Path(".")
                files = list(p.rglob(pattern)) if "**" in pattern else list(p.glob(pattern))
                return {"output": "\n".join(str(f) for f in files[:50])}
            elif tool == "grep":
                pattern = args[0] if args else ""
                p = Path(args[1]) if len(args) > 1 else Path(".")
                matches = []
                for f in p.rglob("*"):
                    if f.is_file() and f.suffix in {".py", ".ts", ".js", ".md", ".txt", ".json", ".yaml", ".toml"}:
                        try:
                            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                                if pattern in line:
                                    matches.append(f"{f}:{i}: {line.strip()[:120]}")
                        except Exception:
                            continue
                return {"output": "\n".join(matches[:50])}
            else:
                return {"output": f"Tool '{tool}' executed with args: {args}"}
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out"}
        except Exception as e:
            return {"error": str(e)}

    def _run_task(self, data):
        task = data.get("task", "")
        model = data.get("model", "auto")
        workspace = data.get("workspace", ".")
        try:
            from orchestra.code_agent.config import AgentConfig, LLMConfig
            llm = LLMConfig(model=model if model != "auto" else "gpt-4o")
            cfg = AgentConfig(llm=llm, workspace=str(Path(workspace).resolve()), max_iterations=5)
            from orchestra.code_agent.agent import Agent
            import asyncio
            agent = Agent(cfg)
            result = asyncio.run(agent.run_async(task))
            return {"output": str(result)}
        except Exception as e:
            return {"error": str(e)}

    def log_message(self, format, *args):
        pass


class PlaygroundServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8400):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, open_browser: bool = True) -> None:
        if HTTPServer is None:
            print("http.server not available; cannot start playground")
            return

        _Handler.playground = self
        self.server = HTTPServer((self.host, self.port), _Handler)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        url = f"http://{self.host}:{self.port}"
        print(f"Playground running at {url}")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
