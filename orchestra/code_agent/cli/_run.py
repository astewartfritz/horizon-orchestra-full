"""CLI commands — run."""
from __future__ import annotations

import click

from ._core import main


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


