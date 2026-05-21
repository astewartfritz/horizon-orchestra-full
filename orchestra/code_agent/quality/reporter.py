from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class FileReport:
    file: str = ""
    lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    functions: int = 0
    classes: int = 0
    complexity_score: float = 0.0
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def coverage_pct(self) -> float:
        if self.lines == 0:
            return 0.0
        comment_pct = self.comment_lines / self.lines * 100
        return round(comment_pct, 1)


QUALITY_ISSUES = {
    "long_lines": {"pattern": r"^.{120,}$", "message": "Line exceeds 120 chars", "severity": "warn"},
    "no_docstring": {"pattern": r"^(?!.*('''|\"\"\"|///|//!|# |-- ))", "message": "Missing docstring at file level", "severity": "info"},
    "todo": {"pattern": r"#\s*(TODO|FIXME|HACK|XXX)", "message": "Contains TODO/FIXME", "severity": "info"},
    "too_many_params": {"pattern": r"def\s+\w+\([^)]*,{4,}", "message": "Function has many parameters", "severity": "warn"},
    "print_stmt": {"pattern": r"^\s*print\(", "message": "Contains print() statement (possibly debugging)", "severity": "info"},
    "bare_except": {"pattern": r"^\s*except\s*:", "message": "Bare except clause", "severity": "warn"},
}


class QualityReporter:
    def __init__(self, path: str = "."):
        self.path = Path(path)

    def analyze_file(self, file_path: Path) -> FileReport:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.split("\n")
        report = FileReport(file=str(file_path), lines=len(lines))

        for line in lines:
            stripped = line.strip()
            if not stripped:
                report.blank_lines += 1
            elif stripped.startswith(("#", "//", "/*", "*", "--", "///", "//!")):
                report.comment_lines += 1
            else:
                report.code_lines += 1

        # Count functions and classes
        report.functions = len(re.findall(r'^\s*(?:def|function|fn|func)\s+\w+', text, re.MULTILINE))
        report.classes = len(re.findall(r'^\s*(?:class|struct|interface|trait)\s+\w+', text, re.MULTILINE))

        # Check quality issues
        for issue_name, issue in QUALITY_ISSUES.items():
            for i, line in enumerate(lines, 1):
                if re.search(issue["pattern"], line):
                    if len(report.issues) < 20:
                        report.issues.append(f"  L{i:4} [{issue_name}] {issue['message']}")
                    break

        # Complexity estimate
        report.complexity_score = report.functions * 1.5 + report.classes * 2.0 + len(report.issues) * 0.5

        return report

    def analyze_directory(self, pattern: str = "**/*.py") -> list[FileReport]:
        reports = []
        for f in sorted(self.path.glob(pattern)):
            if f.is_file():
                reports.append(self.analyze_file(f))
        return reports

    def generate_report(self, pattern: str = "**/*.py") -> str:
        files = self.analyze_directory(pattern)
        total_lines = sum(f.lines for f in files)
        total_issues = sum(len(f.issues) for f in files)
        total_functions = sum(f.functions for f in files)
        total_classes = sum(f.classes for f in files)

        lines = [
            f"Code Quality Report",
            f"{'='*50}",
            f"Files analyzed: {len(files)}",
            f"Total lines: {total_lines}",
            f"Functions: {total_functions}",
            f"Classes: {total_classes}",
            f"Issues found: {total_issues}",
            "",
        ]

        # Per-file summary
        for f in files:
            lines.append(f"\n{f.file}")
            lines.append(f"  Lines: {f.lines} (code: {f.code_lines}, comment: {f.comment_lines}, blank: {f.blank_lines})")
            lines.append(f"  Functions: {f.functions}, Classes: {f.classes}")
            lines.append(f"  Complexity: {f.complexity_score:.1f}")
            for issue in f.issues:
                lines.append(f"  {issue}")

        return "\n".join(lines)

    def to_json(self, pattern: str = "**/*.py") -> str:
        files = self.analyze_directory(pattern)
        return json.dumps([f.to_dict() for f in files], indent=2)
