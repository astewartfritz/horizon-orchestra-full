from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class LogEntry:
    timestamp: Optional[str] = None
    level: str = "INFO"
    message: str = ""
    logger: str = ""
    source: str = ""
    line: int = 0
    raw: str = ""


@dataclass
class LogSummary:
    total_lines: int = 0
    parsed: int = 0
    levels: Counter = field(default_factory=Counter)
    loggers: Counter = field(default_factory=Counter)
    error_messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    time_range: Optional[tuple[str, str]] = None
    top_errors: list[tuple[str, int]] = field(default_factory=list)
    error_rate: float = 0.0


_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "TRACE", "FATAL"}


class LogAnalyzer:
    def __init__(self):
        self.entries: list[LogEntry] = []

    def parse_file(self, file_path: str, format: str = "auto") -> LogSummary:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        return self.parse_text(text, format=format, source=str(path))

    def parse_text(self, text: str, format: str = "auto", source: str = "") -> LogSummary:
        self.entries = []
        lines = text.splitlines()

        for i, line in enumerate(lines, 1):
            raw = line
            entry: Optional[LogEntry] = None

            if format == "auto":
                entry = self._parse_json(line, source, i)
                if not entry:
                    entry = self._parse_syslog(line, source, i)
                if not entry:
                    entry = self._parse_python(line, source, i)
                if not entry:
                    entry = self._parse_apache(line, source, i)
                if not entry:
                    entry = self._parse_generic(line, source, i)
            elif format == "json":
                entry = self._parse_json(line, source, i)
            elif format == "syslog":
                entry = self._parse_syslog(line, source, i)
            elif format == "python":
                entry = self._parse_python(line, source, i)
            elif format == "apache":
                entry = self._parse_apache(line, source, i)
            elif format == "raw":
                entry = LogEntry(raw=raw, source=source, line=i)

            if entry:
                self.entries.append(entry)

        return self._build_summary()

    def _parse_json(self, line: str, source: str, line_num: int) -> Optional[LogEntry]:
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            return None
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        level = str(obj.get("level", obj.get("severity", obj.get("lvl", "INFO")))).upper()
        message = str(obj.get("message", obj.get("msg", obj.get("event", str(obj)))))
        ts = str(obj.get("timestamp", obj.get("time", obj.get("@timestamp", ""))))
        logger = str(obj.get("logger", obj.get("name", obj.get("logger_name", ""))))
        return LogEntry(timestamp=ts, level=level, message=message, logger=logger, source=source, line=line_num, raw=line)

    _SYSLOG_PATTERN = re.compile(
        r"^(\w{3}\s+\d+\s+\d+:\d+:\d+)\s+\S+\s+(\w+)(?:\[(\d+)\])?:\s*(.*)"
    )

    def _parse_syslog(self, line: str, source: str, line_num: int) -> Optional[LogEntry]:
        m = self._SYSLOG_PATTERN.match(line)
        if not m:
            return None
        ts, logger, pid, message = m.groups()
        level = "INFO"
        lvl_match = re.search(r"\b(ERROR|WARNING|INFO|DEBUG|CRITICAL)\b", message, re.IGNORECASE)
        if lvl_match:
            level = lvl_match.group(1).upper()
        return LogEntry(timestamp=ts, level=level, message=message.strip(), logger=logger, source=source, line=line_num, raw=line)

    _PYTHON_PATTERN = re.compile(
        r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d+(?:[,\.]\d+)?)\s+-\s+(\w+)\s+-\s+(\w+)\s+-\s+(.*)"
    )
    _PYTHON_PATTERN2 = re.compile(
        r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d+(?:[,\.]\d+)?)\s*[,\.]\d+\s+(ERROR|WARNING|INFO|DEBUG|CRITICAL)\s+(\w+)?:?\s*(.*)"
    )

    def _parse_python(self, line: str, source: str, line_num: int) -> Optional[LogEntry]:
        m = self._PYTHON_PATTERN.match(line)
        if m:
            ts, level, logger, message = m.groups()
            return LogEntry(timestamp=ts, level=level.upper(), message=message.strip(), logger=logger, source=source, line=line_num, raw=line)
        m2 = self._PYTHON_PATTERN2.match(line)
        if m2:
            ts, level, logger, message = m2.groups()
            return LogEntry(timestamp=ts, level=level.upper(), message=(message or "").strip(), logger=(logger or ""), source=source, line=line_num, raw=line)

        level_match = re.search(r"\b(ERROR|WARNING|INFO|DEBUG|CRITICAL)\b", line)
        if level_match:
            return LogEntry(level=level_match.group(1).upper(), message=line.strip(), source=source, line=line_num, raw=line)
        return None

    _APACHE_PATTERN = re.compile(
        r'^(\S+)\s+\S+\s+\S+\s+\[([^\]]+)\]\s+"(?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+\S+\s+\S+"\s+(\d+)\s+(\d+)'
    )

    def _parse_apache(self, line: str, source: str, line_num: int) -> Optional[LogEntry]:
        m = self._APACHE_PATTERN.match(line)
        if not m:
            return None
        ip, ts, status, size = m.groups()
        level = "ERROR" if int(status) >= 500 else "WARNING" if int(status) >= 400 else "INFO"
        return LogEntry(timestamp=ts, level=level, message=f"{ip} -> {status} ({size}b)", logger="apache", source=source, line=line_num, raw=line)

    def _parse_generic(self, line: str, source: str, line_num: int) -> LogEntry:
        for lvl in _LOG_LEVELS:
            if lvl in line.upper():
                return LogEntry(level=lvl, message=line.strip(), source=source, line=line_num, raw=line)
        return LogEntry(level="INFO", message=line.strip(), source=source, line=line_num, raw=line)

    def _build_summary(self) -> LogSummary:
        levels: Counter = Counter()
        loggers: Counter = Counter()
        errors: list[str] = []
        warnings: list[str] = []
        timestamps: list[str] = []

        for e in self.entries:
            levels[e.level] += 1
            if e.logger:
                loggers[e.logger] += 1
            if e.level == "ERROR" or e.level == "CRITICAL" or e.level == "FATAL":
                errors.append(f"[{e.timestamp or ''}] {e.message[:200]}")
            elif e.level == "WARNING":
                warnings.append(f"[{e.timestamp or ''}] {e.message[:200]}")
            if e.timestamp:
                timestamps.append(e.timestamp)

        time_range = None
        if timestamps:
            sorted_ts = sorted(timestamps)
            time_range = (sorted_ts[0], sorted_ts[-1])

        top_errors = Counter(errors).most_common(10)
        total = len(self.entries)
        error_count = levels.get("ERROR", 0) + levels.get("CRITICAL", 0) + levels.get("FATAL", 0)

        return LogSummary(
            total_lines=sum(1 for e in self.entries if e.raw),
            parsed=len(self.entries),
            levels=levels,
            loggers=loggers,
            error_messages=list(dict.fromkeys(errors))[:20],
            warnings=list(dict.fromkeys(warnings))[:20],
            time_range=time_range,
            top_errors=top_errors,
            error_rate=error_count / total if total > 0 else 0.0,
        )

    def filter_by_level(self, level: str) -> list[LogEntry]:
        return [e for e in self.entries if e.level == level.upper()]

    def filter_by_logger(self, logger: str) -> list[LogEntry]:
        return [e for e in self.entries if logger.lower() in e.logger.lower()]

    def search(self, query: str) -> list[LogEntry]:
        ql = query.lower()
        return [e for e in self.entries if ql in e.message.lower() or ql in e.raw.lower()]

    def summary_text(self, summary: LogSummary) -> str:
        lines = [
            f"Log Analysis Summary",
            f"{'=' * 50}",
            f"Total lines: {summary.total_lines}",
            f"Parsed entries: {summary.parsed}",
            f"Time range: {summary.time_range or 'N/A'}",
            f"Error rate: {summary.error_rate:.1%}",
            "",
            "Levels:",
        ]
        for level, count in summary.levels.most_common():
            lines.append(f"  {level:10}: {count}")
        if summary.loggers:
            lines.append("\nTop loggers:")
            for logger, count in summary.loggers.most_common(10):
                lines.append(f"  {logger}: {count}")
        if summary.top_errors:
            lines.append(f"\nTop errors ({len(summary.top_errors)}):")
            for msg, count in summary.top_errors[:5]:
                lines.append(f"  [{count}x] {msg[:100]}")
        return "\n".join(lines)
