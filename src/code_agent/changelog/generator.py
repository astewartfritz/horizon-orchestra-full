from __future__ import annotations

import subprocess
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class ChangelogEntry:
    hash: str
    author: str
    date: str
    message: str
    type: str = ""
    scope: str = ""
    breaking: bool = False
    body: str = ""


@dataclass
class Changelog:
    entries: list[ChangelogEntry] = field(default_factory=list)
    since_tag: str = ""
    from_date: str = ""
    to_date: str = ""


_COMMIT_PATTERN = re.compile(
    r"^(?P<type>feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(?:\((?P<scope>[^)]+)\))?"
    r"(?P<breaking>!)?"
    r":\s*(?P<message>.+)$",
    re.IGNORECASE,
)

_TYPE_LABELS = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "docs": "Documentation",
    "style": "Style",
    "refactor": "Code Refactoring",
    "perf": "Performance Improvements",
    "test": "Tests",
    "build": "Build System",
    "ci": "CI/CD",
    "chore": "Chores",
    "revert": "Reverts",
}


class ChangelogGenerator:
    def __init__(self, repo_path: str = "."):
        self.repo = Path(repo_path).resolve()

    def generate(self, since: Optional[str] = None, to: Optional[str] = None, max_count: int = 100) -> Changelog:
        args = ["git", "log", f"--max-count={max_count}", "--format=%H||%an||%ai||%s||%b"]
        if since:
            range_spec = f"{since}..{to or 'HEAD'}"
            args.insert(2, range_spec)
        elif to:
            args.insert(2, to)

        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=30,
                cwd=str(self.repo),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return Changelog()

        changelog = Changelog()
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("||", 4)
            if len(parts) < 4:
                continue
            chash, author, date, msg = parts[0], parts[1], parts[2], parts[3]
            body = parts[4] if len(parts) > 4 else ""

            entry = ChangelogEntry(hash=chash[:8], author=author, date=date, message=msg, body=body.strip())

            cm = _COMMIT_PATTERN.match(msg)
            if cm:
                entry.type = cm.group("type").lower()
                entry.scope = cm.group("scope") or ""
                entry.breaking = bool(cm.group("breaking"))
                entry.message = cm.group("message").strip()
            else:
                entry.type = "other"

            changelog.entries.append(entry)

        return changelog

    def generate_markdown(self, changelog: Changelog) -> str:
        if not changelog.entries:
            return "# Changelog\n\nNo entries found."

        lines = ["# Changelog", ""]
        if changelog.since_tag:
            lines.append(f"Since: `{changelog.since_tag}` → `{changelog.to_date or 'HEAD'}`")
            lines.append("")

        grouped: dict[str, list[ChangelogEntry]] = {}
        for entry in changelog.entries:
            grouped.setdefault(entry.type, []).append(entry)

        for type_key in ["feat", "fix", "perf", "refactor", "docs", "test", "ci", "chore", "other"]:
            if type_key not in grouped:
                continue
            label = _TYPE_LABELS.get(type_key, type_key.capitalize())
            lines.append(f"## {label}")
            lines.append("")
            for e in grouped[type_key]:
                breaking = " 💥" if e.breaking else ""
                scope = f"**{e.scope}:** " if e.scope else ""
                lines.append(f"- {scope}{e.message}{breaking} ({e.hash})")
            lines.append("")

        return "\n".join(lines)

    def generate_json(self, changelog: Changelog) -> str:
        import json
        data = {
            "since": changelog.since_tag,
            "entries": [
                {"hash": e.hash, "author": e.author, "date": e.date,
                 "message": e.message, "type": e.type, "scope": e.scope,
                 "breaking": e.breaking}
                for e in changelog.entries
            ],
        }
        return json.dumps(data, indent=2, default=str)

    def summary_text(self, changelog: Changelog) -> str:
        if not changelog.entries:
            return "No changelog entries."

        counts = {}
        for e in changelog.entries:
            counts[e.type] = counts.get(e.type, 0) + 1

        lines = [
            f"Changelog ({len(changelog.entries)} entries):",
            f"{'Type':<20} {'Count':<8}",
            "─" * 28,
        ]
        for t, c in sorted(counts.items(), key=lambda x: -x[1]):
            label = _TYPE_LABELS.get(t, t.capitalize())
            lines.append(f"{label:<20} {c:<8}")
        lines.append("")
        for e in changelog.entries[:10]:
            lines.append(f"  {e.hash} {e.message[:70]}")
        return "\n".join(lines)
