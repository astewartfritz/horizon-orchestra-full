"""Horizon Orchestra — Unified CLI for Architectures A, C, and E.

Run directly::

    python -m orchestra.cli run "Build a REST API" --arch A
    python -m orchestra.cli run "Build a REST API" --arch A --model gemma-4-31b
    python -m orchestra.cli run "Research + build dashboard" --arch C --model gemma-4-26b-moe
    python -m orchestra.cli serve --port 3000                      # Arch E
    python -m orchestra.cli serve --model gemma-4-31b              # Arch E with Gemma 4
    python -m orchestra.cli docker                                 # Generate Docker files
    python -m orchestra.cli gemma4 info                            # Gemma 4 model info
    python -m orchestra.cli gemma4 modelfile --variant 31b         # Generate Ollama Modelfile
    python -m orchestra.cli gemma4 vllm --variant 31b              # Generate vLLM command
    python -m orchestra.cli memory search "What projects am I working on?"
    python -m orchestra.cli memory store "I prefer Python over JS" --category preference
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# ANSI colours (reuse from horizon.py)
C = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
    "red": "\033[31m", "magenta": "\033[35m", "blue": "\033[34m",
}


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(name)-24s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_run(args: argparse.Namespace) -> int:
    """Run a task through Architecture A or C."""
    from .agent_loop import FinalAnswerEvent, ToolCallEvent, ToolResultEvent, ErrorEvent

    arch = args.arch.upper()
    task = " ".join(args.task)
    if not task:
        print(f"{C['red']}No task provided.{C['reset']}")
        return 1

    print(f"\n{C['cyan']}{'=' * 52}{C['reset']}")
    print(f"{C['cyan']}{C['bold']} HORIZON ORCHESTRA — Architecture {arch}{C['reset']}")
    print(f"{C['dim']} Model: {args.model} | User: {args.user}{C['reset']}")
    print(f"{C['cyan']}{'=' * 52}{C['reset']}\n")
    print(f"{C['dim']}Task: {task}{C['reset']}\n")

    if arch == "C":
        from .arch_c import SwarmAgent, SwarmConfig
        config = SwarmConfig(
            coordinator_model=args.model,
            user_id=args.user,
            verbose=args.verbose,
        )
        agent = SwarmAgent(config=config)
    else:
        from .arch_a import MonolithicAgent, MonolithicConfig
        config = MonolithicConfig(
            model=args.model,
            user_id=args.user,
            verbose=args.verbose,
        )
        agent = MonolithicAgent(config=config)

    # Stream events
    async for event in agent.stream(task):
        if isinstance(event, ToolCallEvent):
            print(f"  {C['dim']}[{event.iteration}] 🔧 {event.tool_name}{C['reset']}")
        elif isinstance(event, ToolResultEvent):
            status = f"{C['green']}✓{C['reset']}" if event.success else f"{C['red']}✗{C['reset']}"
            print(f"  {C['dim']}      {status} {event.tool_name} ({event.duration:.1f}s){C['reset']}")
        elif isinstance(event, FinalAnswerEvent):
            print(f"\n{C['green']}{'─' * 52}{C['reset']}")
            print(event.content)
            print(f"\n{C['green']}{'─' * 52}{C['reset']}")
            print(f"{C['dim']}Iterations: {event.total_iterations} | "
                  f"Tool calls: {event.total_tool_calls}{C['reset']}")
        elif isinstance(event, ErrorEvent):
            print(f"  {C['red']}[ERROR] {event.message}{C['reset']}")

    print(f"\n{C['dim']}Stats: {json.dumps(agent.stats, indent=2)}{C['reset']}\n")
    return 0


async def cmd_serve(args: argparse.Namespace) -> int:
    """Start the Architecture E production server."""
    try:
        import uvicorn
    except ImportError:
        print(f"{C['red']}Install uvicorn: pip install uvicorn[standard]{C['reset']}")
        return 1

    from .arch_e import create_app, ProductionConfig

    config = ProductionConfig(
        architecture=args.arch.upper(),
        model=args.model,
        port=args.port,
        host=args.host,
        api_key=args.api_key or "",
        verbose=args.verbose,
    )
    app = create_app(config)

    print(f"\n{C['cyan']}{'=' * 52}{C['reset']}")
    print(f"{C['cyan']}{C['bold']} HORIZON ORCHESTRA — Architecture E Server{C['reset']}")
    print(f"{C['dim']} Backend: {config.architecture} | Model: {config.model}{C['reset']}")
    print(f"{C['dim']} Listening: http://{config.host}:{config.port}{C['reset']}")
    print(f"{C['cyan']}{'=' * 52}{C['reset']}\n")

    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    return 0


async def cmd_docker(args: argparse.Namespace) -> int:
    """Generate Docker Compose files for Architecture E."""
    from .arch_e import generate_docker_compose

    output_dir = args.output or "."
    files = generate_docker_compose(output_dir)
    print(f"\n{C['green']}Generated Architecture E infrastructure:{C['reset']}")
    for name, path in files.items():
        print(f"  {C['cyan']}{name}{C['reset']} → {path}")
    print(f"\n{C['dim']}Next steps:")
    print(f"  1. Copy .env.example to .env and fill in API keys")
    print(f"  2. docker compose up -d")
    print(f"  3. curl http://localhost:3000/health{C['reset']}\n")
    return 0


async def cmd_memory(args: argparse.Namespace) -> int:
    """Search or store memories."""
    from .memory import MemoryStore, MemoryManager

    store = MemoryStore()

    if args.memory_action == "search":
        query = " ".join(args.query)
        results = await store.search(args.user, query, limit=args.limit)
        if not results:
            print(f"{C['dim']}No memories found.{C['reset']}")
            return 0
        for r in results:
            score = f"{r.relevance_score:.2f}" if r.relevance_score else "—"
            print(f"  [{C['cyan']}{r.category}{C['reset']}] (rel: {score}) {r.content}")
        return 0

    elif args.memory_action == "store":
        content = " ".join(args.content)
        entry = await store.store(
            args.user, content, category=args.category, source="explicit",
        )
        print(f"{C['green']}Stored:{C['reset']} [{entry.category}] {content}")
        return 0

    elif args.memory_action == "list":
        entries = await store.list_all(args.user, limit=args.limit)
        if not entries:
            print(f"{C['dim']}No memories stored.{C['reset']}")
            return 0
        for e in entries:
            print(f"  {C['dim']}{e.id}{C['reset']} [{C['cyan']}{e.category}{C['reset']}] {e.content}")
        return 0

    return 1


async def cmd_gemma4(args: argparse.Namespace) -> int:
    """Gemma 4 model utilities."""
    if args.gemma4_action == "info":
        from .gemma4_provider import Gemma4Provider
        provider = Gemma4Provider()
        card = provider.get_model_card(args.model)
        print(f"\n{C['cyan']}{C['bold']}Gemma 4 Model Card: {card['name']}{C['reset']}")
        print(f"{C['dim']}{'─' * 52}{C['reset']}")
        print(f"  Model ID:      {card['model_id']}")
        print(f"  Provider:      {card['provider']}")
        print(f"  Architecture:  {card['architecture']}")
        print(f"  Parameters:    {card['parameters_b']}B")
        print(f"  Context:       {card['max_context']:,} tokens")
        print(f"  License:       {card['license']}")
        print(f"\n{C['cyan']}Capabilities:{C['reset']}")
        for cap, enabled in card['capabilities'].items():
            icon = f"{C['green']}✓{C['reset']}" if enabled else f"{C['dim']}✗{C['reset']}"
            print(f"  {icon} {cap}")
        if card.get('quantization'):
            print(f"\n{C['cyan']}Memory Requirements:{C['reset']}")
            for q, size in card['quantization'].items():
                print(f"  {q}: {size}")
        print(f"\n{C['cyan']}Cost:{C['reset']}")
        print(f"  Input:  ${card['cost']['input_per_1m']}/1M tokens")
        print(f"  Output: ${card['cost']['output_per_1m']}/1M tokens")
        print()
        return 0

    elif args.gemma4_action == "modelfile":
        from .gemma4_provider import generate_ollama_modelfile
        content = generate_ollama_modelfile(variant=args.variant)
        Path(args.output).write_text(content, encoding="utf-8")
        print(f"{C['green']}Generated:{C['reset']} {args.output}")
        print(f"{C['dim']}Deploy: ollama create gemma4-orchestra -f {args.output}{C['reset']}")
        return 0

    elif args.gemma4_action == "vllm":
        from .gemma4_provider import generate_vllm_command
        cmd = generate_vllm_command(
            variant=args.variant,
            tensor_parallel=args.gpus,
            port=args.port,
        )
        print(f"\n{C['cyan']}vLLM Serve Command:{C['reset']}\n")
        print(cmd)
        print()
        return 0

    print(f"{C['red']}Unknown gemma4 action. Use: info, modelfile, vllm{C['reset']}")
    return 1


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="horizon-orchestra",
        description="Horizon Orchestra — Agentic AI Harness",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    # -- run ----------------------------------------------------------------
    run_p = sub.add_parser("run", help="Run a task (Architecture A or C)")
    run_p.add_argument("task", nargs="+", help="The task to execute")
    run_p.add_argument("--arch", default="A", choices=["A", "C"],
                       help="Architecture: A (monolithic) or C (swarm)")
    run_p.add_argument("--model", default="kimi-k2.5", help="Model name")
    run_p.add_argument("--user", default="default", help="User ID for memory")

    # -- serve --------------------------------------------------------------
    serve_p = sub.add_parser("serve", help="Start Architecture E server")
    serve_p.add_argument("--arch", default="A", choices=["A", "C"],
                         help="Backend architecture")
    serve_p.add_argument("--model", default="kimi-k2.5")
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--port", type=int, default=3000)
    serve_p.add_argument("--api-key", default="")

    # -- docker -------------------------------------------------------------
    docker_p = sub.add_parser("docker", help="Generate Docker Compose files")
    docker_p.add_argument("--output", default=".", help="Output directory")

    # -- memory -------------------------------------------------------------
    mem_p = sub.add_parser("memory", help="Memory operations")
    mem_sub = mem_p.add_subparsers(dest="memory_action")

    search_p = mem_sub.add_parser("search", help="Search memories")
    search_p.add_argument("query", nargs="+")
    search_p.add_argument("--user", default="default")
    search_p.add_argument("--limit", type=int, default=10)

    store_p = mem_sub.add_parser("store", help="Store a memory")
    store_p.add_argument("content", nargs="+")
    store_p.add_argument("--user", default="default")
    store_p.add_argument("--category", default="fact", choices=[
        "identity", "preference", "project", "person", "tool", "workflow", "fact",
    ])

    list_p = mem_sub.add_parser("list", help="List all memories")
    list_p.add_argument("--user", default="default")
    list_p.add_argument("--limit", type=int, default=50)

    # -- gemma4 -------------------------------------------------------------
    g4_p = sub.add_parser("gemma4", help="Gemma 4 model tools")
    g4_sub = g4_p.add_subparsers(dest="gemma4_action")

    info_p = g4_sub.add_parser("info", help="Show Gemma 4 model capabilities")
    info_p.add_argument("--model", default="gemma-4-31b",
                        help="Gemma 4 variant to inspect")

    mf_p = g4_sub.add_parser("modelfile", help="Generate Ollama Modelfile")
    mf_p.add_argument("--variant", default="31b",
                      choices=["31b", "26b-a4b", "e4b", "e2b"])
    mf_p.add_argument("--output", default="Modelfile")

    vllm_p = g4_sub.add_parser("vllm", help="Generate vLLM serve command")
    vllm_p.add_argument("--variant", default="31b",
                        choices=["31b", "26b-a4b", "e4b", "e2b"])
    vllm_p.add_argument("--gpus", type=int, default=1)
    vllm_p.add_argument("--port", type=int, default=8000)

    # -- skills subcommand --------------------------------------------------
    skills_p = sub.add_parser("skills", help="Skill management")
    skills_sub = skills_p.add_subparsers(dest="skills_action")
    
    sk_list = skills_sub.add_parser("list", help="List all available skills")
    sk_list.add_argument("--builtin-only", action="store_true")
    sk_list.add_argument("--custom-only", action="store_true")
    
    sk_match = skills_sub.add_parser("match", help="Find skills matching a task")
    sk_match.add_argument("task", help="Task description to match against")
    sk_match.add_argument("--max", type=int, default=3)
    
    sk_show = skills_sub.add_parser("show", help="Show a skill's full instructions")
    sk_show.add_argument("name", help="Skill name")
    
    sk_create = skills_sub.add_parser("create", help="Create a skill from a description")
    sk_create.add_argument("name")
    sk_create.add_argument("description")
    sk_create.add_argument("--instructions", default="", help="Path to instructions file or inline text")

    # -- tasks subcommand ---------------------------------------------------
    tasks_p = sub.add_parser("tasks", help="Task management")
    tasks_sub = tasks_p.add_subparsers(dest="tasks_action")
    
    t_list = tasks_sub.add_parser("list", help="List tasks")
    t_list.add_argument("--status", default="", help="Filter by status")
    
    t_submit = tasks_sub.add_parser("submit", help="Submit a task")
    t_submit.add_argument("prompt", help="Task prompt")
    t_submit.add_argument("--name", default="")
    t_submit.add_argument("--model", default="")
    t_submit.add_argument("--cron", default="", help="Cron expression for scheduling")
    
    t_status = tasks_sub.add_parser("status", help="Get task status")
    t_status.add_argument("task_id")
    
    t_pause = tasks_sub.add_parser("pause", help="Pause a running task")
    t_pause.add_argument("task_id")
    
    t_resume = tasks_sub.add_parser("resume", help="Resume a paused task")
    t_resume.add_argument("task_id")
    
    t_cancel = tasks_sub.add_parser("cancel", help="Cancel a task")
    t_cancel.add_argument("task_id")

    # -- council subcommand -------------------------------------------------
    council_p = sub.add_parser("council", help="Model Council -- parallel multi-model deliberation")
    council_p.add_argument("prompt", help="Prompt to deliberate on")
    council_p.add_argument("--models", default="", help="Comma-separated model names")
    council_p.add_argument("--orchestrator", default="", help="Model to synthesize results")

    # -- models subcommand --------------------------------------------------
    models_p = sub.add_parser("models", help="List and query available models")
    models_sub = models_p.add_subparsers(dest="models_action")
    
    m_list = models_sub.add_parser("list", help="List all registered models")
    m_list.add_argument("--available-only", action="store_true", help="Only show models with API keys configured")
    m_list.add_argument("--json", dest="json_out", action="store_true")
    
    m_info = models_sub.add_parser("info", help="Get model capabilities")
    m_info.add_argument("model_name")

    # -- connectors subcommand ----------------------------------------------
    conn_p = sub.add_parser("connectors", help="List available connectors")
    conn_p.add_argument("--status", action="store_true", help="Show connection status")

    return parser


# ---------------------------------------------------------------------------
# New command handlers
# ---------------------------------------------------------------------------

async def cmd_skills(args: argparse.Namespace) -> int:
    from .skills import SkillRegistry
    registry = SkillRegistry.default()
    action = getattr(args, "skills_action", None)
    
    if action == "list" or not action:
        skills = registry.all_skills
        if getattr(args, "builtin_only", False):
            skills = registry.builtin_skills
        elif getattr(args, "custom_only", False):
            skills = registry.custom_skills
        print(f"\n{'─'*60}")
        print(f"  Orchestra Skills  ({len(skills)} total)")
        print(f"{'─'*60}")
        for s in skills:
            tag = "[builtin]" if s.is_builtin else "[custom]"
            chains = f" -> {', '.join(s.chains_to)}" if s.chains_to else ""
            print(f"  {s.name:<30} {tag}{chains}")
            print(f"    {s.description[:70]}")
        return 0
    
    elif action == "match":
        matches = registry.match(args.task, max_skills=args.max)
        print(f"\nSkills matching: '{args.task}'")
        print(f"{'─'*60}")
        for m in matches:
            print(f"  {m.skill.name:<30} score={m.score:.2f}")
            print(f"    {m.trigger_reason}")
        return 0
    
    elif action == "show":
        skill = registry.get(args.name)
        if not skill:
            print(f"Skill '{args.name}' not found.")
            return 1
        print(f"\n## {skill.name} (v{skill.version})")
        print(f"\n**Description:** {skill.description}")
        if skill.tools_required:
            print(f"**Tools:** {', '.join(skill.tools_required)}")
        if skill.models_preferred:
            print(f"**Models:** {', '.join(skill.models_preferred)}")
        if skill.chains_to:
            print(f"**Chains to:** {', '.join(skill.chains_to)}")
        print(f"\n{skill.instructions}")
        return 0
    
    elif action == "create":
        skill = registry.create_skill_from_description(
            name=args.name,
            description=args.description,
            instructions=args.instructions or f"# {args.name}\n\n{args.description}",
        )
        path = registry.save_skill(skill)
        print(f"Skill '{skill.name}' created at {path}")
        return 0
    
    return 0


async def cmd_tasks(args: argparse.Namespace) -> int:
    import json as _json
    from .tasks import TaskManager, TaskSpec, Schedule, TaskStatus
    manager = TaskManager()
    action = getattr(args, "tasks_action", None)
    
    if action == "list" or not action:
        status_filter = TaskStatus(args.status) if getattr(args, "status", "") else None
        tasks = await manager.list_tasks(status=status_filter)
        print(f"\n{'─'*70}")
        print(f"  Tasks  ({len(tasks)} found)")
        print(f"{'─'*70}")
        for t in tasks:
            dur = f"{t.duration_seconds:.0f}s" if t.duration_seconds else ""
            print(f"  {t.id[:12]:<14} {t.status.value:<20} {t.name[:30]:<32} {dur}")
        return 0
    
    elif action == "submit":
        schedule = Schedule(cron=args.cron) if getattr(args, "cron", "") else None
        spec = TaskSpec(
            name=getattr(args, "name", "") or args.prompt[:40],
            prompt=args.prompt,
            model=getattr(args, "model", "") or "claude-opus-4.6-openrouter",
            schedule=schedule,
        )
        task_id = await manager.submit(spec)
        print(f"Task submitted: {task_id}")
        return 0
    
    elif action == "status":
        task = await manager.get_status(args.task_id)
        if not task:
            print(f"Task {args.task_id} not found.")
            return 1
        print(_json.dumps(task.to_dict(), indent=2, default=str))
        return 0
    
    elif action in ("pause", "resume", "cancel"):
        fn = getattr(manager, action)
        ok = await fn(args.task_id)
        print(f"Task {args.task_id}: {action}d" if ok else f"Failed to {action} {args.task_id}")
        return 0 if ok else 1
    
    return 0


async def cmd_council(args: argparse.Namespace) -> int:
    from .router import ModelRouter
    from .model_council import ModelCouncil
    router = ModelRouter()
    council = ModelCouncil(router=router)
    models = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else None
    print(f"\nModel Council deliberating...\nModels: {models or 'default'}")
    print(f"{'─'*60}")
    result = await council.deliberate(
        prompt=args.prompt,
        models=models,
        orchestrator=getattr(args, "orchestrator", "") or "",
    )
    print(result.to_markdown())
    print(f"\nAgreement score: {result.agreement_score:.2f}")
    if result.failed_models:
        print(f"Failed models: {result.failed_models}")
    return 0


async def cmd_models(args: argparse.Namespace) -> int:
    import json as _json
    from .router import ModelRouter
    router = ModelRouter()
    action = getattr(args, "models_action", None)
    
    if action == "list" or not action:
        models = router.list_models()
        if getattr(args, "available_only", False):
            models = [m for m in models if m["available"]]
        if getattr(args, "json_out", False):
            print(_json.dumps(models, indent=2))
            return 0
        print(f"\n{'─'*80}")
        print(f"  Orchestra Models  ({len(models)} registered)")
        print(f"{'─'*80}")
        for m in models:
            avail = "v" if m["available"] else "x"
            ctx = f"{m['max_context']//1000}K"
            cost = f"${m['cost_input']}/{m['cost_output']}"
            think = "[T]" if m.get("supports_thinking") else ""
            vis = "[V]" if m.get("supports_vision") else ""
            print(f"  {avail} {m['name']:<35} {ctx:<6} {cost:<12} {think}{vis}")
            print(f"      {', '.join(m['strengths'][:4])}")
        return 0
    
    elif action == "info":
        try:
            cfg = router.get_config(args.model_name)
            print(f"\n## {args.model_name}")
            for k, v in cfg.__dict__.items():
                print(f"  {k}: {v}")
        except KeyError:
            print(f"Model '{args.model_name}' not found.")
            return 1
        return 0
    
    return 0


async def cmd_connectors(args: argparse.Namespace) -> int:
    from .arch_e import ConnectorRegistry
    reg = ConnectorRegistry.default()
    conns = reg.list_connectors()
    print(f"\n{'─'*60}")
    print(f"  Orchestra Connectors  ({len(conns)} registered)")
    print(f"{'─'*60}")
    for c in conns:
        status = "v connected" if c["connected"] else "x not connected"
        tools_str = ", ".join(c["tools"][:4])
        print(f"  {c['name']:<20} {status:<16}  Tools: {tools_str}")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _setup_logging(getattr(args, "verbose", False))

    if not args.command:
        parser.print_help()
        return 0

    dispatch = {
        "run": cmd_run,
        "serve": cmd_serve,
        "docker": cmd_docker,
        "memory": cmd_memory,
        "gemma4": cmd_gemma4,
        "skills": cmd_skills,
        "tasks": cmd_tasks,
        "council": cmd_council,
        "models": cmd_models,
        "connectors": cmd_connectors,
    }
    handler = dispatch.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    return asyncio.run(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
