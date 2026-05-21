from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class BackupEntry:
    name: str
    timestamp: str = ""
    size_bytes: int = 0
    path: str = ""
    modules: list[str] = field(default_factory=list)
    files: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class RestoreResult:
    success: bool
    entry: Optional[BackupEntry] = None
    files_restored: int = 0
    errors: list[str] = field(default_factory=list)


_BACKUP_DIRS = {
    "sessions": ".code-agent-sessions",
    "logs": ".agent-logs",
    "profiles": ".agent-profiles",
    "knowledge": ".code-agent-knowledge.db",
    "learnings": ".agent-learnings.json",
    "config": "code-agent.json",
    "traces": ".agent-traces.jsonl",
    "calendar": ".agent-calendar",
}

_BACKUP_ROOT = Path.home() / ".agent-backups"


class BackupManager:
    def __init__(self, backup_root: str = ""):
        self.root = Path(backup_root) if backup_root else _BACKUP_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, name: str = "", project_root: str = ".", modules: Optional[list[str]] = None) -> BackupEntry:
        if not name:
            name = f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        backup_dir = self.root / name
        backup_dir.mkdir(parents=True, exist_ok=True)
        proj = Path(project_root).resolve()

        module_list = modules or list(_BACKUP_DIRS.keys())
        total_files = 0
        total_size = 0
        manifest = {"name": name, "timestamp": datetime.now().isoformat(), "modules": module_list, "files": []}

        for module in module_list:
            rel_path = _BACKUP_DIRS.get(module)
            if not rel_path:
                continue
            src = proj / rel_path
            if src.exists():
                dst = backup_dir / rel_path
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(dst))
                    total_files += 1
                    total_size += src.stat().st_size
                    manifest["files"].append(str(rel_path))
                elif src.is_dir():
                    shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
                    for f in src.rglob("*"):
                        if f.is_file():
                            total_files += 1
                            total_size += f.stat().st_size
                            manifest["files"].append(str(f.relative_to(proj)))

        manifest["total_files"] = total_files
        manifest["total_size"] = total_size
        (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        archive_path = str(backup_dir) + ".tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(str(backup_dir), arcname=name)

        entry = BackupEntry(
            name=name,
            timestamp=manifest["timestamp"],
            size_bytes=total_size,
            path=archive_path,
            modules=module_list,
            files=total_files,
        )
        self._save_meta(entry)
        return entry

    def list(self) -> list[BackupEntry]:
        entries = self._load_meta()
        return sorted(entries, key=lambda e: e.timestamp, reverse=True)

    def restore(self, name: str, target_dir: str = ".", modules: Optional[list[str]] = None) -> RestoreResult:
        entry = next((e for e in self.list() if e.name == name), None)
        if not entry:
            archive_path = self.root / f"{name}.tar.gz"
            if not archive_path.exists():
                return RestoreResult(success=False, errors=[f"Backup '{name}' not found"])
            entry = BackupEntry(name=name, path=str(archive_path))

        target = Path(target_dir).resolve()
        temp_dir = Path(tempfile.mkdtemp())

        try:
            if entry.path.endswith(".tar.gz"):
                with tarfile.open(entry.path, "r:gz") as tar:
                    tar.extractall(path=str(temp_dir))

            extract_root = temp_dir / name
            if not extract_root.exists():
                extract_root = temp_dir

            module_list = modules or list(_BACKUP_DIRS.keys())
            files_restored = 0
            errors = []

            for module in module_list:
                rel_path = _BACKUP_DIRS.get(module)
                if not rel_path:
                    continue
                src = extract_root / rel_path
                dst = target / rel_path
                if src.exists():
                    if src.is_file():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(src), str(dst))
                        files_restored += 1
                    elif src.is_dir():
                        shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
                        files_restored += sum(1 for _ in src.rglob("*") if _.is_file())

            shutil.rmtree(str(temp_dir))
            return RestoreResult(success=True, entry=entry, files_restored=files_restored)

        except Exception as e:
            shutil.rmtree(str(temp_dir), ignore_errors=True)
            return RestoreResult(success=False, errors=[str(e)])

    def delete(self, name: str) -> bool:
        entries = [e for e in self.list() if e.name != name]
        self._save_meta_list(entries)
        archive = self.root / f"{name}.tar.gz"
        if archive.exists():
            archive.unlink()
            return True
        dir_path = self.root / name
        if dir_path.exists():
            shutil.rmtree(str(dir_path))
            return True
        return False

    def _save_meta(self, entry: BackupEntry) -> None:
        entries = self._load_meta()
        entries = [e for e in entries if e.name != entry.name]
        entries.append(entry)
        self._save_meta_list(entries)

    def _load_meta(self) -> list[BackupEntry]:
        meta_file = self.root / "backups.json"
        if not meta_file.exists():
            return []
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            return [BackupEntry(**e) for e in data]
        except (json.JSONDecodeError, Exception):
            return []

    def _save_meta_list(self, entries: list[BackupEntry]) -> None:
        meta_file = self.root / "backups.json"
        meta_file.write_text(
            json.dumps([asdict(e) for e in entries], indent=2, default=str),
            encoding="utf-8",
        )

    def summary_text(self) -> str:
        entries = self.list()
        if not entries:
            return "No backups found."
        lines = [
            f"Backups ({len(entries)}):",
            f"{'Name':<30} {'Date':<25} {'Size':<12} {'Files':<8}",
            "─" * 75,
        ]
        for e in entries:
            sz = f"{e.size_bytes / 1024:.1f} KB" if e.size_bytes < 1048576 else f"{e.size_bytes / 1048576:.1f} MB"
            ts = e.timestamp[:19] if len(e.timestamp) > 19 else e.timestamp
            lines.append(f"{e.name:<30} {ts:<25} {sz:<12} {e.files:<8}")
        return "\n".join(lines)
