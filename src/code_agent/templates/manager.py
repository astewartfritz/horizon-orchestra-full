from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_agent.config import AgentConfig, LLMConfig


AGENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "code-review-pr": {
        "name": "code-review-pr",
        "description": "Review pull requests for code quality, security, and best practices",
        "system_prompt": "You are a senior code reviewer. Review the provided code diff for bugs, security issues, performance problems, and adherence to best practices. Be thorough but constructive.",
        "llm": {"model": "gpt-4", "temperature": 0.1},
        "max_turns": 10,
        "tools": ["read", "diff", "grep", "analyze"],
    },
    "bug-fix": {
        "name": "bug-fix",
        "description": "Diagnose and fix bugs with root cause analysis",
        "system_prompt": "You are a debugging expert. Methodically identify the root cause of the bug, then implement and verify the fix.",
        "llm": {"model": "gpt-4", "temperature": 0.0},
        "max_turns": 30,
        "tools": ["read", "write", "edit", "bash", "grep", "analyze", "git"],
    },
    "refactor": {
        "name": "refactor",
        "description": "Refactor code for better structure and maintainability",
        "system_prompt": "You are a software architect specializing in code refactoring. Improve code structure while preserving behavior.",
        "llm": {"model": "gpt-4", "temperature": 0.2},
        "max_turns": 25,
        "tools": ["read", "write", "edit", "analyze", "testgen", "transform", "graphviz"],
    },
    "add-tests": {
        "name": "add-tests",
        "description": "Generate comprehensive test coverage",
        "system_prompt": "You are a testing expert. Generate thorough tests covering happy paths, edge cases, and error conditions.",
        "llm": {"model": "gpt-4", "temperature": 0.3},
        "max_turns": 20,
        "tools": ["read", "write", "analyze", "testgen", "bash"],
    },
    "docs-generation": {
        "name": "docs-generation",
        "description": "Generate comprehensive documentation",
        "system_prompt": "You are a technical writer. Create clear, comprehensive documentation with examples.",
        "llm": {"model": "gpt-4", "temperature": 0.4},
        "max_turns": 15,
        "tools": ["read", "write", "docgen", "graphviz", "prompt"],
    },
    "security-audit": {
        "name": "security-audit",
        "description": "Full security audit of codebase",
        "system_prompt": "You are a security engineer. Scan for vulnerabilities, secrets, and insecure patterns. Provide actionable remediation.",
        "llm": {"model": "gpt-4", "temperature": 0.1},
        "max_turns": 25,
        "tools": ["read", "grep", "git", "security_audit", "analyze"],
    },
    "dependency-update": {
        "name": "dependency-update",
        "description": "Audit and update project dependencies",
        "system_prompt": "You are a dependency management expert. Audit dependencies for updates, security issues, and breaking changes.",
        "llm": {"model": "gpt-4", "temperature": 0.2},
        "max_turns": 15,
        "tools": ["read", "bash", "grep", "webfetch", "websearch"],
    },
    "api-development": {
        "name": "api-development",
        "description": "Design and implement API endpoints",
        "system_prompt": "You are an API developer. Design RESTful endpoints with proper error handling, validation, and documentation.",
        "llm": {"model": "gpt-4", "temperature": 0.3},
        "max_turns": 30,
        "tools": ["read", "write", "edit", "bash", "api", "testgen"],
    },
}


@dataclass
class AgentTemplate:
    name: str
    description: str
    system_prompt: str
    llm: dict[str, Any] = field(default_factory=dict)
    max_turns: int = 20
    tools: list[str] = field(default_factory=list)

    def to_agent_config(self) -> AgentConfig:
        cfg = AgentConfig(
            name=self.name,
            max_iterations=self.max_turns,
        )
        if self.system_prompt:
            cfg.system_prompt = self.system_prompt
        if self.llm:
            llm_cfg = LLMConfig()
            for k, v in self.llm.items():
                if hasattr(llm_cfg, k):
                    setattr(llm_cfg, k, v)
            cfg.llm = llm_cfg
        if self.tools:
            cfg.allowed_tools = list(self.tools)
        return cfg


class TemplateManager:
    def __init__(self, custom_dir: str = ".agent-templates"):
        self.custom_dir = Path(custom_dir)
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        self._builtin = {k: AgentTemplate(**v) for k, v in AGENT_TEMPLATES.items()}

    def list(self) -> list[str]:
        builtin = list(self._builtin.keys())
        custom = [f.stem for f in self.custom_dir.glob("*.json")]
        return sorted(set(builtin + custom))

    def get(self, name: str) -> AgentTemplate | None:
        if name in self._builtin:
            return self._builtin[name]
        custom_file = self.custom_dir / f"{name}.json"
        if custom_file.exists():
            import json
            data = json.loads(custom_file.read_text())
            return AgentTemplate(**data)
        return None

    def save(self, template: AgentTemplate) -> None:
        import json
        file = self.custom_dir / f"{template.name}.json"
        file.write_text(json.dumps({
            "name": template.name,
            "description": template.description,
            "system_prompt": template.system_prompt,
            "llm": template.llm,
            "max_turns": template.max_turns,
            "tools": template.tools,
        }, indent=2))

    def delete(self, name: str) -> bool:
        file = self.custom_dir / f"{name}.json"
        if file.exists():
            file.unlink()
            return True
        return False
