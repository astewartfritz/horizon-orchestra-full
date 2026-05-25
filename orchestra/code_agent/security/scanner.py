from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SECRET_PATTERNS: dict[str, str] = {
    "AWS Access Key": r"AKIA[0-9A-Z]{16}",
    "AWS Secret Key": r"(?i)aws[\s_]*(secret|access)[\s_]*key[\s_]*=+[\s_]*['\"][A-Za-z0-9/+=]{40}['\"]",
    "GitHub Token": r"(?i)github[\s_]*token[\s_]*=+[\s_]*['\"][A-Za-z0-9_]{40}['\"]",
    "GitHub PAT": r"gh[pousr]_[A-Za-z0-9_]{36,}",
    "Slack Token": r"xox[baprs]-[A-Za-z0-9-]{10,}",
    "Slack Webhook": r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}",
    "Generic API Key": r"(?i)(api[\s_]*(key|secret)|token)[\s_]*=+[\s_]*['\"][A-Za-z0-9_\-\.]{16,64}['\"]",
    "JWT Token": r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+",
    "Private Key": r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    "Password Assignment": r"(?i)(password|passwd|pwd)[\s_]*=+[\s_]*['\"][^'\"]{6,}['\"]",
    "Connection String": r"(?i)(connection[\s_]*(string|uri)|connstr)[\s_]*=+[\s_]*['\"][^'\"]+['\"]",
    "Google API Key": r"AIza[0-9A-Za-z\-_]{35}",
    "Heroku API Key": r"(?i)heroku[\s_]*api[\s_]*key[\s_]*=+[\s_]*['\"][A-Za-z0-9\-_]{20,}['\"]",
    "npm token": r"npm_[A-Za-z0-9]{36}",
    "PyPI token": r"pypi[A-Za-z0-9\-_]{36,}",
}

IGNORE_PATTERNS = [
    r"\.git/",
    r"\.venv/",
    r"__pycache__/",
    r"node_modules/",
    r"\.pytest_cache/",
    r"\.agent-",
    r"\.code-agent",
]


@dataclass
class ScanResult:
    file: str
    line: int
    match: str
    pattern_name: str
    severity: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "match": self.match[:80], "pattern": self.pattern_name, "severity": self.severity}


@dataclass
class ScanSummary:
    """Result of scanning a string for secrets."""
    secrets_found: list[ScanResult] = field(default_factory=list)
    scan_id: str = ""
    timestamp: str = ""
    total_files: int = 0
    total_secrets: int = 0


class SecretScanner:
    def __init__(self, path: str | Path = "."):
        self.path = Path(path)
        self.compiled = [(name, re.compile(pat)) for name, pat in SECRET_PATTERNS.items()]
        self.ignores = [re.compile(p) for p in IGNORE_PATTERNS]

    def scan(self, text: str) -> ScanSummary:
        """Scan a string for secrets."""
        results = []
        for i, line in enumerate(text.split("\n"), 1):
            for name, pattern in self.compiled:
                for match in pattern.finditer(line):
                    results.append(ScanResult(
                        file="<content>",
                        line=i,
                        match=match.group(),
                        pattern_name=name,
                        severity="high" if "KEY" in name or "Private" in name else "medium",
                    ))
        return ScanSummary(secrets_found=results, total_secrets=len(results))

    def scan_file(self, file_path: Path) -> list[ScanResult]:
        results = []
        for ip in self.ignores:
            if ip.search(str(file_path)):
                return results

        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            return results

        lines = text.split("\n")
        for i, line in enumerate(lines, 1):
            for name, pattern in self.compiled:
                for match in pattern.finditer(line):
                    results.append(ScanResult(
                        file=str(file_path),
                        line=i,
                        match=match.group(),
                        pattern_name=name,
                        severity="high" if "KEY" in name or "Private" in name else "medium",
                    ))
        return results

    def scan_directory(self, pattern: str = "**/*") -> list[ScanResult]:
        results = []
        for f in self.path.glob(pattern):
            if f.is_file():
                results.extend(self.scan_file(f))
        results.sort(key=lambda r: r.severity)
        return results

    def scan_git_history(self) -> list[ScanResult]:
        results = []
        try:
            import subprocess
            for name, pattern in self.compiled:
                proc = subprocess.run(
                    ["git", "log", "--all", "-p", "-G", pattern.pattern,
                     "--pickaxe-regex"],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(self.path),
                )
                for match in pattern.finditer(proc.stdout):
                    results.append(ScanResult(
                        file="(git history)", line=0,
                        match=match.group(), pattern_name=name,
                        severity="high",
                    ))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return results
