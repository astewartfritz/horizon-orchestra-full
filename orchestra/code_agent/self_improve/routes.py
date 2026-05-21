"""Self-improvement analysis — Orchestra reads itself and surfaces improvement ideas."""
from __future__ import annotations

import asyncio
import collections
import json
import pathlib
import re
import subprocess
from typing import Any

from fastapi import FastAPI, Request

# Root of the Orchestra repo
_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent.parent


SELF_ANALYSIS_PROMPT = """\
You are an expert software architect reviewing the Orchestra AI agent platform — \
an autonomous coding assistant with a FastAPI backend, SQLite persistence, MCP server \
integration, and domain verticals (Healthcare, Finance, Logistics).

You have been given a structured snapshot of the codebase below. \
Work ONLY from this snapshot — do NOT read any files or use any tools. \
Your job is to identify the highest-leverage improvements Orchestra could make to itself.

Think across all dimensions:
- Developer experience (easier to extend, configure, debug)
- User experience (clearer UI, faster workflows, better feedback)
- Reliability (error handling, retries, graceful degradation)
- Performance (caching, concurrency, token efficiency)
- Security (input validation, auth, secrets management)
- Business value (features that unlock new customers or revenue)
- Code quality (dead code, inconsistent patterns, missing tests)

Return a JSON array of exactly 8 improvement suggestions, ordered by priority (highest first).
Each item must have these fields:
{
  "title": "Short, specific title (max 8 words)",
  "why": "1-2 sentences explaining the concrete pain or opportunity",
  "priority": "critical|high|medium|low",
  "effort": "30min|2h|half-day|day|week",
  "area": "which module/system this touches (e.g. 'ui/html.py', 'MCP', 'Healthcare billing')",
  "category": "ux|reliability|performance|security|feature|quality|dx",
  "prompt": "The exact task description to pass to Orchestra's agentic mode to implement this. Be specific — include file names, what to add/change, and the expected outcome."
}

Return ONLY the JSON array. No markdown, no explanation.
"""


def _collect_snapshot(app: Any = None) -> dict[str, Any]:
    """Build a rich but compact snapshot of Orchestra's own codebase."""
    snap: dict[str, Any] = {}

    # Module inventory
    module_counts: dict[str, int] = collections.Counter()
    test_count = 0
    todo_lines: list[str] = []
    total_lines = 0
    all_py: list[pathlib.Path] = []

    for p in (_REPO_ROOT / "orchestra" / "code_agent").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        all_py.append(p)
        parts = p.parts
        idx = next((i for i, x in enumerate(parts) if x == "code_agent"), None)
        if idx is not None and idx + 1 < len(parts):
            module_counts[parts[idx + 1]] += 1
        if "test" in p.name.lower():
            test_count += 1
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            lines = text.splitlines()
            total_lines += len(lines)
            for i, ln in enumerate(lines, 1):
                stripped = ln.strip()
                if re.search(r"#\s*(TODO|FIXME|HACK|XXX)", stripped):
                    todo_lines.append(f"{p.relative_to(_REPO_ROOT)}:{i}: {stripped}")
        except Exception:
            pass

    snap["module_inventory"] = dict(
        sorted(module_counts.items(), key=lambda x: -x[1])[:25]
    )
    snap["total_python_files"] = len(all_py)
    snap["total_lines_of_code"] = total_lines
    snap["test_files"] = test_count
    snap["todo_fixme_count"] = len(todo_lines)
    snap["todo_samples"] = todo_lines[:10]

    # Route inventory — read directly from the FastAPI app object
    if app is not None:
        try:
            paths = sorted({
                r.path for r in app.routes
                if hasattr(r, "path") and r.path.startswith("/api/")
            })
            snap["api_route_count"] = len(paths)
            snap["api_routes_sample"] = paths[:50]
        except Exception:
            snap["api_route_count"] = "unknown"
            snap["api_routes_sample"] = []
    else:
        snap["api_route_count"] = "unknown"
        snap["api_routes_sample"] = []

    # Read CLAUDE.md for architectural context
    claude_md = _REPO_ROOT / "CLAUDE.md"
    if claude_md.exists():
        snap["architecture_doc"] = claude_md.read_text(encoding="utf-8", errors="ignore")[:3000]

    # Git log — last 10 commits
    try:
        log = subprocess.check_output(
            ["git", "log", "--oneline", "-15"],
            cwd=str(_REPO_ROOT), stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        snap["recent_commits"] = log
    except Exception:
        snap["recent_commits"] = ""

    # Git status — what's modified
    try:
        status = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=str(_REPO_ROOT), stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        snap["git_status"] = status[:1000]
    except Exception:
        snap["git_status"] = ""

    # UI files (what the user sees)
    ui_files = [str(p.relative_to(_REPO_ROOT)) for p in
                (_REPO_ROOT / "orchestra" / "code_agent" / "ui").glob("*.py")]
    snap["ui_files"] = ui_files

    # Verticals present
    verticals = []
    for name in ("healthcare", "finance", "logistics", "legal"):
        if (_REPO_ROOT / "orchestra" / "code_agent" / name).exists():
            verticals.append(name)
    snap["verticals_built"] = verticals

    # Check for missing __init__ files (common source of import errors)
    missing_inits = []
    for d in (_REPO_ROOT / "orchestra" / "code_agent").iterdir():
        if d.is_dir() and not (d / "__init__.py").exists() and d.name != "__pycache__":
            missing_inits.append(d.name)
    snap["modules_missing_init"] = missing_inits[:10]

    # Env vars referenced but potentially unset
    env_refs: set[str] = set()
    for p in all_py[:100]:  # sample for speed
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            env_refs.update(re.findall(r'os\.environ\.get\(["\'](\w+)["\']', text))
            env_refs.update(re.findall(r'os\.environ\[["\'](\w+)["\']', text))
        except Exception:
            pass
    snap["env_vars_referenced"] = sorted(env_refs)[:30]

    return snap


def _compact_snapshot(snapshot: dict[str, Any]) -> str:
    """Trim snapshot to ~8KB so it fits inline in a CLI argument."""
    compact = {
        "total_python_files": snapshot.get("total_python_files"),
        "total_lines_of_code": snapshot.get("total_lines_of_code"),
        "api_route_count": snapshot.get("api_route_count"),
        "test_files": snapshot.get("test_files"),
        "todo_fixme_count": snapshot.get("todo_fixme_count"),
        "verticals_built": snapshot.get("verticals_built"),
        "modules_missing_init": snapshot.get("modules_missing_init"),
        # Top 15 modules by file count
        "top_modules": dict(list((snapshot.get("module_inventory") or {}).items())[:15]),
        # Sample of API routes grouped by prefix
        "api_route_prefixes": sorted({
            "/".join(r.split("/")[:3])
            for r in (snapshot.get("api_routes_sample") or [])
        })[:20],
        "todo_samples": snapshot.get("todo_samples", [])[:5],
        "recent_commits": (snapshot.get("recent_commits") or "")[:600],
        "repo_root": str(_REPO_ROOT),
    }
    return json.dumps(compact, indent=2)


def _extract_json_array(text: str) -> list[dict]:
    """Parse a JSON array out of LLM output, tolerating markdown fences."""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    else:
        s, e = text.find("["), text.rfind("]")
        if s != -1 and e != -1:
            text = text[s:e + 1]
    return json.loads(text)


async def _call_claude_code(snapshot: dict[str, Any]) -> list[dict]:
    """Run the self-analysis prompt through the Claude Code CLI (stdin pipe variant).

    Uses stdin to avoid Windows cmd.exe 8191-char command-line limit.
    stdin=PIPE with communicate() prevents hanging when server has no terminal.
    """
    import asyncio
    import shutil

    compact = _compact_snapshot(snapshot)
    prompt = (SELF_ANALYSIS_PROMPT + "\n\nORCHESTRA CODEBASE SNAPSHOT:\n" + compact).encode("utf-8")

    cli = shutil.which("claude") or "claude"
    cmd = [
        cli, "--print",
        "--output-format", "text",
        "--permission-mode", "bypassPermissions",
        "--max-turns", "1",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_REPO_ROOT),
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(input=prompt), timeout=180)
    output = stdout.decode("utf-8", errors="replace").strip()

    if not output:
        err = stderr.decode("utf-8", errors="replace").strip()[:600] if stderr else ""
        raise RuntimeError(f"Claude Code CLI produced no output (rc={proc.returncode}). stderr: {err}")

    # Try to parse even if rc != 0 — Claude Code sometimes exits 1 but still writes valid JSON
    try:
        return _extract_json_array(output)
    except Exception:
        err = stderr.decode("utf-8", errors="replace").strip()[:300] if stderr else ""
        raise RuntimeError(f"Claude Code CLI output not parseable (rc={proc.returncode}): {output[:300]!r} | stderr: {err}")


async def _call_llm_api(
    snapshot: dict[str, Any],
    provider: str = "anthropic",
    model: str = "claude-opus-4-7",
    api_key: str = "",
) -> list[dict]:
    """Fallback: call LLM API directly when Claude Code CLI is unavailable."""
    from orchestra.code_agent.llm.base import LLM, Message

    compact = _compact_snapshot(snapshot)
    user_prompt = "ORCHESTRA CODEBASE SNAPSHOT:\n" + compact

    llm = LLM(provider=provider, model=model, api_key=api_key or None, temperature=0.2)
    messages = [
        Message(role="system", content=SELF_ANALYSIS_PROMPT),
        Message(role="user", content=user_prompt),
    ]
    response = await llm.chat(messages)
    return _extract_json_array(response.content)


def register_self_improve_routes(app: FastAPI) -> None:  # noqa: C901

    @app.get("/api/self/debug")
    async def self_debug():
        """Raw subprocess debug — see exactly what Claude Code returns from inside the server."""
        import asyncio, shutil
        cli = shutil.which("claude") or "claude"
        prompt = b'Return ONLY this exact JSON array and nothing else: ["ok"]'
        cmd = [cli, "--print", "--output-format", "text", "--permission-mode", "bypassPermissions", "--max-turns", "1"]
        proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(_REPO_ROOT))
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=prompt), timeout=60)
        return {
            "cli": cli,
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace")[:500],
        }

    @app.get("/api/self/snapshot")
    async def self_snapshot(request: Request):
        """Return the raw codebase snapshot (no LLM call)."""
        snap = _collect_snapshot(request.app)
        snap.pop("architecture_doc", None)
        return snap

    @app.post("/api/self/analyze")
    async def self_analyze(request: Request):
        """Collect codebase snapshot → Claude Code (with API fallback) → prioritized improvements."""
        body: dict = {}
        try:
            body = await request.json()
        except Exception:
            pass

        provider = body.get("provider", "anthropic")
        model = body.get("model", "claude-opus-4-7")
        api_key = body.get("api_key", "")

        snapshot = _collect_snapshot(request.app)
        engine = "claude_code"

        try:
            suggestions = await _call_claude_code(snapshot)
        except Exception as cli_err:
            # Claude Code CLI unavailable or rate-limited — fall back to direct API
            engine = "api"
            try:
                suggestions = await _call_llm_api(snapshot, provider=provider, model=model, api_key=api_key)
            except Exception as api_err:
                return {
                    "error": f"Claude Code CLI: {cli_err} | API fallback: {api_err}",
                    "snapshot": {k: v for k, v in snapshot.items() if k != "architecture_doc"},
                    "suggestions": [],
                    "engine": "failed",
                }

        return {
            "snapshot": {k: v for k, v in snapshot.items() if k != "architecture_doc"},
            "suggestions": suggestions,
            "engine": engine,
        }
