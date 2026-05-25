"""CLI commands — config."""
from __future__ import annotations

import click

from ._core import main


@main.group()
def session():
    """Manage chat sessions."""


@session.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def session_list(json_output):
    """List all sessions."""
    from orchestra.code_agent.session import SessionManager
    mgr = SessionManager()
    items = mgr.list_sessions()
    if not items:
        safe_echo("No sessions found.")
        return

    if json_output:
        import json as _j
        safe_echo(_j.dumps(items, indent=2))
        return

    safe_echo(f"{'ID':<14} {'Task':<50} {'Created':<12} {'Turns':<6}")
    safe_echo("-" * 82)
    for s in items:
        sid = s["id"][:12]
        task = s["task"][:48]
        created = s.get("created_at", "")[:10]
        turns = s.get("message_count", 0)
        safe_echo(f"{sid:<14} {task:<50} {created:<12} {turns:<6}")


@session.command("show")
@click.argument("session_id")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def session_show(session_id, json_output):
    """Show a session's messages."""
    from orchestra.code_agent.session import SessionManager
    mgr = SessionManager()
    session = mgr.load(session_id)
    if not session:
        safe_echo(f"Session {session_id} not found.")
        return

    if json_output:
        import json as _j
        safe_echo(_j.dumps({"id": session.id, "task": session.task, "messages": session.messages}, indent=2))
        return

    safe_echo(f"Session: {session.id}")
    safe_echo(f"Task: {session.task}")
    safe_echo(f"Messages: {len(session.messages)}")
    safe_echo("")
    for m in session.messages:
        role = m.get("role", "?").upper()
        content = (m.get("content", "") or "")[:200]
        safe_echo(f"[{role}] {content}")
        safe_echo("")


@session.command("delete")
@click.argument("session_id")
def session_delete(session_id):
    """Delete a session."""
    from orchestra.code_agent.session import SessionManager
    import os
    mgr = SessionManager()
    try:
        os.remove(str(mgr.path / f"{session_id}.json"))
        safe_echo(f"Deleted session {session_id}.")
    except Exception as e:
        safe_echo(f"Error: {e}", err=True)


@session.command("export")
@click.argument("session_id")
@click.option("-f", "--format", "fmt", default="md", help="Export format (md, json)")
def session_export(session_id, fmt):
    """Export a session as markdown or JSON."""
    from orchestra.code_agent.session import SessionManager
    mgr = SessionManager()
    session = mgr.load(session_id)
    if not session:
        safe_echo(f"Session {session_id} not found.")
        return

    if fmt == "json":
        import json as _j
        safe_echo(_j.dumps({"id": session.id, "task": session.task, "messages": session.messages}, indent=2))
    else:
        safe_echo(f"# Session: {session.task}")
        safe_echo(f"Date: {session.created_at}")
        safe_echo(f"Messages: {len(session.messages)}")
        safe_echo("")
        for m in session.messages:
            role = m.get("role", "?").upper()
            content = m.get("content", "")
            if content:
                safe_echo(f"## {role}")
                safe_echo(content[:2000])
                safe_echo("")


# ═══════════════════════════════════════════════════════════════
# Config Management
# ═══════════════════════════════════════════════════════════════

@main.group()
def config():
    """Manage configuration."""


@config.command("show")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def config_show(json_output):
    """Show current configuration."""
    import json as _j
    from orchestra.code_agent.config import AgentConfig, LLMConfig

    cfg = AgentConfig()
    data = {
        "llm": {
            "provider": cfg.llm.provider,
            "model": cfg.llm.model,
            "max_tokens": cfg.llm.max_tokens,
            "temperature": cfg.llm.temperature,
            "timeout": cfg.llm.timeout,
        },
        "workspace": cfg.workspace,
        "max_iterations": cfg.max_iterations,
        "max_tool_rounds": cfg.max_tool_rounds,
        "allow_bash": cfg.allow_bash,
        "allow_web": cfg.allow_web,
        "enable_skills": cfg.enable_skills,
        "memory_type": cfg.memory_type,
    }
    if json_output:
        safe_echo(_j.dumps(data, indent=2))
    else:
        safe_echo("Current configuration:")
        for k, v in data.items():
            safe_echo(f"  {k}: {v}")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value (e.g., code-agent config set provider openai)."""
    import json, os
    config_dir = os.path.expanduser("~/.config/code-agent")
    config_file = os.path.join(config_dir, "config.json")
    os.makedirs(config_dir, exist_ok=True)

    try:
        with open(config_file) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}

    cfg[key] = value
    with open(config_file, "w") as f:
        json.dump(cfg, f, indent=2)
    safe_echo(f"Set {key} = {value}")


@config.command("init")
def config_init():
    """Initialize default configuration."""
    import json, os
    config_dir = os.path.expanduser("~/.config/code-agent")
    config_file = os.path.join(config_dir, "config.json")
    os.makedirs(config_dir, exist_ok=True)

    cfg = {
        "provider": "ollama",
        "model": "nemotron-mini",
        "max_tokens": 1024,
        "temperature": 0.0,
        "timeout": 600,
        "max_iterations": 50,
        "allow_bash": True,
        "allow_web": True,
        "enable_skills": True,
    }
    with open(config_file, "w") as f:
        json.dump(cfg, f, indent=2)
    safe_echo(f"Config initialized at {config_file}")


# ═══════════════════════════════════════════════════════════════
# Version
# ═══════════════════════════════════════════════════════════════

