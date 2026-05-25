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
    serve_p = sub.add_parser("serve", help="Start the Orchestra server (API + GUI)")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--workers", type=int, default=1)
    serve_p.add_argument("--no-open", action="store_true", dest="no_open",
                         help="Don't open the browser automatically")

    # -- gui --
    gui_p = sub.add_parser("gui", help="Open the Orchestra dashboard in a browser")
    gui_p.add_argument("--port", type=int, default=5757, help="Local port (default: 5757)")
    gui_p.add_argument("--no-open", action="store_true", dest="no_open",
                       help="Start server but don't open browser automatically")

    # -- status --
    sub.add_parser("status", help="Show system status")

    # -- validate --
    val_p = sub.add_parser("validate", help="Validate request JSON against schema")
    val_p.add_argument("schema", help="Schema name (e.g., RunRequest)")
    val_p.add_argument("json_file", help="Path to JSON file")

    # -- science --
    sci_p = sub.add_parser("science", help="Literature-to-experiment pipeline")
    sci_p.add_argument("question", help="Research question to investigate")
    sci_p.add_argument("--model", default="kimi-k2.5", help="LLM model (default: kimi-k2.5)")
    sci_p.add_argument("--max-papers", type=int, default=15, dest="max_papers",
                       help="Max papers to retrieve (default: 15)")
    sci_p.add_argument("--output", "-o", default=None,
                       help="Write markdown report to this file path")

    # -- miles --
    miles_p = sub.add_parser(
        "miles",
        help="M.I.L.E.S — Machine Intelligence Learning and Execution System",
    )
    miles_p.add_argument("--user", default="default", help="User ID (default: default)")
    miles_p.add_argument("--model", default="kimi-k2.5", help="LLM model (default: kimi-k2.5)")
    miles_p.add_argument("--timezone", default="America/Chicago", help="Timezone (default: America/Chicago)")
    miles_sub = miles_p.add_subparsers(dest="miles_command")

    miles_chat_p = miles_sub.add_parser("chat", help="Send a message to MILES")
    miles_chat_p.add_argument("message", help="Message to send")

    miles_sub.add_parser("brief", help="Generate a morning briefing")
    miles_sub.add_parser("summarise", help="Generate an end-of-day summary")
    miles_sub.add_parser("remind", help="Show active smart reminders")
    miles_sub.add_parser("suggest", help="Show proactive action suggestions")
    miles_sub.add_parser("repl", help="Interactive REPL session with MILES")

    # -- miles channels --
    channels_p = miles_sub.add_parser("channels", help="Manage multi-channel ingestion")
    channels_sub = channels_p.add_subparsers(dest="channels_command")

    ch_start = channels_sub.add_parser("start", help="Start polling all configured channels")
    ch_start.add_argument("--slack", action="store_true", help="Enable Slack")
    ch_start.add_argument("--telegram", action="store_true", help="Enable Telegram")
    ch_start.add_argument("--gmail", action="store_true", help="Enable Gmail")
    ch_start.add_argument("--poll-interval", type=float, default=10.0,
                          dest="poll_interval", help="Polling interval in seconds (default: 10)")

    channels_sub.add_parser("status", help="Show channel hub status")

    optin_p = channels_sub.add_parser("opt-in", help="Opt a user into MILES")
    optin_p.add_argument("channel", help="Channel name (slack, telegram, gmail, …)")
    optin_p.add_argument("sender_id", help="Sender ID on that channel")

    optout_p = channels_sub.add_parser("opt-out", help="Opt a user out of MILES")
    optout_p.add_argument("channel", help="Channel name")
    optout_p.add_argument("sender_id", help="Sender ID")

    args = parser.parse_args(argv)

    if args.version:
        from orchestra import __version__
        print(f"horizon-orchestra {__version__}")
        return

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "science":
        _cmd_science(args)
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "gui":
        _cmd_gui(args)
    elif args.command == "status":
        _cmd_status()
    elif args.command == "validate":
        _cmd_validate(args)
    elif args.command == "miles":
        _cmd_miles(args)
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


def _cmd_science(args: Any) -> None:
    """Run the literature-to-experiment pipeline."""
    try:
        from orchestra.code_agent.science import LiteratureToExperimentPipeline
    except ImportError as exc:
        print(f"Science pipeline unavailable: {exc}", file=sys.stderr)
        print("Make sure httpx and openai are installed: pip install httpx openai", file=sys.stderr)
        sys.exit(1)

    pipeline = LiteratureToExperimentPipeline(
        model=args.model,
        max_papers=args.max_papers,
    )

    print(f"\nOrchestra Science Pipeline")
    print(f"Question : {args.question}")
    print(f"Model    : {args.model}")
    print(f"Papers   : up to {args.max_papers}")
    print()

    try:
        report = asyncio.run(pipeline.run(args.question, verbose=True))
    except Exception as exc:
        print(f"\nPipeline error: {exc}", file=sys.stderr)
        sys.exit(1)

    md = report.to_markdown()

    if args.output:
        import pathlib
        pathlib.Path(args.output).write_text(md, encoding="utf-8")
        print(f"\nReport written to: {args.output}")
    else:
        print()
        print(md)


def _cmd_serve(args: Any) -> None:
    """Start the Orchestra server (API + GUI) and open the browser."""
    import pathlib
    import threading
    import webbrowser

    # Load .env from project root (no-op if already set or file missing)
    try:
        import dotenv
        dotenv.load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env", override=False)
    except ImportError:
        pass

    try:
        import uvicorn
        from orchestra.api.server import create_production_app, APIConfig
        config = APIConfig(host=args.host, port=args.port)
        app = create_production_app(config)

        url = f"http://localhost:{args.port}"
        print(f"\n  Orchestra  →  {url}")
        print(f"  M.I.L.E.S  →  {url}/#/miles")
        print(f"  API docs   →  {url}/docs")
        print("\n  Press Ctrl+C to stop.\n")

        if not getattr(args, "no_open", False):
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()

        uvicorn.run(app, host=args.host, port=args.port, workers=args.workers,
                    log_level="warning")
    except ImportError:
        print("FastAPI/Uvicorn required: pip install fastapi uvicorn", file=sys.stderr)
        sys.exit(1)


def _cmd_gui(args: Any) -> None:
    """Serve the Orchestra dashboard on a local port and open the browser."""
    import pathlib
    import threading
    import webbrowser
    import http.server

    # Locate gui/orchestra-gui relative to this file
    here = pathlib.Path(__file__).resolve().parent.parent
    gui_dir = here / "gui" / "orchestra-gui"

    if not gui_dir.is_dir():
        print(f"GUI directory not found: {gui_dir}", file=sys.stderr)
        print("Make sure you're running from the Orchestra_Full root.", file=sys.stderr)
        sys.exit(1)

    port = args.port
    url = f"http://localhost:{port}"

    # Use Python's built-in HTTP server — zero extra dependencies
    handler = http.server.SimpleHTTPRequestHandler

    class _Handler(http.server.SimpleHTTPRequestHandler):
        """Serve from gui_dir; silence request logs."""
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(gui_dir), **kw)

        def log_message(self, fmt, *a):
            pass  # quiet

    try:
        server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        print(f"Port {port} is in use. Try: horizon gui --port 5758", file=sys.stderr)
        sys.exit(1)

    print(f"Orchestra GUI → {url}")
    print("Press Ctrl+C to stop.\n")

    if not args.no_open:
        # Open after a short delay so the server is ready
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGUI server stopped.")
        server.shutdown()


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


def _build_miles(args: Any) -> Any:
    """Construct a MILES instance from CLI args."""
    from orchestra.router import ModelRouter
    from orchestra.memory import MemoryManager, MemoryStore
    from orchestra.miles.core import MILES, MILESConfig

    router = ModelRouter()
    store = MemoryStore()
    memory = MemoryManager(store=store, user_id=args.user)
    config = MILESConfig(
        user_id=args.user,
        preferred_model=args.model,
        timezone=args.timezone,
    )
    return MILES(router=router, memory=memory, config=config)


def _cmd_miles(args: Any) -> None:
    """Dispatch MILES subcommands."""
    cmd = getattr(args, "miles_command", None)
    if cmd == "chat":
        _miles_chat(args)
    elif cmd == "brief":
        _miles_brief(args)
    elif cmd == "summarise":
        _miles_summarise(args)
    elif cmd == "remind":
        _miles_remind(args)
    elif cmd == "suggest":
        _miles_suggest(args)
    elif cmd == "repl":
        _miles_repl(args)
    elif cmd == "channels":
        _cmd_miles_channels(args)
    else:
        print(
            "M.I.L.E.S — Machine Intelligence Learning and Execution System\n"
            "\nSubcommands:\n"
            "  chat <message>   Send a message and get a response\n"
            "  brief            Morning briefing (calendar, email, tasks)\n"
            "  summarise        End-of-day summary\n"
            "  remind           Show active smart reminders\n"
            "  suggest          Proactive action suggestions\n"
            "  repl             Interactive session\n"
            "  channels         Manage multi-channel ingestion (Slack, Telegram, Gmail, …)\n"
            "\nOptions: --user, --model, --timezone"
        )


def _miles_chat(args: Any) -> None:
    """Send a single message to MILES and print the response."""
    try:
        miles = _build_miles(args)
        response = asyncio.run(miles.run(args.message))
        print(f"\nM.I.L.E.S: {response}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _miles_brief(args: Any) -> None:
    """Print a morning briefing."""
    try:
        miles = _build_miles(args)
        briefing = asyncio.run(miles.brief())
        print("\n── M.I.L.E.S Morning Briefing ─────────────────────────")
        print(briefing.summary)
        if briefing.suggestions:
            print("\nFocus areas:")
            for s in briefing.suggestions:
                print(f"  • {s}")
        if briefing.weather:
            print(f"\nWeather: {briefing.weather}")
        print("────────────────────────────────────────────────────────")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _miles_summarise(args: Any) -> None:
    """Print an end-of-day summary."""
    try:
        miles = _build_miles(args)
        summary = asyncio.run(miles.summarise())
        print("\n── M.I.L.E.S End-of-Day Summary ───────────────────────")
        print(summary.summary_text)
        if summary.accomplishments:
            print("\nAccomplishments:")
            for a in summary.accomplishments:
                print(f"  ✓ {a}")
        if summary.unfinished:
            print("\nUnfinished:")
            for u in summary.unfinished:
                print(f"  • {u}")
        if summary.tomorrow_priorities:
            print("\nTomorrow's priorities:")
            for i, p in enumerate(summary.tomorrow_priorities, 1):
                print(f"  {i}. {p}")
        print("────────────────────────────────────────────────────────")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _miles_remind(args: Any) -> None:
    """Print active smart reminders."""
    try:
        miles = _build_miles(args)
        reminders = asyncio.run(miles.remind())
        if not reminders:
            print("M.I.L.E.S: No active reminders.")
            return
        print(f"\n── M.I.L.E.S Reminders ({len(reminders)}) ──────────────────")
        for r in reminders:
            urgency_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(r.urgency, "•")
            print(f"\n{urgency_icon} [{r.urgency.upper()}] {r.title}")
            print(f"   {r.body}")
            print(f"   Action: {r.action}  |  Due: {r.due_at}")
        print("────────────────────────────────────────────────────────")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _miles_suggest(args: Any) -> None:
    """Print proactive suggestions."""
    try:
        miles = _build_miles(args)
        suggestions = asyncio.run(miles.suggest())
        if not suggestions:
            print("M.I.L.E.S: No suggestions right now.")
            return
        print("\n── M.I.L.E.S Suggestions ──────────────────────────────")
        for s in suggestions:
            print(f"\n  [{s.priority.upper()}] {s.action}")
            print(f"  Why: {s.reasoning}")
        print("────────────────────────────────────────────────────────")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _miles_repl(args: Any) -> None:
    """Interactive REPL session with MILES."""
    try:
        miles = _build_miles(args)
    except Exception as exc:
        print(f"Failed to start M.I.L.E.S: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"M.I.L.E.S — {miles.full_name}")
    print(f"User: {args.user}  |  Model: {args.model}  |  Type 'exit' to quit.\n")

    history: list[dict[str, str]] = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nM.I.L.E.S: Goodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye"):
            print("M.I.L.E.S: Goodbye.")
            break

        # Built-in shortcut commands
        if user_input.lower() == "/brief":
            _miles_brief(args)
            continue
        if user_input.lower() == "/remind":
            _miles_remind(args)
            continue
        if user_input.lower() == "/suggest":
            _miles_suggest(args)
            continue
        if user_input.lower() == "/summarise":
            _miles_summarise(args)
            continue

        try:
            response = asyncio.run(miles.run(user_input, context=history))
            print(f"M.I.L.E.S: {response}\n")
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": response})
            # Keep rolling window of last 20 turns
            if len(history) > 20:
                history = history[-20:]
        except Exception as exc:
            print(f"Error: {exc}\n", file=sys.stderr)


def _cmd_miles_channels(args: Any) -> None:
    """Dispatch miles channels subcommands."""
    cmd = getattr(args, "channels_command", None)

    if cmd == "opt-in":
        from orchestra.miles.channels.base import ConsentRegistry
        reg = ConsentRegistry()
        reg.opt_in(args.channel, args.sender_id)
        print(f"Opted in: {args.channel}/{args.sender_id}")
        return

    if cmd == "opt-out":
        from orchestra.miles.channels.base import ConsentRegistry
        reg = ConsentRegistry()
        reg.opt_out(args.channel, args.sender_id)
        print(f"Opted out: {args.channel}/{args.sender_id}")
        return

    if cmd == "status":
        from orchestra.miles.channels.base import ConsentRegistry
        import sqlite3
        from pathlib import Path
        db = Path.home() / ".horizon" / "miles_consent.db"
        if not db.exists():
            print("No consent database found — no channels have been configured yet.")
            return
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT channel, sender_id, opted_in FROM consent").fetchall()
        conn.close()
        if not rows:
            print("Consent registry is empty.")
            return
        print(f"{'Channel':<14} {'Sender':<30} Status")
        print("-" * 56)
        for channel, sender_id, opted_in in rows:
            status = "opted-in" if opted_in else "opted-out"
            print(f"{channel:<14} {sender_id:<30} {status}")
        return

    if cmd == "start":
        try:
            from orchestra.miles.channels.base import ConsentRegistry
            from orchestra.miles.channels.slack import SlackChannelAdapter
            from orchestra.miles.channels.telegram import TelegramChannelAdapter
            from orchestra.miles.channels.gmail import GmailChannelAdapter

            miles = _build_miles(args)
            hub = miles.build_channel_hub(poll_interval=args.poll_interval)

            adapters_registered = 0
            if args.slack or os.environ.get("SLACK_BOT_TOKEN"):
                hub.register(SlackChannelAdapter())
                print("  Slack: registered")
                adapters_registered += 1
            if args.telegram or os.environ.get("TELEGRAM_BOT_TOKEN"):
                hub.register(TelegramChannelAdapter())
                print("  Telegram: registered")
                adapters_registered += 1
            if args.gmail or os.environ.get("GMAIL_CREDENTIALS_PATH"):
                hub.register(GmailChannelAdapter())
                print("  Gmail: registered")
                adapters_registered += 1

            if adapters_registered == 0:
                print(
                    "No channels configured. Set env vars or pass --slack / --telegram / --gmail.\n"
                    "Required env vars:\n"
                    "  Slack:    SLACK_BOT_TOKEN\n"
                    "  Telegram: TELEGRAM_BOT_TOKEN\n"
                    "  Gmail:    GMAIL_CREDENTIALS_PATH"
                )
                return

            print(f"\nStarting M.I.L.E.S channel hub ({adapters_registered} adapter(s))…")
            print("Press Ctrl+C to stop.\n")

            async def _run() -> None:
                await hub.start()
                try:
                    while True:
                        await asyncio.sleep(1)
                except asyncio.CancelledError:
                    pass
                finally:
                    await hub.stop()

            asyncio.run(_run())

        except KeyboardInterrupt:
            print("\nM.I.L.E.S channel hub stopped.")
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # Default: show help
    print(
        "M.I.L.E.S channel management\n\n"
        "Subcommands:\n"
        "  start [--slack] [--telegram] [--gmail]  Start polling channels\n"
        "  status                                   Show opted-in users\n"
        "  opt-in  <channel> <sender_id>            Opt a user in\n"
        "  opt-out <channel> <sender_id>            Opt a user out\n"
        "\nChannel env vars:\n"
        "  Slack:    SLACK_BOT_TOKEN, SLACK_APP_TOKEN\n"
        "  Telegram: TELEGRAM_BOT_TOKEN\n"
        "  Gmail:    GMAIL_CREDENTIALS_PATH\n"
        "  WhatsApp: WHATSAPP_TOKEN, WHATSAPP_PHONE_ID\n"
        "  Instagram: INSTAGRAM_PAGE_TOKEN, INSTAGRAM_PAGE_ID\n"
    )


if __name__ == "__main__":
    main()
