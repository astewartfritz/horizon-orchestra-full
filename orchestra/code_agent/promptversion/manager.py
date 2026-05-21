from __future__ import annotations

import datetime
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class PromptVersion:
    name: str = ""
    content: str = ""
    version: int = 1
    created_at: str = ""
    notes: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PromptVersionManager:
    """Version control for prompts. Track changes, compare versions, rollback."""

    def __init__(self, storage_path: str = ".agent-prompts"):
        self.path = Path(storage_path)
        self.path.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, content: str, notes: str = "", tags: list[str] | None = None) -> PromptVersion:
        existing = self.list_versions(name)
        next_version = (existing[-1].version + 1) if existing else 1

        version = PromptVersion(
            name=name,
            content=content,
            version=next_version,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
            notes=notes,
            tags=tags or [],
        )
        self._write(version)
        return version

    def get(self, name: str, version: int = -1) -> PromptVersion | None:
        versions = self.list_versions(name)
        if not versions:
            return None
        if version == -1:
            return versions[-1]
        for v in versions:
            if v.version == version:
                return v
        return None

    def list_versions(self, name: str) -> list[PromptVersion]:
        versions = []
        for f in sorted(self.path.glob(f"{name}-v*.json")):
            try:
                data = json.loads(f.read_text())
                versions.append(PromptVersion(**data))
            except (json.JSONDecodeError, OSError):
                pass
        return versions

    def list_prompts(self) -> list[str]:
        names = set()
        for f in self.path.glob("*.json"):
            parts = f.stem.rsplit("-v", 1)
            if len(parts) == 2:
                names.add(parts[0])
        return sorted(names)

    def diff(self, name: str, v1: int, v2: int) -> str:
        p1 = self.get(name, v1)
        p2 = self.get(name, v2)
        if not p1 or not p2:
            return "Version not found"

        lines1 = p1.content.split("\n")
        lines2 = p2.content.split("\n")

        diff_lines = [f"--- {name} v{v1}", f"+++ {name} v{v2}", ""]
        import difflib
        for line in difflib.unified_diff(lines1, lines2, lineterm=""):
            diff_lines.append(line)
        return "\n".join(diff_lines)

    def rollback(self, name: str, version: int) -> PromptVersion | None:
        target = self.get(name, version)
        if not target:
            return None
        # Create a new version with the old content
        return self.save(
            name=name,
            content=target.content,
            notes=f"Rollback to v{version}",
            tags=target.tags,
        )

    def delete(self, name: str, version: int = -1) -> bool:
        if version == -1:
            deleted = False
            for f in self.path.glob(f"{name}-v*.json"):
                f.unlink()
                deleted = True
            return deleted
        else:
            f = self.path / f"{name}-v{version}.json"
            if f.exists():
                f.unlink()
                return True
        return False

    def _write(self, version: PromptVersion) -> None:
        f = self.path / f"{version.name}-v{version.version}.json"
        f.write_text(json.dumps(version.to_dict(), indent=2))
