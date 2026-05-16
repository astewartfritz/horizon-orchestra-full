from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional


class ChannelType(Enum):
    CLI = "cli"
    SLACK = "slack"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    WEB = "web"
    WHATSAPP = "whatsapp"
    REPL = "repl"


@dataclass
class Message:
    content: str
    channel: ChannelType
    sender: str = "user"
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)
    attachments: list[str] = field(default_factory=list)


class ChannelManager:
    def __init__(self):
        self._handlers: dict[ChannelType, list[Callable]] = {}
        self._sessions: dict[str, list[Message]] = {}
        self._agents: dict[str, Any] = {}
        self.logger = logging.getLogger("channels")

    def register(self, channel: ChannelType, handler: Callable) -> None:
        self._handlers.setdefault(channel, []).append(handler)

    def send(self, channel: ChannelType, message: str, session_id: str = "default") -> None:
        msg = Message(content=message, channel=channel, sender="agent")
        self._sessions.setdefault(session_id, []).append(msg)

    def receive(self, channel: ChannelType, content: str, sender: str = "user", session_id: str = "default") -> Message:
        msg = Message(content=content, channel=channel, sender=sender)
        self._sessions.setdefault(session_id, []).append(msg)

        for handler in self._handlers.get(channel, []):
            try:
                handler(msg)
            except Exception as e:
                self.logger.error(f"Handler error on {channel}: {e}")

        return msg

    def get_history(self, session_id: str = "default", limit: int = 50) -> list[Message]:
        return self._sessions.get(session_id, [])[-limit:]

    def clear_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def bind_agent(self, session_id: str, agent: Any) -> None:
        self._agents[session_id] = agent

    async def process_message(self, session_id: str, content: str) -> str:
        agent = self._agents.get(session_id)
        if agent is None:
            return f"No agent bound to session '{session_id}'"

        self.receive(ChannelType.CLI, content, session_id=session_id)

        try:
            if hasattr(agent, "run_async"):
                result = await agent.run_async(content)
            elif hasattr(agent, "run"):
                result = await asyncio.to_thread(agent.run, content)
            else:
                result = str(agent)
            self.send(ChannelType.CLI, str(result)[:2000], session_id)
            return str(result)
        except Exception as e:
            err = f"Error: {e}"
            self.send(ChannelType.CLI, err, session_id)
            return err

    def export_session(self, session_id: str, path: str) -> None:
        messages = self._sessions.get(session_id, [])
        data = [{"sender": m.sender, "channel": m.channel.value, "content": m.content, "timestamp": m.timestamp.isoformat()} for m in messages]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
