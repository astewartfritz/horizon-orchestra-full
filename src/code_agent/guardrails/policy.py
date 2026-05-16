from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class CheckResult:
    passed: bool
    message: str = ""
    severity: str = "warning"  # info, warning, block


@dataclass
class Rule:
    name: str
    description: str
    check_fn: Callable[[dict[str, Any]], CheckResult]
    severity: str = "warning"
    enabled: bool = True


@dataclass
class Policy:
    name: str
    rules: list[Rule] = field(default_factory=list)

    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)


class Guardrails:
    def __init__(self):
        self.policies: dict[str, Policy] = {}
        self._load_defaults()

    def add_policy(self, policy: Policy) -> None:
        self.policies[policy.name] = policy

    def _load_defaults(self) -> None:
        default = Policy("default")

        default.add_rule(Rule(
            name="no-rm-rf",
            description="Prevent destructive rm -rf commands",
            severity="block",
            check_fn=lambda ctx: CheckResult(
                passed="rm -rf" not in ctx.get("command", ""),
                message="rm -rf is blocked for safety",
            ),
        ))

        default.add_rule(Rule(
            name="no-force-push",
            description="Prevent git force push to main/master",
            severity="block",
            check_fn=lambda ctx: CheckResult(
                passed=not (
                    ctx.get("git_action") == "push"
                    and "--force" in str(ctx.get("args", ""))
                ),
                message="Force push to main/master is blocked",
            ),
        ))

        default.add_rule(Rule(
            name="no-commit-secrets",
            description="Warn about potential secrets in commits",
            severity="warning",
            check_fn=lambda ctx: CheckResult(
                passed=not any(
                    kw in ctx.get("content", "")
                    for kw in ["api_key", "password", "secret", "token", "credential"]
                ),
                message="Potential secret detected in content",
            ),
        ))

        default.add_rule(Rule(
            name="no-overwrite-config",
            description="Warn about overwriting config files",
            severity="warning",
            check_fn=lambda ctx: CheckResult(
                passed=".env" not in ctx.get("file_path", "")
                and "credentials" not in ctx.get("file_path", ""),
                message="Overwriting config/credentials file",
            ),
        ))

        default.add_rule(Rule(
            name="no-delete-src",
            description="Block deletion of source directories",
            severity="block",
            check_fn=lambda ctx: (
                CheckResult(
                    passed=not (
                        "rm" in ctx.get("command", "")
                        and any(d in ctx.get("command", "")
                                for d in ["/src", "/lib", "/node_modules"])
                    ),
                    message="Deleting source directories is blocked",
                )
                if "command" in ctx
                else CheckResult(passed=True)
            ),
        ))

        self.policies["default"] = default

    def check_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> list[CheckResult]:
        results = []
        for policy in self.policies.values():
            for rule in policy.rules:
                if not rule.enabled:
                    continue
                ctx = {"tool": tool_name, **tool_args}
                result = rule.check_fn(ctx)
                if isinstance(result, bool):
                    result = CheckResult(passed=result, message=rule.description, severity=rule.severity)
                else:
                    # propagate rule severity to CheckResult if not explicitly set
                    if result.severity == "warning" and rule.severity != "warning":
                        result.severity = rule.severity
                if not result.passed:
                    results.append(result)
        return results

    def check_command(self, command: str) -> list[CheckResult]:
        return self.check_tool_call("bash", {"command": command})

    def check_file_write(self, file_path: str, content: str) -> list[CheckResult]:
        return self.check_tool_call("write", {"file_path": file_path, "content": content})

    def has_blocks(self, results: list[CheckResult]) -> bool:
        return any(r.severity == "block" and not r.passed for r in results)

    def summary(self, results: list[CheckResult]) -> str:
        if not results:
            return "All checks passed"
        lines = []
        for r in results:
            icon = {"block": "BLOCK", "warning": "WARN", "info": "INFO"}.get(r.severity, "?")
            lines.append(f"  [{icon}] {r.message}")
        return "\n".join(lines)
