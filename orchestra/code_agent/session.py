from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestra.code_agent import Agent, AgentConfig
from orchestra.code_agent.llm.base import Message

_log = logging.getLogger(__name__)


@dataclass
class Session:
    """A chat session with conversation history and agent state.

    Backed by SessionStore (SQLite, same DB as MemoryStore).
    JSON-file persistence is deprecated — sessions auto-migrate on first access.
    """
    id: str = ""
    task: str = ""
    created_at: str = ""
    updated_at: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    result: str | None = None
    finished: bool = False

    @classmethod
    def create(cls, task: str, config: AgentConfig) -> Session:
        return cls(
            id=uuid.uuid4().hex[:12],
            task=task,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            config={
                "provider": config.llm.provider,
                "model": config.llm.model,
                "max_iterations": config.max_iterations,
                "workspace": config.workspace,
            },
        )

    def add_message(self, msg: Message) -> None:
        self.messages.append({
            "role": msg.role,
            "content": msg.content,
            "tool_call_id": msg.tool_call_id,
            "name": msg.name,
            "tool_calls": msg.tool_calls,
        })
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(**data)


class SessionManager:
    """Manages chat sessions backed by SessionStore (SQLite).

    Delegates to ``orchestra.code_agent.memory.session_store.SessionStore``
    which stores sessions in the same ``.agent-memory.db`` as MemoryStore,
    replacing the old JSON-file-per-session approach.

    Old JSON sessions are auto-migrated on first access (idempotent).
    The public API is unchanged — all 20+ call sites work without modification.
    """

    def __init__(self, path: str | Path = ".code-agent-sessions"):
        self._json_path = Path(path)
        self._store: Any = None  # Lazy-init SessionStore to avoid circular imports
        self._migrated = False

    def _get_store(self):
        if self._store is None:
            from orchestra.code_agent.memory.session_store import SessionStore
            self._store = SessionStore()
            if not self._migrated:
                migrated = self._store.migrate_from_json(self._json_path)
                if migrated:
                    _log.info("Migrated %d sessions to unified SQLite store", migrated)
                self._migrated = True
        return self._store

    def save(self, session: Session) -> None:
        from orchestra.code_agent.memory.session_store import StoredSession
        store = self._get_store()
        stored = StoredSession(
            id=session.id,
            task=session.task,
            created_at=session.created_at,
            updated_at=session.updated_at,
            messages=session.messages,
            config=session.config,
            state=session.state,
            result=session.result,
            finished=session.finished,
        )
        store.save(stored)

    def load(self, sid: str) -> Session | None:
        store = self._get_store()
        stored = store.load(sid)
        if not stored:
            return None
        return Session(
            id=stored.id,
            task=stored.task,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
            messages=stored.messages,
            config=stored.config,
            state=stored.state,
            result=stored.result,
            finished=stored.finished,
        )

    def delete(self, sid: str) -> None:
        store = self._get_store()
        store.delete(sid)

    def list_sessions(self) -> list[dict[str, Any]]:
        store = self._get_store()
        return store.list_sessions()

    async def resume_agent(self, sid: str) -> Agent | None:
        session = self.load(sid)
        if not session:
            return None

        from orchestra.code_agent.config import LLMConfig
        cfg = AgentConfig(
            llm=LLMConfig(
                provider=session.config.get("provider", "openai"),
                model=session.config.get("model", "gpt-4o"),
            ),
            max_iterations=session.config.get("max_iterations", 50),
            workspace=session.config.get("workspace"),
        )
        agent = Agent(cfg)

        agent.messages = [
            Message(**m) if isinstance(m, dict) else m
            for m in session.messages
        ]
        agent.state.finished = session.finished
        agent.state.result = session.result

        return agent
