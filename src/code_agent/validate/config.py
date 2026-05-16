from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ValidationIssue:
    field: str = ""
    message: str = ""
    severity: str = "warn"
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "message": self.message,
                "severity": self.severity}


VALID_PROVIDERS = {"openai", "anthropic", "ollama", "azure", "google"}
VALID_TOOLS = {
    "read", "write", "edit", "glob", "bash", "grep",
    "webfetch", "websearch", "git", "task", "diff", "patch",
    "apply_edit", "index", "analyze", "testgen", "watch",
    "sandbox", "scaffold", "improve", "workflow", "docgen",
    "graphviz", "knowledge", "api", "sql", "jupyter",
    "swarm", "transform", "security_audit", "multilang",
}


class ConfigValidator:
    def validate_agent_config(self, config: dict[str, Any]) -> list[ValidationIssue]:
        issues = []

        # Check required fields
        if "llm" not in config:
            issues.append(ValidationIssue("llm", "Missing LLM configuration", "error"))
        else:
            llm = config["llm"]
            if not isinstance(llm, dict):
                issues.append(ValidationIssue("llm", "LLM config must be an object", "error"))
            else:
                provider = llm.get("provider", "openai")
                if provider not in VALID_PROVIDERS:
                    issues.append(ValidationIssue(
                        "llm.provider",
                        f"Unknown provider '{provider}'. Valid: {', '.join(sorted(VALID_PROVIDERS))}",
                        "warn", provider,
                    ))
                max_tokens = llm.get("max_tokens", 4096)
                if max_tokens < 256 or max_tokens > 200000:
                    issues.append(ValidationIssue(
                        "llm.max_tokens", f"Unusual max_tokens: {max_tokens}", "warn", max_tokens,
                    ))
                temperature = llm.get("temperature", 0.0)
                if temperature < 0.0 or temperature > 2.0:
                    issues.append(ValidationIssue(
                        "llm.temperature", "Temperature should be 0.0-2.0", "error", temperature,
                    ))

        # Check agent fields
        max_iter = config.get("max_iterations", 50)
        if max_iter < 1 or max_iter > 500:
            issues.append(ValidationIssue(
                "max_iterations", f"Unusual max_iterations: {max_iter}", "warn", max_iter,
            ))

        workspace = config.get("workspace", "")
        if workspace and not Path(workspace).exists():
            issues.append(ValidationIssue(
                "workspace", f"Workspace path does not exist: {workspace}", "warn", workspace,
            ))

        # Check allowed_tools
        tools = config.get("allowed_tools", [])
        if tools:
            unknown = [t for t in tools if t not in VALID_TOOLS]
            if unknown:
                issues.append(ValidationIssue(
                    "allowed_tools",
                    f"Unknown tools: {', '.join(unknown)}",
                    "warn", unknown,
                ))

        return issues

    def validate_config_file(self, path: str | Path) -> list[ValidationIssue]:
        p = Path(path)
        if not p.exists():
            return [ValidationIssue("file", f"Config file not found: {path}", "error")]
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return [ValidationIssue("file", f"Invalid JSON: {e}", "error")]
        return self.validate_agent_config(data)

    def validate_all(self, config_path: str = "code-agent.json") -> list[ValidationIssue]:
        if Path(config_path).exists():
            return self.validate_config_file(config_path)
        return [ValidationIssue("file", "No config file found (using defaults)", "info")]
