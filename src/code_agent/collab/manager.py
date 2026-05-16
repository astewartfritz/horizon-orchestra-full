from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from code_agent.agent import Agent
from code_agent.config import AgentConfig


ROLE_DESCRIPTIONS = {
    "lead": "Coordinates the team, assigns subtasks, synthesizes results.",
    "writer": "Writes and edits code. Implements the solution.",
    "reviewer": "Reviews code for bugs, security, and best practices.",
    "tester": "Writes and runs tests. Verifies correctness.",
    "researcher": "Researches APIs, libraries, and approaches.",
    "documenter": "Documents the code and writes explanations.",
}


@dataclass
class Collaborator:
    id: str = ""
    name: str = ""
    role: str = "writer"
    agent: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "role": self.role}


@dataclass
class CollabSession:
    id: str = ""
    task: str = ""
    collaborators: list[Collaborator] = field(default_factory=list)
    messages: list[dict[str, str]] = field(default_factory=list)
    status: str = "created"
    output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "task": self.task,
                "collaborators": [c.to_dict() for c in self.collaborators],
                "status": self.status}


class CollaborationManager:
    """Multiple agents collaborate on a shared task via message passing."""

    def __init__(self, storage_path: str = ".agent-collab"):
        self.path = Path(storage_path)
        self.path.mkdir(parents=True, exist_ok=True)

    def create_session(self, task: str, roles: list[str] | None = None) -> CollabSession:
        session = CollabSession(
            id=str(uuid.uuid4())[:8],
            task=task,
        )
        roles = roles or ["lead", "writer", "reviewer"]
        for role in roles:
            cfg = AgentConfig(name=f"{role.title()}-Agent")
            agent = Agent(cfg)
            session.collaborators.append(Collaborator(
                id=str(uuid.uuid4())[:8],
                name=f"{role.title()}-Agent",
                role=role,
                agent=agent,
            ))
        self._save(session)
        return session

    async def run_session(self, session: CollabSession) -> CollabSession:
        session.status = "running"

        # Phase 1: Lead delegates
        lead = next((c for c in session.collaborators if c.role == "lead"), session.collaborators[0])
        others = [c for c in session.collaborators if c.id != lead.id]

        lead_prompt = (
            f"Task: {session.task}\n\n"
            f"You are the lead coordinator. Break this task into subtasks for your team:\n"
            + "\n".join(f"- {c.name} ({c.role}): {ROLE_DESCRIPTIONS.get(c.role, '')}"
                        for c in others) +
            "\n\nAssign specific subtasks to each team member."
        )
        plan = await lead.agent.run(lead_prompt)
        session.messages.append({"role": "lead", "content": plan})

        # Phase 2: Each collaborator contributes
        contributions = {}
        for collab in others:
            ctx = "\n".join(f"[{m['role']}] {m['content'][:200]}" for m in session.messages[-3:])
            role_desc = ROLE_DESCRIPTIONS.get(collab.role, "")
            prompt = (
                f"Task: {session.task}\n\n"
                f"Your role: {collab.name} ({collab.role})\n{role_desc}\n\n"
                f"Context from team:\n{ctx}\n\n"
                f"Provide your contribution to this task."
            )
            contribution = await collab.agent.run(prompt)
            contributions[collab.role] = contribution
            session.messages.append({"role": collab.role, "content": contribution[:500]})

        # Phase 3: Lead synthesizes
        contribs_str = "\n\n".join(f"=== {role} ===\n{text}" for role, text in contributions.items())
        synthesis = await lead.agent.run(
            f"Original task: {session.task}\n\n"
            f"Team contributions:\n{contribs_str}\n\n"
            f"Synthesize these into a final coherent output."
        )
        session.output = synthesis
        session.messages.append({"role": "lead", "content": f"SYNTHESIS:\n{synthesis[:1000]}"})
        session.status = "completed"
        self._save(session)
        return session

    def load_session(self, session_id: str) -> CollabSession | None:
        f = self.path / f"{session_id}.json"
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text())
            session = CollabSession(id=data["id"], task=data["task"], status=data.get("status", ""))
            for cd in data.get("collaborators", []):
                cfg = AgentConfig(name=cd.get("name", "Agent"))
                session.collaborators.append(Collaborator(
                    id=cd["id"], name=cd["name"], role=cd.get("role", "writer"),
                    agent=Agent(cfg),
                ))
            session.messages = data.get("messages", [])
            session.output = data.get("output", "")
            return session
        except (json.JSONDecodeError, KeyError):
            return None

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for f in self.path.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                sessions.append({"id": data["id"], "task": data.get("task", "")[:60],
                                "status": data.get("status", ""),
                                "collaborators": len(data.get("collaborators", []))})
            except (json.JSONDecodeError, OSError):
                pass
        return sessions

    def _save(self, session: CollabSession) -> None:
        f = self.path / f"{session.id}.json"
        f.write_text(json.dumps(session.to_dict(), indent=2))
