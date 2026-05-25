"""CLI commands — adhoc."""
from __future__ import annotations

import click

from ._core import main


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


