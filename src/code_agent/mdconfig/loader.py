from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_agent.mdconfig.parser import MdConfig, parse_md, parse_md_text
from code_agent.mdconfig.generator import write_config


@dataclass
class ConfigSource:
    path: Path
    mtime: float = 0.0
    config: MdConfig | None = None

    def needs_reload(self) -> bool:
        return self.path.exists() and self.path.stat().st_mtime > self.mtime

    def load(self) -> MdConfig:
        self.config = parse_md(self.path)
        self.mtime = self.path.stat().st_mtime
        return self.config


class MarkdownConfigLoader:
    """Load, cache, merge, and watch Markdown config files."""

    def __init__(self, watch: bool = True):
        self.sources: dict[str, ConfigSource] = {}
        self.watch = watch
        self._default_dirs = [Path.cwd(), Path.home()]

    def add_file(self, path: str | Path, key: str | None = None) -> ConfigSource:
        p = Path(path)
        if not p.exists():
            return ConfigSource(path=p, config=MdConfig())
        k = key or p.stem
        source = ConfigSource(path=p)
        source.load()
        self.sources[k] = source
        return source

    def add_dir(self, dir_path: str | Path, pattern: str = "*.md") -> list[ConfigSource]:
        p = Path(dir_path)
        if not p.exists():
            return []
        sources = []
        for md_file in sorted(p.glob(pattern)):
            source = self.add_file(md_file, md_file.stem)
            sources.append(source)
        return sources

    def load(self, key: str) -> MdConfig | None:
        source = self.sources.get(key)
        if not source:
            return None
        if self.watch and source.needs_reload():
            source.load()
        return source.config

    def get(self, key: str, default: Any = None) -> Any:
        cfg = self.load(key)
        if cfg is None:
            return default
        return cfg.get(key, default)

    def merge(
        self, keys: list[str], prefer: str | None = None
    ) -> MdConfig:
        """Merge multiple configs. Later keys override earlier ones."""
        merged = MdConfig()
        for k in keys:
            cfg = self.load(k)
            if cfg:
                merged.frontmatter.update(cfg.frontmatter)
                for s in cfg.sections:
                    existing = merged.get_section(s.heading)
                    if existing:
                        existing.pairs.update(s.pairs)
                        existing.items.extend(s.items)
                    else:
                        merged.sections.append(s)
        return merged

    def load_defaults(self) -> None:
        """Load standard config files from common locations."""
        for d in self._default_dirs:
            for name in ["CLAUDE.md", "AGENTS.md", ".claude/config.md", ".agent/config.md"]:
                p = d / name
                if p.exists():
                    self.add_file(p, name.replace(".md", "").replace("/", "_"))
        # Load from .agent-mdconfig/ directory if exists
        for d in self._default_dirs:
            config_dir = d / ".agent-mdconfig"
            if config_dir.exists():
                self.add_dir(config_dir)

    def reload_all(self) -> int:
        count = 0
        for source in self.sources.values():
            if source.needs_reload():
                source.load()
                count += 1
        return count

    def keys(self) -> list[str]:
        return list(self.sources.keys())

    def summary(self) -> str:
        lines = [f"Markdown configs loaded: {len(self.sources)}"]
        for k, s in self.sources.items():
            status = "OK" if s.config else "EMPTY"
            fm_keys = list(s.config.frontmatter.keys()) if s.config else []
            sections = len(s.config.sections) if s.config else 0
            lines.append(f"  {k:20} [{status}] {s.path.name}  ({sections} sections, fm={fm_keys})")
        return "\n".join(lines)


class AgentMdConventions:
    """High-level interface for reading agent conventions from Markdown files."""

    def __init__(self, loader: MarkdownConfigLoader | None = None):
        self.loader = loader or MarkdownConfigLoader()
        self.loader.load_defaults()

    def get_project_rules(self) -> str:
        cfg = self.loader.load("CLAUDE.md")
        if not cfg:
            return ""
        parts = []
        for section in cfg.sections:
            if section.heading.lower() in ("architecture", "commands", "conventions", "test", "lint"):
                parts.append(f"## {section.heading}\n{section.content.strip()}")
        return "\n\n".join(parts)

    def get_agent_instructions(self) -> str:
        cfg = self.loader.load("AGENTS.md")
        if not cfg:
            return ""
        return cfg.raw_text[:3000]

    def get_tool_permissions(self) -> dict[str, str]:
        cfg = self.loader.load("CLAUDE.md")
        if not cfg:
            return {}
        perms: dict[str, str] = {}
        section = cfg.get_section("tool permissions")
        if section:
            for item in section.items:
                if ":" in item:
                    tool, perm = item.split(":", 1)
                    perms[tool.strip().lower()] = perm.strip()
        return perms

    def get_goals(self) -> list[str]:
        cfg = self.loader.load("AGENTS.md")
        if not cfg:
            return []
        section = cfg.get_section("goals")
        return section.items if section else []

    def get_constraints(self) -> list[str]:
        cfg = self.loader.load("AGENTS.md")
        if not cfg:
            return []
        section = cfg.get_section("constraints")
        return section.items if section else []

    def get_preferences(self) -> dict[str, str]:
        cfg = self.loader.load("AGENTS.md")
        if not cfg:
            return {}
        section = cfg.get_section("preferences")
        return section.pairs if section else {}

    def get_tool_access(self) -> list[str]:
        cfg = self.loader.load("AGENTS.md")
        if not cfg:
            return []
        section = cfg.get_section("tool access")
        return section.items if section else []

    def format_for_context(self) -> str:
        """Format all markdown config as context for the LLM."""
        parts = []
        rules = self.get_project_rules()
        if rules:
            parts.append(f"[Project Conventions]\n{rules[:1500]}")
        instructions = self.get_agent_instructions()
        if instructions:
            parts.append(f"[Agent Instructions]\n{instructions[:1500]}")
        goals = self.get_goals()
        if goals:
            parts.append(f"[Goals]\n" + "\n".join(f"- {g}" for g in goals))
        constraints = self.get_constraints()
        if constraints:
            parts.append(f"[Constraints]\n" + "\n".join(f"- {c}" for c in constraints))
        return "\n\n".join(parts)
