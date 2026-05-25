"""CLI commands — reason."""
from __future__ import annotations

import click

from ._core import main


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


