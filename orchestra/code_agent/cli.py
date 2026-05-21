from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import click

from orchestra.code_agent import Agent, AgentConfig


def safe_echo(msg: str, nl: bool = True, err: bool = False) -> None:
    """Echo text safely on Windows consoles that don't support Unicode."""
    try:
        click.echo(msg, nl=nl, err=err)
    except UnicodeEncodeError:
        ascii_safe = msg.encode("ascii", "replace").decode("ascii")
        click.echo(ascii_safe, nl=nl, err=err)

import os as _SYS_ENVIRON
from orchestra.code_agent.config import LLMConfig


@click.group()
def main():
    """Code Agent - Autonomous AI-powered software engineering assistant."""


@main.command()
@click.argument("task", required=False)
@click.option("-m", "--model", default="gpt-4o", help="LLM model to use")
@click.option("-p", "--provider", default="openai", help="LLM provider (openai, anthropic, ollama)")
@click.option("-w", "--workspace", default=".", help="Workspace directory")
@click.option("--max-iter", default=50, help="Max iterations", type=int)
@click.option("--config", "-c", help="Path to config JSON file")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--confirm", is_flag=True, help="Confirm before running commands")
@click.option("--no-guardrails", is_flag=True, help="Disable automated guardrails safety checks")
@click.option("--no-nemoclaw", is_flag=True, help="Disable Nemoclaw LLM guardrails")
@click.option("--no-skills", is_flag=True, help="Disable skill library retrieval and distillation")
@click.option("--cache", is_flag=True, help="Enable LLM response caching")
@click.option("--stream", is_flag=True, help="Stream response tokens in real-time")
@click.option("--list-tools", is_flag=True, help="List available tools and exit")
@click.option("--session", help="Resume a previous session by ID")
@click.option("--reasoning", default="auto", help="Reasoning strategy: cot, plan, reflect, tot, auto")
@click.option("--plan/--no-plan", default=True, help="Plan before executing")
@click.option("--show-thought/--quiet", default=True, help="Show reasoning output")
@click.option("--mdconfig", "mdconfig_dir", help="Load .md config files from directory")
def run(task, model, provider, workspace, max_iter, config, verbose, confirm, no_guardrails, no_nemoclaw, no_skills, cache, stream, list_tools, session, reasoning, plan, show_thought, mdconfig_dir):
    """Run the code agent with a TASK."""
    from orchestra.code_agent.config import ReasoningConfig
    from orchestra.code_agent.mdconfig.loader import MarkdownConfigLoader
    reason_cfg = ReasoningConfig(strategy=reasoning, plan_first=plan, show_thinking=show_thought)

    if config:
        cfg = AgentConfig.from_file(config)
        cfg.reasoning = reason_cfg
    else:
        llm = LLMConfig(provider=provider, model=model)
        cfg = AgentConfig(
            llm=llm,
            max_iterations=max_iter,
            workspace=str(Path(workspace).resolve()),
            verbose=verbose,
            confirm_commands=confirm,
            enable_guardrails=not no_guardrails,
            enable_nemoclaw=not no_nemoclaw,
            enable_skills=not no_skills,
            reasoning=reason_cfg,
        )

    # Load .md config files if specified
    if mdconfig_dir:
        loader = MarkdownConfigLoader()
        loaded = loader.add_dir(mdconfig_dir)
        if loaded:
            click.echo(f"Loaded {len(loaded)} markdown config files from {mdconfig_dir}")

    if session:
        from orchestra.code_agent.session import SessionManager
        mgr = SessionManager()
        agent = asyncio.run(mgr.resume_agent(session))
        if not agent:
            click.echo(f"Session not found: {session}")
            return
        click.echo(f"Resumed session {session}")
    else:
        agent = Agent(cfg)

    if cache:
        from orchestra.code_agent.cache.patch_llm import CachedLLM
        from orchestra.code_agent.cache.base import DiskCache
        agent.llm = CachedLLM(agent.llm, DiskCache())
        click.echo("LLM caching enabled")

    if list_tools:
        click.echo(agent.get_tools_summary())
        return

    if not task:
        click.echo("Enter your task (Ctrl+Z then Enter to submit, or type ':q' to quit):")
        lines = []
        try:
            for line in sys.stdin:
                line = line.rstrip("\n\r")
                if line.strip() == ":q":
                    break
                lines.append(line)
        except KeyboardInterrupt:
            pass
        task = "\n".join(lines).strip()

    if not task:
        click.echo("No task provided.")
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"Code Agent - Running task")
    click.echo(f"Model: {cfg.llm.provider}/{cfg.llm.model}")
    click.echo(f"Workspace: {cfg.workspace}")
    click.echo(f"{'='*60}\n")

    result = asyncio.run(agent.run(task, stream=stream))
    click.echo(f"\n{'='*60}")
    click.echo("Result:")
    click.echo(f"{'='*60}")
    click.echo(result)

    from orchestra.code_agent.session import Session, SessionManager
    session = Session.create(task, cfg)
    session.result = result
    session.finished = agent.state.finished
    session.add_message(
        __import__("code_agent.llm.base", fromlist=[""]).Message(
            role="user", content=task
        )
    )
    session.add_message(
        __import__("code_agent.llm.base", fromlist=[""]).Message(
            role="assistant", content=result
        )
    )
    mgr = SessionManager()
    mgr.save(session)
    click.echo(f"\nSession ID: {session.id}")


@main.command()
@click.argument("path", type=click.Path())
@click.option("-s", "--shell", is_flag=True, help="Open interactive shell")
def review(path, shell):
    """Review code changes. PATH can be a file, directory, or git diff."""
    from orchestra.code_agent.reviewer import CodeReviewer

    reviewer = CodeReviewer()
    if shell:
        click.echo("Interactive review shell not yet implemented.")
        return

    p = Path(path)
    if not p.exists():
        click.echo(f"Path not found: {path}")
        return

    click.echo(f"Reviewing: {path}")
    click.echo("=" * 60)

    review_text = p.read_text("utf-8") if p.is_file() else str(p)
    result = asyncio.run(reviewer.review(review_text))
    click.echo(result)


@main.command()
def init():
    """Create a default code-agent config file in the current directory."""
    cfg = AgentConfig()
    cfg_path = Path.cwd() / "code-agent.json"
    cfg.to_file(str(cfg_path))
    click.echo(f"Created default config: {cfg_path}")


@main.command()
def tools():
    """List all available tools."""
    from orchestra.code_agent.tools import get_all_tools
    all_tools = get_all_tools()
    for t_cls in all_tools:
        spec = t_cls.spec
        click.echo(f"\n  {spec.name}")
        click.echo(f"    {spec.description}")
        for pname, pinfo in spec.parameters.items():
            req = "*" if "default" not in pinfo else " "
            click.echo(f"    {req} {pname}: {pinfo.get('type', 'string')} - {pinfo.get('description', '')}")


@main.command()
@click.argument("template", type=click.Choice([
    "python-package", "python-script", "typescript-package", "web-app", "fastapi-app",
    "rust-package", "typescript-lib", "typescript-cli", "typescript-nextjs", "mojo-package",
]))
@click.argument("name")
@click.option("-d", "--description", default="", help="Project description")
@click.option("-o", "--output-dir", help="Output directory")
def scaffold(template, name, description, output_dir):
    """Generate a project from a template."""
    from orchestra.code_agent.scaffold.generator import ScaffoldGenerator
    gen = ScaffoldGenerator()
    result = asyncio.run(gen(template=template, name=name, description=description, output_dir=output_dir))
    click.echo(result.output)
    if result.error:
        click.echo(f"Error: {result.error}", err=True)


@main.command()
@click.argument("name")
@click.option("-d", "--description", default="", help="Project description")
@click.option("-o", "--output-dir", help="Output directory")
def scaffold_rust(name, description, output_dir):
    """Generate a Rust project with Cargo, CLI (clap), tokio, serde, tests, CI."""
    from orchestra.code_agent.scaffold.rust import RustScaffold
    result = asyncio.run(RustScaffold()(name=name, description=description, output_dir=output_dir))
    click.echo(result.output)


@main.command()
@click.argument("variant", type=click.Choice(["lib", "cli", "nextjs"]))
@click.argument("name")
@click.option("-d", "--description", default="", help="Project description")
@click.option("-o", "--output-dir", help="Output directory")
def scaffold_ts(variant, name, description, output_dir):
    """Generate a TypeScript project (lib, cli, or nextjs)."""
    vmap = {"lib": "typescript-lib", "cli": "typescript-cli", "nextjs": "typescript-nextjs"}
    from orchestra.code_agent.scaffold.typescript import TypeScriptScaffold
    result = asyncio.run(TypeScriptScaffold()(variant=vmap[variant], name=name, description=description, output_dir=output_dir))
    click.echo(result.output)


@main.command()
@click.argument("name")
@click.option("-d", "--description", default="", help="Project description")
@click.option("-o", "--output-dir", help="Output directory")
def scaffold_mojo(name, description, output_dir):
    """Generate a Mojo project with module, tests, Makefile, and notebook."""
    from orchestra.code_agent.scaffold.mojo import MojoScaffold
    result = asyncio.run(MojoScaffold()(name=name, description=description, output_dir=output_dir))
    click.echo(result.output)


@main.command()
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind")
@click.option("-p", "--port", default=8000, type=int, help="Port to bind")
@click.option("--provider", default="ollama", help="Default LLM provider")
@click.option("--model", default="nemotron-mini", help="Default model")
def serve(host, port, provider, model):
    """Start the Code Agent web UI."""
    from orchestra.code_agent.ui.server import create_ui_app
    import uvicorn
    cfg = AgentConfig(llm=LLMConfig(provider=provider, model=model))
    app = create_ui_app(cfg)
    click.echo(f"Code Agent UI at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


@main.command()
def check():
    """Run system diagnostics: LLM, GPU, providers, runtimes, libraries."""
    import subprocess, shutil, sys as _sys

    click.echo("=== Orchestra System Check ===")

    click.echo(f"\nPython:     {_sys.version.split()[0]} ({_sys.platform})")
    click.echo(f"PyTorch:    ", nl=False)
    try:
        import torch
        click.echo(f"{torch.__version__} CUDA={torch.cuda.is_available()}")
    except ImportError:
        click.echo("not installed")

    click.echo("GPU:        ", nl=False)
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=3)
        click.echo("NVIDIA" if r.returncode == 0 else "none detected")
    except Exception:
        click.echo("none detected")

    click.echo("Ollama:     ", nl=False)
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            click.echo(f"running ({len(models)} models: {', '.join(models[:4])}{'...' if len(models)>4 else ''})")
        else:
            click.echo("not responding")
    except Exception:
        click.echo("not running")

    click.echo("Runtimes:   ", nl=False)
    found = []
    for cmd in ["rustc", "node", "cargo", "mojo"]:
        p = shutil.which(cmd)
        if p:
            try:
                v = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=3)
                found.append(f"{cmd} {v.stdout.split()[1] if v.stdout else ''}")
            except Exception:
                found.append(cmd)
    click.echo(", ".join(found) if found else "none")

    click.echo("Skills:     ", nl=False)
    try:
        from orchestra.code_agent.skills.base import SkillLibrary
        lib = SkillLibrary()
        count = lib.count()
        click.echo(f"{count} skills in library")
        if count == 0:
            click.echo("  Run: python -c \"from orchestra.code_agent.skills.seed import seed_library; seed_library()\"")
    except Exception as e:
        click.echo(f"error: {e}")

    click.echo("Tests:      ", nl=False)
    try:
        r = subprocess.run([_sys.executable, "-m", "pytest", "-q", "--tb=no"], capture_output=True, text=True, timeout=60)
        last = r.stdout.strip().split("\n")[-1] if r.stdout else "?"
        click.echo(last)
    except Exception:
        click.echo("could not run")

    click.echo("\nEndpoints:")
    click.echo("  GUI:           http://127.0.0.1:8000/")
    click.echo("  Health:        http://127.0.0.1:8000/api/health")
    click.echo("  Metrics:       http://127.0.0.1:8000/api/metrics")
    click.echo("  Observability: http://127.0.0.1:8000/observability")
    click.echo("  Templates:     http://127.0.0.1:8000/api/scaffold/templates")


@main.group()
def model():
    """Manage models and serving infrastructure."""


@model.command("list")
@click.option("--provider", help="Filter by provider (openai, anthropic, ollama)")
@click.option("--capability", help="Filter by capability (chat, streaming, structured, tools, vision, code, reasoning)")
def model_list(provider, capability):
    """List registered models with their capabilities."""
    from orchestra.code_agent.serving.registry import ModelRegistry, ModelCapability
    registry = ModelRegistry()
    cap = ModelCapability(capability) if capability else None
    models = registry.list_models(provider=provider, capability=cap)
    if not models:
        click.echo("No models found.")
        return
    click.echo(f"{'Model ID':30} {'Provider':12} {'Capabilities':40} {'Cost (in/out)':20} {'Health':10}")
    click.echo("-" * 112)
    for m in models:
        caps = ", ".join(sorted(c.value for c in m.capabilities))[:38]
        cost = f"${m.cost_per_million_input:.2f}/${m.cost_per_million_output:.2f}"
        health = m.health_status or "unknown"
        click.echo(f"{m.model_id:30} {m.provider:12} {caps:40} {cost:20} {health:10}")


@model.command("register")
@click.argument("model_id")
@click.argument("provider")
@click.option("--capabilities", "-c", multiple=True, help="Capabilities (chat, streaming, structured, tools, vision, code, reasoning)")
@click.option("--context-window", default=8192, type=int, help="Context window size")
@click.option("--max-output", default=4096, type=int, help="Max output tokens")
@click.option("--cost-in", default=0.0, type=float, help="Cost per million input tokens")
@click.option("--cost-out", default=0.0, type=float, help="Cost per million output tokens")
@click.option("--alias", multiple=True, help="Model aliases")
def model_register(model_id, provider, capabilities, context_window, max_output, cost_in, cost_out, alias):
    """Register a new model in the registry."""
    from orchestra.code_agent.serving.registry import ModelRegistry
    registry = ModelRegistry()
    entry = registry.register(
        model_id=model_id,
        provider=provider,
        capabilities=list(capabilities) if capabilities else ["chat"],
        context_window=context_window,
        max_output_tokens=max_output,
        cost_per_million_input=cost_in,
        cost_per_million_output=cost_out,
        aliases=list(alias) if alias else [],
    )
    click.echo(f"Registered: {entry.model_id} ({entry.provider})")
    click.echo(f"  Capabilities: {', '.join(sorted(c.value for c in entry.capabilities))}")


@model.command("unregister")
@click.argument("model_id")
def model_unregister(model_id):
    """Remove a model from the registry."""
    from orchestra.code_agent.serving.registry import ModelRegistry
    registry = ModelRegistry()
    if registry.unregister(model_id):
        click.echo(f"Unregistered: {model_id}")
    else:
        click.echo(f"Model not found: {model_id}")


@model.command("info")
@click.argument("model_id")
def model_info(model_id):
    """Show detailed information about a registered model."""
    from orchestra.code_agent.serving.registry import ModelRegistry
    registry = ModelRegistry()
    entry = registry.get(model_id)
    if not entry:
        click.echo(f"Model not found: {model_id}")
        return
    click.echo(f"Model ID:     {entry.model_id}")
    click.echo(f"Provider:     {entry.provider}")
    click.echo(f"Capabilities: {', '.join(sorted(c.value for c in entry.capabilities))}")
    click.echo(f"Context:      {entry.context_window:,} tokens")
    click.echo(f"Max Output:   {entry.max_output_tokens:,} tokens")
    click.echo(f"Cost (in):    ${entry.cost_per_million_input:.4f}/M tokens")
    click.echo(f"Cost (out):   ${entry.cost_per_million_output:.4f}/M tokens")
    click.echo(f"Health:       {entry.health_status}")
    click.echo(f"Aliases:      {', '.join(entry.aliases) if entry.aliases else '(none)'}")
    click.echo(f"Tags:         {entry.tags}")


@model.command("probe")
@click.argument("provider")
@click.argument("model")
@click.option("--timeout", default=10.0, type=float, help="Probe timeout in seconds")
def model_probe(provider, model, timeout):
    """Check if a model provider is healthy."""
    import asyncio
    from orchestra.code_agent.serving.health import ModelHealthChecker
    checker = ModelHealthChecker()
    result = asyncio.run(checker.probe(provider, model, timeout))
    status = "[OK] Healthy" if result.healthy else "[FAIL] Unhealthy"
    safe_echo(f"Provider: {result.provider}")
    safe_echo(f"Model:    {result.model}")
    safe_echo(f"Status:   {status}")
    safe_echo(f"Latency:  {result.latency_ms:.1f}ms")
    if result.error:
        click.echo(f"Error:    {result.error}")


@model.command("route")
@click.argument("prompt")
@click.option("--strategy", default="fallback", help="Routing strategy: fallback, cheapest, fastest, round_robin, weighted")
@click.option("--capability", help="Required capability")
def model_route(prompt, strategy, capability):
    """Route a prompt through the model router and return the response."""
    import asyncio
    from orchestra.code_agent.llm.base import Message
    from orchestra.code_agent.serving.registry import ModelRegistry, ModelCapability
    from orchestra.code_agent.serving.router import ModelRouter, RouterRule, RouteTarget, RoutingStrategy

    registry = ModelRegistry()
    cap = ModelCapability(capability) if capability else None
    targets = [RouteTarget(provider=m.provider, model=m.model_id) for m in registry.list_models()]
    rule = RouterRule(
        name="cli-route",
        strategy=RoutingStrategy(strategy),
        targets=targets or [RouteTarget(provider="openai", model="gpt-4o")],
        required_capability=cap,
    )
    router = ModelRouter(registry, rules=[rule])
    messages = [Message(role="user", content=prompt)]
    result = asyncio.run(router.route_chat(messages, task=prompt))

    if result.success:
        safe_echo(f"\n[OK] Routed to: {result.provider}/{result.model}")
        safe_echo(f"Latency: {result.total_latency:.2f}s")
        safe_echo(f"Attempts: {len(result.attempts)}")
        safe_echo(f"\nResponse:\n{result.output[:2000]}")
    else:
        safe_echo(f"\n[FAIL] All routing attempts failed:")
        for a in result.attempts:
            safe_echo(f"  - {a['provider']}/{a['model']}: {a.get('error', 'unknown')}")


@model.command("health")
def model_health():
    """Show health summary for all probed models."""
    import asyncio
    from orchestra.code_agent.serving.health import ModelHealthChecker
    from orchestra.code_agent.serving.registry import ModelRegistry

    registry = ModelRegistry()
    checker = ModelHealthChecker()
    for m in registry.list_models():
        checker.register(m.provider, m.model_id, interval=300)
    results = asyncio.run(checker.probe_all())

    if not results:
        click.echo("No probe results. Use 'model probe' to check specific models.")
        return

    click.echo(f"{'Model':30} {'Health':10} {'Latency':10}")
    click.echo("-" * 50)
    for key, r in sorted(results.items()):
        status = "[OK]" if r.healthy else "[FAIL]"
        safe_echo(f"{key:30} {status + ' healthy':10} {r.latency_ms:>8.1f}ms")


@main.group()
def memory():
    """Manage agent memory, retrieval, and consolidation."""


@memory.command("store")
@click.argument("content")
@click.option("--tier", default="normal", help="Tier: critical, important, normal, low")
@click.option("--importance", default=0.5, type=float, help="Importance 0.0-1.0")
@click.option("--source", default="cli", help="Source label")
def memory_store(content, tier, importance, source):
    """Store a memory."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    mid = mgr.remember(content=content, tier=tier, importance=importance, source=source)
    click.echo(f"Stored memory #{mid}")


@memory.command("search")
@click.argument("query")
@click.option("--top-k", default=10, type=int, help="Number of results")
@click.option("--type", "memory_type", help="Filter by type: working, episodic, semantic, long_term")
def memory_search(query, top_k, memory_type):
    """Search memories by semantic similarity."""
    import asyncio
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    results = mgr.search_memories(query, top_k=top_k, memory_type=memory_type)
    if not results:
        click.echo("No matching memories found.")
        return
    click.echo(f"Found {len(results)} memories:\n")
    for i, r in enumerate(results, 1):
        click.echo(f"  {i}. [{r.tier:10}][{r.source:15}] ({r.score:.3f}) {r.content[:120]}...")


@memory.command("recall")
@click.argument("query")
@click.option("--top-k", default=5, type=int, help="Number of context snippets")
def memory_recall(query, top_k):
    """Retrieve relevant memory context for a query."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    context = mgr.get_context(query, max_tokens=top_k * 2000)
    if not context:
        click.echo("No relevant memories found.")
        return
    click.echo(context)


@memory.command("recent")
@click.option("--limit", default=20, type=int)
def memory_recent(limit):
    """Show most recent memories."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    results = mgr.recall_recent(limit=limit)
    if not results:
        click.echo("No recent memories.")
        return
    click.echo(f"Recent {len(results)} memories:\n")
    for i, r in enumerate(results, 1):
        click.echo(f"  {i}. [{r.tier:10}] ({time.strftime('%H:%M:%S', time.localtime(r.created_at))}) {r.content[:150]}...")


@memory.command("forget")
@click.argument("memory_id", type=int)
def memory_forget(memory_id):
    """Delete a specific memory by ID."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    if mgr.forget(memory_id):
        click.echo(f"Forgot memory #{memory_id}")
    else:
        click.echo(f"Memory #{memory_id} not found")


@memory.command("stats")
def memory_stats():
    """Show memory system statistics."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    stats = mgr.stats()
    ss = stats.get("store", {})
    bs = stats.get("buffer", {})
    gs = stats.get("graph", {})
    click.echo("Memory Statistics:")
    click.echo(f"  Store: {ss.get('total_memories', 0):>6} memories ({ss.get('total_tokens', 0):>8} tokens)")
    click.echo(f"    By type: {ss.get('by_type', {})}")
    click.echo(f"    By tier: {ss.get('by_tier', {})}")
    click.echo(f"  Buffer: {bs.get('total_entries', 0):>6} entries ({bs.get('utilization', 0)}% full)")
    click.echo(f"  Entities: {gs.get('total_entities', 0)} in graph")


@memory.command("consolidate")
@click.option("--session-id", help="Also summarize this session")
def memory_consolidate(session_id):
    """Run memory consolidation (dedup, tier migration, cleanup)."""
    import asyncio
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    reports = asyncio.run(mgr.consolidate(session_id=session_id))
    click.echo("Consolidation complete:\n")
    for r in reports:
        click.echo(f"  [{r.operation}] {r.summary} ({r.tokens_saved} tokens, {r.duration_ms:.0f}ms)")


@memory.command("entities")
@click.argument("name", required=False)
@click.option("--depth", default=2, type=int, help="Graph traversal depth")
def memory_entities(name, depth):
    """Show entity graph. With NAME, show entity network centered on that entity."""
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    if name:
        network = mgr.get_entity_network(name, depth=depth)
        click.echo(f"Entity Network: {name}")
        click.echo(f"  Nodes: {len(network.get('nodes', []))}")
        click.echo(f"  Edges: {len(network.get('edges', []))}")
        for edge in network.get("edges", [])[:10]:
            click.echo(f"    {edge['source']} --[{edge['relation']}]--> {edge['target']}")
    else:
        stats = mgr.stats()
        gs = stats.get("graph", {})
        click.echo(f"Total entities: {gs.get('total_entities', 0)}")
        for t, c in gs.get("by_type", {}).items():
            click.echo(f"  {t}: {c}")


@memory.command("clear")
@click.option("--force", is_flag=True, help="Confirm clearing all memories")
def memory_clear(force):
    """Clear all memories (requires --force)."""
    if not force:
        click.echo("Use --force to confirm clearing all memories.")
        return
    from orchestra.code_agent.memory.manager import MemoryManager
    mgr = MemoryManager()
    mgr.clear()
    click.echo("All memories cleared.")


@main.command()
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind")
@click.option("-p", "--port", default=8300, type=int, help="Port to bind")
def serving(host, port):
    """Start the model serving API server (streaming, registry, routing, health)."""
    import asyncio
    import uvicorn
    from orchestra.code_agent.serving.server import ServingServer
    server = ServingServer()
    click.echo(f"Model Serving API at http://{host}:{port}")
    click.echo(f"  Chat Completions: POST /v1/chat/completions")
    click.echo(f"  Router:           POST /v1/chat/router")
    click.echo(f"  Model Registry:   GET/POST /v1/models")
    click.echo(f"  Health Probes:    GET /v1/health/probes")
    uvicorn.run(server.app, host=host, port=port)


@main.command()
@click.argument("config_path", type=click.Path(exists=True))
def mcp(config_path):
    """Connect to an MCP server and expose its tools."""
    import asyncio
    from orchestra.code_agent.mcp.client import MCPClient

    async def _run():
        client = await MCPClient.from_config(config_path)
        click.echo("Available MCP tools:")
        from orchestra.code_agent.tools import CORE_TOOLS
        for tool in client._tools:
            CORE_TOOLS.append(type(tool))
            click.echo(f"  {tool.spec.name}: {tool.spec.description}")
        click.echo("\nTools registered. Run: code-agent run")
    asyncio.run(_run())


@main.command()
@click.option("--scenario", default="default", help="Benchmark scenario name")
@click.option("--save", help="Save results to JSON file")
def benchmark(scenario, save):
    """Run agent benchmarks."""
    from orchestra.code_agent.benchmark import Benchmark, BenchmarkTask

    tasks = [
        BenchmarkTask("read-file", "Read the main agent.py file and summarize its structure."),
        BenchmarkTask("list-files", "List all Python files in the src directory and count their total lines."),
        BenchmarkTask("self-test", "Read the pyproject.toml and summarize the project dependencies."),
    ]

    bm = Benchmark()
    for t in tasks:
        bm.add_task(t)

    click.echo(f"Running {len(tasks)} benchmark tasks...")
    results = asyncio.run(bm.run_all())
    report = bm.report(results)
    click.echo(f"\n{report}")

    if save:
        bm.save_json(results, save)
        click.echo(f"Results saved to {save}")


@main.command()
@click.option("--list", "list_sessions", is_flag=True, help="List all sessions")
@click.argument("session_id", required=False)
def session(list_sessions, session_id):
    """Manage agent sessions."""
    from orchestra.code_agent.session import SessionManager
    mgr = SessionManager()

    if list_sessions:
        sessions = mgr.list_sessions()
        if not sessions:
            click.echo("No sessions found.")
            return
        for s in sessions:
            status = "done" if s.get("finished") else "pending"
            click.echo(f"  {s['id']:12} {status:8} {s.get('task', '')[:60]}")
        return

    if session_id:
        s = mgr.load(session_id)
        if not s:
            click.echo(f"Session not found: {session_id}")
            return
        click.echo(f"Session: {s.id}")
        click.echo(f"Task: {s.task}")
        click.echo(f"Created: {s.created_at}")
        click.echo(f"Finished: {s.finished}")
        if s.result:
            click.echo(f"\nResult:\n{s.result[:2000]}")
        return

    click.echo("Use --list to list sessions or provide a session ID to view.")


@main.command()
def repl():
    """Start an interactive REPL session."""
    from orchestra.code_agent.repl import run_repl
    run_repl()


@main.command()
def tui():
    """Start the Textual TUI (graphical terminal interface)."""
    from orchestra.code_agent.tui import run_tui
    run_tui()


@main.command()
@click.argument("path", required=False, default=".")
@click.option("-a", "--action", default="summary", help="Analysis: summary, functions, classes, imports, deps, callgraph, all")
@click.option("-p", "--pattern", default="**/*.py", help="File pattern")
def analyze(path, action, pattern):
    """Analyze Python code structure."""
    from orchestra.code_agent.analysis.tool import AnalyzeTool
    tool = AnalyzeTool()
    result = asyncio.run(tool(path=path, action=action, pattern=pattern))
    click.echo(result.output or result.error)


@main.command()
@click.argument("path", required=False, default=".")
@click.option("-p", "--pattern", default="**/*.py", help="Glob pattern for indexing")
@click.option("-a", "--action", default="index", help="Action: index, search, stats, remove")
@click.option("-q", "--query", default="", help="Search query")
@click.option("-k", "--top-k", default=5, type=int, help="Search results count")
def vector(path, pattern, action, query, top_k):
    """Index and semantically search code."""
    from orchestra.code_agent.vector.indexer import IndexerTool
    tool = IndexerTool()
    result = asyncio.run(tool(path=path, pattern=pattern, action=action, query=query, top_k=top_k))
    click.echo(result.output or result.error)


@main.command()
@click.argument("file_path")
@click.option("-f", "--framework", default="pytest", help="Test framework (pytest, unittest)")
@click.option("-o", "--output", help="Output file path")
def testgen(file_path, framework, output):
    """Auto-generate tests from source code."""
    from orchestra.code_agent.output.testgen import TestGenTool
    tool = TestGenTool()
    result = asyncio.run(tool(file_path=file_path, framework=framework, output=output))
    click.echo(result.output or result.error)


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--action", default="status", help="start, stop, status")
@click.option("--timeout", default=0, type=int, help="Watch duration in seconds")
def watch(path, action, timeout):
    """Watch files for changes."""
    from orchestra.code_agent.watcher.tool import WatchTool
    tool = WatchTool()
    result = asyncio.run(tool(path=path, action=action, timeout=timeout))
    click.echo(result.output or result.error)


@main.command()
@click.argument("dir_path", required=False, default=".")
def plugins(dir_path):
    """Discover and load external tool plugins."""
    from orchestra.code_agent.plugins.loader import PluginLoader
    loader = PluginLoader()
    tools = loader.load_directory(dir_path)
    if not tools:
        click.echo("No plugins found.")
        return
    for path, plugin_tools in tools.items():
        for t in plugin_tools:
            click.echo(f"  Loaded {t.spec.name} from {path}")
    click.echo(f"\nTotal: {sum(len(v) for v in tools.values())} tools loaded")


@main.command()
def cost():
    """Show token usage and cost summary."""
    from orchestra.code_agent.cost.tracker import CostTracker
    tracker = CostTracker()
    click.echo(tracker.summary())


@main.command()
@click.argument("path", required=False, default=".")
@click.option("-a", "--action", default="analyze", help="analyze, improve, auto")
@click.option("-p", "--pattern", default="**/*.py", help="File pattern")
def improve(path, action, pattern):
    """Analyze and auto-improve code."""
    from orchestra.code_agent.improve.tool import ImproveTool
    tool = ImproveTool()
    result = asyncio.run(tool(path=path, action=action, pattern=pattern))
    click.echo(result.output or result.error)


@main.command()
@click.argument("definition", required=False)
@click.option("-n", "--name", default="", help="Workflow name")
@click.option("-a", "--action", default="run", help="run, status, list")
def workflow(name, definition, action):
    """Define and run multi-step workflows."""
    from orchestra.code_agent.workflow.tool import WorkflowTool
    tool = WorkflowTool()
    if definition:
        from pathlib import Path
        p = Path(definition)
        if p.exists():
            definition = p.read_text("utf-8")
    result = asyncio.run(tool(name=name, definition=definition or "", action=action))
    click.echo(result.output or result.error)


@main.command()
@click.argument("path", required=True)
@click.option("-a", "--action", default="file", help="file or readme")
def docgen(path, action):
    """Generate documentation from code."""
    from orchestra.code_agent.docs.generator import DocGenTool
    tool = DocGenTool()
    result = asyncio.run(tool(path=path, action=action))
    click.echo(result.output or result.error)


@main.command()
@click.argument("path", required=False, default=".")
@click.option("-t", "--type", "viz_type", default="deps", help="deps, codemap, callgraph")
@click.option("-p", "--pattern", default="**/*.py", help="File pattern")
def graphviz(path, viz_type, pattern):
    """Generate code maps and dependency graphs (Mermaid)."""
    from orchestra.code_agent.visualize.graph import GraphVizTool
    tool = GraphVizTool()
    result = asyncio.run(tool(path=path, type=viz_type, pattern=pattern))
    click.echo(result.output or result.error)


@main.command()
@click.argument("action", type=click.Choice(["list", "show", "run"]), default="list")
@click.argument("name", required=False)
def prompt(action, name):
    """List, show, or run templated prompts."""
    from orchestra.code_agent.prompts import PromptLibrary
    lib = PromptLibrary()
    if action == "list":
        for p in lib.list():
            vars_str = ", ".join(p.get("variables", []))
            click.echo(f"  {p['name']:20} {p['description'][:50]}")
            if vars_str:
                click.echo(f"  {'':20} vars: {vars_str}")
    elif action == "show":
        if not name:
            click.echo("Provide prompt name")
            return
        prompt = lib.get(name)
        if prompt:
            click.echo(prompt)
        else:
            click.echo(f"Prompt not found: {name}")
    elif action == "run":
        click.echo("Usage: code-agent prompt run <name> -- variables as --<var>=<value>")


@main.command()
@click.argument("shell_type", type=click.Choice(["bash", "zsh", "powershell"]), default="bash")
@click.option("--install", is_flag=True, help="Install completions")
def completions(shell_type, install):
    """Generate or install shell tab-completions."""
    from orchestra.code_agent.completions.shell import generate_completions, install_completions
    if install:
        path = install_completions(shell_type)
        click.echo(f"Installed completions to: {path}")
    else:
        click.echo(generate_completions(shell_type))


@main.group()
def monitor():
    """Monitor agent metrics, alerts, and dashboards."""


@monitor.command("dashboard")
def monitor_dashboard():
    """Show ASCII metrics dashboard."""
    from orchestra.code_agent.monitor import MonitorDashboard
    dash = MonitorDashboard()
    safe_echo(dash.render())
    dash.close()


@monitor.command("metrics")
@click.option("--name", "-n", default="", help="Filter by metric name")
@click.option("--since", type=float, default=0, help="Show metrics since timestamp")
def monitor_metrics(name, since):
    """List collected metrics with aggregates."""
    from orchestra.code_agent.monitor import MetricsCollector
    collector = MetricsCollector()
    if name:
        pts = collector.query(name, since=since, limit=50)
        if not pts:
            safe_echo(f"No points for '{name}'")
            return
        agg = collector.aggregate(name)
        safe_echo(f"Metric: {name}")
        safe_echo(f"  Type:  {pts[0].metric_type if pts else '?'}")
        safe_echo(f"  Count: {agg['count']}")
        safe_echo(f"  Sum:   {agg['sum']:.2f}")
        safe_echo(f"  Avg:   {agg['avg']:.2f}")
        safe_echo(f"  Min:   {agg['min']:.2f}")
        safe_echo(f"  Max:   {agg['max']:.2f}")
        safe_echo(f"  Last:  {agg['last']:.2f}")
    else:
        metrics = collector.list_metrics()
        if not metrics:
            safe_echo("No metrics recorded.")
            return
        safe_echo(f"{'Metric':30} {'Type':12} {'Last':10} {'Avg':10} {'Max':10} {'Count':8}")
        safe_echo("-" * 80)
        for m in sorted(metrics, key=lambda x: x["name"]):
            safe_echo(f"{m['name']:30} {m['type']:12} {m['last']:<10.2f} {m['avg']:<10.2f} {m['max']:<10.2f} {m['count']:<8}")
    collector.close()


@monitor.command("alerts")
@click.option("--history", is_flag=True, help="Show alert history")
def monitor_alerts(history):
    """List alert rules or show alert history."""
    from orchestra.code_agent.monitor import AlertManager
    mgr = AlertManager()
    if history:
        events = mgr.get_history(limit=50)
        if not events:
            safe_echo("No alert events.")
            return
        for ev in events:
            safe_echo(f"  [{ev.state.value:8}] {ev.message} @ {time.strftime('%H:%M:%S', time.localtime(ev.timestamp))}")
    else:
        rules = mgr.list_rules()
        if not rules:
            safe_echo("No alert rules defined.")
            safe_echo("Use 'code-agent monitor alert-add' to create one.")
            return
        safe_echo(f"{'Name':25} {'Metric':25} {'Condition':10} {'Threshold':10} {'Cooldown':10} {'Enabled':8}")
        safe_echo("-" * 90)
        for r in rules:
            safe_echo(f"{r.name:25} {r.metric_name:25} {r.condition.value:10} {r.threshold:<10.2f} {r.cooldown_seconds:<10.0f} {'Yes' if r.enabled else 'No':8}")


@monitor.command("alert-add")
@click.argument("name")
@click.argument("metric_name")
@click.argument("condition", type=click.Choice(["gt", "lt", "gte", "lte"]))
@click.argument("threshold", type=float)
@click.option("--cooldown", default=300, type=float, help="Cooldown in seconds")
def monitor_alert_add(name, metric_name, condition, threshold, cooldown):
    """Add an alert rule. Condition: gt/lt/gte/lte."""
    from orchestra.code_agent.monitor import AlertManager, AlertRule, AlertCondition
    mgr = AlertManager()
    rule = AlertRule(
        name=name,
        metric_name=metric_name,
        condition=AlertCondition(condition),
        threshold=threshold,
        cooldown_seconds=cooldown,
    )
    mgr.add_rule(rule)
    safe_echo(f"Alert rule added: {name}")


@monitor.command("alert-remove")
@click.argument("name")
def monitor_alert_remove(name):
    """Remove an alert rule."""
    from orchestra.code_agent.monitor import AlertManager
    mgr = AlertManager()
    if mgr.remove_rule(name):
        safe_echo(f"Removed alert rule: {name}")
    else:
        safe_echo(f"Alert rule not found: {name}")


@monitor.command("server")
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind")
@click.option("-p", "--port", default=9090, type=int, help="Port to bind")
def monitor_server(host, port):
    """Start the monitoring web server (dashboard + Prometheus + SSE)."""
    from orchestra.code_agent.monitor import MonitorServer
    server = MonitorServer()
    server.run(host=host, port=port)


@monitor.command("prometheus")
@click.option("-p", "--port", default=9091, type=int, help="Prometheus metrics port")
@click.option("--interval", default=5, type=int, help="Sync interval in seconds")
def monitor_prometheus(port, interval):
    """Start a standalone Prometheus HTTP metrics server."""
    from orchestra.code_agent.monitor import MetricsCollector
    from orchestra.code_agent.monitor.prometheus import PrometheusExporter
    import time
    collector = MetricsCollector()
    exporter = PrometheusExporter(collector)
    from prometheus_client import start_http_server
    start_http_server(port)
    safe_echo(f"Prometheus metrics: http://127.0.0.1:{port}/metrics")
    try:
        while True:
            time.sleep(interval)
            exporter.generate()
    except KeyboardInterrupt:
        safe_echo("Stopped")


@monitor.command("prune")
@click.option("--older-than", default=86400, type=int, help="Prune metrics older than N seconds (default 24h)")
def monitor_prune(older_than):
    """Prune old metrics from the database."""
    from orchestra.code_agent.monitor import MetricsCollector
    import time
    collector = MetricsCollector()
    cutoff = time.time() - older_than
    deleted = collector.prune(cutoff)
    safe_echo(f"Pruned {deleted} metric points older than {older_than}s")
    collector.close()


@main.group()
def knowledge():
    """Manage agent knowledge base (persistent memory)."""


@knowledge.command("store")
@click.argument("content")
@click.option("-k", "--key", default="", help="Memory key")
@click.option("--source", default="cli", help="Source label")
@click.option("--tags", default="", help="Comma-separated tags")
def knowledge_store(content, key, source, tags):
    """Store content in knowledge base."""
    from orchestra.code_agent.knowledge.base import KnowledgeBase
    kb = KnowledgeBase()
    if not key:
        import time
        key = f"cli_{int(time.time() * 1000)}"
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    kb.store(key, content, source=source, tags=tag_list)
    click.echo(f"Stored: {key}")


@knowledge.command("search")
@click.argument("query")
@click.option("-k", "--top-k", default=5, type=int)
@click.option("--tag", default="", help="Filter by tag")
def knowledge_search(query, top_k, tag):
    """Search knowledge base."""
    from orchestra.code_agent.knowledge.base import KnowledgeBase
    kb = KnowledgeBase()
    results = kb.search(query, top_k=top_k, tag_filter=tag)
    if not results:
        click.echo("(no results)")
        return
    for r in results:
        e = r.entry
        click.echo(f"\n  [{r.score:.3f}] {e.key} ({e.source})")
        click.echo(f"         {e.content[:120].strip()}")


@knowledge.command("stats")
def knowledge_stats():
    """Show knowledge base stats."""
    from orchestra.code_agent.knowledge.base import KnowledgeBase
    kb = KnowledgeBase()
    for k, v in kb.stats().items():
        click.echo(f"  {k}: {v}")


@main.command()
@click.argument("url")
@click.option("-m", "--method", default="GET", help="HTTP method")
@click.option("--header", "headers", multiple=True, help="Headers (Key:Value)")
@click.option("--body", default="", help="Request body")
@click.option("--timeout", default=30, type=int)
def api(url, method, header, body, timeout):
    """Make HTTP API requests."""
    from orchestra.code_agent.data.api_tool import ApiTool
    import json
    headers_dict = {}
    for h in header:
        if ":" in h:
            k, v = h.split(":", 1)
            headers_dict[k.strip()] = v.strip()
    tool = ApiTool()
    result = asyncio.run(tool(
        url=url, method=method, headers=json.dumps(headers_dict),
        body=body, timeout=timeout,
    ))
    click.echo(result.output or result.error)


@main.command()
@click.argument("query")
@click.option("-d", "--db", default=":memory:", help="Database file path")
@click.option("--params", default="[]", help="JSON array of parameters")
@click.option("-f", "--fetch", default="all", help="all|one|none")
def sql(query, db, params, fetch):
    """Run SQL queries against a SQLite database."""
    from orchestra.code_agent.data.sql_tool import SqlTool
    tool = SqlTool()
    result = asyncio.run(tool(query=query, db_path=db, params=params, fetch=fetch))
    click.echo(result.output or result.error)


@main.group()
def swarm():
    """Multi-agent collaboration and debate."""


@swarm.command("debate")
@click.argument("topic")
@click.option("--rounds", default=2, type=int)
def swarm_debate(topic, rounds):
    """Two agents debate a topic."""
    from orchestra.code_agent.swarm.tool import SwarmTool
    tool = SwarmTool()
    result = asyncio.run(tool(task=topic, mode="debate", rounds=rounds))
    click.echo(result.output or result.error)


@swarm.command("reflect")
@click.argument("task")
def swarm_reflect(task):
    """Agent self-reflects and improves its answer."""
    from orchestra.code_agent.swarm.tool import SwarmTool
    tool = SwarmTool()
    result = asyncio.run(tool(task=task, mode="reflect"))
    click.echo(result.output or result.error)


@swarm.command("specialists")
@click.argument("task")
@click.option("--roles", default="", help="Comma-separated roles (architect,engineer,reviewer,debugger,docs)")
def swarm_specialists(task, roles):
    """Team of specialists collaborate on a task."""
    from orchestra.code_agent.swarm.tool import SwarmTool
    tool = SwarmTool()
    result = asyncio.run(tool(task=task, mode="specialists", roles=roles))
    click.echo(result.output or result.error)


@main.command()
@click.argument("file_path")
@click.option("-a", "--action", default="rename", help="rename, extract, inline")
@click.option("--old", default="", help="Old symbol name")
@click.option("--new", default="", help="New symbol name")
@click.option("--var", "variable", default="", help="Variable name to inline")
@click.option("--dry-run", is_flag=True, help="Preview only")
def transform(file_path, action, old, new, variable, dry_run):
    """AST-safe code transformations."""
    from orchestra.code_agent.transform.tool import TransformTool
    tool = TransformTool()
    result = asyncio.run(tool(
        file_path=file_path, action=action,
        old_name=old, new_name=new,
        variable_name=variable, dry_run=dry_run,
    ))
    click.echo(result.output or result.error)


@main.command()
@click.argument("action", type=click.Choice(["install", "remove"]))
@click.option("--hook-type", default="pre-commit", help="Hook type")
def hooks(action, hook_type):
    """Manage git hooks for code-agent."""
    from orchestra.code_agent.githooks import install_hook, remove_hook
    if action == "install":
        result = install_hook(hook_type=hook_type)
    else:
        result = remove_hook(hook_type=hook_type)
    if result["success"]:
        click.echo(result["message"])
    else:
        click.echo(f"Error: {result['error']}")


@main.group()
def profile():
    """Manage named configuration profiles."""


@profile.command("list")
def profile_list():
    """List available profiles."""
    from orchestra.code_agent.profiles.base import ProfileManager
    mgr = ProfileManager()
    for name in mgr.list():
        profile = mgr.get(name)
        click.echo(f"  {name:20} {profile.description if profile else ''}")


@profile.command("show")
@click.argument("name")
def profile_show(name):
    """Show profile details."""
    from orchestra.code_agent.profiles.base import ProfileManager
    mgr = ProfileManager()
    profile = mgr.get(name)
    if not profile:
        click.echo(f"Profile not found: {name}")
        return
    import json
    click.echo(json.dumps(profile.to_dict(), indent=2))


@profile.command("save")
@click.argument("name")
@click.option("--agent", help="JSON with agent config values")
@click.option("--llm", help="JSON with LLM config values")
@click.option("--desc", default="", help="Profile description")
def profile_save(name, agent, llm, desc):
    """Save current config as a named profile."""
    from orchestra.code_agent.profiles.base import Profile, ProfileManager
    import json
    profile = Profile(name=name, description=desc)
    if agent:
        profile.agent = json.loads(agent)
    if llm:
        profile.llm = json.loads(llm)
    mgr = ProfileManager()
    mgr.save(profile)
    click.echo(f"Saved profile: {name}")


@profile.command("delete")
@click.argument("name")
def profile_delete(name):
    """Delete a saved profile."""
    from orchestra.code_agent.profiles.base import ProfileManager
    mgr = ProfileManager()
    if mgr.delete(name):
        click.echo(f"Deleted profile: {name}")
    else:
        click.echo(f"Profile not found: {name}")


@main.command()
@click.argument("action", type=click.Choice(["info", "warn", "error"]), default="info")
@click.argument("title")
@click.argument("body", required=False, default="")
@click.option("--webhook", help="Webhook URL to send notification")
@click.option("--slack", help="Slack webhook URL")
def notify(action, title, body, webhook, slack):
    """Send notifications via webhook or Slack."""
    import json
    from orchestra.code_agent.notify.notifier import Notification
    payload = Notification(title=title, body=body, level=action)

    if slack:
        from orchestra.code_agent.notify.slack import SlackNotifier
        notifier = SlackNotifier(slack)
    elif webhook:
        from orchestra.code_agent.notify.slack import WebhookNotifier
        notifier = WebhookNotifier(webhook)
    else:
        click.echo("Provide --webhook or --slack URL")
        return

    result = asyncio.run(notifier.send(payload))
    click.echo(f"Notification sent: {result}")


@main.command()
@click.argument("action", type=click.Choice(["stats", "recent", "export"]), default="stats")
@click.option("--n", "count", default=10, type=int, help="Number of recent entries")
@click.option("--output", default="", help="Export to file")
def logs(action, count, output):
    """View agent activity logs."""
    from orchestra.code_agent.logbook import AgentLogger
    logger = AgentLogger.get()
    if action == "stats":
        s = logger.stats()
        click.echo(f"Log entries: {s['total_entries']}")
        for level, count in s['levels'].items():
            click.echo(f"  {level}: {count}")
        click.echo(f"Log file: {s['log_file']}")
    elif action == "recent":
        entries = logger.recent(count)
        for e in entries:
            click.echo(f"  [{e.level:7}] {e.module:20} {e.message[:100]}")
    elif action == "export":
        import json
        from dataclasses import asdict
        entries = logger.recent(10000)
        data = json.dumps([asdict(e) for e in entries], indent=2)
        path = output or logger.get_log_file()
        Path(path).write_text(data)
        click.echo(f"Exported {len(entries)} entries to {path}")


@main.group()
def schedule():
    """Manage scheduled agent tasks."""


@schedule.command("add")
@click.argument("name")
@click.argument("task")
@click.option("--interval", default=3600, type=int, help="Interval in seconds")
@click.option("--cron", default="", help="Cron expression (5-field), overrides --interval")
@click.option("--profile", default="minimal", help="Agent profile to use")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--max-retries", default=3, type=int, help="Max retry attempts on failure")
@click.option("--timeout", default=300, type=float, help="Task timeout in seconds")
@click.option("--provider", default="ollama", help="LLM provider to use (ollama, openai, anthropic)")
def schedule_add(name, task, interval, cron, profile, tags, max_retries, timeout, provider):
    """Add a scheduled task. Supports cron expressions or interval."""
    from orchestra.code_agent.scheduler.base import ScheduledTask, RetryPolicy
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    st = ScheduledTask(
        name=name, task=task, cron=cron, interval_seconds=interval,
        profile=profile, tags=tag_list,
        retry_policy=RetryPolicy(max_retries=max_retries),
        timeout_seconds=timeout, provider=provider,
    )
    st.compute_next_run()
    engine.add_task(st)
    sched_str = f"cron '{cron}'" if cron else f"every {interval}s"
    safe_echo(f"Scheduled: {name} ({sched_str}, profile={profile}, provider={provider})")


@schedule.command("list")
def schedule_list():
    """List scheduled tasks with status and next run."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    tasks = engine.list_tasks()
    if not tasks:
        safe_echo("No scheduled tasks.")
        return
    import time
    safe_echo(f"{'Name':25} {'Status':12} {'Schedule':20} {'Next Run':22} {'Runs':6} {'Fails':6}")
    safe_echo("-" * 90)
    for t in tasks:
        status_str = f"[{t.status.value.upper()}]" if t.enabled else "[PAUSED]"
        sched_str = f"cron '{t.cron}'" if t.cron else f"every {t.interval_seconds}s"
        next_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(t.next_run)) if t.next_run else "?"
        safe_echo(f"{t.name:25} {status_str:12} {sched_str:20} {next_str:22} {t.run_count:<6} {t.failure_count:<6}")


@schedule.command("remove")
@click.argument("name")
def schedule_remove(name):
    """Remove a scheduled task."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    if engine.remove_task(name):
        safe_echo(f"Removed: {name}")
    else:
        safe_echo(f"Not found: {name}")


@schedule.command("pause")
@click.argument("name")
def schedule_pause(name):
    """Pause a scheduled task."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    if engine.pause_task(name):
        safe_echo(f"Paused: {name}")
    else:
        safe_echo(f"Not found: {name}")


@schedule.command("resume")
@click.argument("name")
def schedule_resume(name):
    """Resume a scheduled task."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    if engine.resume_task(name):
        safe_echo(f"Resumed: {name}")
    else:
        safe_echo(f"Not found: {name}")


@schedule.command("status")
@click.argument("name")
def schedule_status(name):
    """Show detailed status of a scheduled task."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    import time
    engine = SchedulerEngine()
    task = engine.get_task(name)
    if not task:
        safe_echo(f"Task not found: {name}")
        return
    safe_echo(f"Name:      {task.name}")
    safe_echo(f"Task:      {task.task}")
    safe_echo(f"Status:    {task.status.value}")
    safe_echo(f"Enabled:   {task.enabled}")
    safe_echo(f"Provider:  {task.provider}")
    if task.cron:
        safe_echo(f"Schedule:  cron '{task.cron}'")
    else:
        safe_echo(f"Interval:  every {task.interval_seconds}s")
    safe_echo(f"Profile:   {task.profile}")
    safe_echo(f"Next Run:  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(task.next_run)) if task.next_run else '?'}")
    safe_echo(f"Last Run:  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(task.last_run)) if task.last_run else 'never'}")
    safe_echo(f"Runs:      {task.run_count} (ok={task.success_count}, fail={task.failure_count})")
    safe_echo(f"Timeout:   {task.timeout_seconds}s")
    if task.retry_policy:
        rp = task.retry_policy
        safe_echo(f"Retries:   {rp.max_retries} (backoff {rp.base_delay_seconds}s * {rp.backoff_multiplier}^n, max {rp.max_delay_seconds}s)")
    if task.last_error:
        safe_echo(f"Last err:  {task.last_error[:200]}")
    if task.tags:
        safe_echo(f"Tags:      {', '.join(task.tags)}")


@schedule.command("history")
@click.argument("name", required=False, default="")
@click.option("--limit", default=20, type=int, help="Number of entries")
def schedule_history(name, limit):
    """Show execution history for tasks."""
    from orchestra.code_agent.scheduler.store import SchedulerStore
    import time
    store = SchedulerStore()
    entries = store.load_history(task_name=name if name else None, limit=limit)
    if not entries:
        safe_echo("No history entries.")
        return
    safe_echo(f"{'Task':25} {'Status':12} {'Duration':10} {'Attempt':8} {'Error':30}")
    safe_echo("-" * 85)
    for e in entries:
        dur = f"{e['duration_ms']:.0f}ms"
        err = (e.get("error", "") or "")[:30]
        safe_echo(f"{e['task_name']:25} {e['status']:12} {dur:10} {e.get('attempt', 1):<8} {err:30}")


@schedule.command("run")
@click.argument("name")
def schedule_run(name):
    """Execute a scheduled task immediately."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    import asyncio
    engine = SchedulerEngine()
    if engine.run_now(name):
        safe_echo(f"Triggered: {name}")
    else:
        safe_echo(f"Task not found: {name}")


@schedule.command("dep")
@click.argument("task_name")
@click.argument("depends_on")
def schedule_dep(task_name, depends_on):
    """Add a dependency: task_name depends on depends_on."""
    from orchestra.code_agent.scheduler.engine import SchedulerEngine
    engine = SchedulerEngine()
    engine.add_dependency(task_name, depends_on)
    safe_echo(f"Dependency added: {task_name} depends on {depends_on}")


@schedule.command("stats")
@click.argument("name")
def schedule_stats(name):
    """Show execution statistics for a task."""
    from orchestra.code_agent.scheduler.store import SchedulerStore
    store = SchedulerStore()
    stats = store.task_stats(name)
    safe_echo(f"Task:      {name}")
    safe_echo(f"Total:     {stats['total']}")
    safe_echo(f"Completed: {stats['completed']}")
    safe_echo(f"Failed:    {stats['failed']}")
    safe_echo(f"Avg time:  {stats['avg_dur']:.0f}ms" if stats.get("avg_dur") else "Avg time:  N/A")


@schedule.command("health")
@click.option("--interval", default=60, type=int, help="Health check interval in seconds")
@click.option("--timeout", default=10.0, type=float, help="Health check probe timeout")
def schedule_health(interval, timeout):
    """Run scheduler with provider health checking. Tasks are skipped when their provider is unhealthy."""
    try:
        from orchestra.code_agent.serving.health import ModelHealthChecker
        from orchestra.code_agent.scheduler.engine import SchedulerEngine
        import asyncio
    except ImportError:
        safe_echo("Health checker not available (serving module required)")
        return
    hc = ModelHealthChecker()
    hc.register("ollama", "ollama", interval=interval, timeout=timeout)
    engine = SchedulerEngine(health_checker=hc)
    hc.start()
    engine.start()
    safe_echo("Scheduler running with health checking (Ctrl+C to stop)")
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        asyncio.get_event_loop().run_until_complete(hc.stop())
        safe_echo("Scheduler stopped")


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--pattern", default="**/*", help="Glob pattern")
@click.option("--git-history", is_flag=True, help="Scan git history too")
@click.option("--summary", "show_summary", is_flag=True, help="Show summary only")
def audit(path, pattern, git_history, show_summary):
    """Scan for secrets, keys, and credentials."""
    from orchestra.code_agent.security.scanner import SecretScanner
    scanner = SecretScanner(path)
    results = scanner.scan_directory(pattern)
    if git_history:
        results.extend(scanner.scan_git_history())

    if show_summary:
        by_type: dict[str, int] = {}
        for r in results:
            by_type[r.pattern_name] = by_type.get(r.pattern_name, 0) + 1
        click.echo(f"Found {len(results)} potential secrets:")
        for pname, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
            click.echo(f"  {pname}: {cnt}")
        return

    if not results:
        click.echo("No secrets found.")
        return
    for r in results[:30]:
        click.echo(f"  [{r.severity:7}] {r.file}:{r.line} ({r.pattern_name})")


@main.command()
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind")
@click.option("-p", "--port", default=9090, type=int, help="Port to bind")
def dashboard(host, port):
    """Start the agent monitoring dashboard (web + Prometheus + SSE)."""
    from orchestra.code_agent.monitor import MonitorServer
    server = MonitorServer()
    server.run(host=host, port=port)


@main.group()
def trace():
    """Agent trace collection, viewing, and export."""


@trace.command("list")
@click.option("--limit", default=20, type=int, help="Number of traces to show")
def trace_list(limit):
    """List recent agent execution traces."""
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.viewer import TraceViewer
    collector = TraceCollector()
    viewer = TraceViewer(collector)
    click.echo(viewer.list_traces(limit=limit))


@trace.command("show")
@click.argument("trace_id")
@click.option("--waterfall", is_flag=True, help="Show waterfall timeline")
def trace_show(trace_id, waterfall):
    """Show detailed trace with timeline."""
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.viewer import TraceViewer
    collector = TraceCollector()
    viewer = TraceViewer(collector)
    if waterfall:
        click.echo(viewer.waterfall(trace_id))
    else:
        click.echo(viewer.show_trace(trace_id))


@trace.command("search")
@click.argument("query")
@click.option("--limit", default=50, type=int)
def trace_search(query, limit):
    """Search trace events by text."""
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.viewer import TraceViewer
    collector = TraceCollector()
    viewer = TraceViewer(collector)
    click.echo(viewer.search(query, limit=limit))


@trace.command("stats")
def trace_stats():
    """Show trace collection statistics."""
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.viewer import TraceViewer
    collector = TraceCollector()
    viewer = TraceViewer(collector)
    click.echo(viewer.summary())


@trace.command("export")
@click.argument("trace_id", required=False)
@click.option("--format", "fmt", default="md", help="Export format: md, chrome, otel")
@click.option("--output", "-o", help="Output path")
@click.option("--all", "export_all", is_flag=True, help="Export all traces")
def trace_export(trace_id, fmt, output, export_all):
    """Export trace as markdown, Chrome trace, or summary."""
    import asyncio
    from orchestra.code_agent.trace.collector import TraceCollector
    from orchestra.code_agent.trace.export import TraceExporter
    collector = TraceCollector()
    exporter = TraceExporter(collector)

    if export_all:
        out = exporter.export_all(output or ".agent-trace-export")
        click.echo(f"Exported all traces to {out}")
        return

    if not trace_id:
        click.echo("Provide a trace_id or use --all")
        return

    if fmt == "chrome":
        path = output or f"trace-{trace_id}.json"
        exporter.to_chrome_trace(trace_id, path)
        click.echo(f"Chrome trace exported to {path}")
    elif fmt == "otel":
        path = output or f"trace-{trace_id}.json"
        data = exporter.to_chrome_trace(trace_id, path)
        click.echo(f"Trace exported to {path}")
    else:
        path = output or f"trace-{trace_id}.md"
        exporter.to_markdown(trace_id, path)
        click.echo(f"Trace markdown exported to {path}")


@main.group()
def export():
    """Export agent data."""


@export.command("sessions")
@click.option("-f", "--format", "fmt", default="json", help="json or markdown")
@click.option("-o", "--output", default="session-exports", help="Output directory")
def export_sessions(fmt, output):
    """Export all sessions."""
    from orchestra.code_agent.export.session_export import SessionExporter
    files = SessionExporter.export_all(format=fmt, output_dir=output)
    click.echo(f"Exported {len(files)} sessions to {output}/")


@export.command("archive")
@click.option("-o", "--output", default="", help="Output zip path")
def export_archive(output):
    """Export all agent data as a zip archive."""
    from orchestra.code_agent.export.full_export import FullExporter
    path = FullExporter.export(output_path=output)
    click.echo(f"Exported to: {path}")


@export.command("import")
@click.argument("archive_path")
@click.option("-o", "--output", default=".agent-import", help="Extract directory")
def export_import(archive_path, output):
    """Import agent data from a zip archive."""
    from orchestra.code_agent.export.full_export import FullExporter
    files = FullExporter.import_archive(archive_path, extract_dir=output)
    click.echo(f"Imported {len(files)} files to {output}/")


@main.command()
@click.option("--report", is_flag=True, help="Show detailed health report")
def health(report):
    """Check project health."""
    from orchestra.code_agent.health.checker import HealthChecker
    checker = HealthChecker()
    result = checker.run_all()
    click.echo(result.to_text() if report else f"Overall: {result.overall}")


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--pattern", default="**/*", help="Glob pattern")
@click.option("-a", "--action", default="summary", help="summary, analyze, languages")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
def multilang(path, pattern, action, json_output):
    """Analyze multi-language codebases (Python, JS, TS, Rust, Go, Java)."""
    from orchestra.code_agent.multilang.analyzer import MultiLangTool
    tool = MultiLangTool()
    result = asyncio.run(tool(path=path, pattern=pattern, action=action))
    click.echo(result.output or result.error)


@main.command()
@click.argument("prompt", required=False)
@click.option("--auto", is_flag=True, help="Use AI to optimize")
def optimize(prompt, auto):
    """Analyze and improve prompts for better LLM results."""
    from orchestra.code_agent.optimizer.optimizer import PromptOptimizer
    opt = PromptOptimizer()

    if not prompt:
        click.echo("Enter prompt to optimize (Ctrl+Z then Enter):")
        lines = []
        try:
            for line in sys.stdin:
                lines.append(line)
        except KeyboardInterrupt:
            pass
        prompt = "\n".join(lines).strip()

    if not prompt:
        click.echo("No prompt provided.")
        return

    if auto:
        result = asyncio.run(opt.auto_optimize(prompt))
    else:
        result = opt.optimize(prompt)

    click.echo(f"Score: {result.score:.2f}")
    click.echo(f"Improvements: {', '.join(result.improvements) if result.improvements else 'None'}")
    click.echo(f"\nOptimized prompt:\n{result.optimized}")


@main.command()
@click.argument("prompt")
@click.option("--providers", default="", help="Comma-separated providers to try")
@click.option("--max-attempts", default=3, type=int)
def fallback(prompt, providers, max_attempts):
    """Try multiple LLM providers in sequence until one succeeds."""
    from orchestra.code_agent.fallback.chain import FallbackChain
    from orchestra.code_agent.llm.base import LLMConfig

    if providers:
        configs = [LLMConfig(provider=p.strip()) for p in providers.split(",") if p.strip()]
        chain = FallbackChain(configs=configs)
    else:
        chain = FallbackChain()

    click.echo(f"Running prompt with fallback chain ({max_attempts} attempts)...")
    result = asyncio.run(chain.run(prompt, max_attempts=max_attempts))

    for a in result.attempts:
        status_icon = {"success": "OK", "error": "FAIL", "pending": "SKIP"}.get(a["status"], "?")
        click.echo(f"  [{status_icon}] {a['provider']}/{a['model']}: {a.get('error', '')[:80]}")

    if result.success:
        click.echo(f"\nResult ({result.provider}/{result.model}):\n{result.output[:500]}")
    else:
        click.echo("\nAll providers failed.")


@main.command()
@click.argument("url", required=False)
def ratelimit(url):
    """Show rate limit status for LLM providers."""
    from orchestra.code_agent.ratelimit.limiter import RateLimiter
    limiter = RateLimiter()
    stats = limiter.stats()
    for provider, info in stats.items():
        remaining = info["remaining"]
        icon = "OK" if remaining > 0 else "BLOCKED"
        click.echo(f"  [{icon}] {provider:12} {remaining:3}/{info['max_calls']:3} calls remaining ({info['window_seconds']}s window)")


@main.group()
def template():
    """Manage agent templates (pre-built configurations)."""


@template.command("list")
def template_list():
    """List available agent templates."""
    from orchestra.code_agent.templates.manager import TemplateManager
    mgr = TemplateManager()
    for name in mgr.list():
        t = mgr.get(name)
        click.echo(f"  {name:25} {t.description if t else ''}")


@template.command("show")
@click.argument("name")
def template_show(name):
    """Show template details."""
    from orchestra.code_agent.templates.manager import TemplateManager
    mgr = TemplateManager()
    t = mgr.get(name)
    if not t:
        click.echo(f"Template not found: {name}")
        return
    click.echo(f"Name: {t.name}")
    click.echo(f"Description: {t.description}")
    click.echo(f"Max turns: {t.max_turns}")
    click.echo(f"Tools: {', '.join(t.tools)}")
    click.echo(f"System prompt: {t.system_prompt[:200]}...")


@template.command("use")
@click.argument("name")
@click.argument("task")
def template_use(name, task):
    """Run an agent using a template configuration."""
    from orchestra.code_agent.templates.manager import TemplateManager
    from orchestra.code_agent.agent import Agent
    mgr = TemplateManager()
    t = mgr.get(name)
    if not t:
        click.echo(f"Template not found: {name}")
        return
    cfg = t.to_agent_config()
    agent = Agent(cfg)
    click.echo(f"Running template '{name}'...")
    result = asyncio.run(agent.run(task))
    click.echo(result)


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--pattern", default="**/*.py", help="Glob pattern")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
def quality(path, pattern, json_output):
    """Generate code quality reports."""
    from orchestra.code_agent.quality.reporter import QualityReporter
    reporter = QualityReporter(path)
    if json_output:
        click.echo(reporter.to_json(pattern))
    else:
        click.echo(reporter.generate_report(pattern))


@main.command()
@click.argument("error_text", required=False)
@click.option("--action", default="analyze", help="analyze, suggest, stats, clear")
@click.option("--source", default="", help="Error source label")
def errors(error_text, action, source):
    """Learn from errors and suggest solutions."""
    from orchestra.code_agent.learner.learner import ErrorLearner
    learner = ErrorLearner()

    if action == "stats":
        s = learner.stats()
        click.echo(f"Total errors: {s['total_errors']}")
        click.echo(f"Unique errors: {s['unique_errors']}")
        for cat, cnt in sorted(s['categories'].items(), key=lambda x: -x[1]):
            click.echo(f"  {cat}: {cnt}")
        return

    if action == "clear":
        learner.clear()
        click.echo("Error history cleared.")
        return

    if not error_text:
        click.echo("Provide error text or use --action stats/clear")
        return

    if action == "suggest":
        suggestion = learner.suggest(error_text)
        click.echo(suggestion)
    else:
        rec = learner.record(error_text, source=source)
        click.echo(f"Categorized as: {rec.category}")
        click.echo(f"Solution: {rec.solution}")


@main.command()
@click.argument("action", type=click.Choice(["stats", "visual", "info", "trim", "add", "clear"]), default="visual")
@click.argument("content", required=False)
@click.option("--tier", default="normal", help="priority tier: critical, important, normal, low")
@click.option("--source", default="", help="Content source label")
@click.option("--max-tokens", default=128000, type=int, help="Context window size")
@click.option("--reserve", default=4000, type=int, help="Reserved tokens")
@click.option("--add-demo", is_flag=True, help="Add demo entries for visual effect")
@click.option("--detail", is_flag=True, help="Show detailed breakdown")
@click.option("--session", "session_id", help="Analyze a saved session's context")
def context(action, content, tier, source, max_tokens, reserve, add_demo, detail, session_id):
    """Manage LLM context window with rich visual display."""
    cm = ContextManager(max_tokens=max_tokens, reserve_tokens=reserve)

    if session_id:
        from orchestra.code_agent.session import SessionManager
        mgr = SessionManager()
        session = mgr.load(session_id)
        if session:
            for m in session.messages:
                role = m.get("role", "unknown")
                c = m.get("content", "")
                if c:
                    t = "critical" if role == "system" else "important" if role == "user" else "normal"
                    cm.add(c, tier=t, source=role)
            click.echo(f"[dim]Loaded session: {session_id} ({len(session.messages)} messages)[/]")
        else:
            click.echo(f"Session not found: {session_id}")
            return

    if add_demo:
        cm.add("System prompt: You are a helpful AI coding agent.", tier="critical", source="system")
        cm.add("User requested: Build a web scraper for news sites.", tier="important", source="user")
        cm.add("Scraped https://example.com (120KB HTML, 200 links)", tier="normal", source="webfetch")
        cm.add("Analyzed 15 Python files in src/", tier="normal", source="analyze")
        cm.add("Search results for 'web scraping best practices'", tier="normal", source="websearch")
        cm.add("Debug log: Connection timeout on retry 2", tier="low", source="log")
        cm.add("Cache hit for get_page_content: 2.3ms", tier="low", source="cache")

    if action == "visual":
        from orchestra.code_agent.context.display import render_cli_context
        click.echo(render_cli_context(cm, detailed=detail))

    elif action == "stats":
        s = cm.stats()
        click.echo(f"  Entries:      {s['entries']}")
        click.echo(f"  Used tokens:  {s['used_tokens']:,}")
        click.echo(f"  Max tokens:   {s['max_tokens']:,}")
        click.echo(f"  Reserve:      {s['reserve_tokens']:,}")
        click.echo(f"  Available:    {s['available_tokens']:,}")
        click.echo(f"  Saturation:   {s['saturation_pct']}%")
        for tier_name in ["critical", "important", "normal", "low"]:
            c = s["tiers"].get(tier_name, 0)
            t = s["tier_tokens"].get(tier_name, 0)
            if c or t:
                click.echo(f"    {tier_name:>12}: {c} entries, {t:,} tokens")

    elif action == "info":
        s = cm.stats()
        click.echo(f"  Max:     {s['max_tokens']:,} tokens")
        click.echo(f"  Used:    {s['used_tokens']:,} tokens")
        click.echo(f"  Reserve: {s['reserve_tokens']:,} tokens")
        click.echo(f"  Free:    {s['available_tokens']:,} tokens")
        click.echo(f"  Entries: {s['entries']}")
        click.echo(f"  Saturation: {s['saturation_pct']}%")

    elif action == "trim":
        removed = cm.trim()
        click.echo(f"Trimmed {len(removed)} entries.")
        click.echo(f"{cm.current_tokens():,} tokens remaining in context.")

    elif action == "add":
        if not content:
            click.echo("Provide content to add.")
            return
        cm.add(content, tier=tier, source=source)
        click.echo(f"Added ({tier}, {source}): {content[:80]}...")

    elif action == "clear":
        cm.clear(tier=content if content else "")
        if content:
            click.echo(f"Cleared all '{content}' tier entries.")
        else:
            click.echo("Cleared all context entries.")


@main.command()
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind")
@click.option("-p", "--port", default=8100, type=int, help="Port to bind")
def apiserver(host, port):
    """Start the full REST API server."""
    from orchestra.code_agent.api.server import AgentAPI
    api = AgentAPI()
    asyncio.run(api.run_server(host=host, port=port))


@main.group()
def github():
    """GitHub integration commands."""


@github.command("webhook")
@click.option("--secret", default="", help="Webhook secret")
@click.option("-h", "--host", default="127.0.0.1")
@click.option("-p", "--port", default=8200, type=int)
def github_webhook(secret, host, port):
    """Start GitHub webhook handler server."""
    from orchestra.code_agent.github.webhook import GitHubWebhookHandler
    import uvicorn
    handler = GitHubWebhookHandler(secret=secret)
    click.echo(f"Webhook server: http://{host}:{port}/webhook")
    uvicorn.run(handler.app, host=host, port=port)


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--pattern", default="**/*.py", help="Glob pattern")
@click.option("--json", "json_output", is_flag=True)
def smells(path, pattern, json_output):
    """Detect code smells (long functions, nested loops, etc.)."""
    from orchestra.code_agent.smells.detector import SmellDetector
    detector = SmellDetector()

    p = Path(path)
    if p.is_file():
        results = detector.detect_file(p)
    else:
        import os
        orig = os.getcwd()
        os.chdir(str(p))
        results = detector.detect_directory(pattern)
        os.chdir(orig)

    if json_output:
        import json as j
        click.echo(j.dumps([r.to_dict() for r in results], indent=2))
        return

    if not results:
        click.echo("No code smells found.")
        return
    click.echo(f"Found {len(results)} code smells:\n")
    for r in results[:20]:
        click.echo(f"  [{r.type:16}] {r.file}:{r.line} - {r.message}")
    if len(results) > 20:
        click.echo(f"  ... and {len(results) - 20} more")


@main.command()
@click.argument("config_path", required=False, default="code-agent.json")
def validate(config_path):
    """Validate agent configuration."""
    from orchestra.code_agent.validate.config import ConfigValidator
    validator = ConfigValidator()
    issues = validator.validate_all(config_path)
    if not issues:
        click.echo("Configuration is valid.")
        return
    for issue in issues:
        icon = {"error": "FAIL", "warn": "WARN", "info": "INFO"}.get(issue.severity, "?")
        click.echo(f"  [{icon}] {issue.field}: {issue.message}")


@main.command()
@click.argument("input_file", required=False)
@click.option("--tasks", default="", help="Comma-separated tasks")
@click.option("--max-concurrency", default=5, type=int)
@click.option("--model", default="gpt-4o-mini")
@click.option("--output", default="batch-results.json", help="Output file")
def batch(input_file, tasks, max_concurrency, model, output):
    """Process multiple tasks in parallel."""
    from orchestra.code_agent.batch.processor import BatchProcessor, BatchTask
    processor = BatchProcessor(max_concurrency=max_concurrency)

    task_list: list[BatchTask] = []
    if input_file:
        p = Path(input_file)
        if p.suffix == ".json":
            task_list = BatchProcessor.from_json(str(p))
        elif p.suffix == ".csv":
            task_list = BatchProcessor.from_csv(str(p))
    elif tasks:
        for i, t in enumerate(tasks.split(",")):
            task_list.append(BatchTask(id=f"task-{i+1}", task=t.strip(), model=model))

    if not task_list:
        click.echo("Provide --tasks or --input-file")
        return

    click.echo(f"Processing {len(task_list)} tasks (concurrency: {max_concurrency})...")
    results = asyncio.run(processor.process(task_list))
    processor.save_results(results, output)
    summary = processor.summary(results)
    click.echo(f"Done: {summary['success']} OK, {summary['failed']} FAIL, "
               f"avg {summary['avg_duration_ms']:.0f}ms/task")
    click.echo(f"Results saved to {output}")


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--json", "json_output", is_flag=True)
def licenses(path, json_output):
    """Scan dependencies for license information."""
    from orchestra.code_agent.licenses.scanner import LicenseScanner
    scanner = LicenseScanner()
    deps = scanner.scan_directory(path)
    summary = scanner.summary(deps)

    if json_output:
        import json as j
        click.echo(j.dumps({"dependencies": [d.to_dict() for d in deps], "summary": summary}, indent=2))
        return

    click.echo(f"Dependencies: {summary['total_dependencies']}")
    for dtype, count in summary['by_license_type'].items():
        click.echo(f"  {dtype}: {count}")
    if summary['unknown_licenses']:
        click.echo(f"\nWARNING: {summary['unknown_licenses']} dependencies have unknown licenses")


@main.command()
@click.argument("partial", required=False)
def autocomplete(partial):
    """Suggest tasks based on context."""
    from orchestra.code_agent.autocomplete.completer import TaskCompleter
    completer = TaskCompleter()
    if partial:
        suggestions = completer.complete_partial(partial)
        for s in suggestions:
            click.echo(f"  {s}")
    else:
        suggestions = completer.suggest()
        for s in suggestions:
            click.echo(f"  [{s['category']}] {s['task']}")


@main.group()
def promptver():
    """Version control for prompts."""


@promptver.command("list")
def promptver_list():
    """List all versioned prompts."""
    from orchestra.code_agent.promptversion.manager import PromptVersionManager
    mgr = PromptVersionManager()
    for name in mgr.list_prompts():
        versions = mgr.list_versions(name)
        click.echo(f"  {name:20} ({len(versions)} versions)")


@promptver.command("save")
@click.argument("name")
@click.argument("content")
@click.option("--notes", default="", help="Change notes")
@click.option("--tags", default="", help="Comma-separated tags")
def promptver_save(name, content, notes, tags):
    """Save a new version of a prompt."""
    from orchestra.code_agent.promptversion.manager import PromptVersionManager
    mgr = PromptVersionManager()
    v = mgr.save(name, content, notes=notes, tags=[t.strip() for t in tags.split(",") if t.strip()])
    click.echo(f"Saved {name} v{v.version}")


@promptver.command("show")
@click.argument("name")
@click.option("--version", "ver", default=-1, type=int)
def promptver_show(name, ver):
    """Show a prompt version."""
    from orchestra.code_agent.promptversion.manager import PromptVersionManager
    mgr = PromptVersionManager()
    v = mgr.get(name, version=ver)
    if not v:
        click.echo(f"Prompt not found: {name}")
        return
    click.echo(f"--- {name} v{v.version} ---")
    click.echo(v.content)
    if v.notes:
        click.echo(f"\nNotes: {v.notes}")


@promptver.command("diff")
@click.argument("name")
@click.argument("v1", type=int)
@click.argument("v2", type=int)
def promptver_diff(name, v1, v2):
    """Show diff between prompt versions."""
    from orchestra.code_agent.promptversion.manager import PromptVersionManager
    mgr = PromptVersionManager()
    click.echo(mgr.diff(name, v1, v2))


@promptver.command("rollback")
@click.argument("name")
@click.argument("version", type=int)
def promptver_rollback(name, version):
    """Rollback to a previous prompt version."""
    from orchestra.code_agent.promptversion.manager import PromptVersionManager
    mgr = PromptVersionManager()
    v = mgr.rollback(name, version)
    if v:
        click.echo(f"Rolled back {name} to v{version} (new version: v{v.version})")
    else:
        click.echo(f"Version {version} not found")


@main.command()
@click.argument("query")
@click.option("--max", "max_results", default=10, type=int)
def memsearch(query, max_results):
    """Search through conversation history."""
    from orchestra.code_agent.memsearch.searcher import MemorySearcher
    searcher = MemorySearcher()
    results = searcher.search(query, max_results=max_results)
    if not results:
        click.echo("No matches found.")
        return
    click.echo(f"Found {len(results)} matching sessions:\n")
    for r in results:
        click.echo(f"  [{r['relevance']:.1f}] {r['session_id']}: {r['task'][:80]}")
        for m in r.get("message_matches", [])[:2]:
            click.echo(f"       {m['role']}: {m['snippet'][:100]}")


@main.command()
@click.argument("action", type=click.Choice(["start", "stop", "status"]), default="status")
@click.option("--config", "config_path", default="", help="Daemon config JSON")
@click.option("--api-port", default=8100, type=int)
@click.option("--dashboard-port", default=9090, type=int)
def daemon(action, config_path, api_port, dashboard_port):
    """Run code-agent as a background service."""
    from orchestra.code_agent.runner.daemon import AgentDaemon, DaemonConfig, run_daemon

    if action == "status":
        click.echo("Use --action start to launch the daemon")
        return

    cfg = DaemonConfig(api_port=api_port, dashboard_port=dashboard_port)
    asyncio.run(run_daemon(config_path))


@main.group()
def market():
    """Plugin marketplace commands."""


@market.command("list")
@click.option("--source", default="builtin", help="builtin, remote, installed")
def market_list(source):
    """List available plugins."""
    from orchestra.code_agent.market.plugins import PluginMarket
    market = PluginMarket()
    if source == "installed":
        plugins = market.list_installed()
    else:
        plugins = market.list_builtin()
    for p in plugins:
        click.echo(f"  {p['name']:25} v{p.get('version', '?')}  {p['description'][:60]}")


@market.command("install")
@click.argument("plugin_name")
def market_install(plugin_name):
    """Install a plugin."""
    from orchestra.code_agent.market.plugins import PluginMarket
    market = PluginMarket()
    result = market.install(plugin_name)
    click.echo(result.get("message", result.get("error", "")))
    if not result.get("success"):
        click.echo(f"  Try: code-agent market list")


@market.command("search")
@click.argument("query")
def market_search(query):
    """Search for plugins."""
    from orchestra.code_agent.market.plugins import PluginMarket
    market = PluginMarket()
    results = market.search(query)
    if not results:
        click.echo("No plugins found.")
        return
    for p in results:
        source = p.get("_source", "builtin")
        click.echo(f"  [{source:8}] {p['name']:25} {p['description'][:60]}")


@main.command()
@click.argument("task", required=False)
@click.option("--model", default="gpt-4o", help="Model to estimate")
@click.option("--turns", default=5, type=int, help="Expected agent turns")
@click.option("--compare", is_flag=True, help="Compare all models")
def estimate(task, model, turns, compare):
    """Estimate LLM cost before running."""
    from orchestra.code_agent.estimate.calculator import CostEstimator
    estimator = CostEstimator(model=model)

    if not task:
        click.echo("Provide a task description.")
        return

    if compare:
        results = estimator.compare_models(task)
        click.echo(f"{'Model':30} {'Input Tokens':>15} {'Output Tokens':>15} {'Cost':>10}")
        click.echo("-" * 70)
        for r in results:
            click.echo(f"{r['model']:30} {r['estimated_input_tokens']:>10,} {r['estimated_output_tokens']:>10,} ${r['estimated_cost_usd']:<8.6f}")
        return

    result = estimator.estimate_task(task, expected_turns=turns)
    click.echo(f"Task tokens: {result['task_tokens']:,}")
    click.echo(f"Expected turns: {result['expected_turns']}")
    click.echo(f"Est. input:  {result['estimated_input_tokens']:>8,} tokens")
    click.echo(f"Est. output: {result['estimated_output_tokens']:>8,} tokens")
    click.echo(f"Est. cost:   ${result['estimated_cost_usd']:.6f}")


@main.command()
@click.argument("task")
@click.option("--model-a", default="gpt-4o-mini")
@click.option("--model-b", default="gpt-4o")
@click.option("--runs", default=3, type=int)
@click.option("--name", default="ab-test", help="Test name")
def abtest(task, model_a, model_b, runs, name):
    """A/B test two model configurations."""
    from orchestra.code_agent.abtest.runner import ABTestRunner, ABTestConfig
    config = ABTestConfig(name=name, task=task, model_a=model_a, model_b=model_b, runs=runs)
    runner = ABTestRunner()
    click.echo(f"A/B test: {model_a} vs {model_b} ({runs} runs each)")
    result = asyncio.run(runner.run(config))
    click.echo(result.summary())
    click.echo(f"Winner: {result.winner}")


@main.command()
@click.option("--report", is_flag=True)
@click.option("--path", default=".", help="Project path")
def deps(report, path):
    """Audit and check for dependency updates."""
    from orchestra.code_agent.depupdater.updater import DepUpdater
    updater = DepUpdater()

    if report:
        click.echo(updater.generate_report(path))
        return

    all_deps = []
    all_deps.extend(updater.scan_requirements())
    all_deps.extend(updater.scan_pyproject())
    all_deps.extend(updater.scan_npm())

    click.echo(f"Found {len(all_deps)} dependencies")
    all_deps = updater.check_updates(all_deps)
    updates = [d for d in all_deps if d.update_available]
    if updates:
        for d in updates[:10]:
            click.echo(f"  {d.name:25} {d.current_version:10} -> {d.latest_version}")
        if len(updates) > 10:
            click.echo(f"  ... and {len(updates) - 10} more")
    else:
        click.echo("All dependencies up to date.")


@main.command()
@click.option("--command", default="python -m pytest", help="Test command")
@click.option("--path", default=".", help="Watch path")
@click.option("--interval", default=2.0, type=float, help="Poll interval")
@click.option("--once", is_flag=True, help="Run tests once without watching")
def testwatch(command, path, interval, once):
    """Watch files and auto-run tests."""
    from orchestra.code_agent.testwatcher.runner import TestWatcher
    watcher = TestWatcher(test_command=command)

    if once:
        click.echo(f"Running: {command}")
        result = asyncio.run(watcher.run_tests())
        status = "PASS" if result.success else "FAIL"
        click.echo(f"[{status}] ({result.duration_ms:.0f}ms)")
        if not result.success:
            click.echo(result.output[:1000])
        return

    click.echo(f"Watching {path} for changes (Ctrl+C to stop)...")
    try:
        asyncio.run(watcher.watch_and_run(path, interval=interval))
    except KeyboardInterrupt:
        watcher.stop()
        click.echo("\nStopped.")


@main.command()
@click.argument("path", required=False)
@click.option("--action", default="info", help="info, describe, encode")
@click.option("--output", default="", help="Output path for encoded data")
def image(path, action, output):
    """Process images for multi-modal LLM input."""
    from orchestra.code_agent.multimodal.processor import ImageProcessor

    if not path:
        click.echo("Provide an image path.")
        return

    if action == "info":
        info = ImageProcessor.describe_image_locally(path)
        click.echo(info)
    elif action == "describe":
        info = ImageProcessor.describe_image_locally(path)
        click.echo(f"Image: {info}")
        click.echo("Use multi-modal LLM support for AI description.")
    elif action == "encode":
        b64 = ImageProcessor.encode_image(path)
        if output:
            Path(output).write_text(b64)
            size_kb = Path(path).stat().st_size / 1024
            click.echo(f"Encoded {size_kb:.1f}KB image to {output}")
        else:
            click.echo(b64[:200] + "..." if len(b64) > 200 else b64)


@main.command()
@click.argument("query")
@click.option("--max", "max_results", default=10, type=int)
def sessearch(query, max_results):
    """Semantic search across all sessions."""
    from orchestra.code_agent.sessearch.searcher import SessionSearchEngine
    engine = SessionSearchEngine()
    results = engine.search(query, top_k=max_results)
    if not results:
        click.echo("No matching sessions found.")
        return
    click.echo(f"Found {len(results)} sessions:\n")
    for r in results:
        click.echo(f"  [{r.score:.2f}] {r.session_id}")
        click.echo(f"        Task: {r.task[:80]}")
        click.echo(f"        {r.snippet[:120]}")


@main.command()
def diagnose():
    """Run self-diagnosis checks on the agent."""
    from orchestra.code_agent.selfdiag.check import SelfDiagnosis
    diag = SelfDiagnosis()
    report = diag.run()
    click.echo(report.to_text())


@main.group()
def tenant():
    """Multi-tenant management."""


@tenant.command("create")
@click.argument("name")
@click.option("--workspace", default="", help="Workspace directory")
def tenant_create(name, workspace):
    """Create a new tenant."""
    from orchestra.code_agent.tenants.manager import TenantManager
    mgr = TenantManager()
    t = mgr.create_tenant(name, workspace)
    click.echo(f"Tenant: {t.id} ({t.name})")
    click.echo(f"API Key: {t.api_key}")
    click.echo(f"Workspace: {t.workspace}")


@tenant.command("list")
def tenant_list():
    """List all tenants."""
    from orchestra.code_agent.tenants.manager import TenantManager
    mgr = TenantManager()
    for t in mgr.list_tenants():
        click.echo(f"  {t['id']:12} {t['name']:20} users={t['users']}  workspace={t['workspace']}")


@tenant.command("add-user")
@click.argument("tenant_id")
@click.argument("name")
@click.option("--email", default="")
@click.option("--role", default="user")
def tenant_add_user(tenant_id, name, email, role):
    """Add a user to a tenant."""
    from orchestra.code_agent.tenants.manager import TenantManager
    mgr = TenantManager()
    user = mgr.add_user(tenant_id, name, email, role)
    if user:
        click.echo(f"Added user: {user.id} ({user.name})")
    else:
        click.echo(f"Tenant not found: {tenant_id}")


@main.command()
@click.argument("code", required=False)
@click.option("--file", "file_path", help="Run code from file")
@click.option("--timeout", default=30, type=int)
def sandbox(code, file_path, timeout):
    """Run Python code in a restricted sandbox."""
    from orchestra.code_agent.sbox.sandbox import SubprocessSandbox
    sbox = SubprocessSandbox(timeout=timeout)

    if file_path:
        result = sbox.run_file(file_path)
    elif code:
        result = sbox.run(code)
    else:
        click.echo("Provide --code or --file")
        return

    if result.blocked:
        click.echo(f"[BLOCKED] {result.stderr}")
        return
    if result.stderr:
        click.echo(f"[STDERR] {result.stderr[:1000]}")
    click.echo(result.stdout[:2000])
    click.echo(f"\n[exit: {result.return_code}, {result.duration_ms:.0f}ms]")


@main.command()
@click.argument("code", required=False)
@click.option("--file", "file_path", help="Debug code from file")
@click.option("--breakpoints", default="", help="Comma-separated line numbers")
@click.option("--explain", is_flag=True, help="Explain errors")
def debug(code, file_path, breakpoints, explain):
    """Debug Python code interactively."""
    from orchestra.code_agent.debugger.interactive import InteractiveDebugger
    debugger = InteractiveDebugger()

    bps = [int(b.strip()) for b in breakpoints.split(",") if b.strip()] if breakpoints else None

    if file_path:
        result = debugger.debug_file(file_path, bps)
    elif code:
        result = debugger.debug_code(code, bps)
    else:
        click.echo("Provide --code or --file")
        return

    if result.get("error"):
        click.echo(f"Error: {result['error']}")
        return
    if result.get("debug_trace"):
        click.echo("Debug trace:")
        for line in result["debug_trace"]:
            click.echo(f"  {line}")
    if result.get("stderr"):
        click.echo(f"\nStderr: {result['stderr'][:500]}")
    if explain and result.get("stderr"):
        click.echo(f"\nExplanation: {debugger.explain_error(result['stderr'])}")
    click.echo(f"\n[exit: {result.get('return_code', -1)}, {result.get('duration_ms', 0):.0f}ms]")


@main.command()
@click.argument("action", type=click.Choice(["ask", "confirm", "pending"]), default="pending")
@click.argument("question", required=False)
@click.option("--context", default="")
def human(action, question, context):
    """Request or manage human input."""
    from orchestra.code_agent.human.input import HumanInputHandler
    handler = HumanInputHandler()

    if action == "pending":
        requests = handler.requests()
        if not requests:
            click.echo("No pending requests.")
            return
        for r in requests:
            status = "answered" if r["answered"] else "pending"
            click.echo(f"  [{status}] {r['id']}: {r['question'][:80]}")
    elif action == "ask" and question:
        response = asyncio.run(handler.ask(question, context=context))
        click.echo(f"Response: {response}")
    elif action == "confirm" and question:
        result = asyncio.run(handler.confirm(question, context))
        click.echo(f"Confirmed: {result}")


@main.command()
@click.argument("action", type=click.Choice(["unified", "terminal", "markdown", "stats", "side"]), default="unified")
@click.argument("old_file")
@click.argument("new_file", required=False)
@click.option("--width", default=80, type=int)
def diffview(action, old_file, new_file, width):
    """Render file diffs in multiple formats."""
    from orchestra.code_agent.diffview.renderer import DiffRenderer

    old_text = Path(old_file).read_text(encoding="utf-8", errors="ignore")
    new_text = Path(new_file).read_text(encoding="utf-8", errors="ignore") if new_file else ""

    if action == "unified":
        click.echo(DiffRenderer.unified(old_text, new_text))
    elif action == "terminal":
        click.echo(DiffRenderer.terminal(old_text, new_text))
    elif action == "markdown":
        click.echo(DiffRenderer.markdown(old_text, new_text, filename=old_file))
    elif action == "stats":
        s = DiffRenderer.stats(old_text, new_text)
        click.echo(f"Changes: +{s['added']} -{s['removed']} ~{s['changed']} ({s['total_changes']} total)")
    elif action == "side":
        click.echo(DiffRenderer.side_by_side(old_text, new_text, width=width))


@main.group()
def collab():
    """Multi-agent collaboration sessions."""


@collab.command("create")
@click.argument("task")
@click.option("--roles", default="lead,writer,reviewer", help="Comma-separated roles")
def collab_create(task, roles):
    """Create a collaboration session."""
    from orchestra.code_agent.collab.manager import CollaborationManager
    mgr = CollaborationManager()
    role_list = [r.strip() for r in roles.split(",") if r.strip()]
    session = mgr.create_session(task, roles=role_list)
    click.echo(f"Session: {session.id}")
    click.echo(f"Collaborators: {len(session.collaborators)}")
    for c in session.collaborators:
        click.echo(f"  {c.name} ({c.role})")


@collab.command("run")
@click.argument("session_id")
def collab_run(session_id):
    """Run a collaboration session."""
    from orchestra.code_agent.collab.manager import CollaborationManager
    mgr = CollaborationManager()
    session = mgr.load_session(session_id)
    if not session:
        click.echo(f"Session not found: {session_id}")
        return
    click.echo(f"Running session: {session_id}")
    result = asyncio.run(mgr.run_session(session))
    click.echo(f"Output: {result.output[:1000]}")


@collab.command("list")
def collab_list():
    """List collaboration sessions."""
    from orchestra.code_agent.collab.manager import CollaborationManager
    mgr = CollaborationManager()
    for s in mgr.list_sessions():
        click.echo(f"  {s['id']:12} [{s['status']:10}] {s['task']}")


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--action", default="review", help="review, dashboard, trend")
@click.option("--html", is_flag=True, help="HTML output")
@click.option("--port", default=8400, type=int, help="Dashboard server port")
def reviews(path, action, html, port):
    """Code review management and dashboard."""
    from orchestra.code_agent.reviews.dashboard import ReviewDashboard
    dashboard = ReviewDashboard()

    if action == "dashboard":
        if html:
            import webbrowser
            html_content = dashboard.get_html_dashboard()
            out = Path("review-dashboard.html")
            out.write_text(html_content)
            click.echo(f"Dashboard written to {out}")
        else:
            trend = dashboard.get_trend()
            click.echo(f"Reviews: {trend['reviews_count']}")
            click.echo(f"Avg score: {trend['avg_score']}")
        return

    if action == "trend":
        trend = dashboard.get_trend()
        click.echo(json.dumps(trend, indent=2))
        return

    result = asyncio.run(dashboard.review_file(path))
    click.echo(f"Score: {result.score:.1f}/10")
    click.echo(f"Issues: {len(result.comments)}")
    if result.comments:
        for c in result.comments[:10]:
            click.echo(f"  [{c.severity:7}] {c.message[:80]}")


@main.command()
@click.argument("query")
def nlquery(query):
    """Ask natural language questions about the codebase."""
    from orchestra.code_agent.nlquery.engine import NLQueryEngine
    engine = NLQueryEngine()
    result = asyncio.run(engine.query(query))
    click.echo(result)


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--action", default="mermaid", help="mermaid, markdown, json")
def arch(path, action):
    """Generate architecture diagrams from codebase."""
    from orchestra.code_agent.archgen.generator import ArchitectureGenerator
    gen = ArchitectureGenerator(path)
    if action == "mermaid":
        click.echo(gen.generate_mermaid())
    elif action == "markdown":
        click.echo(gen.generate_markdown())
    elif action == "json":
        click.echo(gen.generate_json())


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--output", default="docs-site", help="Output directory")
@click.option("--serve", "do_serve", is_flag=True, help="Serve after building")
@click.option("--port", default=8300, type=int)
def docssite(path, output, do_serve, port):
    """Build a self-hosted documentation site."""
    from orchestra.code_agent.docssite.builder import DocsSiteBuilder
    builder = DocsSiteBuilder(output_dir=output)
    files = builder.build(source_path=path)
    click.echo(f"Built {len(files)} pages in {output}/")
    if do_serve:
        builder.serve(port=port)


@main.command()
@click.argument("query", required=False)
@click.option("--path", "-p", default=".", help="Project path")
@click.option("--kind", "-k", help="Filter by kind (function, class, variable, etc)")
@click.option("--definitions", "find_defs", is_flag=True, help="Find definitions only")
@click.option("--build-index", "do_build", is_flag=True, help="Build the symbol index")
def codesearch(query, path, kind, find_defs, do_build):
    """Search code symbols (functions, classes, variables)."""
    from orchestra.code_agent.codesearch.base import CodeSearchEngine
    engine = CodeSearchEngine(path)
    if do_build or not query:
        engine.build_index()
        click.echo(f"Indexed {len(engine.index.symbols)} symbols in {path}")
        return
    if find_defs:
        results = engine.find_definitions(query)
    else:
        results = engine.search(query, kind=kind)
    if not results:
        click.echo("No matches found.")
        return
    for r in results:
        sig = f"  # {r.signature}" if r.signature else ""
        click.echo(f"{r.kind:15} {r.name:25} {r.file_path}:{r.line}{sig}")


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--title", default="API Documentation")
@click.option("--version", default="1.0.0")
@click.option("--output", "-o", help="Output file (JSON)")
@click.option("--format", "fmt", default="openapi", help="openapi, postman")
def apidocs(path, title, version, output, fmt):
    """Generate API documentation from source code."""
    from orchestra.code_agent.apidocs.base import ApiDocGenerator
    gen = ApiDocGenerator(path)
    spec = gen.generate(title=title, version=version)
    if fmt == "postman":
        result = spec.to_postman()
        output_data = json.dumps(result, indent=2)
    else:
        output_data = spec.to_json()
    if output:
        Path(output).write_text(output_data, encoding="utf-8")
        click.echo(f"Written to {output}")
    else:
        click.echo(output_data[:2000])


@main.command()
@click.argument("data_source", required=False)
@click.option("--type", "chart_type", default="bar", help="bar, line, pie, scatter, histogram, area, box")
@click.option("--title", default="Chart")
@click.option("--x", "x_key", help="X-axis key or column")
@click.option("--y", "y_key", help="Y-axis key or column")
@click.option("--output", "-o", help="Output SVG file")
@click.option("--width", default=800, type=int)
@click.option("--height", default=500, type=int)
def dataviz(data_source, chart_type, title, x_key, y_key, output, width, height):
    """Generate data visualizations as SVG."""
    from orchestra.code_agent.dataviz.base import DataVizEngine, ChartType, ChartConfig
    engine = DataVizEngine()
    cfg = ChartConfig(title=title, width=width, height=height)
    ct_map = {
        "bar": ChartType.BAR, "line": ChartType.LINE, "pie": ChartType.PIE,
        "scatter": ChartType.SCATTER, "histogram": ChartType.HISTOGRAM,
        "area": ChartType.AREA, "box": ChartType.BOX,
    }
    ct = ct_map.get(chart_type, ChartType.BAR)
    try:
        if data_source and data_source.endswith(".csv"):
            svg = engine.from_csv(data_source, ct, x_key, y_key)
        elif data_source and data_source.endswith(".json"):
            svg = engine.from_json(Path(data_source).read_text(), ct, x_key, y_key)
        else:
            click.echo("Provide a CSV or JSON file, or use --help for options.")
            return
        if output:
            engine.save(svg, output)
            click.echo(f"Chart saved to {output}")
        else:
            click.echo(svg[:2000])
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@main.command()
@click.argument("target", required=False)
@click.option("--script", help="Profile a Python script file")
@click.option("--code", help="Profile inline Python code")
@click.option("--output", "-o", help="Save flamegraph data")
def profile(target, script, code, output):
    """Profile Python code execution."""
    from orchestra.code_agent.profilers.base import CodeProfiler
    profiler = CodeProfiler()
    try:
        if code:
            result = profiler.profile_code(code)
        elif script:
            result = profiler.profile_script(script)
        elif target:
            def _run():
                exec(Path(target).read_text())
            result = profiler.profile_function(_run)
        else:
            click.echo("Provide --code, --script, or a target")
            return
        click.echo(profiler.summary_text(result))
        if output:
            profiler.save_flamegraph(result, output)
            click.echo(f"Flamegraph data saved to {output}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@main.command()
@click.argument("file")
@click.option("--format", "fmt", default="auto", help="auto, json, syslog, python, apache, raw")
@click.option("--level", help="Filter by level (ERROR, WARNING, etc)")
@click.option("--search", help="Search in log messages")
@click.option("--summary", "show_summary", is_flag=True, default=True)
def loganalyze(file, fmt, level, search, show_summary):
    """Analyze and summarize log files."""
    from orchestra.code_agent.loganalyze.base import LogAnalyzer
    analyzer = LogAnalyzer()
    summary = analyzer.parse_file(file, format=fmt)
    if show_summary:
        click.echo(analyzer.summary_text(summary))
    if level:
        entries = analyzer.filter_by_level(level)
        click.echo(f"\nFiltered ({level}): {len(entries)} entries")
        for e in entries[:10]:
            click.echo(f"  {e.source}:{e.line} {e.message[:120]}")
    if search:
        entries = analyzer.search(search)
        click.echo(f"\nSearch '{search}': {len(entries)} matches")
        for e in entries[:10]:
            click.echo(f"  [{e.level:8}] {e.message[:120]}")


@main.command()
@click.argument("path", required=False, default=".")
@click.option("--target", help="Specific test target")
@click.option("--args", "extra_args", default="", help="Extra args for pytest")
@click.option("--output", "-o", default="", help="Output coverage report path")
def coverage(path, target, extra_args, output):
    """Analyze test coverage."""
    from orchestra.code_agent.coverage.base import CoverageAnalyzer
    analyzer = CoverageAnalyzer(path)
    report = analyzer.run_coverage(target=target or "", args=extra_args)
    click.echo(analyzer.summary_text(report))
    if output:
        Path(output).write_text(json.dumps({
            "overall": report.overall_coverage,
            "files": [{"file": f.file_path, "coverage": f.coverage_pct} for f in report.files],
        }, indent=2), encoding="utf-8")


@main.command()
@click.argument("template_name", required=False)
@click.option("--list", "list_tmpl", is_flag=True, help="List available templates")
@click.option("--name", default="MyClass", help="Class/object name")
@click.option("--output", "-o", help="Output file")
@click.option("--params", default="", help="Constructor params")
def boilerplate(template_name, list_tmpl, name, output, params):
    """Generate boilerplate code from templates."""
    from orchestra.code_agent.boilerplate.base import BoilerplateGenerator
    gen = BoilerplateGenerator()
    if list_tmpl or not template_name:
        templates = gen.list_templates()
        click.echo(f"Available templates ({len(templates)}):")
        for t in templates:
            click.echo(f"  {t.name:20} {t.description}")
        return
    try:
        code = gen.generate(template_name, name=name, params=params)
        if output:
            Path(output).write_text(code, encoding="utf-8")
            click.echo(f"Written to {output}")
        else:
            click.echo(code)
    except ValueError as e:
        click.echo(str(e), err=True)


@main.command()
@click.argument("action", type=click.Choice(["create", "remove", "list", "info", "install", "freeze"]))
@click.argument("name", required=False)
@click.option("--python", "python_path", help="Python executable path")
@click.option("--packages", help="Packages to install (comma-separated)")
@click.option("--dir", "envs_dir", default=".venvs", help="Environments directory")
def envmgr(action, name, python_path, packages, envs_dir):
    """Manage Python virtual environments."""
    from orchestra.code_agent.envmgr.base import EnvManager
    mgr = EnvManager(envs_dir=envs_dir)
    try:
        if action == "create":
            if not name:
                click.echo("Name required for create", err=True); return
            info = mgr.create(name, python_path=python_path or "")
            click.echo(f"Created: {info.name} ({info.python_version})")
        elif action == "remove":
            if not name:
                click.echo("Name required for remove", err=True); return
            mgr.remove(name)
            click.echo(f"Removed: {name}")
        elif action == "list":
            infos = mgr.list()
            click.echo(mgr.summary_text(infos))
        elif action == "info":
            if not name:
                click.echo("Name required for info", err=True); return
            info = mgr.get(name)
            if info:
                click.echo(f"Name: {info.name}\nPath: {info.path}\nPython: {info.python_version}\nPackages: {info.packages}")
            else:
                click.echo(f"Environment '{name}' not found")
        elif action == "install":
            if not name or not packages:
                click.echo("Name and --packages required for install", err=True); return
            pkgs = [p.strip() for p in packages.split(",")]
            output = mgr.pip_install(name, pkgs)
            click.echo(output[:2000])
        elif action == "freeze":
            if not name:
                click.echo("Name required for freeze", err=True); return
            click.echo(mgr.pip_freeze(name))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


@main.command()
@click.argument("plan_name", required=False)
@click.option("--list", "list_plans", is_flag=True, help="List migration plans")
@click.option("--path", default=".", help="Source path")
@click.option("--analyze", "do_analyze", is_flag=True, help="Analyze without applying")
@click.option("--apply", "do_apply", is_flag=True, help="Apply migration")
@click.option("--common-fixes", is_flag=True, help="Apply common modernizations")
def migrate(plan_name, list_plans, path, do_analyze, do_apply, common_fixes):
    """Migrate code between frameworks or versions."""
    from orchestra.code_agent.migrate.base import CodeMigrator
    migrator = CodeMigrator(path)
    if common_fixes:
        results = migrator.apply_common_fixes(dry_run=not do_apply)
        click.echo(f"Common fixes: {len(results)} changes {'applied' if do_apply else 'detected'}")
        for r in results[:20]:
            click.echo(f"  {r['file']}: {r['fix']}")
        return
    if list_plans or not plan_name:
        plans = migrator.list_plans()
        click.echo("Available migration plans:")
        for p in plans:
            click.echo(f"  {p.name:25} {p.description}")
        return
    if do_analyze or not do_apply:
        plan = migrator.analyze(plan_name)
        click.echo(migrator.summary_text(plan))
    if do_apply:
        plan = migrator.apply(plan_name, dry_run=False)
        click.echo(f"\nApplied {len(plan.changes)} changes.")


@main.command()
@click.option("--port", default=8400, type=int, help="Port to serve on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--no-browser", is_flag=True, help="Don't open browser")
def playground(port, host, no_browser):
    """Launch the interactive tool playground."""
    from orchestra.code_agent.playground.server import PlaygroundServer
    server = PlaygroundServer(host=host, port=port)
    server.start(open_browser=not no_browser)
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        click.echo("\nPlayground stopped.")


@main.command()
@click.argument("query")
@click.option("--local", "local_model", default="llama3", help="Local model")
@click.option("--cloud", "cloud_model", default="gpt-4o", help="Cloud model")
@click.option("--sensitive", "sensitive_model", default="nemo-mistral", help="Sensitive data model")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def privacy(query, local_model, cloud_model, sensitive_model, output_json):
    """Route queries to appropriate model based on sensitivity."""
    from orchestra.code_agent.privacy.router import PrivacyRouter
    router = PrivacyRouter(local_model=local_model, cloud_model=cloud_model, sensitive_model=sensitive_model)
    decision = router.classify(query)
    if output_json:
        import json
        click.echo(json.dumps({
            "query": query,
            "sensitivity": decision.sensitivity.value,
            "provider": decision.recommended_provider,
            "model": decision.recommended_model,
            "reason": decision.reason,
        }, indent=2))
    else:
        click.echo(f"Query: {query[:80]}...")
        click.echo(f"Sensitivity: {decision.sensitivity.value}")
        click.echo(f"Route to: {decision.recommended_provider}/{decision.recommended_model}")
        click.echo(f"Reason: {decision.reason}")


@main.command()
@click.argument("action", type=click.Choice(["status", "check", "approve", "deny", "profile", "list"]))
@click.argument("target", required=False)
@click.option("--profile", "profile_name", default="standard", help="Policy profile")
@click.option("--type", "check_type", default="network", help="network, filesystem, shell")
def openshell(action, target, profile_name, check_type):
    """OpenShell network and filesystem policy engine."""
    from orchestra.code_agent.openshell.policy import OpenShellPolicy, Decision
    policy = OpenShellPolicy(profile_name)
    if action == "status":
        click.echo(policy.summary_text())
    elif action == "list":
        from orchestra.code_agent.openshell.policy import OpenShellPolicy as OSP
        profiles = OSP.list_profiles()
        click.echo("Available profiles:")
        for p in profiles:
            click.echo(f"  {p.name:15} {p.description}")
    elif action == "profile":
        click.echo(policy.summary_text())
    elif action == "check" and target:
        check_map = {"network": policy.check_network, "filesystem": policy.check_filesystem, "shell": policy.check_shell}
        fn = check_map.get(check_type, policy.check_network)
        decision = fn(target)
        click.echo(f"[{decision.value.upper():5}] {target}")
    elif action == "approve" and target:
        policy.approve_endpoint(target)
        click.echo(f"Approved: {target}")
    elif action == "deny" and target:
        policy.deny_endpoint(target)
        click.echo(f"Denied: {target}")


@main.command()
@click.argument("url", required=False)
@click.option("--search", help="Search query")
@click.option("--extract", "do_extract", is_flag=True, help="Extract readable text")
@click.option("--list", "list_tabs", is_flag=True, help="List open tabs")
@click.option("--close", type=int, help="Close tab by index")
def browser(url, search, do_extract, list_tabs, close):
    """Headless browser for web research."""
    from orchestra.code_agent.browser.engine import BrowserEngine
    engine = BrowserEngine()
    if list_tabs:
        for i, tab in enumerate(engine.tabs):
            click.echo(f"[{i}] {tab.url} — {tab.title[:60]}")
        return
    if close is not None:
        engine.close_tab(close)
        click.echo(f"Closed tab {close}")
        return
    if search:
        result = engine.search(search)
        if result.success:
            click.echo(f"Search results for: {search}")
            for i, src in enumerate(result.sources[:10], 1):
                click.echo(f"  {i}. {src['title']}")
                click.echo(f"     {src['url']}")
        else:
            click.echo(f"Error: {result.error}")
        return
    if url:
        result = engine.navigate(url)
        if result.success and result.data:
            click.echo(f"Title: {result.data.title}")
            click.echo(f"Status: {result.data.status}")
            click.echo(f"URL: {result.data.url}")
            if do_extract:
                text = engine.extract_text(result.data.content)
                click.echo(f"\nContent:\n{text[:2000]}")
        else:
            click.echo(f"Error: {result.error}")


@main.command()
@click.argument("action", type=click.Choice(["send", "history", "sessions"]))
@click.option("--message", "-m", help="Message content")
@click.option("--session", "session_id", default="default", help="Session ID")
@click.option("--export", "export_path", help="Export session to file")
def channel(action, message, session_id, export_path):
    """Multi-channel communication manager."""
    from orchestra.code_agent.channels.manager import ChannelManager, ChannelType
    mgr = ChannelManager()
    if action == "send" and message:
        mgr.receive(ChannelType.CLI, message, session_id=session_id)
        click.echo(f"Sent to session '{session_id}'")
    elif action == "history":
        msgs = mgr.get_history(session_id)
        click.echo(f"Session '{session_id}' ({len(msgs)} messages):")
        for m in msgs[-20:]:
            click.echo(f"  [{m.timestamp:%H:%M:%S}] {m.sender}: {m.content[:120]}")
    elif action == "sessions":
        pass
    if export_path:
        mgr.export_session(session_id, export_path)
        click.echo(f"Exported to {export_path}")


@main.command()
@click.argument("action", type=click.Choice(["speak", "listen", "status"]))
@click.argument("text", required=False)
@click.option("--output", "-o", help="Output audio file path")
def voice(action, text, output):
    """Voice interaction (TTS/STT)."""
    from orchestra.code_agent.voice.engine import VoiceEngine
    engine = VoiceEngine()
    if action == "speak" and text:
        result = engine.speak(text, output)
        if result.error:
            click.echo(f"Error: {result.error}", err=True)
        else:
            click.echo(f"Spoken: {text[:80]}...")
            if result.audio_path:
                click.echo(f"Audio saved: {result.audio_path}")
    elif action == "listen":
        result = engine.listen()
        if result.error:
            click.echo(f"Error: {result.error}", err=True)
        else:
            click.echo(f"Heard: {result.text}")
    elif action == "status":
        click.echo(f"Voice engine available: {engine.is_available()}")
        click.echo(f"TTS backend: {engine.tts_backend.value}")
        click.echo(f"STT backend: {engine.stt_backend.value}")


@main.command()
@click.argument("action", type=click.Choice(["status", "insights", "preferences", "summarize"]))
@click.option("--category", help="Filter insights by category")
@click.option("--store", "store_path", default=".agent-learnings.json", help="Store file path")
@click.option("--pref-key", help="Preference key to look up")
def selflearn(action, category, store_path, pref_key):
    """Self-learning agent that improves across sessions."""
    from orchestra.code_agent.selflearn.engine import SelfLearningEngine
    engine = SelfLearningEngine(store_path=store_path)
    if action == "status":
        click.echo(f"Store: {store_path}")
        click.echo(f"Insights: {len(engine.store.insights)}")
        click.echo(f"Preferences: {len(engine.store.preferences)}")
        click.echo(f"Patterns: {len(engine.store.patterns)}")
    elif action == "insights":
        insights = engine.get_insights(category=category)
        click.echo(f"Insights ({len(insights)}):")
        for i in sorted(insights, key=lambda x: x.confidence, reverse=True):
            click.echo(f"  [{i.category:20}] [{i.confidence:.0%}] {i.content[:80]}")
    elif action == "preferences":
        if pref_key:
            val = engine.get_preference(pref_key)
            click.echo(f"{pref_key}: {val}")
        else:
            for k, v in engine.store.preferences.items():
                click.echo(f"  {k}: {v['value']}")
    elif action == "summarize":
        click.echo(engine.summarize_learnings())


@main.command()
@click.argument("integration", type=click.Choice(["calendar", "email", "status"]))
@click.argument("action", required=False)
@click.option("--event", help="Calendar event description")
@click.option("--to", "to_addr", help="Email recipient")
@click.option("--subject", help="Email subject")
@click.option("--body", help="Email body")
def integrate(integration, action, event, to_addr, subject, body):
    """Integrate with external services (calendar, email)."""
    if integration == "status":
        from orchestra.code_agent.integrations.email import EmailIntegration
        email = EmailIntegration()
        click.echo(f"Email configured: {email.is_configured()}")
    elif integration == "calendar":
        from orchestra.code_agent.integrations.calendar import CalendarIntegration, CalendarEvent
        cal = CalendarIntegration()
        if action == "today":
            events = cal.today()
            click.echo(f"Today's events ({len(events)}):")
            for e in events:
                click.echo(f"  {e.start[:16]} — {e.summary}")
        elif action == "list":
            events = cal.list_events()
            click.echo(f"Events ({len(events)}):")
            for e in events:
                click.echo(f"  {e.start[:16]} — {e.summary}")
        elif action == "add" and event:
            parsed = cal.parse_natural_language(event)
            if parsed:
                cal.add_event(parsed)
                click.echo(f"Added: {parsed.summary} ({parsed.start})")
            else:
                click.echo("Could not parse event")
    elif integration == "email":
        from orchestra.code_agent.integrations.email import EmailIntegration, EmailMessage
        email = EmailIntegration()
        if action == "configure":
            click.echo("Use: code-agent email configure --help")
        elif action == "send" and to_addr:
            msg = EmailMessage(to=to_addr, subject=subject or "(no subject)", body=body or "(empty)")
            sent = email.send(msg)
            click.echo(f"Email sent: {sent}")
        elif not email.is_configured():
            click.echo("Email not configured. Create ~/.agent-email.json")


@main.command()
@click.argument("action", type=click.Choice(["list", "add", "remove", "run", "test"]))
@click.argument("host", required=False)
@click.option("--port", default=22, type=int, help="SSH port")
@click.option("--user", default="", help="SSH user")
@click.option("--key", "key_path", help="SSH key path")
@click.option("--name", help="Host display name")
@click.option("--command", "-c", help="Command to run")
@click.option("--timeout", default=60, type=int)
def remote(action, host, port, user, key_path, name, command, timeout):
    """Run agent commands on remote machines via SSH."""
    from orchestra.code_agent.remote.agent import RemoteAgent, RemoteHost
    agent = RemoteAgent()
    if action == "list":
        click.echo(agent.summary_text())
    elif action == "add" and host:
        rh = RemoteHost(host=host, port=port, user=user, key_path=key_path or "", name=name or host)
        agent.add_host(rh)
        click.echo(f"Added host: {rh.name} ({rh.user}@{rh.host}:{rh.port})")
    elif action == "remove" and host:
        if agent.remove_host(host):
            click.echo(f"Removed host: {host}")
        else:
            click.echo(f"Host not found: {host}")
    elif action == "test" and host:
        result = agent.test_connection(host)
        if result.error:
            click.echo(f"Error: {result.error}", err=True)
        else:
            click.echo(f"Connected to {host} ({result.duration:.2f}s)")
            click.echo(result.stdout[:500])
    elif action == "run" and host and command:
        result = agent.run(host, command, timeout=timeout)
        if result.error:
            click.echo(f"Error: {result.error}", err=True)
        else:
            click.echo(f"Exit code: {result.exit_code} ({result.duration:.2f}s)")
            if result.stdout:
                click.echo(result.stdout[:2000])
            if result.stderr:
                click.echo(f"STDERR:\n{result.stderr[:1000]}")


@main.command()
@click.argument("action", type=click.Choice(["create", "list", "restore", "delete"]))
@click.argument("name", required=False)
@click.option("--project", default=".", help="Project root directory")
@click.option("--output", "-o", help="Backup output directory")
@click.option("--modules", help="Comma-separated module list to backup/restore")
def backup(action, name, project, output, modules):
    """Backup and restore agent state."""
    from orchestra.code_agent.backup.manager import BackupManager
    mgr = BackupManager(backup_root=output or "")
    if action == "create":
        mod_list = [m.strip() for m in modules.split(",")] if modules else None
        entry = mgr.create(name=name or "", project_root=project, modules=mod_list)
        click.echo(f"Backup created: {entry.name}")
        click.echo(f"  Path:  {entry.path}")
        click.echo(f"  Files: {entry.files}")
        click.echo(f"  Size:  {entry.size_bytes / 1024:.1f} KB")
    elif action == "list":
        click.echo(mgr.summary_text())
    elif action == "restore" and name:
        mod_list = [m.strip() for m in modules.split(",")] if modules else None
        result = mgr.restore(name, target_dir=project, modules=mod_list)
        if result.success:
            click.echo(f"Restored {result.files_restored} files from '{name}'")
        else:
            click.echo(f"Restore failed: {'; '.join(result.errors)}", err=True)
    elif action == "delete" and name:
        if mgr.delete(name):
            click.echo(f"Deleted backup: {name}")
        else:
            click.echo(f"Backup not found: {name}")


@main.command()
@click.argument("range_spec", required=False)
@click.option("--max-count", default=100, type=int, help="Max commits")
@click.option("--format", "fmt", default="markdown", help="markdown, json, summary")
@click.option("--output", "-o", help="Output file")
@click.option("--path", default=".", help="Repository path")
def changelog(range_spec, max_count, fmt, output, path):
    """Generate changelog from git history."""
    from orchestra.code_agent.changelog.generator import ChangelogGenerator
    gen = ChangelogGenerator(repo_path=path)
    since, to = None, None
    if range_spec and ".." in range_spec:
        since, to = range_spec.split("..", 1)
    elif range_spec:
        since = range_spec
    cl = gen.generate(since=since, to=to, max_count=max_count)
    if fmt == "json":
        result = gen.generate_json(cl)
    elif fmt == "summary":
        result = gen.summary_text(cl)
    else:
        result = gen.generate_markdown(cl)
    if output:
        Path(output).write_text(result, encoding="utf-8")
        click.echo(f"Written to {output}")
    else:
        click.echo(result[:3000])


@main.group()
def reason():
    """Manage agent reasoning strategies and modules."""


@reason.command("config")
@click.option("--strategy", default="auto", help="cot, plan, reflect, tot, auto")
@click.option("--plan-first/--no-plan", default=True, help="Plan before executing")
@click.option("--verify-steps/--no-verify", default=False, help="Periodically verify progress")
@click.option("--show-thinking/--quiet", default=True, help="Show thinking output")
def reason_config(strategy, plan_first, verify_steps, show_thinking):
    """Configure reasoning strategy for the agent."""
    from orchestra.code_agent.config import ReasoningConfig
    cfg = ReasoningConfig(
        strategy=strategy,
        plan_first=plan_first,
        verify_steps=verify_steps,
        show_thinking=show_thinking,
    )
    click.echo(f"Reasoning config:")
    click.echo(f"  Strategy:     {cfg.strategy}")
    click.echo(f"  Plan first:   {cfg.plan_first}")
    click.echo(f"  Verify steps: {cfg.verify_steps}")
    click.echo(f"  Show thought: {cfg.show_thinking}")
    click.echo(f"  Trace dir:   {cfg.trace_dir}")


@reason.command("think")
@click.argument("task")
@click.option("--strategy", default="auto", help="cot, plan, reflect, tot, auto")
@click.option("--llm", "model", default="gpt-4o-mini", help="Model to use")
@click.option("--save", "do_save", is_flag=True, help="Save as reusable module")
def reason_think(task, strategy, model, do_save):
    """Run the reasoning engine on a task (no tool execution)."""
    from orchestra.code_agent.llm.base import LLM
    from orchestra.code_agent.reasoning.engine import ReasoningEngine
    from orchestra.code_agent.config import ReasoningConfig

    cfg = ReasoningConfig(strategy=strategy, show_thinking=True)
    llm = LLM(model=model)
    engine = ReasoningEngine(llm, cfg)

    click.echo(f"\n  Thinking about: {task}")
    click.echo(f"  Strategy: {strategy}\n")
    result = asyncio.run(engine.think(task))
    click.echo(f"\n  Thought complete.\n")

    if do_save and engine.current_session:
        from orchestra.code_agent.reasoning.saver import ModuleSaver
        saver = ModuleSaver()
        saver.save_from_session(engine.current_session.to_dict())
        click.echo("  Saved as reasoning module.")


@reason.command("traces")
@click.option("--name", help="Show specific trace")
@click.option("--delete", "do_delete", help="Delete trace by name")
def reason_traces(name, do_delete):
    """View saved reasoning traces."""
    from orchestra.code_agent.config import ReasoningConfig
    from orchestra.code_agent.reasoning.engine import ReasoningEngine
    cfg = ReasoningConfig()
    engine = ReasoningEngine.__new__(ReasoningEngine)
    engine.config = cfg
    engine.llm = None

    if do_delete:
        Path(f"{cfg.trace_dir}/{do_delete}.json").unlink(missing_ok=True)
        click.echo(f"Deleted: {do_delete}")
        return

    if name:
        session = engine.load_trace(name)
        if not session:
            click.echo(f"Trace not found: {name}")
            return
        click.echo(f"Task: {session.task}")
        click.echo(f"Strategy: {session.strategy}")
        click.echo(f"Duration: {session.duration_ms:.0f}ms")
        click.echo(f"Errors: {len(session.errors)}")
        click.echo(f"Result: {(session.result or '')[:200]}")
        if session.plan:
            click.echo(f"\nPlan:\n{session.plan[:500]}")
        if session.traces:
            for i, t in enumerate(session.traces):
                steps = t.get("steps", [])
                click.echo(f"\nTrace {i+1}: {len(steps)} steps")
                for s in steps[-3:]:
                    click.echo(f"  [{s.get('label','?')}] {s.get('content','')[:120]}")
        return

    traces = engine.list_traces()
    if not traces:
        click.echo("No traces found. Run an agent task to generate traces.")
        return
    click.echo(f"Saved reasoning traces ({len(traces)}):")
    for t in traces:
        err = f" ({t['errors']} errors)" if t['errors'] else ""
        click.echo(f"  {t['name']:50} {t['strategy']:8} {t['duration_ms']:8.0f}ms{err}")


@reason.command("modules")
@click.option("--name", help="Show module details")
@click.option("--delete", "do_delete", help="Delete module")
def reason_modules(name, do_delete):
    """List and manage saved reasoning modules."""
    from orchestra.code_agent.reasoning.saver import ModuleSaver
    saver = ModuleSaver()

    if do_delete:
        if saver.delete_module(do_delete):
            click.echo(f"Deleted module: {do_delete}")
        else:
            click.echo(f"Module not found: {do_delete}")
        return

    if name:
        mod = saver.load_module(name)
        if not mod:
            click.echo(f"Module not found: {name}")
            return
        click.echo(f"Name:        {mod.name}")
        click.echo(f"Strategy:    {mod.strategy}")
        click.echo(f"Description: {mod.description}")
        click.echo(f"Tags:        {', '.join(mod.tags)}")
        click.echo(f"Successes:   {mod.success_count}")
        click.echo(f"Plan template:\n{mod.plan_template[:500]}")
        return

    modules = saver.list_modules()
    if not modules:
        click.echo("No modules saved yet.")
        return
    click.echo(f"Saved reasoning modules ({len(modules)}):")
    for m in modules:
        tags = f" [{', '.join(m['tags'])}]" if m['tags'] else ""
        click.echo(f"  {m['name']:40} {m['strategy']:8} {m['description'][:50]}{tags}")


@reason.command("errors")
@click.option("--pattern", help="Search for matching error pattern")
def reason_errors(pattern):
    """View learned error patterns and solutions."""
    from orchestra.code_agent.reasoning.saver import ModuleSaver
    saver = ModuleSaver()
    patterns = saver.list_error_patterns()
    if not patterns:
        click.echo("No error patterns saved yet.")
        return
    if pattern:
        patterns = [p for p in patterns if pattern.lower() in p["pattern"].lower()]
    click.echo(f"Error patterns ({len(patterns)}):")
    for p in patterns:
        click.echo(f"  [{p['count']:3}x] {p['pattern'][:60]}")
        click.echo(f"       -> {p['solution'][:80]}")


@main.group()
def mdconfig():
    """Manage Markdown configuration files."""


@mdconfig.command("init")
@click.option("--project", default="", help="Project name")
@click.option("--force", is_flag=True, help="Overwrite existing files")
def mdconfig_init(project, force):
    """Generate CLAUDE.md and AGENTS.md config files."""
    from orchestra.code_agent.mdconfig.generator import (
        generate_claude_md, generate_agents_md, write_config,
    )

    claude_path = Path("CLAUDE.md")
    agents_path = Path("AGENTS.md")

    if claude_path.exists() and not force:
        click.echo("CLAUDE.md already exists. Use --force to overwrite.")
    else:
        content = generate_claude_md(
            project_name=project or Path.cwd().name,
            description="AI coding agent project",
            architecture="CLI/API -> Agent Loop -> Tools/LLM -> Infrastructure",
            conventions=[
                "Follow existing code style and patterns",
                "Add tests for new functionality",
                "Run lint before committing",
                "Use type hints everywhere",
                "Keep functions small and focused",
            ],
            tests="python -m pytest",
            lint="ruff check .",
        )
        write_config("CLAUDE.md", content)
        click.echo(f"  Created: CLAUDE.md ({len(content)} chars)")

    if agents_path.exists() and not force:
        click.echo("AGENTS.md already exists. Use --force to overwrite.")
    else:
        content = generate_agents_md(
            role="autonomous coding agent",
            goals=[
                "Understand tasks before acting",
                "Write clean, tested code",
                "Follow project conventions",
                "Verify work with tests",
            ],
            constraints=[
                "Never commit secrets or API keys",
                "Confirm before destructive operations",
                "Keep responses concise",
            ],
            preferences={
                "editor": "code",
                "test_runner": "pytest",
                "python_version": "3.13",
            },
            tools=["read", "write", "edit", "glob", "grep", "bash", "git"],
        )
        write_config("AGENTS.md", content)
        click.echo(f"  Created: AGENTS.md ({len(content)} chars)")


@mdconfig.command("generate")
@click.argument("type", type=click.Choice(["claude", "agents", "prompt", "tool", "board", "workflow"]))
@click.argument("name")
@click.option("--output", "-o", help="Output file path")
@click.option("--desc", "description", default="", help="Description")
@click.option("--content", help="Content for prompt/tool body")
@click.option("--force", is_flag=True, help="Overwrite existing file")
def mdconfig_generate(type, name, output, description, content, force):
    """Generate a specific Markdown config file."""
    from orchestra.code_agent.mdconfig.generator import (
        generate_claude_md, generate_agents_md, generate_prompt_md,
        generate_tool_md, generate_project_board_md, generate_workflow_md,
        write_config,
    )

    ext = ".md"
    if type == "claude":
        text = generate_claude_md(project_name=name, description=description or "Project config")
        default_name = "CLAUDE.md"
    elif type == "agents":
        text = generate_agents_md(role=description or name)
        default_name = "AGENTS.md"
    elif type == "prompt":
        text = generate_prompt_md(name=name, description=description or "", system_prompt=content or "")
        default_name = f"{name}.prompt.md"
    elif type == "tool":
        text = generate_tool_md(name=name, description=description or "", parameters=[])
        default_name = f"{name}.tool.md"
    elif type == "board":
        text = generate_project_board_md(tasks=[{"title": name, "status": "todo"}], name=description or "Board")
        default_name = f"{name}.board.md"
    elif type == "workflow":
        text = generate_workflow_md(name=name, description=description or "", steps=[])
        default_name = f"{name}.workflow.md"
    else:
        click.echo(f"Unknown type: {type}")
        return

    out_path = output or default_name
    p = Path(out_path)
    if p.exists() and not force:
        click.echo(f"File exists: {out_path}. Use --force to overwrite.")
        return
    write_config(out_path, text)
    click.echo(f"  Created: {out_path}")


@mdconfig.command("show")
@click.argument("file", required=False)
@click.option("--dir", "dir_path", default=".", help="Directory to scan")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
def mdconfig_show(file, dir_path, json_output):
    """Parse and display a Markdown config file."""
    from orchestra.code_agent.mdconfig.parser import parse_md, extract_frontmatter

    if file:
        p = Path(file)
    else:
        p = Path(dir_path) / "CLAUDE.md"
        if not p.exists():
            p = Path(dir_path) / "AGENTS.md"

    if not p.exists():
        click.echo(f"No config file found at: {p}")
        return

    cfg = parse_md(p)
    if json_output:
        import json as j
        click.echo(j.dumps(cfg.to_dict(), indent=2))
        return

    fm = cfg.frontmatter
    click.echo(f"\n  File: {p.name}")
    if fm:
        click.echo(f"  Frontmatter keys: {list(fm.keys())}")
        for k, v in list(fm.items())[:5]:
            click.echo(f"    {k}: {v}")
    click.echo(f"  Sections: {len(cfg.sections)}")
    for s in cfg.sections[:10]:
        items = len(s.items)
        pairs = len(s.pairs)
        children = len(s.children)
        extra = []
        if items:
            extra.append(f"{items} items")
        if pairs:
            extra.append(f"{pairs} pairs")
        if children:
            extra.append(f"{children} subsections")
        extra_str = f" ({', '.join(extra)})" if extra else ""
        click.echo(f"    {'#' * s.level} {s.heading}{extra_str}")
        for child in s.children[:3]:
            click.echo(f"      {'#' * child.level} {child.heading}")


@mdconfig.command("list")
@click.option("--dir", "dir_path", default=".", help="Directory to scan")
def mdconfig_list(dir_path):
    """List all Markdown config files in a directory."""
    from orchestra.code_agent.mdconfig.parser import extract_frontmatter

    d = Path(dir_path)
    md_files = list(d.glob("*.md"))
    # Also check .agent-mdconfig/
    config_dir = d / ".agent-mdconfig"
    if config_dir.exists():
        md_files.extend(config_dir.glob("*.md"))

    if not md_files:
        click.echo(f"No .md files found in {dir_path}")
        return

    click.echo(f"Markdown config files ({len(md_files)}):")
    for f in sorted(md_files):
        size = f.stat().st_size
        fm = extract_frontmatter(f)
        tags = list(fm.keys())[:3] if fm else []
        tag_str = f"  [{', '.join(tags)}]" if tags else ""
        click.echo(f"  {f.name:40} {size:>6}B{tag_str}")


@main.command()
@click.argument("action", type=click.Choice(["check", "scan"]))
@click.argument("text", required=False)
@click.option("--file", "file_path", help="Check a file instead of inline text")
@click.option("--sensitivity", default=0.5, type=float, help="Detection sensitivity (0-1)")
def shield(action, text, file_path, sensitivity):
    """Detect prompt injection and PII leaks."""
    from orchestra.code_agent.shield.detector import InjectionShield
    detector = InjectionShield(sensitivity=sensitivity)
    if file_path:
        text = Path(file_path).read_text(encoding="utf-8")
    if not text:
        click.echo("Provide --text or --file")
        return
    result = detector.analyze(text)
    click.echo(detector.summary_text(result))


@main.command()
@click.argument("name")
@click.argument("description")
@click.argument("behavior")
@click.option("--output", "-o", help="Output directory")
@click.option("--save", "do_save", is_flag=True, help="Save tool to file")
def toolbuilder(name, description, behavior, output, do_save):
    """Generate a new tool from a natural language description."""
    from orchestra.code_agent.toolbuilder.builder import ToolBuilder
    builder = ToolBuilder(output_dir=output or "src/code_agent/custom_tools")
    tool = builder.from_description(name, description, behavior)
    if do_save:
        path = builder.save(tool)
        click.echo(f"Tool saved to {path}")
    click.echo(builder.summary_text(tool))


@main.command()
@click.argument("action", type=click.Choice(["start", "stop", "status", "broadcast"]))
@click.option("--port", default=8500, type=int, help="WebSocket port")
@click.option("--host", default="127.0.0.1", help="Bind address")
@click.option("--message", help="Message to broadcast")
@click.option("--event", "event_type", default="message", help="Event type")
def ws(action, port, host, message, event_type):
    """WebSocket server for real-time agent events."""
    from orchestra.code_agent.ws.server import WebSocketServer
    server = WebSocketServer(host=host, port=port)
    if action == "status":
        click.echo(server.summary_text())
    elif action == "start":
        import asyncio
        try:
            asyncio.run(server.start())
        except KeyboardInterrupt:
            asyncio.run(server.stop())
            click.echo("\nWebSocket server stopped.")
    elif action == "broadcast" and message:
        import asyncio
        async def _send():
            await server.broadcast(event_type, {"message": message})
        asyncio.run(_send())
        click.echo(f"Broadcast '{event_type}' to {server.client_count} clients")


@main.command()
@click.option("--geometry", default="1280x800", help="Window size")
@click.option("--fallback/--no-fallback", default=True, help="Fallback to web UI if Tkinter unavailable")
def desktop(geometry, fallback):
    """Launch the desktop GUI. Falls back to web UI if Tkinter unavailable."""
    try:
        from orchestra.code_agent.desktop.app import DesktopGUI
        app = DesktopGUI()
        if geometry:
            app.root.geometry(geometry)
        app.run()
    except ImportError as e:
        click.echo(f"Tkinter not available: {e}")
        if fallback:
            click.echo("Falling back to web UI...")
            try:
                from orchestra.code_agent.ui.server import create_ui_app
                from orchestra.code_agent import AgentConfig
                import uvicorn
                app = create_ui_app(AgentConfig())
                click.echo("  Web UI at http://127.0.0.1:8000")
                uvicorn.run(app, host="127.0.0.1", port=8000)
            except ImportError:
                click.echo("FastAPI/uvicorn not installed. Run: pip install code-agent[server]")
        else:
            click.echo("Install python-tk package for your system.")
    except Exception as e:
        click.echo(f"Error starting desktop GUI: {e}")


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


@main.group()
def skill():
    """Manage the skill library (retrieval, distillation, credit)."""


@skill.command("list")
def skill_list():
    """List all skills in the library."""
    from orchestra.code_agent.skills.base import SkillLibrary
    lib = SkillLibrary()
    skills = lib.list_all()
    if not skills:
        safe_echo("Skill library is empty.")
        return
    safe_echo(f"Skill library ({len(skills)} skills):")
    for s in skills:
        safe_echo(f"  [{s.id}] {s.body[:80]} (used {s.usage_count}x, reward={s.avg_reward:.2f})")


@skill.command("show")
@click.argument("skill_id", type=int)
def skill_show(skill_id):
    """Show a skill by ID."""
    from orchestra.code_agent.skills.base import SkillLibrary
    s = SkillLibrary().get(skill_id)
    if not s:
        safe_echo(f"Skill #{skill_id} not found.")
        return
    safe_echo(f"ID: {s.id}")
    safe_echo(f"Body: {s.body}")
    safe_echo(f"Tags: {', '.join(s.tags)}")
    safe_echo(f"Usage count: {s.usage_count}")
    safe_echo(f"Avg reward: {s.avg_reward:.2f}")
    safe_echo(f"Success rate: {s.success_rate:.0%}")


@skill.command("search")
@click.argument("query")
@click.option("--top-k", default=5, help="Number of results")
def skill_search(query, top_k):
    """Search skills by semantic similarity."""
    from orchestra.code_agent.skills.base import SkillLibrary
    from orchestra.code_agent.skills.manager import SkillManager, Embedder
    mgr = SkillManager(SkillLibrary(), Embedder())
    results = asyncio.run(mgr.retrieve(query, top_k=top_k))
    if not results:
        safe_echo("No matching skills found.")
        return
    safe_echo(f"Top {len(results)} skills for: {query}")
    for s in results:
        safe_echo(f"  [{s.id}] {s.body[:80]} (reward={s.avg_reward:.2f})")


@skill.command("remove")
@click.argument("skill_id", type=int)
def skill_remove(skill_id):
    """Remove a skill by ID."""
    from orchestra.code_agent.skills.base import SkillLibrary
    ok = SkillLibrary().remove(skill_id)
    if ok:
        safe_echo(f"Removed skill #{skill_id}.")
    else:
        safe_echo(f"Skill #{skill_id} not found.")


@skill.command("add")
@click.option("--body", required=True, help="Skill body/procedure")
@click.option("--tags", default="", help="Comma-separated tags")
def skill_add(body, tags):
    """Add a skill manually."""
    from orchestra.code_agent.skills.base import Skill, SkillLibrary
    from orchestra.code_agent.skills.manager import Embedder
    skill = Skill(body=body, tags=[t.strip() for t in tags.split(",") if t.strip()])
    embedder = Embedder()
    skill.embedding = embedder.embed(body)
    skill.id = SkillLibrary().add(skill)
    safe_echo(f"Added skill #{skill.id}")


@skill.command("credit")
def skill_credit():
    """Show credit assignment signals for the last session."""
    from orchestra.code_agent.skills.base import SkillLibrary
    from orchestra.code_agent.skills.manager import SkillManager, Embedder
    mgr = SkillManager(SkillLibrary(), Embedder())
    credit = mgr.compute_credit()
    safe_echo("Credit signals:")
    safe_echo(f"  Selection:    {credit.selection:.3f}")
    safe_echo(f"  Utilization:  {credit.utilization:.3f}")
    safe_echo(f"  Distillation: {credit.distillation:.3f}")


@skill.command("seed")
@click.option("--clear", is_flag=True, help="Clear existing skills first")
def skill_seed(clear):
    """Seed the library with 20+ predefined coding skills."""
    from orchestra.code_agent.skills.seed import seed_library
    count = seed_library(clear=clear)
    safe_echo(f"Seeded {count} skills to the library.")


@main.group()
def skillv2():
    """Skill1-style meta-policy with 4-mode lifecycle (query, rerank, act, distill)."""


@skillv2.command("episode")
@click.argument("instruction")
@click.option("--difficulty", default=0.5, help="Task difficulty 0-1")
@click.option("--seed", type=int, default=None, help="Random seed")
@click.option("--provider", default="ollama", help="LLM provider")
@click.option("--model", default="nemotron-mini", help="LLM model")
def skillv2_episode(instruction, difficulty, seed, provider, model):
    """Run one full Skill1 episode: query → rerank → rollout → distill."""
    from orchestra.code_agent.llm.base import LLM
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    llm = LLM(provider=provider, model=model, timeout=120)
    mgr = SkillManagerV2(llm=llm)
    result = asyncio.run(mgr.run_episode(instruction, difficulty=difficulty, seed=seed))
    safe_echo(f"Episode {result['episode_id']}")
    safe_echo(f"  Task: {result['task']}")
    safe_echo(f"  Query: {result.get('query', '')}")
    safe_echo(f"  Selected skill: #{result.get('selected_skill_id', 'none')}")
    safe_echo(f"  Steps: {result.get('steps', 0)}")
    safe_echo(f"  Final reward: {result.get('final_reward', 0.0):.2f}")
    safe_echo(f"  Success: {result.get('success', False)}")
    safe_echo(f"  New skill distilled: #{result.get('new_skill_id', 'none')}")
    credit = result.get("credit", {})
    safe_echo(f"  Credit — selection: {credit.get('selection', 0):.3f}, utilization: {credit.get('utilization', 0):.3f}, distillation: {credit.get('distillation', 0):.3f}")


@skillv2.command("train")
@click.argument("num_episodes", type=int, default=5)
@click.option("--provider", default="ollama", help="LLM provider")
@click.option("--model", default="nemotron-mini", help="LLM model")
def skillv2_train(num_episodes, provider, model):
    """Run multiple training episodes with credit-based RL updates."""
    from orchestra.code_agent.llm.base import LLM
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    llm = LLM(provider=provider, model=model, timeout=120)
    mgr = SkillManagerV2(llm=llm)
    safe_echo(f"Training for {num_episodes} episodes...")
    results = asyncio.run(mgr.train(num_episodes=num_episodes))
    successes = sum(1 for r in results if r.get("success"))
    rewards = [r.get("final_reward", 0.0) for r in results]
    safe_echo(f"Completed {len(results)} episodes. Successes: {successes}/{len(results)}")
    safe_echo(f"Avg reward: {sum(rewards)/len(rewards):.2f}")
    safe_echo(f"Skills in library: {mgr.library.count()}")
    stats = mgr.trainer.stats()
    safe_echo(f"RL params: {stats.get('params', {})}")


@skillv2.command("evaluate")
@click.argument("skill_id", type=int)
def skillv2_evaluate(skill_id):
    """Evaluate a skill against held-out tasks."""
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    from orchestra.code_agent.skills.v2.evaluation import SkillEvaluator, EvalStore
    from orchestra.code_agent.skills.v2.environment import WebShopEnv
    mgr = SkillManagerV2()
    ev = EvalStore()
    env = WebShopEnv()
    evaluator = SkillEvaluator(mgr.library, env, ev)
    tasks = [
        "Buy a monitor under $300",
        "Find a red dress size M",
        "Buy a premium electronics product",
        "Find a sports item under $100",
    ]
    safe_echo(f"Evaluating skill #{skill_id} on {len(tasks)} tasks...")
    results = asyncio.run(evaluator.evaluate_skill(skill_id, tasks))
    if not results:
        safe_echo("Skill not found or no results.")
        return
    rewards = [r.reward for r in results]
    successes = sum(1 for r in results if r.success)
    safe_echo(f"Avg reward: {sum(rewards)/len(rewards):.2f}  Success: {successes}/{len(results)}")
    for r in results:
        safe_echo(f"  {r.task_instruction[:50]:50s} reward={r.reward:+.2f} success={r.success} steps={r.steps}")


@skillv2.command("benchmark")
def skillv2_benchmark():
    """Benchmark all skills against held-out tasks (comparison)."""
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    from orchestra.code_agent.skills.v2.evaluation import EvalStore
    ev = EvalStore()
    comp = ev.comparison()
    if not comp:
        safe_echo("No evaluation data. Run 'skillv2 evaluate' first.")
        return
    safe_echo("Skill comparison:")
    for s in comp:
        safe_echo(f"  [{s['skill_id']}] rate={s['success_rate']*100:.0f}% reward={s['avg_reward']:.2f} n={s['count']}  {s['skill_body']}")


@skillv2.command("credit")
def skillv2_credit():
    """Show persistent credit signal history."""
    from orchestra.code_agent.skills.v2 import CreditStore
    cs = CreditStore()
    hist = cs.history(limit=20)
    if not hist:
        safe_echo("No credit history yet.")
        return
    safe_echo("Credit history (last 20):")
    safe_echo("  step  outcome  sel     util    dist")
    for r in hist[-10:]:
        safe_echo(f"  {r.step:4d}  {r.outcome:+.2f}   {r.selection:.3f}  {r.utilization:.3f}  {r.distillation:.3f}")
    safe_echo(f"Latest: sel={hist[-1].selection:.3f} util={hist[-1].utilization:.3f} dist={hist[-1].distillation:.3f}")


@skillv2.command("library")
def skillv2_library():
    """Show v2 skill library stats."""
    from orchestra.code_agent.skills.v2 import SkillManagerV2
    mgr = SkillManagerV2()
    stats = mgr.stats()
    safe_echo("Skill Library v2 stats:")
    safe_echo(f"  Skills: {stats['library'].get('count', 0)}")
    safe_echo(f"  Avg reward: {stats['library'].get('avg_reward', 0):.3f}")
    safe_echo(f"  Avg success rate: {stats['library'].get('avg_success_rate', 0):.3f}")
    safe_echo(f"  Total usage: {stats['library'].get('total_usage', 0)}")

    lib_skills = mgr.library.list_all(limit=20)
    if lib_skills:
        safe_echo("\nTop skills by usage:")
        for s in lib_skills[:10]:
            safe_echo(f"  [{s.id}] usage={s.usage_count} reward={s.avg_reward:.2f} rate={s.success_rate:.2f}")
            safe_echo(f"       {s.body[:100]}")


# ═══════════════════════════════════════════════════════════════
# Interactive Chat
# ═══════════════════════════════════════════════════════════════

@main.command()
@click.option("--provider", default="ollama", help="LLM provider")
@click.option("--model", default="nemotron-mini", help="Model name")
@click.option("--stream/--no-stream", default=True, help="Stream tokens live")
def chat(provider, model, stream):
    """Interactive chat session with the agent."""
    import sys
    from orchestra.code_agent.llm.base import LLM, Message

    llm = LLM(provider=provider, model=model)
    safe_echo(f"Orchestra chat ({provider}/{model}) — Ctrl+C or type /exit to quit")
    safe_echo("")

    messages = []
    while True:
        try:
            user_input = click.prompt("You", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            safe_echo("")
            break

        if user_input.lower() in ("/exit", "/quit", ""):
            break

        messages.append(Message(role="user", content=user_input))

        try:
            if stream:
                safe_echo("Agent: ", nl=False)
                response = asyncio.run(llm.chat(messages, stream=True))
                safe_echo("")
            else:
                response = asyncio.run(llm.chat(messages))
                safe_echo(f"Agent: {response.content}")

            if response.content:
                messages.append(Message(role="assistant", content=response.content))

        except KeyboardInterrupt:
            safe_echo("\n[Interrupted]")
            break
        except Exception as e:
            safe_echo(f"Error: {e}")

    safe_echo("Bye!")


# ═══════════════════════════════════════════════════════════════
# Shell Completions
# ═══════════════════════════════════════════════════════════════

@main.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish", "powershell"]))
def completion(shell):
    """Generate shell completion scripts."""
    import subprocess, sys

    if shell == "powershell":
        script = """
# Orchestra CLI PowerShell completion
Register-ArgumentCompleter -Native -CommandName code-agent -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    code-agent completion powershell-inner | ForEach-Object {
        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
    }
}
"""
        safe_echo(script.strip())
    else:
        # Use Click's built-in completion for bash/zsh/fish
        env = {**dict(_SYS_ENVIRON), "_CODE_AGENT_COMPLETE": f"{shell}_source"}
        r = subprocess.run([sys.executable, "-m", "code_agent.cli"], capture_output=True, text=True, env=env)
        safe_echo(r.stdout)


# ═══════════════════════════════════════════════════════════════
# Session Management
# ═══════════════════════════════════════════════════════════════

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

@main.command()
def version():
    """Show version information."""
    try:
        from importlib.metadata import version as _v
        v = _v("code-agent")
    except Exception:
        v = "1.0.0"
    safe_echo(f"Orchestra v{v}")
    safe_echo("Autonomous AI software engineering assistant")


if __name__ == "__main__":
    main()
