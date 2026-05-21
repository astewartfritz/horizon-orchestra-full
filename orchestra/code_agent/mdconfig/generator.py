from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_claude_md(
    project_name: str = "",
    description: str = "",
    architecture: str = "",
    conventions: list[str] | None = None,
    commands: list[dict[str, str]] | None = None,
    env: dict[str, str] | None = None,
    tests: str = "",
    lint: str = "",
) -> str:
    """Generate a structured CLAUDE.md config file."""
    sections = [
        _fm("project", {
            "name": project_name or Path.cwd().name,
            "description": description or "AI coding agent project",
            "language": "python",
            "version": "3.13+",
        }),
    ]

    if architecture:
        sections.append(f"## Architecture\n\n{architecture}\n")

    sections.append("## Commands\n")
    if commands:
        for cmd in commands:
            name = cmd.get("name", "")
            run = cmd.get("run", "")
            desc = cmd.get("description", "")
            sections.append(f"- `{name}`: {desc}\n  ```\n  {run}\n  ```\n")

    sections.append(f"## Test\n\n- Run: `{tests or 'python -m pytest'}`\n")
    sections.append(f"## Lint\n\n- Run: `{lint or 'python -m ruff check .'}`\n")

    if conventions:
        sections.append("## Conventions\n")
        for c in conventions:
            sections.append(f"- {c}\n")

    if env:
        sections.append("## Environment\n")
        for k, v in env.items():
            sections.append(f"- `{k}`: {v}\n")

    # Tool permissions
    sections.append("""## Tool Permissions

- read: allowed
- write: allowed
- edit: allowed
- glob: allowed
- grep: allowed
- bash: confirm before destructive commands
- webfetch: allowed
- websearch: allowed
- git: allowed
""")

    return "\n".join(sections)


def generate_agents_md(
    role: str = "coding agent",
    goals: list[str] | None = None,
    constraints: list[str] | None = None,
    preferences: dict[str, str] | None = None,
    tools: list[str] | None = None,
) -> str:
    """Generate a structured AGENTS.md config file."""
    sections = [
        _fm("agent", {
            "role": role,
            "version": "1.0",
        }),
    ]

    if goals:
        sections.append("## Goals\n")
        for g in goals:
            sections.append(f"- {g}\n")

    if constraints:
        sections.append("## Constraints\n")
        for c in constraints:
            sections.append(f"- {c}\n")

    if preferences:
        sections.append("## Preferences\n")
        for k, v in preferences.items():
            sections.append(f"- {k}: {v}\n")

    if tools:
        sections.append("## Tool Access\n")
        for t in tools:
            sections.append(f"- {t}\n")

    return "\n".join(sections)


def generate_prompt_md(
    name: str,
    description: str,
    system_prompt: str,
    variables: list[str] | None = None,
    tags: list[str] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    examples: list[dict[str, str]] | None = None,
) -> str:
    """Generate a Markdown prompt template file."""
    md = _fm("prompt", {
        "name": name,
        "description": description,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "variables": variables or [],
        "tags": tags or [],
    })

    md += f"\n## System\n\n{system_prompt}\n"

    if examples:
        md += "\n## Examples\n"
        for i, ex in enumerate(examples, 1):
            inp = ex.get("input", "")
            out = ex.get("output", "")
            md += f"\n### Example {i}\n"
            if inp:
                md += f"\n**Input:**\n```\n{inp}\n```\n"
            if out:
                md += f"\n**Output:**\n```\n{out}\n```\n"

    return md


def generate_tool_md(
    name: str,
    description: str,
    parameters: list[dict[str, str]],
    examples: list[dict[str, str]] | None = None,
) -> str:
    """Generate a Markdown tool definition file."""
    md = _fm("tool", {
        "name": name,
        "description": description,
    })

    md += "\n## Parameters\n\n"
    md += "| Name | Type | Required | Description |\n"
    md += "|------|------|----------|-------------|\n"
    for p in parameters:
        req = "Yes" if p.get("required", False) else "No"
        md += f"| {p['name']} | {p.get('type', 'string')} | {req} | {p.get('description', '')} |\n"

    if examples:
        md += "\n## Examples\n"
        for ex in examples:
            inp = ex.get("input", "")
            out = ex.get("output", "")
            md += f"\n```\n# {ex.get('name', 'Example')}\n{inp}\n# -> {out}\n```\n"

    return md


def generate_project_board_md(
    tasks: list[dict[str, str]],
    name: str = "Project Board",
) -> str:
    """Generate a Markdown project board with todo/done tracking."""
    md = f"# {name}\n\n"

    columns = {"todo": "To Do", "in_progress": "In Progress", "done": "Done", "blocked": "Blocked"}
    for col_key, col_label in columns.items():
        items = [t for t in tasks if t.get("status", "todo") == col_key]
        if not items:
            continue
        md += f"## {col_label}\n\n"
        for t in items:
            md += f"- [{'x' if col_key == 'done' else ' '}] **{t.get('title', '')}**"
            if t.get("description"):
                md += f" — {t['description'][:120]}"
            md += "\n"
        md += "\n"

    return md


def generate_workflow_md(
    name: str,
    description: str,
    steps: list[dict[str, str]],
    triggers: list[str] | None = None,
) -> str:
    """Generate a Markdown workflow definition."""
    md = _fm("workflow", {
        "name": name,
        "description": description,
        "triggers": triggers or [],
    })

    md += "\n## Steps\n\n"
    for i, step in enumerate(steps, 1):
        md += f"### Step {i}: {step.get('name', '')}\n\n"
        md += f"{step.get('description', '')}\n\n"
        tool = step.get("tool", "")
        if tool:
            md += f"- Tool: `{tool}`\n"
        args = step.get("args", "")
        if args:
            md += f"- Args: `{args}`\n"
        md += "\n"

    return md


def _fm(key: str, data: dict[str, Any]) -> str:
    """Generate YAML frontmatter block."""
    lines = ["---"]
    lines.append(f"{key}:")
    for k, v in data.items():
        if isinstance(v, list):
            if v:
                lines.append(f"  {k}:")
                for item in v:
                    lines.append(f"    - {item}")
            else:
                lines.append(f"  {k}: []")
        elif isinstance(v, bool):
            lines.append(f"  {k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"  {k}: {v}")
        else:
            lines.append(f"  {k}: \"{v}\"")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def write_config(path: str | Path, content: str) -> Path:
    """Write a generated config to file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p
