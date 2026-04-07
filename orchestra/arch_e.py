"""Architecture E — Full Production Stack.

Complete system integrating:

* **API Gateway** — FastAPI server with WebSocket streaming, auth, sessions.
* **Orchestrator Service** — Architecture A or C as the execution backend.
* **Connector Layer** — Pluggable external service integrations (Gmail,
  Slack, GitHub, Notion, etc.).
* **Task Queue** — Async job dispatch for background and scheduled work.
* **Memory Service** — Persistent cross-session memory with embedding search.
* **Code Sandbox** — Isolated subprocess execution (Docker in production).

This module provides:
1. ``ProductionOrchestrator`` — wires A/C + memory + connectors together.
2. ``ConnectorRegistry`` — pluggable external service integrations.
3. ``TaskQueue`` — asyncio-based task queue (swap to Celery/Temporal in prod).
4. ``create_app()`` — FastAPI application factory.
5. Docker Compose template generation.

Usage (development)::

    from orchestra.arch_e import ProductionOrchestrator
    orch = ProductionOrchestrator(user_id="ashton")
    result = await orch.run("Search my Gmail for investor emails and summarise")

Usage (server)::

    uvicorn orchestra.arch_e:app --host 0.0.0.0 --port 3000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

from .router import ModelRouter
from .agent_loop import (
    AgentConfig,
    AgentEvent,
    AgentLoop,
    FinalAnswerEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolRegistry,
    create_default_tools,
)
from .memory import (
    MemoryStore,
    MemoryManager,
    SessionContext,
    register_memory_tools,
)
from .arch_a import MonolithicAgent, MonolithicConfig
from .arch_c import SwarmAgent, SwarmConfig
from .perplexity import PerplexitySearch, PerplexityAgent
from .security import SecurityMiddleware, standard_policy
from .opus4_provider import Opus4Provider, Opus4Config
try:
    from .stripe_billing import BillingManager, PricingTier, NullBillingManager
    from .usage_tracker import UsageTracker
except ImportError:
    BillingManager = None  # type: ignore[assignment,misc]
    PricingTier = None  # type: ignore[assignment,misc]
    NullBillingManager = None  # type: ignore[assignment,misc]
    UsageTracker = None  # type: ignore[assignment,misc]

__all__ = [
    "ProductionOrchestrator",
    "ProductionConfig",
    "Connector",
    "ConnectorRegistry",
    "TaskQueue",
    "TaskJob",
    "create_app",
    "generate_docker_compose",
]

log = logging.getLogger("orchestra.arch_e")


# ===========================================================================
# Configuration
# ===========================================================================

@dataclass
class ProductionConfig:
    """Master configuration for Architecture E."""
    # -- execution mode --
    architecture: str = "A"               # "A" (monolithic) or "C" (swarm)
    model: str = "kimi-k2.5"
    user_id: str = "default"

    # -- memory --
    memory_db: str = ""                   # SQLite path; empty = default
    auto_extract_memory: bool = True

    # -- infrastructure --
    workspace_dir: str = "/tmp/horizon_workspace"
    host: str = "0.0.0.0"
    port: int = 3000
    api_key: str = ""                     # for authenticating inbound requests
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    # -- task queue --
    max_concurrent_jobs: int = 20
    job_timeout: int = 600                # seconds

    # -- logging --
    verbose: bool = False
    enable_security: bool = True
    security_policy: str = "standard"


# ===========================================================================
# Connector system
# ===========================================================================

class Connector(ABC):
    """Base class for external service integrations."""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with the service."""
        ...

    @abstractmethod
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an action on the service."""
        ...

    @abstractmethod
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas for this connector."""
        ...

    @property
    def connected(self) -> bool:
        return False


class GmailConnector(Connector):
    """Gmail integration (requires google-auth + gmail API)."""

    name = "gmail"
    description = "Search, read, and send emails via Gmail."

    def __init__(self) -> None:
        self._connected = False
        self._token = ""

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, credentials: dict[str, str]) -> bool:
        # In production: OAuth2 flow with google-auth-oauthlib
        self._token = credentials.get("token", "")
        self._connected = bool(self._token)
        return self._connected

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "Gmail not connected. Provide OAuth token via connect()."}
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        base = "https://gmail.googleapis.com/gmail/v1/users/me"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                if action == "gmail_search":
                    q = params.get("query", "")
                    max_r = params.get("max_results", 10)
                    resp = await client.get(f"{base}/messages", headers=headers, params={"q": q, "maxResults": max_r})
                    data = resp.json()
                    messages = []
                    for msg in data.get("messages", [])[:max_r]:
                        detail = await client.get(f"{base}/messages/{msg['id']}", headers=headers, params={"format": "metadata", "metadataHeaders": ["Subject","From","Date"]})
                        d = detail.json()
                        hdrs = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
                        messages.append({"id": msg["id"], "subject": hdrs.get("Subject",""), "from": hdrs.get("From",""), "date": hdrs.get("Date",""), "snippet": d.get("snippet","")})
                    return {"messages": messages, "count": len(messages)}
                elif action == "gmail_send":
                    import base64, email.mime.text
                    msg = email.mime.text.MIMEText(params.get("body", ""))
                    msg["To"] = params.get("to", "")
                    msg["Subject"] = params.get("subject", "")
                    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
                    resp = await client.post(f"{base}/messages/send", headers=headers, json={"raw": raw})
                    return resp.json()
                elif action == "gmail_get":
                    resp = await client.get(f"{base}/messages/{params['message_id']}", headers=headers)
                    return resp.json()
                elif action == "gmail_mark_read":
                    resp = await client.post(f"{base}/messages/{params['message_id']}/modify", headers=headers, json={"removeLabelIds": ["UNREAD"]})
                    return resp.json()
                elif action == "gmail_trash":
                    resp = await client.post(f"{base}/messages/{params['message_id']}/trash", headers=headers)
                    return resp.json()
                else:
                    return {"error": f"Unknown Gmail action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "gmail_search",
                "description": "Search Gmail for emails matching a query. Returns subject, from, date, snippet.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "Gmail search query (e.g. 'from:boss@company.com is:unread')"},
                    "max_results": {"type": "integer", "description": "Max results to return (default 10)"},
                }, "required": ["query"]}}},
            {"type": "function", "function": {"name": "gmail_send",
                "description": "Send an email via Gmail.",
                "parameters": {"type": "object", "properties": {
                    "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                }, "required": ["to", "subject", "body"]}}},
            {"type": "function", "function": {"name": "gmail_get",
                "description": "Get the full content of a Gmail message by ID.",
                "parameters": {"type": "object", "properties": {
                    "message_id": {"type": "string"},
                }, "required": ["message_id"]}}},
            {"type": "function", "function": {"name": "gmail_mark_read",
                "description": "Mark a Gmail message as read.",
                "parameters": {"type": "object", "properties": {
                    "message_id": {"type": "string"},
                }, "required": ["message_id"]}}},
            {"type": "function", "function": {"name": "gmail_trash",
                "description": "Move a Gmail message to trash.",
                "parameters": {"type": "object", "properties": {
                    "message_id": {"type": "string"},
                }, "required": ["message_id"]}}},
        ]


class SlackConnector(Connector):
    """Slack integration."""

    name = "slack"
    description = "Post messages and search Slack channels."

    def __init__(self) -> None:
        self._connected = False
        self._token = ""

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", "")
        self._connected = bool(self._token)
        return self._connected

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "Slack not connected. Provide bot token via connect()."}
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                if action == "slack_post":
                    resp = await client.post("https://slack.com/api/chat.postMessage", headers=headers,
                        json={"channel": params.get("channel", ""), "text": params.get("message", ""),
                              "blocks": params.get("blocks", None)})
                    return resp.json()
                elif action == "slack_search":
                    resp = await client.get("https://slack.com/api/search.messages", headers=headers,
                        params={"query": params.get("query",""), "count": params.get("limit",20)})
                    return resp.json()
                elif action == "slack_list_channels":
                    resp = await client.get("https://slack.com/api/conversations.list", headers=headers,
                        params={"limit": params.get("limit", 100), "types": "public_channel,private_channel"})
                    return resp.json()
                elif action == "slack_get_history":
                    resp = await client.get("https://slack.com/api/conversations.history", headers=headers,
                        params={"channel": params.get("channel",""), "limit": params.get("limit",50)})
                    return resp.json()
                elif action == "slack_reply":
                    resp = await client.post("https://slack.com/api/chat.postMessage", headers=headers,
                        json={"channel": params.get("channel",""), "text": params.get("message",""),
                              "thread_ts": params.get("thread_ts","")})
                    return resp.json()
                elif action == "slack_react":
                    resp = await client.post("https://slack.com/api/reactions.add", headers=headers,
                        json={"channel": params.get("channel",""), "name": params.get("emoji","thumbsup"),
                              "timestamp": params.get("ts","")})
                    return resp.json()
                else:
                    return {"error": f"Unknown Slack action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "slack_post",
                "description": "Post a message to a Slack channel.",
                "parameters": {"type": "object", "properties": {
                    "channel": {"type": "string", "description": "Channel name or ID (e.g. #general or C1234567)"},
                    "message": {"type": "string"},
                    "blocks": {"type": "array", "items": {"type": "object"}, "description": "Optional Block Kit blocks for rich formatting"},
                }, "required": ["channel", "message"]}}},
            {"type": "function", "function": {"name": "slack_search",
                "description": "Search messages across Slack.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"}, "limit": {"type": "integer"},
                }, "required": ["query"]}}},
            {"type": "function", "function": {"name": "slack_list_channels",
                "description": "List available Slack channels.",
                "parameters": {"type": "object", "properties": {
                    "limit": {"type": "integer", "description": "Max channels (default 100)"},
                }, "required": []}}},
            {"type": "function", "function": {"name": "slack_get_history",
                "description": "Get message history from a Slack channel.",
                "parameters": {"type": "object", "properties": {
                    "channel": {"type": "string"}, "limit": {"type": "integer"},
                }, "required": ["channel"]}}},
            {"type": "function", "function": {"name": "slack_reply",
                "description": "Reply to a thread in Slack.",
                "parameters": {"type": "object", "properties": {
                    "channel": {"type": "string"}, "message": {"type": "string"},
                    "thread_ts": {"type": "string", "description": "Timestamp of the parent message to reply to"},
                }, "required": ["channel", "message", "thread_ts"]}}},
            {"type": "function", "function": {"name": "slack_react",
                "description": "Add an emoji reaction to a Slack message.",
                "parameters": {"type": "object", "properties": {
                    "channel": {"type": "string"}, "emoji": {"type": "string", "description": "Emoji name without colons (e.g. thumbsup)"},
                    "ts": {"type": "string", "description": "Message timestamp"},
                }, "required": ["channel", "emoji", "ts"]}}},
        ]


class GitHubConnector(Connector):
    """GitHub integration."""

    name = "github"
    description = "Manage repos, issues, PRs, and code on GitHub."

    def __init__(self) -> None:
        self._connected = False
        self._token = ""

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", os.environ.get("GITHUB_TOKEN", ""))
        self._connected = bool(self._token)
        return self._connected

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "GitHub not connected. Provide token via connect()."}
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        base = "https://api.github.com"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                if action == "github_create_issue":
                    repo = params.get("repo","")
                    resp = await client.post(f"{base}/repos/{repo}/issues", headers=headers,
                        json={"title": params.get("title",""), "body": params.get("body",""),
                              "labels": params.get("labels",[]), "assignees": params.get("assignees",[])})
                    return resp.json()
                elif action == "github_search_code":
                    q = params.get("query","")
                    if params.get("repo"):
                        q += f" repo:{params['repo']}"
                    resp = await client.get(f"{base}/search/code", headers=headers, params={"q": q, "per_page": 10})
                    return resp.json()
                elif action == "github_list_prs":
                    repo = params.get("repo","")
                    resp = await client.get(f"{base}/repos/{repo}/pulls", headers=headers,
                        params={"state": params.get("state","open"), "per_page": params.get("limit",20)})
                    return resp.json()
                elif action == "github_get_pr":
                    repo = params.get("repo","")
                    resp = await client.get(f"{base}/repos/{repo}/pulls/{params['pr_number']}", headers=headers)
                    return resp.json()
                elif action == "github_list_issues":
                    repo = params.get("repo","")
                    resp = await client.get(f"{base}/repos/{repo}/issues", headers=headers,
                        params={"state": params.get("state","open"), "per_page": params.get("limit",20)})
                    return resp.json()
                elif action == "github_comment":
                    repo = params.get("repo","")
                    num = params.get("issue_number","")
                    resp = await client.post(f"{base}/repos/{repo}/issues/{num}/comments", headers=headers,
                        json={"body": params.get("body","")})
                    return resp.json()
                elif action == "github_get_file":
                    repo = params.get("repo","")
                    path = params.get("path","")
                    resp = await client.get(f"{base}/repos/{repo}/contents/{path}", headers=headers,
                        params={"ref": params.get("ref","main")})
                    data = resp.json()
                    if "content" in data:
                        import base64
                        data["decoded_content"] = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                    return data
                elif action == "github_create_pr":
                    repo = params.get("repo","")
                    resp = await client.post(f"{base}/repos/{repo}/pulls", headers=headers,
                        json={"title": params.get("title",""), "body": params.get("body",""),
                              "head": params.get("head",""), "base": params.get("base","main")})
                    return resp.json()
                else:
                    return {"error": f"Unknown GitHub action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "github_create_issue",
                "description": "Create a GitHub issue.",
                "parameters": {"type": "object", "properties": {
                    "repo": {"type": "string", "description": "owner/repo"},
                    "title": {"type": "string"}, "body": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "assignees": {"type": "array", "items": {"type": "string"}},
                }, "required": ["repo", "title"]}}},
            {"type": "function", "function": {"name": "github_search_code",
                "description": "Search code across GitHub repositories.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"},
                    "repo": {"type": "string", "description": "Limit to owner/repo"},
                }, "required": ["query"]}}},
            {"type": "function", "function": {"name": "github_list_prs",
                "description": "List pull requests for a repository.",
                "parameters": {"type": "object", "properties": {
                    "repo": {"type": "string"}, "state": {"type": "string", "enum": ["open","closed","all"]},
                    "limit": {"type": "integer"},
                }, "required": ["repo"]}}},
            {"type": "function", "function": {"name": "github_get_pr",
                "description": "Get a specific pull request by number.",
                "parameters": {"type": "object", "properties": {
                    "repo": {"type": "string"}, "pr_number": {"type": "integer"},
                }, "required": ["repo", "pr_number"]}}},
            {"type": "function", "function": {"name": "github_list_issues",
                "description": "List issues for a repository.",
                "parameters": {"type": "object", "properties": {
                    "repo": {"type": "string"}, "state": {"type": "string", "enum": ["open","closed","all"]},
                    "limit": {"type": "integer"},
                }, "required": ["repo"]}}},
            {"type": "function", "function": {"name": "github_comment",
                "description": "Add a comment to a GitHub issue or PR.",
                "parameters": {"type": "object", "properties": {
                    "repo": {"type": "string"}, "issue_number": {"type": "integer"},
                    "body": {"type": "string"},
                }, "required": ["repo", "issue_number", "body"]}}},
            {"type": "function", "function": {"name": "github_get_file",
                "description": "Get a file's content from a GitHub repository.",
                "parameters": {"type": "object", "properties": {
                    "repo": {"type": "string"}, "path": {"type": "string"},
                    "ref": {"type": "string", "description": "Branch or commit (default: main)"},
                }, "required": ["repo", "path"]}}},
            {"type": "function", "function": {"name": "github_create_pr",
                "description": "Create a pull request.",
                "parameters": {"type": "object", "properties": {
                    "repo": {"type": "string"}, "title": {"type": "string"},
                    "body": {"type": "string"}, "head": {"type": "string", "description": "Source branch"},
                    "base": {"type": "string", "description": "Target branch (default: main)"},
                }, "required": ["repo", "title", "head"]}}},
        ]


class NotionConnector(Connector):
    """Notion integration — create/read/update pages, search database."""
    name = "notion"
    description = "Read, write, and search Notion pages and databases."
    
    def __init__(self) -> None:
        self._connected = False
        self._token = ""
        self._version = "2022-06-28"
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", os.environ.get("NOTION_API_KEY", ""))
        self._connected = bool(self._token)
        return self._connected
    
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "Notion not connected."}
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": self._version,
            "Content-Type": "application/json",
        }
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                if action == "notion_search":
                    resp = await client.post(
                        "https://api.notion.com/v1/search",
                        headers=headers,
                        json={"query": params.get("query", ""), "page_size": params.get("limit", 10)},
                        timeout=15,
                    )
                    return resp.json()
                elif action == "notion_get_page":
                    resp = await client.get(
                        f"https://api.notion.com/v1/pages/{params['page_id']}",
                        headers=headers, timeout=15,
                    )
                    return resp.json()
                elif action == "notion_create_page":
                    body = {
                        "parent": {"database_id": params["database_id"]},
                        "properties": params.get("properties", {}),
                    }
                    resp = await client.post(
                        "https://api.notion.com/v1/pages",
                        headers=headers, json=body, timeout=15,
                    )
                    return resp.json()
                elif action == "notion_append_block":
                    body = {"children": params.get("blocks", [])}
                    resp = await client.patch(
                        f"https://api.notion.com/v1/blocks/{params['block_id']}/children",
                        headers=headers, json=body, timeout=15,
                    )
                    return resp.json()
                else:
                    return {"error": f"Unknown Notion action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}
    
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "notion_search",
                "description": "Search Notion pages and databases.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                }, "required": ["query"]}}},
            {"type": "function", "function": {"name": "notion_get_page",
                "description": "Get a Notion page by ID.",
                "parameters": {"type": "object", "properties": {
                    "page_id": {"type": "string"},
                }, "required": ["page_id"]}}},
            {"type": "function", "function": {"name": "notion_create_page",
                "description": "Create a new page in a Notion database.",
                "parameters": {"type": "object", "properties": {
                    "database_id": {"type": "string"},
                    "properties": {"type": "object", "description": "Page properties"},
                }, "required": ["database_id"]}}},
            {"type": "function", "function": {"name": "notion_append_block",
                "description": "Append content blocks to a Notion page.",
                "parameters": {"type": "object", "properties": {
                    "block_id": {"type": "string"},
                    "blocks": {"type": "array", "items": {"type": "object"}},
                }, "required": ["block_id", "blocks"]}}},
        ]


class LinearConnector(Connector):
    """Linear integration — create/update issues, query projects."""
    name = "linear"
    description = "Create and manage Linear issues, projects, and cycles."
    
    GRAPHQL_URL = "https://api.linear.app/graphql"
    
    def __init__(self) -> None:
        self._connected = False
        self._token = ""
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", os.environ.get("LINEAR_API_KEY", ""))
        self._connected = bool(self._token)
        return self._connected
    
    async def _gql(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.GRAPHQL_URL,
                headers={"Authorization": self._token, "Content-Type": "application/json"},
                json={"query": query, "variables": variables or {}},
                timeout=15,
            )
            return resp.json()
    
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "Linear not connected."}
        try:
            if action == "linear_create_issue":
                q = """mutation CreateIssue($title: String!, $description: String, $teamId: String!) {
                    issueCreate(input: {title: $title, description: $description, teamId: $teamId}) {
                        success issue { id identifier title url }
                    }
                }"""
                return await self._gql(q, {"title": params["title"], "description": params.get("description", ""), "teamId": params["team_id"]})
            elif action == "linear_get_issues":
                q = """query Issues($filter: IssueFilter) {
                    issues(filter: $filter, first: 20) {
                        nodes { id identifier title state { name } assignee { name } url }
                    }
                }"""
                return await self._gql(q, {"filter": params.get("filter", {})})
            elif action == "linear_update_issue":
                q = """mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
                    issueUpdate(id: $id, input: $input) { success issue { id title state { name } } }
                }"""
                return await self._gql(q, {"id": params["issue_id"], "input": params.get("updates", {})})
            elif action == "linear_search_issues":
                q = """query SearchIssues($query: String!) {
                    issueSearch(query: $query, first: 10) {
                        nodes { id identifier title state { name } url }
                    }
                }"""
                return await self._gql(q, {"query": params["query"]})
            else:
                return {"error": f"Unknown Linear action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}
    
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "linear_create_issue",
                "description": "Create a Linear issue.",
                "parameters": {"type": "object", "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "team_id": {"type": "string", "description": "Linear team ID"},
                }, "required": ["title", "team_id"]}}},
            {"type": "function", "function": {"name": "linear_get_issues",
                "description": "List Linear issues with optional filters.",
                "parameters": {"type": "object", "properties": {
                    "filter": {"type": "object", "description": "Linear GraphQL filter"},
                }, "required": []}}},
            {"type": "function", "function": {"name": "linear_update_issue",
                "description": "Update a Linear issue (state, assignee, priority, etc.).",
                "parameters": {"type": "object", "properties": {
                    "issue_id": {"type": "string"},
                    "updates": {"type": "object", "description": "Fields to update"},
                }, "required": ["issue_id"]}}},
            {"type": "function", "function": {"name": "linear_search_issues",
                "description": "Search Linear issues by keyword.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"},
                }, "required": ["query"]}}},
        ]


class SalesforceConnector(Connector):
    """Salesforce integration — query objects, create/update records."""
    name = "salesforce"
    description = "Query and manage Salesforce CRM records (leads, contacts, opportunities)."
    
    def __init__(self) -> None:
        self._connected = False
        self._instance_url = ""
        self._access_token = ""
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    async def connect(self, credentials: dict[str, str]) -> bool:
        self._instance_url = credentials.get("instance_url", os.environ.get("SALESFORCE_INSTANCE_URL", ""))
        self._access_token = credentials.get("access_token", os.environ.get("SALESFORCE_ACCESS_TOKEN", ""))
        self._connected = bool(self._instance_url and self._access_token)
        return self._connected
    
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}
    
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "Salesforce not connected."}
        base = f"{self._instance_url}/services/data/v59.0"
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                if action == "sf_query":
                    resp = await client.get(
                        f"{base}/query", headers=self._headers(),
                        params={"q": params["soql"]}, timeout=15,
                    )
                    return resp.json()
                elif action == "sf_create":
                    resp = await client.post(
                        f"{base}/sobjects/{params['object_type']}",
                        headers=self._headers(), json=params.get("fields", {}), timeout=15,
                    )
                    return resp.json()
                elif action == "sf_update":
                    resp = await client.patch(
                        f"{base}/sobjects/{params['object_type']}/{params['record_id']}",
                        headers=self._headers(), json=params.get("fields", {}), timeout=15,
                    )
                    return {"status": resp.status_code, "success": resp.status_code < 300}
                elif action == "sf_get":
                    resp = await client.get(
                        f"{base}/sobjects/{params['object_type']}/{params['record_id']}",
                        headers=self._headers(), timeout=15,
                    )
                    return resp.json()
                else:
                    return {"error": f"Unknown Salesforce action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}
    
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "sf_query",
                "description": "Run a SOQL query on Salesforce.",
                "parameters": {"type": "object", "properties": {
                    "soql": {"type": "string", "description": "SOQL query string"},
                }, "required": ["soql"]}}},
            {"type": "function", "function": {"name": "sf_create",
                "description": "Create a Salesforce record.",
                "parameters": {"type": "object", "properties": {
                    "object_type": {"type": "string", "description": "e.g. Lead, Contact, Opportunity"},
                    "fields": {"type": "object", "description": "Record field values"},
                }, "required": ["object_type", "fields"]}}},
            {"type": "function", "function": {"name": "sf_update",
                "description": "Update a Salesforce record.",
                "parameters": {"type": "object", "properties": {
                    "object_type": {"type": "string"},
                    "record_id": {"type": "string"},
                    "fields": {"type": "object"},
                }, "required": ["object_type", "record_id"]}}},
            {"type": "function", "function": {"name": "sf_get",
                "description": "Get a specific Salesforce record.",
                "parameters": {"type": "object", "properties": {
                    "object_type": {"type": "string"},
                    "record_id": {"type": "string"},
                }, "required": ["object_type", "record_id"]}}},
        ]


class JiraConnector(Connector):
    """Jira integration — create/update issues, query projects, manage sprints."""
    name = "jira"
    description = "Create and manage Jira issues, projects, and sprints."
    
    def __init__(self) -> None:
        self._connected = False
        self._base_url = ""
        self._token = ""
        self._email = ""
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    async def connect(self, credentials: dict[str, str]) -> bool:
        self._base_url = credentials.get("base_url", os.environ.get("JIRA_BASE_URL", "")).rstrip("/")
        self._token = credentials.get("token", os.environ.get("JIRA_API_TOKEN", ""))
        self._email = credentials.get("email", os.environ.get("JIRA_EMAIL", ""))
        self._connected = bool(self._base_url and self._token)
        return self._connected
    
    def _headers(self) -> dict:
        import base64
        creds = base64.b64encode(f"{self._email}:{self._token}".encode()).decode()
        return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}
    
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "Jira not connected."}
        api = f"{self._base_url}/rest/api/3"
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                if action == "jira_create_issue":
                    body = {
                        "fields": {
                            "project": {"key": params["project_key"]},
                            "summary": params["summary"],
                            "description": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": params.get("description", "")}]}]},
                            "issuetype": {"name": params.get("issue_type", "Task")},
                        }
                    }
                    resp = await client.post(f"{api}/issue", headers=self._headers(), json=body, timeout=15)
                    return resp.json()
                elif action == "jira_search":
                    resp = await client.post(f"{api}/issue/search", headers=self._headers(),
                        json={"jql": params["jql"], "maxResults": params.get("limit", 20)}, timeout=15)
                    return resp.json()
                elif action == "jira_get_issue":
                    resp = await client.get(f"{api}/issue/{params['issue_key']}", headers=self._headers(), timeout=15)
                    return resp.json()
                elif action == "jira_update_issue":
                    resp = await client.put(f"{api}/issue/{params['issue_key']}",
                        headers=self._headers(), json={"fields": params.get("fields", {})}, timeout=15)
                    return {"status": resp.status_code, "success": resp.status_code < 300}
                elif action == "jira_add_comment":
                    body = {"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": params["comment"]}]}]}}
                    resp = await client.post(f"{api}/issue/{params['issue_key']}/comment", headers=self._headers(), json=body, timeout=15)
                    return resp.json()
                else:
                    return {"error": f"Unknown Jira action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}
    
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "jira_create_issue", "description": "Create a Jira issue.",
                "parameters": {"type": "object", "properties": {
                    "project_key": {"type": "string"}, "summary": {"type": "string"},
                    "description": {"type": "string"}, "issue_type": {"type": "string", "description": "Task, Bug, Story, Epic"},
                }, "required": ["project_key", "summary"]}}},
            {"type": "function", "function": {"name": "jira_search", "description": "Search Jira issues with JQL.",
                "parameters": {"type": "object", "properties": {
                    "jql": {"type": "string"}, "limit": {"type": "integer"},
                }, "required": ["jql"]}}},
            {"type": "function", "function": {"name": "jira_get_issue", "description": "Get a Jira issue by key.",
                "parameters": {"type": "object", "properties": {
                    "issue_key": {"type": "string", "description": "e.g. PROJ-123"},
                }, "required": ["issue_key"]}}},
            {"type": "function", "function": {"name": "jira_update_issue", "description": "Update Jira issue fields.",
                "parameters": {"type": "object", "properties": {
                    "issue_key": {"type": "string"}, "fields": {"type": "object"},
                }, "required": ["issue_key"]}}},
            {"type": "function", "function": {"name": "jira_add_comment", "description": "Add a comment to a Jira issue.",
                "parameters": {"type": "object", "properties": {
                    "issue_key": {"type": "string"}, "comment": {"type": "string"},
                }, "required": ["issue_key", "comment"]}}},
        ]


class AirtableConnector(Connector):
    """Airtable integration — read and write records."""
    name = "airtable"
    description = "Read and write Airtable records and query bases."
    
    def __init__(self) -> None:
        self._connected = False
        self._token = ""
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", os.environ.get("AIRTABLE_API_KEY", ""))
        self._connected = bool(self._token)
        return self._connected
    
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "Airtable not connected."}
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        base_id = params.get("base_id", "")
        table = params.get("table", "")
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                if action == "airtable_list_records":
                    resp = await client.get(
                        f"https://api.airtable.com/v0/{base_id}/{table}",
                        headers=headers, params={"maxRecords": params.get("limit", 100), "filterByFormula": params.get("filter", "")},
                        timeout=15,
                    )
                    return resp.json()
                elif action == "airtable_create_record":
                    resp = await client.post(
                        f"https://api.airtable.com/v0/{base_id}/{table}",
                        headers=headers, json={"fields": params.get("fields", {})}, timeout=15,
                    )
                    return resp.json()
                elif action == "airtable_update_record":
                    resp = await client.patch(
                        f"https://api.airtable.com/v0/{base_id}/{table}/{params['record_id']}",
                        headers=headers, json={"fields": params.get("fields", {})}, timeout=15,
                    )
                    return resp.json()
                else:
                    return {"error": f"Unknown Airtable action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}
    
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "airtable_list_records",
                "description": "List records from an Airtable table.",
                "parameters": {"type": "object", "properties": {
                    "base_id": {"type": "string"}, "table": {"type": "string"},
                    "filter": {"type": "string", "description": "Airtable formula filter"},
                    "limit": {"type": "integer"},
                }, "required": ["base_id", "table"]}}},
            {"type": "function", "function": {"name": "airtable_create_record",
                "description": "Create a record in an Airtable table.",
                "parameters": {"type": "object", "properties": {
                    "base_id": {"type": "string"}, "table": {"type": "string"},
                    "fields": {"type": "object"},
                }, "required": ["base_id", "table", "fields"]}}},
            {"type": "function", "function": {"name": "airtable_update_record",
                "description": "Update an Airtable record.",
                "parameters": {"type": "object", "properties": {
                    "base_id": {"type": "string"}, "table": {"type": "string"},
                    "record_id": {"type": "string"}, "fields": {"type": "object"},
                }, "required": ["base_id", "table", "record_id"]}}},
        ]


class CalendarConnector(Connector):
    """Google Calendar integration — read events, create meetings."""
    name = "calendar"
    description = "Read and manage Google Calendar events."
    
    def __init__(self) -> None:
        self._connected = False
        self._token = ""
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", os.environ.get("GOOGLE_CALENDAR_TOKEN", ""))
        self._connected = bool(self._token)
        return self._connected
    
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "Calendar not connected."}
        headers = {"Authorization": f"Bearer {self._token}"}
        calendar_id = params.get("calendar_id", "primary")
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                if action == "calendar_list_events":
                    resp = await client.get(
                        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                        headers=headers, params={
                            "maxResults": params.get("limit", 10),
                            "timeMin": params.get("time_min", ""),
                            "timeMax": params.get("time_max", ""),
                            "orderBy": "startTime",
                            "singleEvents": "true",
                        }, timeout=15,
                    )
                    return resp.json()
                elif action == "calendar_create_event":
                    body = {
                        "summary": params["title"],
                        "description": params.get("description", ""),
                        "start": {"dateTime": params["start"], "timeZone": params.get("timezone", "UTC")},
                        "end": {"dateTime": params["end"], "timeZone": params.get("timezone", "UTC")},
                        "attendees": [{"email": e} for e in params.get("attendees", [])],
                    }
                    resp = await client.post(
                        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                        headers={**headers, "Content-Type": "application/json"},
                        json=body, timeout=15,
                    )
                    return resp.json()
                elif action == "calendar_delete_event":
                    resp = await client.delete(
                        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{params['event_id']}",
                        headers=headers, timeout=15,
                    )
                    return {"status": resp.status_code, "success": resp.status_code < 300}
                else:
                    return {"error": f"Unknown Calendar action: {action}"}
        except Exception as exc:
            return {"error": str(exc)}
    
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "calendar_list_events",
                "description": "List upcoming Google Calendar events.",
                "parameters": {"type": "object", "properties": {
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                    "time_min": {"type": "string", "description": "RFC3339 start time"},
                    "time_max": {"type": "string", "description": "RFC3339 end time"},
                    "limit": {"type": "integer"},
                }, "required": []}}},
            {"type": "function", "function": {"name": "calendar_create_event",
                "description": "Create a Google Calendar event.",
                "parameters": {"type": "object", "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": "RFC3339 datetime"},
                    "end": {"type": "string", "description": "RFC3339 datetime"},
                    "description": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}, "description": "Email addresses"},
                    "timezone": {"type": "string"},
                }, "required": ["title", "start", "end"]}}},
            {"type": "function", "function": {"name": "calendar_delete_event",
                "description": "Delete a Google Calendar event.",
                "parameters": {"type": "object", "properties": {
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string"},
                }, "required": ["event_id"]}}},
        ]


class ConnectorRegistry:
    """Registry of external service connectors.

    Connectors register themselves and their tools are dynamically
    injected into the agent's tool surface.
    """

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.name] = connector
        log.info("Registered connector: %s", connector.name)

    def get(self, name: str) -> Connector | None:
        return self._connectors.get(name)

    @property
    def all(self) -> dict[str, Connector]:
        return dict(self._connectors)

    def register_tools(self, tool_registry: ToolRegistry) -> None:
        """Inject all connected services' tools into the agent's tool surface."""
        for conn in self._connectors.values():
            if not conn.connected:
                continue
            for tool_def in conn.get_tool_definitions():
                fn = tool_def.get("function", {})
                tool_name = fn.get("name", "")
                if not tool_name:
                    continue

                # Create a handler closure for this connector + action
                async def _handler(
                    _conn=conn,
                    _action=tool_name,
                    **kwargs: Any,
                ) -> str:
                    result = await _conn.execute(_action, kwargs)
                    return json.dumps(result)

                tool_registry.register(
                    name=tool_name,
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters", {}),
                    handler=_handler,
                )

    def list_connectors(self) -> list[dict[str, Any]]:
        return [
            {
                "name": c.name,
                "description": c.description,
                "connected": c.connected,
                "tools": [t["function"]["name"] for t in c.get_tool_definitions()],
            }
            for c in self._connectors.values()
        ]

    @classmethod
    def default(cls) -> "ConnectorRegistry":
        """Create a registry with all built-in connectors."""
        reg = cls()
        reg.register(GmailConnector())
        reg.register(SlackConnector())
        reg.register(GitHubConnector())
        reg.register(NotionConnector())
        reg.register(LinearConnector())
        reg.register(SalesforceConnector())
        reg.register(JiraConnector())
        reg.register(AirtableConnector())
        reg.register(CalendarConnector())
        return reg


# ===========================================================================
# Task queue
# ===========================================================================

@dataclass
class TaskJob:
    """A queued task job."""
    id: str = ""
    task: str = ""
    user_id: str = "default"
    architecture: str = "A"
    status: str = "pending"       # pending | running | complete | failed
    result: str = ""
    error: str = ""
    created_at: float = 0.0
    completed_at: float = 0.0
    duration: float = 0.0


class TaskQueue:
    """Asyncio-based in-memory task queue.

    For production, replace with Celery + Redis or Temporal.
    """

    def __init__(self, max_concurrent: int = 20) -> None:
        self._jobs: dict[str, TaskJob] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._orchestrator_factory: Any = None

    def set_orchestrator_factory(self, factory: Any) -> None:
        """Set the callable that creates a ProductionOrchestrator per job."""
        self._orchestrator_factory = factory

    async def submit(
        self,
        task: str,
        user_id: str = "default",
        architecture: str = "A",
    ) -> str:
        """Submit a task and return the job ID."""
        job_id = str(uuid.uuid4())[:12]
        job = TaskJob(
            id=job_id,
            task=task,
            user_id=user_id,
            architecture=architecture,
            created_at=time.time(),
        )
        self._jobs[job_id] = job
        asyncio.create_task(self._execute(job))
        return job_id

    async def _execute(self, job: TaskJob) -> None:
        async with self._semaphore:
            job.status = "running"
            try:
                if self._orchestrator_factory:
                    orch = self._orchestrator_factory(
                        user_id=job.user_id,
                        architecture=job.architecture,
                    )
                    job.result = await orch.run(job.task)
                else:
                    job.result = "[No orchestrator configured]"
                job.status = "complete"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
            finally:
                job.completed_at = time.time()
                job.duration = job.completed_at - job.created_at

    def get(self, job_id: str) -> TaskJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self, user_id: str | None = None, limit: int = 50) -> list[TaskJob]:
        jobs = list(self._jobs.values())
        if user_id:
            jobs = [j for j in jobs if j.user_id == user_id]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]


# ===========================================================================
# Production orchestrator (unifies A + C + memory + connectors)
# ===========================================================================

class ProductionOrchestrator:
    """Architecture E: full production stack.

    Wraps Architecture A or C with:
    - Persistent memory
    - External service connectors
    - Task queue integration
    - Structured logging
    """

    def __init__(
        self,
        config: ProductionConfig | None = None,
        router: ModelRouter | None = None,
        connectors: ConnectorRegistry | None = None,
    ) -> None:
        self.config = config or ProductionConfig()
        self.router = router or ModelRouter()
        self.connectors = connectors or ConnectorRegistry.default()

        # Build the underlying architecture
        if self.config.architecture == "C":
            swarm_cfg = SwarmConfig(
                coordinator_model=self.config.model,
                user_id=self.config.user_id,
                workspace_dir=self.config.workspace_dir,
                memory_db=self.config.memory_db,
                auto_extract_memory=self.config.auto_extract_memory,
                verbose=self.config.verbose,
                enable_security=self.config.enable_security,
                security_policy=self.config.security_policy,
            )
            self._backend = SwarmAgent(config=swarm_cfg, router=self.router)
        else:
            mono_cfg = MonolithicConfig(
                model=self.config.model,
                user_id=self.config.user_id,
                workspace_dir=self.config.workspace_dir,
                memory_db=self.config.memory_db,
                auto_extract_memory=self.config.auto_extract_memory,
                verbose=self.config.verbose,
                enable_security=self.config.enable_security,
                security_policy=self.config.security_policy,
            )
            self._backend = MonolithicAgent(config=mono_cfg, router=self.router)

        # Inject connector tools into the backend's tool registry
        if hasattr(self._backend, "tools"):
            self.connectors.register_tools(self._backend.tools)

    async def run(self, task: str, context: str = "") -> str:
        """Execute a task through the full production stack."""
        return await self._backend.run(task, context=context)

    async def stream(self, task: str, context: str = "") -> AsyncGenerator[AgentEvent, None]:
        """Stream events from the backend."""
        async for event in self._backend.stream(task, context=context):
            yield event

    @property
    def stats(self) -> dict[str, Any]:
        base = self._backend.stats if hasattr(self._backend, "stats") else {}
        return {
            **base,
            "architecture_mode": f"E ({self.config.architecture})",
            "connectors": self.connectors.list_connectors(),
        }


# ===========================================================================
# FastAPI application
# ===========================================================================

def create_app(config: ProductionConfig | None = None) -> Any:
    """Create a FastAPI application for Architecture E.

    Returns the app object.  Run with:
        uvicorn orchestra.arch_e:app --host 0.0.0.0 --port 3000
    """
    try:
        from fastapi import FastAPI, WebSocket, HTTPException, Depends, Header
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError:
        raise ImportError(
            "FastAPI is required for the production server. "
            "Install with: pip install fastapi uvicorn"
        )

    config = config or ProductionConfig()
    app = FastAPI(
        title="Horizon Orchestra",
        description="Agentic AI harness — Architecture E production stack",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- state --------------------------------------------------------------
    router = ModelRouter()
    connectors = ConnectorRegistry.default()
    task_queue = TaskQueue(max_concurrent=config.max_concurrent_jobs)

    def make_orchestrator(user_id: str = "default", architecture: str = "A"):
        cfg = ProductionConfig(
            architecture=architecture,
            model=config.model,
            user_id=user_id,
            memory_db=config.memory_db,
            workspace_dir=config.workspace_dir,
            verbose=config.verbose,
        )
        return ProductionOrchestrator(cfg, router=router, connectors=connectors)

    task_queue.set_orchestrator_factory(
        lambda user_id, architecture: make_orchestrator(user_id, architecture)
    )

    # -- billing --------------------------------------------------------
    try:
        billing = BillingManager()
    except Exception:
        billing = NullBillingManager()

    # -- auth ---------------------------------------------------------------
    async def verify_api_key(authorization: str = Header(default="")):
        if config.api_key and authorization != f"Bearer {config.api_key}":
            raise HTTPException(status_code=401, detail="Invalid API key")

    # -- request models -----------------------------------------------------
    class RunRequest(BaseModel):
        task: str
        user_id: str = "default"
        architecture: str = "A"
        context: str = ""

    class JobSubmitRequest(BaseModel):
        task: str
        user_id: str = "default"
        architecture: str = "A"

    class ConnectRequest(BaseModel):
        connector: str
        credentials: dict[str, str]

    class MemoryStoreRequest(BaseModel):
        user_id: str = "default"
        content: str
        category: str = "fact"

    class MemorySearchRequest(BaseModel):
        user_id: str = "default"
        query: str
        limit: int = 10

    class CreateCustomerRequest(BaseModel):
        email: str
        name: str
        tier: str = "maker"

    class UsageQueryRequest(BaseModel):
        customer_id: str
        usage_type: str = ""
        limit: int = 100

    # -- routes -------------------------------------------------------------

    @app.post("/v1/run")
    async def run_task(req: RunRequest, _=Depends(verify_api_key)):
        """Run a task synchronously and return the result."""
        orch = make_orchestrator(req.user_id, req.architecture)
        result = await orch.run(req.task, context=req.context)
        return {"result": result, "stats": orch.stats}

    @app.websocket("/v1/stream")
    async def stream_task(ws: WebSocket):
        """Stream task events over WebSocket."""
        await ws.accept()
        data = await ws.receive_json()
        task = data.get("task", "")
        user_id = data.get("user_id", "default")
        arch = data.get("architecture", "A")

        orch = make_orchestrator(user_id, arch)
        async for event in orch.stream(task):
            event_data: dict[str, Any] = {"type": type(event).__name__}
            if isinstance(event, ToolCallEvent):
                event_data.update({
                    "tool": event.tool_name,
                    "iteration": event.iteration,
                })
            elif isinstance(event, ToolResultEvent):
                event_data.update({
                    "tool": event.tool_name,
                    "success": event.success,
                    "duration": event.duration,
                })
            elif isinstance(event, FinalAnswerEvent):
                event_data.update({
                    "content": event.content,
                    "iterations": event.total_iterations,
                    "tool_calls": event.total_tool_calls,
                })
            elif isinstance(event, ErrorEvent):
                event_data.update({
                    "message": event.message,
                    "recoverable": event.recoverable,
                })
            await ws.send_json(event_data)
        await ws.close()

    @app.post("/v1/jobs/submit")
    async def submit_job(req: JobSubmitRequest, _=Depends(verify_api_key)):
        """Submit a task to the background queue."""
        job_id = await task_queue.submit(
            task=req.task, user_id=req.user_id, architecture=req.architecture,
        )
        return {"job_id": job_id, "status": "submitted"}

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str, _=Depends(verify_api_key)):
        """Check status of a background job."""
        job = task_queue.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "id": job.id, "status": job.status,
            "result": job.result if job.status == "complete" else None,
            "error": job.error if job.status == "failed" else None,
            "duration": job.duration,
        }

    @app.get("/v1/jobs")
    async def list_jobs(user_id: str = "default", _=Depends(verify_api_key)):
        """List recent jobs."""
        jobs = task_queue.list_jobs(user_id=user_id)
        return [
            {"id": j.id, "task": j.task[:100], "status": j.status, "duration": j.duration}
            for j in jobs
        ]

    @app.post("/v1/connectors/connect")
    async def connect_service(req: ConnectRequest, _=Depends(verify_api_key)):
        """Connect an external service."""
        conn = connectors.get(req.connector)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Unknown connector: {req.connector}")
        success = await conn.connect(req.credentials)
        return {"connector": req.connector, "connected": success}

    @app.get("/v1/connectors")
    async def list_connectors(_=Depends(verify_api_key)):
        """List available connectors."""
        return connectors.list_connectors()

    @app.post("/v1/memory/store")
    async def store_memory(req: MemoryStoreRequest, _=Depends(verify_api_key)):
        """Store a memory."""
        store = MemoryStore(db_path=config.memory_db or None)
        entry = await store.store(req.user_id, req.content, category=req.category)
        return {"id": entry.id, "stored": True}

    @app.post("/v1/memory/search")
    async def search_memory(req: MemorySearchRequest, _=Depends(verify_api_key)):
        """Search memories."""
        store = MemoryStore(db_path=config.memory_db or None)
        results = await store.search(req.user_id, req.query, limit=req.limit)
        return [
            {"content": r.content, "category": r.category, "relevance": round(r.relevance_score, 3)}
            for r in results
        ]

    @app.get("/v1/models")
    async def list_models(_=Depends(verify_api_key)):
        return router.list_models()

    @app.post("/v1/billing/customers")
    async def create_customer(req: CreateCustomerRequest, _=Depends(verify_api_key)):
        """Create a billing customer."""
        tier = PricingTier(req.tier)
        customer = await billing.create_customer(email=req.email, name=req.name, tier=tier)
        return {"customer_id": customer.id, "stripe_customer_id": customer.stripe_customer_id, "tier": customer.tier}

    @app.get("/v1/billing/customers/{customer_id}/usage")
    async def get_usage(customer_id: str, _=Depends(verify_api_key)):
        """Get usage summary for a customer."""
        summary = await billing.get_usage_summary(customer_id)
        return summary.__dict__ if hasattr(summary, '__dict__') else summary

    @app.get("/v1/billing/tiers")
    async def list_tiers(_=Depends(verify_api_key)):
        """List available pricing tiers."""
        return [
            {"tier": "maker", "price": "$0/mo", "description": "Free — local models, basic tools"},
            {"tier": "builder", "price": "$29/mo", "description": "Gemma 4 + Kimi + Sonar, swarm up to 5 agents, $10 model credit"},
            {"tier": "pro", "price": "$99/mo", "description": "All models including Opus 4.6, full production stack, $50 credit"},
            {"tier": "enterprise", "price": "$499/mo", "description": "Unlimited, custom policies, priority support, $200 credit"},
        ]

    @app.get("/v1/billing/customers/{customer_id}/budget")
    async def get_budget(customer_id: str, _=Depends(verify_api_key)):
        """Get remaining budget for a customer."""
        # This would need a tracker instance — return a placeholder
        return {"note": "Budget tracking requires an active UsageTracker session"}

    class CouncilRequest(BaseModel):
        prompt: str
        models: list[str] = []
        orchestrator: str = ""

    @app.post("/v1/council")
    async def run_council(req: CouncilRequest, _=Depends(verify_api_key)):
        """Run Model Council — parallel multi-model deliberation."""
        try:
            from .model_council import ModelCouncil
            council = ModelCouncil(router=router)
            result = await council.deliberate(
                prompt=req.prompt,
                models=req.models or None,
                orchestrator=req.orchestrator,
            )
            return result.to_dict()
        except Exception as exc:
            return {"error": str(exc)}

    class SkillMatchRequest(BaseModel):
        task: str
        max_skills: int = 3

    @app.post("/v1/skills/match")
    async def match_skills_endpoint(req: SkillMatchRequest, _=Depends(verify_api_key)):
        """Find matching skills for a task."""
        try:
            from .skills import SkillRegistry
            registry = SkillRegistry.default()
            matches = registry.match(req.task, max_skills=req.max_skills)
            return [{"skill": m.skill.name, "score": round(m.score, 3), "reason": m.trigger_reason} for m in matches]
        except Exception as exc:
            return {"error": str(exc)}

    @app.get("/v1/skills")
    async def list_skills_endpoint(_=Depends(verify_api_key)):
        """List all available skills."""
        try:
            from .skills import SkillRegistry
            registry = SkillRegistry.default()
            return registry.list_skills()
        except Exception as exc:
            return {"error": str(exc)}

    @app.get("/health")
    async def health():
        return {"status": "ok", "architecture": "E", "version": "0.1.0"}

    return app


# Convenience: create app at module level for `uvicorn orchestra.arch_e:app`
try:
    app = create_app()
except ImportError:
    app = None  # FastAPI not installed; library-only mode


# ===========================================================================
# Docker Compose generator
# ===========================================================================

DOCKER_COMPOSE_TEMPLATE = """\
# Horizon Orchestra — Architecture E Production Stack
# Generated by orchestra.arch_e.generate_docker_compose()

version: "3.9"

services:
  # ── Kimi K2.5 Self-Hosted Inference ─────────────────────────────────────
  kimi-vllm:
    image: vllm/vllm-openai:nightly
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 8
              capabilities: [gpu]
    command: >
      --model moonshotai/Kimi-K2.5
      --tensor-parallel-size 8
      --tool-call-parser kimi_k2
      --reasoning-parser kimi_k2
      --max-model-len 262144
      --trust-remote-code
      --host 0.0.0.0
      --port 8000
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ── Gemma 4 31B Self-Hosted Inference ──────────────────────────────────
  gemma4-vllm:
    image: vllm/vllm-openai:nightly
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    command: >
      --model google/gemma-4-31B-it
      --tensor-parallel-size 1
      --max-model-len 256000
      --trust-remote-code
      --enable-auto-tool-choice
      --tool-call-parser hermes
      --dtype bfloat16
      --host 0.0.0.0
      --port 8001
    ports:
      - "8001:8001"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ── API Gateway ─────────────────────────────────────────────────────────
  api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - KIMI_BASE_URL=http://kimi-vllm:8000/v1
      - GEMMA4_BASE_URL=http://gemma4-vllm:8001/v1
      - MOONSHOT_API_KEY=${{MOONSHOT_API_KEY:-}}
      - GEMINI_API_KEY=${{GEMINI_API_KEY:-}}
      - PERPLEXITY_API_KEY=${{PERPLEXITY_API_KEY:-}}
      - OPENROUTER_API_KEY=${{OPENROUTER_API_KEY:-}}
      - OPENAI_API_KEY=${{OPENAI_API_KEY:-}}
      - ANTHROPIC_API_KEY=${{ANTHROPIC_API_KEY:-}}
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgresql://postgres:horizon@postgres:5432/orchestra
      - HORIZON_API_KEY=${{HORIZON_API_KEY:-}}
      - DEEPGRAM_API_KEY=${{DEEPGRAM_API_KEY:-}}
      - ASSEMBLYAI_API_KEY=${{ASSEMBLYAI_API_KEY:-}}
      - GROQ_API_KEY=${{GROQ_API_KEY:-}}
      - ELEVENLABS_API_KEY=${{ELEVENLABS_API_KEY:-}}
      - FISH_AUDIO_API_KEY=${{FISH_AUDIO_API_KEY:-}}
      - KOKORO_BASE_URL=http://kokoro:8880/v1
      - FISH_SPEECH_BASE_URL=http://fish-speech:8080/v1
      - CHATTERBOX_BASE_URL=http://chatterbox:8765/v1
      - WHISPER_LOCAL_BASE_URL=http://whisper-local:8787/v1
      - BROWSER_REMOTE_URL=ws://playwright:3001
    depends_on:
      kimi-vllm:
        condition: service_healthy
      redis:
        condition: service_started
      postgres:
        condition: service_started
    restart: unless-stopped
    command: >
      uvicorn orchestra.arch_e:app
      --host 0.0.0.0
      --port 3000
      --workers 4

  # ── Code Execution Sandbox ──────────────────────────────────────────────
  sandbox:
    image: python:3.12-slim
    volumes:
      - workspace:/workspace
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:size=512M
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"

  # ── Browser Automation (Playwright + Chromium CDP) ──────────────────────
  playwright:
    image: mcr.microsoft.com/playwright:v1.50.0-noble
    ports:
      - "9222:9222"    # Chrome DevTools Protocol (CDP) endpoint
      - "3001:3001"    # Playwright test server (optional)
    environment:
      - PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
    command: >
      npx -y playwright run-server --port 3001 --host 0.0.0.0
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3001/"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ── Browserless (Chromium-as-a-Service, OpenAI-compatible) ─────────────
  browserless:
    image: browserless/chrome:latest
    ports:
      - "3002:3000"
    environment:
      - TOKEN=${{BROWSERLESS_TOKEN:-orchestra}}
      - MAX_CONCURRENT_SESSIONS=10
      - MAX_QUEUE_LENGTH=100
      - PREBOOT_CHROME=true
      - DEMO_MODE=false
      - ENABLE_DEBUGGER=false
      - WORKSPACE_DELETE_EXPIRED=true
      - WORKSPACE_EXPIRE_DAYS=1
      - DEFAULT_BLOCK_ADS=true
      - DEFAULT_IGNORE_HTTPS_ERRORS=true
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/pressure"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ── Memory / State (PostgreSQL + pgvector) ──────────────────────────────
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: orchestra
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: horizon
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped

  # ── Session Cache / Task Queue ──────────────────────────────────────────
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped
    volumes:
      - redisdata:/data

  # ── Kokoro TTS (Local, Apache 2.0) ──────────────────────────────────────────
  kokoro:
    image: ghcr.io/remsky/kokoro-fastapi:latest
    ports:
      - "8880:8880"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8880/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ── Fish Speech S2 (Local TTS) ──────────────────────────────────────────
  fish-speech:
    image: fishaudio/fish-speech:latest
    ports:
      - "8080:8080"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - fish_models:/root/.cache
    restart: unless-stopped

  # ── Faster Whisper (Local STT) ──────────────────────────────────────────
  whisper-local:
    image: fedirz/faster-whisper-server:latest
    ports:
      - "8787:8787"
    environment:
      - WHISPER__MODEL=large-v3-turbo
      - WHISPER__DEVICE=auto
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

volumes:
  workspace:
  pgdata:
  redisdata:
  fish_models:
"""

DOCKERFILE_TEMPLATE = """\
FROM python:3.12-slim

WORKDIR /app

# System deps for playwright and native packages
RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl build-essential && \\
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \\
    pip install --no-cache-dir fastapi uvicorn[standard]

COPY . .

EXPOSE 3000

CMD ["uvicorn", "orchestra.arch_e:app", "--host", "0.0.0.0", "--port", "3000"]
"""

ENV_TEMPLATE = """\
# Horizon Orchestra — Environment Variables
# Copy to .env and fill in your keys.

# Required: at least one model provider
MOONSHOT_API_KEY=
GEMINI_API_KEY=
PERPLEXITY_API_KEY=
OPENROUTER_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Optional: API authentication for the Horizon Orchestra server
HORIZON_API_KEY=

# Stripe billing
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=

# Optional: connector credentials
GITHUB_TOKEN=
SLACK_TOKEN=
GMAIL_TOKEN=
NOTION_API_KEY=
LINEAR_API_KEY=
SALESFORCE_INSTANCE_URL=
SALESFORCE_ACCESS_TOKEN=
JIRA_BASE_URL=
JIRA_API_TOKEN=
JIRA_EMAIL=
AIRTABLE_API_KEY=
GOOGLE_CALENDAR_TOKEN=
BROWSER_MODE=local
BROWSER_REMOTE_URL=
BROWSER_HEADLESS=true
BROWSERLESS_TOKEN=

# Speech/Audio API keys
DEEPGRAM_API_KEY=
ASSEMBLYAI_API_KEY=
GROQ_API_KEY=
ELEVENLABS_API_KEY=
FISH_AUDIO_API_KEY=

# Local speech model endpoints (for self-hosted TTS/STT)
KOKORO_BASE_URL=http://kokoro:8880/v1
FISH_SPEECH_BASE_URL=http://fish-speech:8080/v1
CHATTERBOX_BASE_URL=http://chatterbox:8765/v1
WHISPER_LOCAL_BASE_URL=http://whisper-local:8787/v1
"""


def generate_docker_compose(output_dir: str = ".") -> dict[str, str]:
    """Write docker-compose.yml, Dockerfile, and .env.example to *output_dir*."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    files = {
        "docker-compose.yml": DOCKER_COMPOSE_TEMPLATE,
        "Dockerfile": DOCKERFILE_TEMPLATE,
        ".env.example": ENV_TEMPLATE,
    }

    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")
        log.info("Generated: %s", out / name)

    return {name: str(out / name) for name in files}
