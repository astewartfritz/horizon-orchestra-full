from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from code_agent.config import AgentConfig, LLMConfig


@dataclass
class Profile:
    name: str = "default"
    description: str = ""
    agent: dict[str, Any] = field(default_factory=dict)
    llm: dict[str, Any] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    hooks: dict[str, str] = field(default_factory=dict)

    def to_agent_config(self) -> AgentConfig:
        cfg = AgentConfig()
        for k, v in self.agent.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        if self.llm:
            llm_cfg = LLMConfig()
            for k, v in self.llm.items():
                if hasattr(llm_cfg, k):
                    setattr(llm_cfg, k, v)
            cfg.llm = llm_cfg
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "coder": {
        "name": "coder",
        "description": "Optimized for writing and editing code",
        "agent": {"max_turns": 50, "verbose": False},
        "llm": {"model": "gpt-4", "temperature": 0.2, "max_tokens": 4096},
        "tools": ["read", "write", "edit", "glob", "grep", "bash", "diff", "analyze", "testgen"],
    },
    "debugger": {
        "name": "debugger",
        "description": "Optimized for debugging and root cause analysis",
        "agent": {"max_turns": 30, "verbose": True},
        "llm": {"model": "gpt-4", "temperature": 0.0, "max_tokens": 4096},
        "tools": ["read", "grep", "bash", "analyze", "watch", "git"],
    },
    "architect": {
        "name": "architect",
        "description": "Optimized for system design and architecture",
        "agent": {"max_turns": 20, "verbose": True},
        "llm": {"model": "gpt-4", "temperature": 0.7, "max_tokens": 8192},
        "tools": ["read", "write", "glob", "grep", "graphviz", "docgen", "workflow", "knowledge"],
    },
    "researcher": {
        "name": "researcher",
        "description": "Optimized for research and information gathering",
        "agent": {"max_turns": 15, "verbose": False},
        "llm": {"model": "gpt-4", "temperature": 0.5, "max_tokens": 4096},
        "tools": ["webfetch", "websearch", "read", "grep", "knowledge"],
    },
    "reviewer": {
        "name": "reviewer",
        "description": "Optimized for code review and quality assurance",
        "agent": {"max_turns": 20, "verbose": True},
        "llm": {"model": "gpt-4", "temperature": 0.1, "max_tokens": 4096},
        "tools": ["read", "grep", "diff", "analyze", "git", "graphviz"],
    },
    "docs": {
        "name": "docs",
        "description": "Optimized for documentation generation",
        "agent": {"max_turns": 15, "verbose": False},
        "llm": {"model": "gpt-4", "temperature": 0.4, "max_tokens": 8192},
        "tools": ["read", "write", "glob", "grep", "docgen", "graphviz", "prompt"],
    },
    "minimal": {
        "name": "minimal",
        "description": "Minimal config for quick tasks",
        "agent": {"max_turns": 10, "verbose": False, "max_retries": 1},
        "llm": {"model": "gpt-4o-mini", "temperature": 0.0, "max_tokens": 2048},
        "tools": ["read", "write", "bash", "grep"],
    },
}


class ProfileManager:
    def __init__(self, profiles_dir: str = ".agent-profiles"):
        self.dir = Path(profiles_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[str]:
        names = list(BUILTIN_PROFILES.keys())
        for f in self.dir.glob("*.json"):
            names.append(f.stem)
        return sorted(set(names))

    def get(self, name: str) -> Profile | None:
        if name in BUILTIN_PROFILES:
            return Profile(**BUILTIN_PROFILES[name])
        file = self.dir / f"{name}.json"
        if file.exists():
            data = json.loads(file.read_text(encoding="utf-8"))
            return Profile(**data)
        return None

    def save(self, profile: Profile) -> None:
        file = self.dir / f"{profile.name}.json"
        file.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")

    def delete(self, name: str) -> bool:
        file = self.dir / f"{name}.json"
        if file.exists():
            file.unlink()
            return True
        return False


def load_profile(name: str, profiles_dir: str = ".agent-profiles") -> AgentConfig | None:
    mgr = ProfileManager(profiles_dir)
    profile = mgr.get(name)
    if profile:
        return profile.to_agent_config()
    return None


def save_profile(name: str, agent_cfg: AgentConfig, profiles_dir: str = ".agent-profiles") -> None:
    profile = Profile(
        name=name,
        agent={k: v for k, v in agent_cfg.__dict__.items() if not k.startswith("_")},
        llm={k: v for k, v in agent_cfg.llm.__dict__.items() if not k.startswith("_")},
    )
    mgr = ProfileManager(profiles_dir)
    mgr.save(profile)
