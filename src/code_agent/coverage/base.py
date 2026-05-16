from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class UncoveredLine:
    line: int
    source: str = ""


@dataclass
class CoverageData:
    file_path: str
    covered_lines: int = 0
    total_lines: int = 0
    coverage_pct: float = 0.0
    missing_lines: list[UncoveredLine] = field(default_factory=list)
    branches_covered: int = 0
    branches_total: int = 0
    branch_coverage_pct: float = 0.0

    @property
    def missing_count(self) -> int:
        return len(self.missing_lines)


@dataclass
class CoverageReport:
    files: list[CoverageData] = field(default_factory=list)
    overall_coverage: float = 0.0
    total_covered: int = 0
    total_lines: int = 0
    low_coverage_files: list[CoverageData] = field(default_factory=list)


class CoverageAnalyzer:
    def __init__(self, project_root: str = "."):
        self.root = Path(project_root).resolve()

    def run_coverage(self, target: str = "", args: str = "") -> CoverageReport:
        cmd = [sys.executable, "-m", "coverage", "run"]
        if args:
            cmd.extend(args.split())
        if target:
            cmd.append(target)
        else:
            cmd.append("-m")
            cmd.append("pytest")
        try:
            subprocess.run(cmd, cwd=str(self.root), capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            pass
        except FileNotFoundError:
            pass
        return self.parse_report()

    def parse_report(self) -> CoverageReport:
        try:
            subprocess.run(
                [sys.executable, "-m", "coverage", "json", "-o", str(self.root / ".coverage_report.json")],
                cwd=str(self.root), capture_output=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return self._parse_xml()

        report_path = self.root / ".coverage_report.json"
        if not report_path.exists():
            return self._parse_xml()

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return CoverageReport()

        report = CoverageReport()
        meta = data.get("meta", {})
        files_data = data.get("files", {})

        total_covered = 0
        total_lines = 0

        for file_path, fdata in files_data.get("files", files_data).items():
            summary = fdata.get("summary", fdata)
            cd = CoverageData(
                file_path=file_path,
                covered_lines=summary.get("covered_lines", 0),
                total_lines=summary.get("num_statements", 0),
                coverage_pct=summary.get("covered_percent", summary.get("percent_covered", 0.0)),
                missing_lines=[],
            )
            if cd.total_lines > 0:
                total_covered += cd.covered_lines
                total_lines += cd.total_lines
                report.files.append(cd)
                if cd.coverage_pct < 80:
                    report.low_coverage_files.append(cd)

            missing = fdata.get("missing_lines", fdata.get("missing", []))
            if isinstance(missing, list):
                for ln in missing:
                    if isinstance(ln, (int, float)):
                        src = ""
                        try:
                            lines = Path(file_path).read_text(encoding="utf-8").splitlines()
                            if 1 <= int(ln) <= len(lines):
                                src = lines[int(ln) - 1].strip()
                        except Exception:
                            pass
                        cd.missing_lines.append(UncoveredLine(line=int(ln), source=src))
                    elif isinstance(ln, dict):
                        cd.missing_lines.append(UncoveredLine(line=ln.get("line", 0), source=ln.get("source", "")))

        report.overall_coverage = (total_covered / total_lines * 100) if total_lines > 0 else 0.0
        report.total_covered = total_covered
        report.total_lines = total_lines
        return report

    def _parse_xml(self) -> CoverageReport:
        xml_path = self.root / "coverage.xml"
        if not xml_path.exists():
            return CoverageReport()
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(str(xml_path))
            root = tree.getroot()
            report = CoverageReport()
            total_covered = 0
            total_lines = 0
            for pkg in root.iter("package"):
                for cls in pkg.iter("class"):
                    fn = cls.get("filename", "")
                    lines = cls.find("lines")
                    if lines is None:
                        continue
                    cd = CoverageData(file_path=fn)
                    for line_el in lines.findall("line"):
                        cd.total_lines += 1
                        if line_el.get("hits", "0") != "0":
                            cd.covered_lines += 1
                        else:
                            cd.missing_lines.append(UncoveredLine(line=int(line_el.get("number", 0))))
                    if cd.total_lines > 0:
                        cd.coverage_pct = cd.covered_lines / cd.total_lines * 100
                        total_covered += cd.covered_lines
                        total_lines += cd.total_lines
                        report.files.append(cd)
                        if cd.coverage_pct < 80:
                            report.low_coverage_files.append(cd)
            report.overall_coverage = (total_covered / total_lines * 100) if total_lines > 0 else 0.0
            report.total_covered = total_covered
            report.total_lines = total_lines
            return report
        except Exception:
            return CoverageReport()

    def summary_text(self, report: CoverageReport) -> str:
        lines = [
            f"Coverage Report",
            f"{'=' * 60}",
            f"Overall: {report.overall_coverage:.1f}%",
            f"Files: {len(report.files)}",
            f"Covered: {report.total_covered} / {report.total_lines} lines",
            "",
        ]
        if report.files:
            lines.append(f"{'File':<50} {'Coverage':<10} {'Status':<10}")
            lines.append("-" * 70)
            for f in sorted(report.files, key=lambda x: x.coverage_pct)[:30]:
                status = "LOW" if f.coverage_pct < 80 else "OK"
                lines.append(f"{f.file_path:<50} {f.coverage_pct:<10.1f}% {status:<10}")

        if report.low_coverage_files:
            lines.append(f"\nLow coverage files (<80%): {len(report.low_coverage_files)}")
            for f in report.low_coverage_files[:5]:
                misses = ", ".join(str(ul.line) for ul in f.missing_lines[:10])
                lines.append(f"  {Path(f.file_path).name}: line(s) {misses}")
        return "\n".join(lines)
