from __future__ import annotations

import datetime
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class HealthCheck:
    name: str
    status: str = "ok"
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    timestamp: str = ""
    checks: list[HealthCheck] = field(default_factory=list)
    overall: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall": self.overall,
            "checks": [
                {"name": c.name, "status": c.status, "message": c.message}
                for c in self.checks
            ],
        }

    def to_text(self) -> str:
        lines = [f"Health Report ({self.timestamp})", f"Overall: {self.overall}", ""]
        for c in self.checks:
            icon = {"ok": "PASS", "warn": "WARN", "fail": "FAIL"}.get(c.status, "?")
            lines.append(f"  [{icon}] {c.name}: {c.message}")
        return "\n".join(lines)


class HealthChecker:
    def __init__(self, project_root: str = "."):
        self.root = Path(project_root).resolve()

    def run_all(self) -> HealthReport:
        report = HealthReport(timestamp=datetime.datetime.utcnow().isoformat() + "Z")
        report.checks.extend(self._check_python())
        report.checks.extend(self._check_disk())
        report.checks.extend(self._check_git())
        report.checks.extend(self._check_deps())
        report.checks.extend(self._check_config())

        if any(c.status == "fail" for c in report.checks):
            report.overall = "fail"
        elif any(c.status == "warn" for c in report.checks):
            report.overall = "warn"

        return report

    def _check_python(self) -> list[HealthCheck]:
        checks = []
        checks.append(HealthCheck(
            name="python_version",
            status="ok",
            message=f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            details={"version": list(sys.version_info)},
        ))
        # Check core imports
        missing = []
        for mod in ["httpx", "click", "pydantic", "yaml", "git"]:
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)
        if missing:
            checks.append(HealthCheck(
                name="python_deps",
                status="warn",
                message=f"Missing modules: {', '.join(missing)}",
            ))
        else:
            checks.append(HealthCheck(
                name="python_deps",
                status="ok",
                message="All core dependencies available",
            ))
        return checks

    def _check_disk(self) -> list[HealthCheck]:
        checks = []
        try:
            usage = os.statvfs(self.root) if hasattr(os, 'statvfs') else None
            if usage:
                free_gb = (usage.f_frsize * usage.f_bavail) / (1024**3)
                if free_gb < 1:
                    checks.append(HealthCheck(name="disk_space", status="warn", message=f"Only {free_gb:.1f}GB free"))
                else:
                    checks.append(HealthCheck(name="disk_space", status="ok", message=f"{free_gb:.1f}GB free"))
            else:
                checks.append(HealthCheck(name="disk_space", status="ok", message="Disk check skipped (no statvfs)"))
        except Exception:
            checks.append(HealthCheck(name="disk_space", status="ok", message="Disk check unavailable"))

        return checks

    def _check_git(self) -> list[HealthCheck]:
        checks = []
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
                cwd=str(self.root),
            )
            if result.returncode == 0:
                branch = subprocess.run(
                    ["git", "branch", "--show-current"],
                    capture_output=True, text=True, timeout=5,
                    cwd=str(self.root),
                )
                checks.append(HealthCheck(
                    name="git_repo",
                    status="ok",
                    message=f"Git repo ({branch.stdout.strip() or 'detached'})",
                ))
            else:
                checks.append(HealthCheck(name="git_repo", status="warn", message="Not a git repository"))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            checks.append(HealthCheck(name="git_repo", status="warn", message="Git not available"))

        return checks

    def _check_deps(self) -> list[HealthCheck]:
        checks = []
        req_file = self.root / "requirements.txt"
        pyproject = self.root / "pyproject.toml"
        if req_file.exists():
            checks.append(HealthCheck(name="requirements", status="ok", message="requirements.txt found"))
        elif pyproject.exists():
            checks.append(HealthCheck(name="requirements", status="ok", message="pyproject.toml found"))
        else:
            checks.append(HealthCheck(name="requirements", status="warn", message="No dependency file found"))
        return checks

    def _check_config(self) -> list[HealthCheck]:
        checks = []
        cfg = self.root / "code-agent.json"
        if cfg.exists():
            import json
            try:
                json.loads(cfg.read_text())
                checks.append(HealthCheck(name="config", status="ok", message="config valid JSON"))
            except json.JSONDecodeError:
                checks.append(HealthCheck(name="config", status="fail", message="config invalid JSON"))
        else:
            checks.append(HealthCheck(name="config", status="ok", message="No config file (using defaults)"))
        return checks
