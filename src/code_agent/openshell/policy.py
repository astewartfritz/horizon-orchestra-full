from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class PolicyRule:
    pattern: str
    decision: Decision
    description: str = ""


@dataclass
class PolicyProfile:
    name: str
    description: str = ""
    network_rules: list[PolicyRule] = field(default_factory=list)
    filesystem_rules: list[PolicyRule] = field(default_factory=list)
    shell_rules: list[PolicyRule] = field(default_factory=list)
    default_network: Decision = Decision.ASK
    default_filesystem: Decision = Decision.ASK
    default_shell: Decision = Decision.ASK


_DEFAULT_PROFILES: dict[str, PolicyProfile] = {
    "strict": PolicyProfile(
        name="strict",
        description="Deny by default. Only allow explicitly listed endpoints, paths, and commands.",
        default_network=Decision.DENY,
        default_filesystem=Decision.DENY,
        default_shell=Decision.DENY,
        network_rules=[
            PolicyRule("github.com", Decision.ALLOW, "GitHub access"),
            PolicyRule("api.openai.com", Decision.ALLOW, "OpenAI API"),
            PolicyRule("api.anthropic.com", Decision.ALLOW, "Anthropic API"),
            PolicyRule("*.python.org", Decision.ALLOW, "Python package index"),
            PolicyRule("pypi.org", Decision.ALLOW, "PyPI"),
            PolicyRule("files.pythonhosted.org", Decision.ALLOW, "PyPI files"),
            PolicyRule("*.docker.com", Decision.ALLOW, "Docker registry"),
            PolicyRule("*.docker.io", Decision.ALLOW, "Docker Hub"),
        ],
        filesystem_rules=[
            PolicyRule(str(Path.home() / "Documents"), Decision.ALLOW, "Documents"),
            PolicyRule(str(Path.home() / "Projects"), Decision.ALLOW, "Projects"),
            PolicyRule(str(Path.home() / ".ssh"), Decision.ASK, "SSH keys"),
            PolicyRule(str(Path.home() / ".aws"), Decision.ASK, "AWS config"),
            PolicyRule(str(Path.home() / ".config"), Decision.ASK, "App configs"),
            PolicyRule(str(Path.home() / ".gitconfig"), Decision.ASK, "Git config"),
        ],
        shell_rules=[
            PolicyRule("rm -rf *", Decision.DENY, "Recursive delete"),
            PolicyRule("rm -rf /", Decision.DENY, "Root delete"),
            PolicyRule("mkfs.*", Decision.DENY, "Format filesystem"),
            PolicyRule("dd if=.* of=.*", Decision.DENY, "Raw disk write"),
            PolicyRule("> /dev/sd*", Decision.DENY, "Block device write"),
            PolicyRule("chmod -R 777", Decision.ASK, "Permissive chmod"),
            PolicyRule("pip install *", Decision.ASK, "Package install"),
            PolicyRule("npm install *", Decision.ASK, "NPM install"),
            PolicyRule("git push --force", Decision.ASK, "Force push"),
            PolicyRule("curl * | sh", Decision.DENY, "Pipe to shell"),
            PolicyRule("wget * -O- | sh", Decision.DENY, "Pipe to shell"),
            PolicyRule("sudo *", Decision.ASK, "Sudo command"),
        ],
    ),
    "standard": PolicyProfile(
        name="standard",
        description="Allow common operations. Ask for sensitive ones.",
        default_network=Decision.ALLOW,
        default_filesystem=Decision.ALLOW,
        default_shell=Decision.ALLOW,
        network_rules=[
            PolicyRule("*.facebook.com", Decision.DENY, "Social media blocked"),
            PolicyRule("*.instagram.com", Decision.DENY, "Social media blocked"),
            PolicyRule("*.tiktok.com", Decision.DENY, "Social media blocked"),
        ],
        filesystem_rules=[
            PolicyRule(str(Path.home() / ".ssh"), Decision.ASK, "SSH keys"),
            PolicyRule("/etc", Decision.ASK, "System config"),
        ],
        shell_rules=[
            PolicyRule("rm -rf /", Decision.DENY, "Root delete"),
            PolicyRule("mkfs.*", Decision.DENY, "Format filesystem"),
            PolicyRule("curl * | sh", Decision.DENY, "Pipe to shell"),
        ],
    ),
    "permissive": PolicyProfile(
        name="permissive",
        description="Allow everything. Trust the agent completely.",
        default_network=Decision.ALLOW,
        default_filesystem=Decision.ALLOW,
        default_shell=Decision.ALLOW,
    ),
    "custom": PolicyProfile(
        name="custom",
        description="User-defined custom policy.",
    ),
}


class OpenShellPolicy:
    def __init__(self, profile_name: str = "standard"):
        self.profile = _DEFAULT_PROFILES.get(profile_name, _DEFAULT_PROFILES["standard"])
        self._session_approvals: set[str] = set()
        self._session_denials: set[str] = set()

    @staticmethod
    def list_profiles() -> list[PolicyProfile]:
        return list(_DEFAULT_PROFILES.values())

    @staticmethod
    def get_profile(name: str) -> Optional[PolicyProfile]:
        return _DEFAULT_PROFILES.get(name)

    def check_network(self, host: str) -> Decision:
        for rule in self.profile.network_rules:
            if fnmatch.fnmatch(host.lower(), rule.pattern.lower()):
                return rule.decision

        if host in self._session_approvals:
            return Decision.ALLOW
        if host in self._session_denials:
            return Decision.DENY

        return self.profile.default_network

    def check_filesystem(self, path: str) -> Decision:
        resolved = str(Path(path).resolve())
        for rule in self.profile.filesystem_rules:
            if resolved.startswith(rule.pattern) or fnmatch.fnmatch(resolved, rule.pattern):
                return rule.decision
        return self.profile.default_filesystem

    def check_shell(self, command: str) -> Decision:
        cmd_lower = command.lower().strip()
        for rule in self.profile.shell_rules:
            try:
                if re.match(rule.pattern, cmd_lower, re.IGNORECASE):
                    return rule.decision
            except re.error:
                if rule.pattern in cmd_lower:
                    return rule.decision
        return self.profile.default_shell

    def approve_endpoint(self, endpoint: str) -> None:
        self._session_approvals.add(endpoint)
        if endpoint in self._session_denials:
            self._session_denials.remove(endpoint)

    def deny_endpoint(self, endpoint: str) -> None:
        self._session_denials.add(endpoint)
        if endpoint in self._session_approvals:
            self._session_approvals.remove(endpoint)

    def summary_text(self) -> str:
        lines = [
            f"OpenShell Policy: {self.profile.name}",
            f"{'=' * 50}",
            f"Network:   default={self.profile.default_network.value}",
            f"Filesystem: default={self.profile.default_filesystem.value}",
            f"Shell:     default={self.profile.default_shell.value}",
            f"Rules: {len(self.profile.network_rules)} network, {len(self.profile.filesystem_rules)} fs, {len(self.profile.shell_rules)} shell",
            f"Session approvals: {len(self._session_approvals)}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile.name,
            "default_network": self.profile.default_network.value,
            "default_filesystem": self.profile.default_filesystem.value,
            "default_shell": self.profile.default_shell.value,
            "session_approvals": list(self._session_approvals),
        }
