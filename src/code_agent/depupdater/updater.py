from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DepInfo:
    name: str
    current_version: str = ""
    latest_version: str = ""
    update_available: bool = False
    source: str = "pip"
    changelog: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "current": self.current_version,
                "latest": self.latest_version, "update": self.update_available}


class DepUpdater:
    """Audit and update project dependencies."""

    def scan_requirements(self, path: str = "requirements.txt") -> list[DepInfo]:
        deps = []
        p = Path(path)
        if not p.exists():
            return deps

        for line in p.read_text().split("\n"):
            line = line.strip()
            if not line or line.startswith(("#", "-", "git+")):
                continue
            m = re.match(r'^([\w-]+)([>=<~!]+\s*[\d.*]+)?', line)
            if m:
                deps.append(DepInfo(
                    name=m.group(1),
                    current_version=(m.group(2) or "").strip(">=<~! "),
                    source="pip",
                ))
        return deps

    def scan_pyproject(self, path: str = "pyproject.toml") -> list[DepInfo]:
        import tomllib
        deps = []
        p = Path(path)
        if not p.exists():
            return deps
        try:
            data = tomllib.loads(p.read_text())
            project = data.get("project", {})
            for dep in project.get("dependencies", []):
                m = re.match(r'^([\w-]+)([>=<~!]+\s*[\d.*]+)?', dep)
                if m:
                    deps.append(DepInfo(
                        name=m.group(1),
                        current_version=(m.group(2) or "").strip(">=<~! "),
                        source="pip",
                    ))
        except Exception:
            pass
        return deps

    def check_updates(self, deps: list[DepInfo]) -> list[DepInfo]:
        for dep in deps:
            try:
                result = subprocess.run(
                    ["pip", "index", "versions", dep.name],
                    capture_output=True, text=True, timeout=30,
                )
                for line in result.stdout.split("\n"):
                    if "Available versions:" in line:
                        versions = re.findall(r'[\d]+\.[\d]+\.[\d]+', line)
                        if versions:
                            dep.latest_version = versions[0]
                            dep.update_available = (
                                dep.latest_version != dep.current_version
                                if dep.current_version else True
                            )
                            break
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        return deps

    def scan_npm(self, path: str = "package.json") -> list[DepInfo]:
        deps = []
        p = Path(path)
        if not p.exists():
            return deps
        try:
            data = json.loads(p.read_text())
            for section in ["dependencies", "devDependencies"]:
                for name, version in data.get(section, {}).items():
                    deps.append(DepInfo(
                        name=name, current_version=version.strip("^~"),
                        source="npm",
                    ))
        except (json.JSONDecodeError, OSError):
            pass
        return deps

    def generate_report(self, path: str = ".") -> str:
        all_deps = []
        all_deps.extend(self.scan_requirements())
        all_deps.extend(self.scan_pyproject())
        all_deps.extend(self.scan_npm())

        if not all_deps:
            return "No dependencies found."

        all_deps = self.check_updates(all_deps)
        updates = [d for d in all_deps if d.update_available]

        lines = [f"Dependencies: {len(all_deps)}, Updates available: {len(updates)}\n"]
        for d in updates[:20]:
            lines.append(f"  {d.name:25} {d.current_version:10} -> {d.latest_version}")
        if len(updates) > 20:
            lines.append(f"  ... and {len(updates) - 20} more")

        return "\n".join(lines)
