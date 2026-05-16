from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Space:
    id: str
    name: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    session_ids: list[str] = field(default_factory=list)
    instructions: str = ""
    pinned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description[:200],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "session_count": len(self.session_ids),
            "instructions": self.instructions[:500] if self.instructions else "",
            "pinned": self.pinned,
        }


class SpaceManager:
    """Hubs for grouping related chats by project or topic."""

    def __init__(self, storage_dir: str = ".agent-spaces"):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._spaces: dict[str, Space] = {}
        self._load()

    def _path(self, sid: str) -> Path:
        return self._dir / f"{sid}.json"

    def _load(self) -> None:
        for p in self._dir.glob("*.json"):
            try:
                data = json.loads(p.read_text("utf-8"))
                s = Space(**data)
                self._spaces[s.id] = s
            except Exception:
                pass

    def _save(self, space: Space) -> None:
        self._path(space.id).write_text(json.dumps({
            "id": space.id,
            "name": space.name,
            "description": space.description,
            "created_at": space.created_at,
            "updated_at": space.updated_at,
            "session_ids": space.session_ids,
            "instructions": space.instructions,
            "pinned": space.pinned,
        }, indent=2), "utf-8")

    def create(self, name: str, description: str = "", instructions: str = "") -> Space:
        space = Space(
            id=str(uuid.uuid4())[:12],
            name=name,
            description=description,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            instructions=instructions,
        )
        self._spaces[space.id] = space
        self._save(space)
        return space

    def get(self, sid: str) -> Space | None:
        return self._spaces.get(sid)

    def list(self) -> list[dict[str, Any]]:
        spaces = sorted(self._spaces.values(), key=lambda s: s.updated_at, reverse=True)
        return [s.to_dict() for s in spaces]

    def update(self, sid: str, **kwargs) -> Space | None:
        space = self._spaces.get(sid)
        if not space:
            return None
        for k, v in kwargs.items():
            if hasattr(space, k):
                setattr(space, k, v)
        space.updated_at = datetime.now().isoformat()
        self._save(space)
        return space

    def delete(self, sid: str) -> bool:
        if sid in self._spaces:
            del self._spaces[sid]
            p = self._path(sid)
            if p.exists():
                p.unlink()
            return True
        return False

    def add_session(self, sid: str, session_id: str) -> bool:
        space = self._spaces.get(sid)
        if not space:
            return False
        if session_id not in space.session_ids:
            space.session_ids.append(session_id)
            space.updated_at = datetime.now().isoformat()
            self._save(space)
        return True

    def remove_session(self, sid: str, session_id: str) -> bool:
        space = self._spaces.get(sid)
        if not space:
            return False
        space.session_ids = [s for s in space.session_ids if s != session_id]
        space.updated_at = datetime.now().isoformat()
        self._save(space)
        return True
