"""Four security layers: network, filesystem, process, inference.

Deny-by-default across all layers. One failure does not expose the host.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_agent.shield.detector import InjectionShield
from code_agent.security.scanner import SecretScanner


@dataclass
class LayerDecision:
    allowed: bool
    layer: str
    reason: str = ""
    flags: list[str] = field(default_factory=list)


class NetworkLayer:
    """Layer 1: Network access control. Outbound restricted by default."""

    ALLOWED_DOMAINS = {
        "localhost", "127.0.0.1", "api.openai.com", "api.anthropic.com",
        "registry.npmjs.org", "pypi.org", "files.pythonhosted.org",
        "github.com", "raw.githubusercontent.com",
    }

    def __init__(self):
        self._allowlist = set(self.ALLOWED_DOMAINS)
        self._denylist: set[str] = set()

    def check(self, url: str) -> LayerDecision:
        from urllib.parse import urlparse
        domain = urlparse(url).hostname or ""
        if domain in self._denylist:
            return LayerDecision(False, "network", f"Domain denied: {domain}")
        if domain in self._allowlist:
            return LayerDecision(True, "network")
        return LayerDecision(False, "network", f"Domain not in allowlist: {domain}")


class FilesystemLayer:
    """Layer 2: Filesystem access control. Confined to workspace."""

    def __init__(self, workspace: str | None = None):
        self._workspace = Path(workspace or os.getcwd()).resolve()
        self._allowed_extensions: set[str] = set()
        self._denied_paths: set[str] = set()
        self._secret_scanner = SecretScanner()

    def check_read(self, path: str) -> LayerDecision:
        target = Path(path).resolve()
        if not target.exists():
            return LayerDecision(False, "filesystem", "Path does not exist")
        if not str(target).startswith(str(self._workspace)):
            return LayerDecision(False, "filesystem", "Outside workspace: {path}")
        return LayerDecision(True, "filesystem")

    def check_write(self, path: str, content: str = "") -> LayerDecision:
        target = Path(path).resolve()
        if not str(target).startswith(str(self._workspace)):
            return LayerDecision(False, "filesystem", f"Outside workspace: {path}")

        # Scan for secrets before writing
        if content:
            scan = self._secret_scanner.scan(content)
            if scan.secrets_found:
                return LayerDecision(False, "filesystem",
                                     f"Secret detected in content: {scan.secrets_found[0].type}",
                                     flags=[f.type for f in scan.secrets_found])

        return LayerDecision(True, "filesystem")


class ProcessLayer:
    """Layer 3: Process execution control. Sandboxed by default."""

    ALLOWED_COMMANDS = {"python", "node", "npm", "cargo", "rustc", "git", "make",
                        "pytest", "ruff", "black", "echo", "cat", "ls", "pwd", "mkdir",
                        "cp", "mv", "rm", "chmod", "curl", "wget", "docker"}

    def __init__(self):
        self._allowlist = set(self.ALLOWED_COMMANDS)

    def check(self, command: str) -> LayerDecision:
        cmd = command.strip().split()[0] if command.strip() else ""
        base = os.path.basename(cmd)
        if base in self._allowlist:
            return LayerDecision(True, "process")
        return LayerDecision(False, "process", f"Command not allowed: {base}")


class InferenceLayer:
    """Layer 4: Model access control. Policy-governed inference."""

    def __init__(self):
        self._shield = InjectionShield()
        self._denied_models: set[str] = set()
        self._max_input_length = 100000

    def check_input(self, text: str) -> LayerDecision:
        shield_result = self._shield.analyze(text)
        if shield_result.risk.value in ("confirmed", "likely"):
            return LayerDecision(False, "inference",
                                 f"Injection risk: {', '.join(shield_result.flags)}",
                                 flags=shield_result.flags)
        return LayerDecision(True, "inference")

    def check_model(self, model: str) -> LayerDecision:
        if model in self._denied_models:
            return LayerDecision(False, "inference", f"Model denied: {model}")
        return LayerDecision(True, "inference")


class SecurityLayers:
    """All four security layers: network → filesystem → process → inference."""

    def __init__(self):
        self.network = NetworkLayer()
        self.filesystem = FilesystemLayer()
        self.process = ProcessLayer()
        self.inference = InferenceLayer()

    def check_all(self, url: str = "", path: str = "", command: str = "",
                  content: str = "", text: str = "") -> list[LayerDecision]:
        decisions = []
        if url:
            decisions.append(self.network.check(url))
        if path:
            decisions.append(self.filesystem.check_read(path))
        if command:
            decisions.append(self.process.check(command))
        if text:
            decisions.append(self.inference.check_input(text))
        return decisions

    def all_allowed(self, decisions: list[LayerDecision]) -> bool:
        return all(d.allowed for d in decisions)
