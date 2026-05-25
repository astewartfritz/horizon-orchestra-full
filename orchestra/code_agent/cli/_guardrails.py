"""CLI commands — guardrails."""
from __future__ import annotations

import click

from ._core import main


@main.group()
def guardrails():
    """Manage automated safety guardrails for tool execution."""


@guardrails.command("list")
def guardrails_list():
    """List all guardrails rules and their status."""
    from orchestra.code_agent.guardrails.policy import Guardrails
    g = Guardrails()
    for pname, policy in g.policies.items():
        safe_echo(f"Policy: {pname}")
        safe_echo(f"{'Rule':30} {'Severity':10} {'Status':8}  Description")
        safe_echo("-" * 80)
        for rule in policy.rules:
            status = "enabled" if rule.enabled else "disabled"
            safe_echo(f"{rule.name:30} {rule.severity:10} {status:8}  {rule.description}")


@guardrails.command("enable")
@click.argument("rule_name")
def guardrails_enable(rule_name):
    """Enable a guardrails rule by name."""
    from orchestra.code_agent.guardrails.policy import Guardrails
    g = Guardrails()
    found = False
    for policy in g.policies.values():
        for rule in policy.rules:
            if rule.name == rule_name:
                rule.enabled = True
                found = True
    if found:
        safe_echo(f"Enabled rule: {rule_name}")
    else:
        safe_echo(f"Rule not found: {rule_name}")


@guardrails.command("disable")
@click.argument("rule_name")
def guardrails_disable(rule_name):
    """Disable a guardrails rule by name."""
    from orchestra.code_agent.guardrails.policy import Guardrails
    g = Guardrails()
    found = False
    for policy in g.policies.values():
        for rule in policy.rules:
            if rule.name == rule_name:
                rule.enabled = False
                found = True
    if found:
        safe_echo(f"Disabled rule: {rule_name}")
    else:
        safe_echo(f"Rule not found: {rule_name}")

@guardrails.command("check")
@click.argument("tool_name")
@click.argument("args_json")
def guardrails_check(tool_name, args_json):
    """Test a tool call against guardrails rules without executing it."""
    from orchestra.code_agent.guardrails.policy import Guardrails
    import json
    g = Guardrails()
    try:
        args = json.loads(args_json)
    except json.JSONDecodeError as e:
        safe_echo(f"Invalid JSON: {e}")
        return
    results = g.check_tool_call(tool_name, args)
    if not results:
        safe_echo("All checks passed")
    else:
        safe_echo(g.summary(results))


# --- Nemoclaw (LLM-powered guardrails) ---

@main.group()
def nemoclaw():
    """LLM-powered safety guardrails using Nemotron for intelligent content validation."""


@nemoclaw.command("check")
@click.argument("action")
@click.argument("context_json", required=False, default="{}")
def nemoclaw_check(action, context_json):
    """Check an action with Nemoclaw LLM guardrails. Provide action name and optional JSON context."""
    import asyncio
    import json
    from orchestra.code_agent.guardrails.nemoclaw import Nemoclaw, NemoclawConfig
    config = NemoclawConfig()
    n = Nemoclaw(config)
    try:
        ctx = json.loads(context_json) if context_json else {}
    except json.JSONDecodeError as e:
        safe_echo(f"Invalid JSON: {e}")
        return
    check = asyncio.run(n.check(action, ctx))
    label = check.label
    safe_echo(f"[{label}] {action}")
    safe_echo(f"  Reasoning: {check.reasoning}")
    safe_echo(f"  Confidence: {check.confidence:.2f}")
    safe_echo(f"  Category: {check.category}")
    safe_echo(f"  Latency: {check.latency_ms:.1f}ms")


@nemoclaw.command("check-tool")
@click.argument("tool_name")
@click.argument("args_json")
def nemoclaw_check_tool(tool_name, args_json):
    """Check a tool call with Nemoclaw."""
    import asyncio
    import json
    from orchestra.code_agent.guardrails.nemoclaw import Nemoclaw, NemoclawConfig
    config = NemoclawConfig()
    n = Nemoclaw(config)
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        safe_echo(f"Invalid JSON: {e}")
        return
    check = asyncio.run(n.check_tool_call(tool_name, args))
    label = check.label
    safe_echo(f"[{label}] tool_call: {tool_name}")
    safe_echo(f"  Reasoning: {check.reasoning}")
    safe_echo(f"  Confidence: {check.confidence:.2f}")
    safe_echo(f"  Category: {check.category}")
    safe_echo(f"  Latency: {check.latency_ms:.1f}ms")


@nemoclaw.command("check-cmd")
@click.argument("command")
def nemoclaw_check_cmd(command):
    """Check a bash command with Nemoclaw."""
    import asyncio
    from orchestra.code_agent.guardrails.nemoclaw import Nemoclaw, NemoclawConfig
    config = NemoclawConfig()
    n = Nemoclaw(config)
    check = asyncio.run(n.check_command(command))
    label = check.label
    safe_echo(f"[{label}] command: {command}")
    safe_echo(f"  Reasoning: {check.reasoning}")
    safe_echo(f"  Confidence: {check.confidence:.2f}")
    safe_echo(f"  Category: {check.category}")
    safe_echo(f"  Latency: {check.latency_ms:.1f}ms")


@nemoclaw.command("stats")
def nemoclaw_stats():
    """Show Nemoclaw usage statistics."""
    from orchestra.code_agent.guardrails.nemoclaw import Nemoclaw, NemoclawConfig
    config = NemoclawConfig()
    n = Nemoclaw(config)
    s = n.stats()
    safe_echo("Nemoclaw Statistics")
    safe_echo(f"  Enabled:     {s['enabled']}")
    safe_echo(f"  Provider:    {s['provider']}")
    safe_echo(f"  Model:       {s['model']}")
    safe_echo(f"  Total checks: {s['total_checks']}")
    safe_echo(f"  Blocks:      {s['blocks']}")
    safe_echo(f"  Warnings:    {s['warnings']}")
    safe_echo(f"  Passes:      {s['passes']}")
    safe_echo(f"  Cache hits:  {s['cache_hits']}")
    safe_echo(f"  Avg latency: {s['avg_latency_ms']}ms")
    safe_echo(f"  Cache size:  {s['cache_size']}")


@nemoclaw.command("health")
def nemoclaw_health():
    """Check if Nemoclaw LLM backend is healthy."""
    import asyncio
    from orchestra.code_agent.guardrails.nemoclaw import Nemoclaw, NemoclawConfig
    config = NemoclawConfig(timeout=10)
    n = Nemoclaw(config)
    h = asyncio.run(n.health())
    if h.get("healthy"):
        safe_echo("Nemoclaw is healthy")
        safe_echo(f"  Provider: {h['provider']}")
        safe_echo(f"  Model: {h['model']}")
        safe_echo(f"  Latency: {h['latency_ms']:.1f}ms")
    else:
        safe_echo("Nemoclaw is unhealthy")
        safe_echo(f"  Error: {h.get('error', 'Unknown')}")


@nemoclaw.command("clear-cache")
def nemoclaw_clear_cache():
    """Clear Nemoclaw result cache."""
    from orchestra.code_agent.guardrails.nemoclaw import Nemoclaw, NemoclawConfig
    config = NemoclawConfig()
    n = Nemoclaw(config)
    count = n.clear_cache()
    safe_echo(f"Cleared {count} cached results")


# --- Prince-style answer engine ---

@main.group()
def prince():
    """Prince-style AI answer engine with search and citations."""


@prince.command("ask")
@click.argument("question")
@click.option("--provider", default="ollama", help="LLM provider")
@click.option("--model", default="nemotron-mini", help="Model name")
@click.option("--query", help="Custom search query (defaults to question)")
def prince_ask(question, provider, model, query):
    """Ask a question and get a Prince-style answer with citations."""
    import asyncio
    import re
    from orchestra.code_agent.prince.engine import PrinceEngine
    eng = PrinceEngine(provider=provider, model=model, timeout=120)
    result = asyncio.run(eng.ask(question, search_query=query))
    safe_echo("=" * 60)
    safe_echo(f"Q: {result['question']}")
    safe_echo("=" * 60)
    plain = re.sub(r'<[^>]+>', '', result.get('annotated_answer', result['answer']))
    safe_echo(plain)
    if result["sources"]:
        safe_echo("\n--- Sources ---")
        for s in result["sources"]:
            safe_echo(f"  [{s['id']}] {s['title']}")
            safe_echo(f"       {s['url']}")
    safe_echo(f"\n[{result['num_sources']} sources, {result['latency_ms']}ms]")


@prince.command("health")
@click.option("--provider", default="ollama", help="LLM provider")
@click.option("--model", default="nemotron-mini", help="Model name")
def prince_health(provider, model):
    """Check if the prince engine's LLM backend is healthy."""
    import asyncio
    from orchestra.code_agent.prince.engine import PrinceEngine
    eng = PrinceEngine(provider=provider, model=model, timeout=10)
    h = asyncio.run(eng.health())
    if h.get("healthy"):
        safe_echo("Prince engine is healthy")
        safe_echo(f"  Provider: {h['provider']}")
        safe_echo(f"  Model: {h['model']}")
        safe_echo(f"  Latency: {h['latency_ms']:.1f}ms")
    else:
        safe_echo("Prince engine is unhealthy")
        safe_echo(f"  Error: {h.get('error', 'Unknown')}")


