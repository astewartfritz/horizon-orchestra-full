"""Horizon Orchestra CLI entry point.

Usage::

    # Via pip install
    horizon run "Build a REST API"
    horizon serve --port 8000
    horizon status

    # Via python -m
    python -m orchestra run "Build a REST API"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

__all__ = ["main"]


def main(argv: list[str] | None = None) -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="horizon",
        description="Horizon Orchestra — Agentic AI Harness",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    sub = parser.add_subparsers(dest="command")

    # -- run --
    run_p = sub.add_parser("run", help="Execute a task")
    run_p.add_argument("task", help="Task description")
    run_p.add_argument("--arch", default="A", choices=["A", "B", "C", "D", "E"],
                       help="Architecture (default: A)")
    run_p.add_argument("--model", default="kimi-k2.5", help="Model to use")
    run_p.add_argument("--user", default="default", help="User ID")

    # -- serve --
    serve_p = sub.add_parser("serve", help="Start the API server")
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--workers", type=int, default=1)

    # -- status --
    sub.add_parser("status", help="Show system status")

    # -- validate --
    val_p = sub.add_parser("validate", help="Validate request JSON against schema")
    val_p.add_argument("schema", help="Schema name (e.g., RunRequest)")
    val_p.add_argument("json_file", help="Path to JSON file")

    args = parser.parse_args(argv)

    if args.version:
        from orchestra import __version__
        print(f"horizon-orchestra {__version__}")
        return

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "status":
        _cmd_status()
    elif args.command == "validate":
        _cmd_validate(args)
    else:
        parser.print_help()


def _cmd_run(args: Any) -> None:
    """Execute a task through an architecture."""
    print(f"Running on Architecture {args.arch} with {args.model}...")
    print(f"Task: {args.task}")
    try:
        from orchestra.arch_a import MonolithicAgent, MonolithicConfig
        from orchestra.arch_b import RAGPipeline, RAGConfig
        from orchestra.arch_c import SwarmAgent, SwarmConfig
        from orchestra.arch_d import MCPToolHub, MCPHubConfig

        if args.arch == "A":
            agent = MonolithicAgent(config=MonolithicConfig(model=args.model, user_id=args.user))
        elif args.arch == "B":
            agent = RAGPipeline(config=RAGConfig(synthesis_model=args.model, user_id=args.user))
        elif args.arch == "C":
            agent = SwarmAgent(config=SwarmConfig(coordinator_model=args.model, user_id=args.user))
        elif args.arch == "D":
            agent = MCPToolHub(config=MCPHubConfig(model=args.model, user_id=args.user))
        else:
            from orchestra.arch_e import ProductionOrchestrator, ProductionConfig
            agent = ProductionOrchestrator(config=ProductionConfig(architecture=args.arch, model=args.model, user_id=args.user))

        result = asyncio.run(agent.run(args.task))
        print(f"\nResult:\n{result}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _cmd_serve(args: Any) -> None:
    """Start the API server."""
    try:
        import uvicorn
        from orchestra.api.server import create_production_app, APIConfig
        config = APIConfig(host=args.host, port=args.port)
        app = create_production_app(config)
        uvicorn.run(app, host=args.host, port=args.port, workers=args.workers)
    except ImportError:
        print("FastAPI/Uvicorn required: pip install fastapi uvicorn", file=sys.stderr)
        sys.exit(1)


def _cmd_status() -> None:
    """Show system status."""
    import importlib

    print("Horizon Orchestra — System Status")
    print("=" * 40)

    count = 0
    failures = 0
    for root, dirs, files in os.walk("orchestra"):
        for f in files:
            if f.endswith(".py") and "__pycache__" not in root:
                mod = os.path.join(root, f).replace("/", ".").replace(".py", "")
                try:
                    importlib.import_module(mod)
                    count += 1
                except Exception:
                    failures += 1

    print(f"Modules:  {count} loaded, {failures} failed")

    from orchestra import __version__
    print(f"Version:  {__version__}")

    # Check key dependencies
    deps = ["openai", "httpx", "fastapi", "pydantic", "boto3", "playwright"]
    for dep in deps:
        try:
            importlib.import_module(dep)
            print(f"  {dep}: installed")
        except ImportError:
            print(f"  {dep}: NOT installed")


def _cmd_validate(args: Any) -> None:
    """Validate a JSON file against an API schema."""
    from orchestra.api.schemas import validate_request

    with open(args.json_file) as f:
        body = json.load(f)

    errors = validate_request(body, args.schema)
    if errors:
        print(f"Validation FAILED ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("Validation OK")


if __name__ == "__main__":
    main()
