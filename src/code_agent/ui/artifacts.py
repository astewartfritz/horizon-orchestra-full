from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Artifact:
    id: str
    type: str  # chart, file, report, code, image, map
    title: str
    content: str = ""
    file_path: str = ""
    session_id: str = ""
    space_id: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title[:200],
            "content": (self.content[:500] if self.content else "")[:500],
            "file_path": self.file_path,
            "session_id": self.session_id,
            "space_id": self.space_id,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "size_bytes": self.size_bytes,
        }


class ArtifactManager:
    """Generated outputs: charts, files, reports, code, images, maps."""

    def __init__(self, storage_dir: str = ".agent-artifacts"):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._artifacts: dict[str, Artifact] = {}
        self._load()

    def _path(self, aid: str) -> Path:
        return self._dir / f"{aid}.json"

    def _load(self) -> None:
        for p in self._dir.glob("*.json"):
            try:
                data = json.loads(p.read_text("utf-8"))
                a = Artifact(**data)
                self._artifacts[a.id] = a
            except Exception:
                pass

    def _save(self, artifact: Artifact) -> None:
        self._path(artifact.id).write_text(json.dumps({
            "id": artifact.id,
            "type": artifact.type,
            "title": artifact.title,
            "content": artifact.content,
            "file_path": artifact.file_path,
            "session_id": artifact.session_id,
            "space_id": artifact.space_id,
            "created_at": artifact.created_at,
            "metadata": artifact.metadata,
            "size_bytes": artifact.size_bytes,
        }, indent=2), "utf-8")

    def create(self, artifact_type: str, title: str, content: str = "",
               session_id: str = "", space_id: str = "",
               file_path: str = "", metadata: dict | None = None) -> Artifact:
        a = Artifact(
            id=str(uuid.uuid4())[:12],
            type=artifact_type,
            title=title,
            content=content,
            session_id=session_id,
            space_id=space_id,
            file_path=file_path,
            created_at=datetime.now().isoformat(),
            metadata=metadata or {},
            size_bytes=len(content.encode("utf-8")) if content else 0,
        )
        self._artifacts[a.id] = a
        self._save(a)
        return a

    def get(self, aid: str) -> Artifact | None:
        return self._artifacts.get(aid)

    def list(self, session_id: str = "", space_id: str = "",
             limit: int = 50) -> list[dict[str, Any]]:
        items = list(self._artifacts.values())
        if session_id:
            items = [a for a in items if a.session_id == session_id]
        if space_id:
            items = [a for a in items if a.space_id == space_id]
        items.sort(key=lambda a: a.created_at, reverse=True)
        return [a.to_dict() for a in items[:limit]]

    def delete(self, aid: str) -> bool:
        if aid in self._artifacts:
            del self._artifacts[aid]
            p = self._path(aid)
            if p.exists():
                p.unlink()
            return True
        return False

    def save_file(self, artifact_id: str, data: bytes, filename: str) -> str:
        """Save a file artifact to disk."""
        file_dir = self._dir / "files"
        file_dir.mkdir(exist_ok=True)
        path = file_dir / filename
        path.write_bytes(data)
        artifact = self._artifacts.get(artifact_id)
        if artifact:
            artifact.file_path = str(path)
            artifact.size_bytes = len(data)
            self._save(artifact)
        return str(path)
