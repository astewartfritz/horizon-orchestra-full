"""Message ingestion pipeline — normalizes multi-channel input and routes to the agent."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from code_agent import Agent, AgentConfig
from code_agent.channels.manager import ChannelType
from code_agent.channels.adapters import InboundMessage, get_adapter


class MessageRouter:
    """Routes normalized messages from any channel to the agent.

    Handles session management, image validation, and error responses.
    """

    def __init__(self, agent_config: AgentConfig | None = None):
        self.config = agent_config or AgentConfig()
        self._agents: dict[str, Agent] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self.logger = logging.getLogger("orchestra.router")

    def _get_agent(self, session_id: str) -> Agent:
        if session_id not in self._agents:
            self._agents[session_id] = Agent(self.config)
        return self._agents[session_id]

    async def route(self, msg: InboundMessage) -> str:
        """Route a normalized message to the agent."""
        session_id = msg.thread_id or msg.sender_id or uuid.uuid4().hex[:12]

        # Validate image attachments — some models don't support vision
        if msg.has_image:
            agent = self._get_agent(session_id)
            model = agent.config.llm.model
            vision_models = {"llava", "bakllava", "gpt-4o", "gpt-4o-mini", "claude-sonnet-4-20250514"}
            if model not in vision_models:
                return (
                    f"Cannot read \"{msg.attachments[0].get('name', 'image')}\" "
                    f"({model} does not support image input). "
                    f"Inform the user and try again without an image, "
                    f"or switch to a vision-capable model like llava or gpt-4o."
                )

        # Route to agent
        agent = self._get_agent(session_id)
        try:
            result = await agent.run(msg.content, stream=True)
            self._sessions.setdefault(session_id, {"turns": 0})["turns"] += 1
            return result
        except Exception as e:
            self.logger.error("Agent error for session %s: %s", session_id, e)
            return f"Error processing message: {e}"

    async def handle_webhook(self, channel: ChannelType, raw_body: dict) -> dict[str, Any]:
        """Handle a webhook payload from any channel."""
        adapter = get_adapter(channel)
        msg = adapter.normalize(raw_body)
        if not msg:
            return {"status": "ignored", "reason": "unrecognized_message_format"}

        response = await self.route(msg)

        return {
            "status": "ok",
            "channel": channel.value,
            "response": response[:500],
            "session_id": msg.thread_id or msg.sender_id,
        }
