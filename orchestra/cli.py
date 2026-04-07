"""Horizon Orchestra — Unified CLI for Architectures A, C, and E.

Run directly::

    python -m orchestra.cli run "Build a REST API" --arch A
    python -m orchestra.cli run "Research + build dashboard" --arch C
    python -m orchestra.cli serve --port 3000                      # Arch E
    python -m orchestra.cli docker                                 # Generate Docker files
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

    return parser


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
    }
    handler = dispatch.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    return asyncio.run(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
