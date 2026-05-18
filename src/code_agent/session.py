from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code_agent import Agent, AgentConfig
from code_agent.llm.base import Message


@dataclass
class Session:
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
    def __init__(self, path: str | Path = ".code-agent-sessions"):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def _path(self, sid: str) -> Path:
        return self.path / f"{sid}.json"

    def save(self, session: Session) -> None:
        self._path(session.id).write_text(
            json.dumps(session.to_dict(), indent=2), "utf-8"
        )

    def load(self, sid: str) -> Session | None:
        p = self._path(sid)
        if not p.exists():
            return None
        return Session.from_dict(json.loads(p.read_text("utf-8")))

    def delete(self, sid: str) -> None:
        p = self._path(sid)
        if p.exists():
            p.unlink()

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for p in sorted(self.path.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text("utf-8"))
                msgs = data.get("messages", [])
                last = ""
                for m in reversed(msgs):
                    if m.get("role") == "assistant" and m.get("content", "").strip():
                        last = m["content"].strip()[:120]
                        break
                sessions.append({
                    "id": data.get("id", p.stem),
                    "task": data.get("task", "")[:80],
                    "created_at": data.get("created_at", ""),
                    "finished": data.get("finished", False),
                    "last_response": last,
                    "message_count": len([m for m in msgs if m.get("role") in ("user", "assistant")]),
                })
            except Exception:
                continue
        return sessions

    async def resume_agent(self, sid: str) -> Agent | None:
        session = self.load(sid)
        if not session:
            return None

        from code_agent.config import LLMConfig
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
