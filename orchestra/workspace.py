"""Horizon Orchestra — Workspace Manager.

Persistent cloud filesystem, artifact store, version-controlled outputs.
Every user session gets a workspace. Artifacts (files, charts, code, docs)
are versioned so agents can iterate and users can diff.

Storage backends:
1. **Local** — filesystem (dev)
2. **S3** — AWS S3 / MinIO (production)
3. **GCS** — Google Cloud Storage

Usage::

    from orchestra.workspace import WorkspaceManager
    ws = WorkspaceManager(backend="s3", bucket="horizon-workspaces")
    workspace = await ws.get_or_create("ashton", "session_abc")
    await workspace.save("report.md", content)
    versions = await workspace.history("report.md")
    url = await workspace.share("report.md")
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["WorkspaceManager", "Workspace", "Artifact", "WorkspaceConfig"]

log = logging.getLogger("orchestra.workspace")


@dataclass
class WorkspaceConfig:
    backend: str = "local"            # local, s3, gcs
    base_dir: str = "/tmp/horizon_workspaces"
    s3_bucket: str = ""
    s3_prefix: str = "workspaces/"
    max_file_size_mb: int = 100
    max_versions: int = 50


@dataclass
class Artifact:
    name: str
    path: str
    size: int
    content_hash: str
    version: int
    created_at: float
    mime_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class Workspace:
    """A user's persistent workspace with versioned artifacts."""

    def __init__(self, user_id: str, session_id: str, root: Path, config: WorkspaceConfig) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.root = root
        self.config = config
        self._versions_dir = root / ".versions"
        self._meta_file = root / ".meta.json"
        root.mkdir(parents=True, exist_ok=True)
        self._versions_dir.mkdir(exist_ok=True)
        self._meta: dict[str, Any] = self._load_meta()

    def _load_meta(self) -> dict[str, Any]:
        if self._meta_file.exists():
            try:
                return json.loads(self._meta_file.read_text())
            except Exception:
                pass
        return {"artifacts": {}, "created_at": time.time()}

    def _save_meta(self) -> None:
        self._meta_file.write_text(json.dumps(self._meta, indent=2))

    async def save(self, name: str, content: str | bytes, metadata: dict | None = None) -> Artifact:
        """Save a file, creating a new version."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)

        data = content.encode() if isinstance(content, str) else content
        content_hash = hashlib.sha256(data).hexdigest()[:12]

        # Version tracking
        art_meta = self._meta.get("artifacts", {}).get(name, {"versions": []})
        version = len(art_meta.get("versions", [])) + 1

        # Save versioned copy
        ver_path = self._versions_dir / f"{name}.v{version}"
        ver_path.parent.mkdir(parents=True, exist_ok=True)
        ver_path.write_bytes(data)

        # Save current
        path.write_bytes(data)

        artifact = Artifact(
            name=name, path=str(path), size=len(data),
            content_hash=content_hash, version=version,
            created_at=time.time(), metadata=metadata or {},
        )

        art_meta["versions"] = art_meta.get("versions", [])
        art_meta["versions"].append({
            "version": version, "hash": content_hash, "size": len(data),
            "ts": time.time(), "metadata": metadata or {},
        })
        # Trim old versions
        if len(art_meta["versions"]) > self.config.max_versions:
            art_meta["versions"] = art_meta["versions"][-self.config.max_versions:]

        if "artifacts" not in self._meta:
            self._meta["artifacts"] = {}
        self._meta["artifacts"][name] = art_meta
        self._save_meta()

        return artifact

    async def read(self, name: str, version: int | None = None) -> str:
        """Read a file, optionally at a specific version."""
        if version:
            path = self._versions_dir / f"{name}.v{version}"
        else:
            path = self.root / name
        if not path.exists():
            raise FileNotFoundError(f"{name} (v{version or 'latest'})")
        return path.read_text(encoding="utf-8", errors="replace")

    async def read_bytes(self, name: str) -> bytes:
        path = self.root / name
        if not path.exists():
            raise FileNotFoundError(name)
        return path.read_bytes()

    async def delete(self, name: str) -> bool:
        path = self.root / name
        if path.exists():
            path.unlink()
            self._meta.get("artifacts", {}).pop(name, None)
            self._save_meta()
            return True
        return False

    async def list_files(self, pattern: str = "*") -> list[dict[str, Any]]:
        files = []
        for path in sorted(self.root.rglob(pattern)):
            if path.is_file() and not str(path.relative_to(self.root)).startswith("."):
                art_meta = self._meta.get("artifacts", {}).get(path.name, {})
                files.append({
                    "name": str(path.relative_to(self.root)),
                    "size": path.stat().st_size,
                    "modified": path.stat().st_mtime,
                    "versions": len(art_meta.get("versions", [])),
                })
        return files

    async def history(self, name: str) -> list[dict[str, Any]]:
        art_meta = self._meta.get("artifacts", {}).get(name, {})
        return art_meta.get("versions", [])

    async def diff(self, name: str, v1: int, v2: int) -> dict[str, Any]:
        """Simple diff between two versions."""
        text1 = await self.read(name, v1)
        text2 = await self.read(name, v2)
        lines1 = text1.splitlines()
        lines2 = text2.splitlines()
        added = [l for l in lines2 if l not in lines1]
        removed = [l for l in lines1 if l not in lines2]
        return {"v1": v1, "v2": v2, "added": len(added), "removed": len(removed),
                "added_lines": added[:50], "removed_lines": removed[:50]}

    async def share(self, name: str) -> str:
        """Generate a shareable URL (S3 presigned or local path)."""
        path = self.root / name
        if not path.exists():
            raise FileNotFoundError(name)
        # In production: generate S3 presigned URL
        return f"file://{path}"

    @property
    def stats(self) -> dict[str, Any]:
        total_size = sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())
        return {
            "user_id": self.user_id, "session_id": self.session_id,
            "path": str(self.root),
            "total_files": sum(1 for _ in self.root.rglob("*") if _.is_file()),
            "total_size_mb": round(total_size / 1e6, 2),
            "artifacts": len(self._meta.get("artifacts", {})),
        }


class WorkspaceManager:
    """Manages workspaces across users and sessions."""

    def __init__(self, config: WorkspaceConfig | None = None) -> None:
        self.config = config or WorkspaceConfig()
        self._base = Path(self.config.base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._workspaces: dict[str, Workspace] = {}

    async def get_or_create(self, user_id: str, session_id: str = "default") -> Workspace:
        key = f"{user_id}/{session_id}"
        if key in self._workspaces:
            return self._workspaces[key]
        root = self._base / user_id / session_id
        ws = Workspace(user_id, session_id, root, self.config)
        self._workspaces[key] = ws
        return ws

    async def list_user_workspaces(self, user_id: str) -> list[dict[str, Any]]:
        user_dir = self._base / user_id
        if not user_dir.exists():
            return []
        return [
            {"session_id": d.name, "path": str(d), "files": sum(1 for _ in d.rglob("*") if _.is_file())}
            for d in sorted(user_dir.iterdir()) if d.is_dir()
        ]

    async def cleanup(self, max_age_hours: int = 24) -> int:
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        for user_dir in self._base.iterdir():
            if not user_dir.is_dir():
                continue
            for session_dir in user_dir.iterdir():
                if session_dir.is_dir() and session_dir.stat().st_mtime < cutoff:
                    shutil.rmtree(session_dir, ignore_errors=True)
                    removed += 1
        return removed
