from __future__ import annotations

import json
from pathlib import Path
from typing import Any


COMPONENT_PATTERNS = {
    "cli": {"dirs": ["cli"], "files": ["cli.py"], "indicators": ["click", "argparse", "typer"]},
    "api": {"dirs": ["api", "server"], "files": ["server.py"], "indicators": ["fastapi", "flask", "django"]},
    "database": {"dirs": ["db", "database", "models"], "indicators": ["sqlalchemy", "sqlite3", "psycopg"]},
    "tests": {"dirs": ["tests"], "files": ["test_"], "indicators": ["pytest", "unittest"]},
    "web_ui": {"dirs": ["ui", "static", "templates"], "indicators": ["html", "htmx", "jinja2"]},
    "docs": {"dirs": ["docs"], "files": ["README.md"], "indicators": ["sphinx", "mkdocs"]},
    "config": {"files": ["pyproject.toml", "setup.py", "config.py"], "indicators": ["pydantic", "yaml"]},
    "ci_cd": {"dirs": [".github"], "files": ["Dockerfile", "docker-compose.yml"]},
}


class ArchitectureGenerator:
    """Generate architecture diagrams and documentation from codebase structure."""

    def __init__(self, path: str = "."):
        self.path = Path(path)

    def detect_components(self) -> dict[str, dict[str, Any]]:
        components = {}
        for name, patterns in COMPONENT_PATTERNS.items():
            found = {"dirs": [], "files": [], "indicators": []}
            for d in patterns.get("dirs", []):
                p = self.path / d
                if p.exists() and p.is_dir():
                    found["dirs"].append(d)
            for f_pattern in patterns.get("files", []):
                for f in self.path.rglob(f_pattern):
                    if f.is_file():
                        found["files"].append(str(f.relative_to(self.path)))
            for indicator in patterns.get("indicators", []):
                for f in self.path.rglob("**/*.py"):
                    try:
                        if indicator in f.read_text(encoding="utf-8", errors="ignore"):
                            found["indicators"].append(indicator)
                            break
                    except (OSError, UnicodeDecodeError):
                        pass
            if found["dirs"] or found["files"] or found["indicators"]:
                components[name] = found
        return components

    def generate_mermaid(self) -> str:
        components = self.detect_components()
        lines = ["graph TD"]
        lines.append(f"  subgraph {self.path.name or 'Project'}")
        for i, (name, info) in enumerate(sorted(components.items())):
            node_id = f"comp_{i}"
            label = name.replace("_", " ").title()
            lines.append(f"    {node_id}[{label}]")
        # Add connections
        comp_list = list(components.keys())
        deps_map = {
            "api": ["config", "database"],
            "cli": ["api", "config"],
            "web_ui": ["api"],
            "tests": ["api", "cli"],
            "docs": ["api", "cli"],
        }
        for i, (name, _) in enumerate(sorted(components.items())):
            for dep in deps_map.get(name, []):
                if dep in components:
                    src_idx = list(components.keys()).index(name)
                    dst_idx = list(components.keys()).index(dep)
                    lines.append(f"    comp_{src_idx} --> comp_{dst_idx}")
        lines.append("  end")
        return "\n".join(lines)

    def generate_markdown(self) -> str:
        components = self.detect_components()
        lines = [f"# Architecture: {self.path.name}\n"]
        if not components:
            return "# No architecture components detected.\n"

        lines.append("## Detected Components\n")
        for name, info in sorted(components.items()):
            label = name.replace("_", " ").title()
            lines.append(f"### {label}")
            if info["dirs"]:
                lines.append(f"- **Directories:** {', '.join(info['dirs'])}")
            if info["files"]:
                lines.append(f"- **Files:** {', '.join(info['files'][:5])}")
            if info["indicators"]:
                lines.append(f"- **Technologies:** {', '.join(info['indicators'][:3])}")
            lines.append("")

        mermaid = self.generate_mermaid()
        lines.append("## Architecture Diagram\n")
        lines.append("```mermaid")
        lines.append(mermaid)
        lines.append("```\n")

        lines.append("## Directory Structure\n")
        lines.append("```")
        lines.extend(self._tree())
        lines.append("```")
        return "\n".join(lines)

    def _tree(self, max_depth: int = 3) -> list[str]:
        lines = []
        root = self.path
        prefix = ""

        def walk(dir_path: Path, depth: int, prefix: str):
            if depth > max_depth:
                return
            entries = sorted([e for e in dir_path.iterdir() if e.name[0] != "."],
                            key=lambda e: (not e.is_dir(), e.name))
            for i, entry in enumerate(entries):
                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{entry.name}/" if entry.is_dir() else f"{prefix}{connector}{entry.name}")
                if entry.is_dir():
                    ext = "    " if is_last else "│   "
                    walk(entry, depth + 1, prefix + ext)

        walk(root, 0, "")
        return lines

    def generate_json(self) -> str:
        components = self.detect_components()
        return json.dumps({
            "project": self.path.name,
            "components": components,
            "mermaid": self.generate_mermaid(),
        }, indent=2)
