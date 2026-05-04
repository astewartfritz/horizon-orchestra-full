"""Slack connector — Bot token auth + Web API.

Requires: SLACK_BOT_TOKEN env var or pass {"token": "xoxb-..."} to connect().
Uses httpx for direct Slack Web API calls (no SDK dependency).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .base import Connector

__all__ = ["SlackConnector"]

log = logging.getLogger("orchestra.connectors.slack")

API_BASE = "https://slack.com/api"


class SlackConnector(Connector):
    """Slack integration via Web API."""

    name = "slack"
    description = "Post messages, search channels, and read threads in Slack."

    def __init__(self) -> None:
        self._token: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._token)

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", "") or os.environ.get("SLACK_BOT_TOKEN", "")
        if not self._token:
            log.error("No Slack token. Set SLACK_BOT_TOKEN or pass token.")
            return False
        # Verify
        result = await self._api("auth.test")
        if result.get("ok"):
            log.info("Slack connected as: %s in %s", result.get("user"), result.get("team"))
            return True
        log.error("Slack auth failed: %s", result.get("error"))
        self._token = ""
        return False

    async def disconnect(self) -> None:
        self._token = ""

    async def _api(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{API_BASE}/{method}", headers=headers, json=params or {},
            )
            return resp.json()

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._token:
            return {"error": "Slack not connected."}
        dispatch = {
            "slack_post_message": self._post_message,
            "slack_search_messages": self._search_messages,
            "slack_list_channels": self._list_channels,
            "slack_read_thread": self._read_thread,
            "slack_add_reaction": self._add_reaction,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    async def _post_message(self, params: dict[str, Any]) -> dict[str, Any]:
        channel = params.get("channel", "")
        message = params.get("message", "")
        thread_ts = params.get("thread_ts", "")
        if not channel or not message:
            return {"error": "channel and message are required"}
        body: dict[str, Any] = {"channel": channel, "text": message}
        if thread_ts:
            body["thread_ts"] = thread_ts
        result = await self._api("chat.postMessage", body)
        if result.get("ok"):
            return {
                "sent": True,
                "channel": result.get("channel"),
                "ts": result.get("ts"),
            }
        return {"error": result.get("error", "Unknown Slack error")}

    async def _search_messages(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        count = params.get("count", 10)
        if not query:
            return {"error": "query is required"}
        # search.messages requires a user token, not bot token
        # Fall back to conversations.history if needed
        result = await self._api("search.messages", {"query": query, "count": count})
        if result.get("ok"):
            matches = result.get("messages", {}).get("matches", [])
            return {
                "total": result.get("messages", {}).get("total", 0),
                "messages": [
                    {
                        "text": m.get("text", "")[:500],
                        "user": m.get("username", ""),
                        "channel": m.get("channel", {}).get("name", ""),
                        "ts": m.get("ts"),
                        "permalink": m.get("permalink"),
                    }
                    for m in matches[:count]
                ],
            }
        return {"error": result.get("error", "Search failed")}

    async def _list_channels(self, params: dict[str, Any]) -> dict[str, Any]:
        result = await self._api("conversations.list", {
            "types": "public_channel,private_channel",
            "limit": params.get("limit", 50),
        })
        if result.get("ok"):
            channels = result.get("channels", [])
            return {
                "count": len(channels),
                "channels": [
                    {
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "topic": c.get("topic", {}).get("value", ""),
                        "members": c.get("num_members"),
                    }
                    for c in channels
                ],
            }
        return {"error": result.get("error", "Failed to list channels")}

    async def _read_thread(self, params: dict[str, Any]) -> dict[str, Any]:
        channel = params.get("channel", "")
        ts = params.get("ts", "")
        if not channel or not ts:
            return {"error": "channel and ts are required"}
        result = await self._api("conversations.replies", {"channel": channel, "ts": ts, "limit": 50})
        if result.get("ok"):
            messages = result.get("messages", [])
            return {
                "count": len(messages),
                "messages": [
                    {"user": m.get("user", ""), "text": m.get("text", "")[:500], "ts": m.get("ts")}
                    for m in messages
                ],
            }
        return {"error": result.get("error", "Failed to read thread")}

    async def _add_reaction(self, params: dict[str, Any]) -> dict[str, Any]:
        channel = params.get("channel", "")
        ts = params.get("ts", "")
        emoji = params.get("emoji", "")
        if not all([channel, ts, emoji]):
            return {"error": "channel, ts, and emoji are required"}
        result = await self._api("reactions.add", {"channel": channel, "timestamp": ts, "name": emoji})
        return {"ok": result.get("ok", False)}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "slack_post_message",
                    "description": "Post a message to a Slack channel.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string", "description": "Channel name or ID"},
                            "message": {"type": "string", "description": "Message text"},
                            "thread_ts": {"type": "string", "description": "Thread timestamp to reply to"},
                        },
                        "required": ["channel", "message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "slack_search_messages",
                    "description": "Search Slack messages. Requires user token scope.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "count": {"type": "integer", "description": "Max results (default 10)"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "slack_list_channels",
                    "description": "List all Slack channels the bot has access to.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer", "description": "Max channels (default 50)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "slack_read_thread",
                    "description": "Read all messages in a Slack thread.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string", "description": "Channel ID"},
                            "ts": {"type": "string", "description": "Thread parent timestamp"},
                        },
                        "required": ["channel", "ts"],
                    },
                },
            },
        ]
