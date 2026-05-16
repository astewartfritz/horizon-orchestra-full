"""Jira connector — API token auth + REST API v3.

Issues, sprints, boards, transitions, comments.
Requires: JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN env vars or pass via connect().
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx

from .base import Connector

__all__ = ["JiraConnector"]
log = logging.getLogger("orchestra.connectors.jira")


class JiraConnector(Connector):
    name = "jira"
    description = "Manage issues, sprints, boards, and workflows in Jira."

    def __init__(self) -> None:
        self._base: str = ""
        self._auth: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._auth)

    async def connect(self, credentials: dict[str, str]) -> bool:
        url = credentials.get("url", "") or os.environ.get("JIRA_URL", "")
        email = credentials.get("email", "") or os.environ.get("JIRA_EMAIL", "")
        token = credentials.get("token", "") or os.environ.get("JIRA_API_TOKEN", "")
        if not all([url, email, token]):
            log.error("Missing JIRA_URL, JIRA_EMAIL, or JIRA_API_TOKEN")
            return False
        self._base = url.rstrip("/")
        self._auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        r = await self._api("GET", "/rest/api/3/myself")
        if "error" not in r:
            log.info("Jira connected as: %s", r.get("displayName"))
            return True
        self._auth = ""
        return False

    async def disconnect(self) -> None:
        self._auth = ""; self._base = ""

    async def _api(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Basic {self._auth}", "Content-Type": "application/json", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.request(method, f"{self._base}{path}", headers=headers, json=body)
            if resp.status_code >= 400:
                return {"error": f"Jira {resp.status_code}: {resp.text[:500]}"}
            return resp.json() if resp.content else {}

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._auth:
            return {"error": "Jira not connected."}
        dispatch = {
            "jira_search": self._search, "jira_create_issue": self._create,
            "jira_transition": self._transition, "jira_add_comment": self._comment,
            "jira_get_issue": self._get_issue, "jira_list_sprints": self._sprints,
        }
        h = dispatch.get(action)
        return await h(params) if h else {"error": f"Unknown: {action}"}

    async def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        jql = params.get("jql", "")
        limit = params.get("limit", 20)
        r = await self._api("GET", f"/rest/api/3/search?jql={jql}&maxResults={limit}&fields=summary,status,assignee,priority,issuetype,created")
        if "error" in r:
            return r
        return {"total": r.get("total", 0), "issues": [
            {"key": i["key"], "summary": i["fields"].get("summary"), "status": (i["fields"].get("status") or {}).get("name"),
             "assignee": (i["fields"].get("assignee") or {}).get("displayName"), "priority": (i["fields"].get("priority") or {}).get("name"),
             "type": (i["fields"].get("issuetype") or {}).get("name")}
            for i in r.get("issues", [])
        ]}

    async def _get_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        key = params.get("key", "")
        if not key:
            return {"error": "key required"}
        return await self._api("GET", f"/rest/api/3/issue/{key}")

    async def _create(self, params: dict[str, Any]) -> dict[str, Any]:
        project = params.get("project", "")
        summary = params.get("summary", "")
        issue_type = params.get("issue_type", "Task")
        description = params.get("description", "")
        if not project or not summary:
            return {"error": "project and summary required"}
        body = {"fields": {"project": {"key": project}, "summary": summary, "issuetype": {"name": issue_type}}}
        if description:
            body["fields"]["description"] = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}]}
        r = await self._api("POST", "/rest/api/3/issue", body)
        return {"created": True, "key": r.get("key"), "id": r.get("id")} if "key" in r else r

    async def _transition(self, params: dict[str, Any]) -> dict[str, Any]:
        key = params.get("key", "")
        transition_id = params.get("transition_id", "")
        if not key or not transition_id:
            return {"error": "key and transition_id required"}
        return await self._api("POST", f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": transition_id}})

    async def _comment(self, params: dict[str, Any]) -> dict[str, Any]:
        key = params.get("key", "")
        body_text = params.get("body", "")
        if not key or not body_text:
            return {"error": "key and body required"}
        body = {"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": body_text}]}]}}
        return await self._api("POST", f"/rest/api/3/issue/{key}/comment", body)

    async def _sprints(self, params: dict[str, Any]) -> dict[str, Any]:
        board_id = params.get("board_id", "")
        if not board_id:
            return {"error": "board_id required"}
        r = await self._api("GET", f"/rest/agile/1.0/board/{board_id}/sprint?state=active,future")
        if "error" in r:
            return r
        return {"sprints": [{"id": s["id"], "name": s["name"], "state": s["state"], "start": s.get("startDate"), "end": s.get("endDate")} for s in r.get("values", [])]}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "jira_search", "description": "Search Jira issues with JQL.", "parameters": {"type": "object", "properties": {"jql": {"type": "string", "description": "JQL query"}, "limit": {"type": "integer"}}, "required": ["jql"]}}},
            {"type": "function", "function": {"name": "jira_get_issue", "description": "Get full details of a Jira issue.", "parameters": {"type": "object", "properties": {"key": {"type": "string", "description": "Issue key (e.g. PROJ-123)"}}, "required": ["key"]}}},
            {"type": "function", "function": {"name": "jira_create_issue", "description": "Create a Jira issue.", "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "summary": {"type": "string"}, "issue_type": {"type": "string"}, "description": {"type": "string"}}, "required": ["project", "summary"]}}},
            {"type": "function", "function": {"name": "jira_transition", "description": "Transition a Jira issue to a new status.", "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "transition_id": {"type": "string"}}, "required": ["key", "transition_id"]}}},
            {"type": "function", "function": {"name": "jira_add_comment", "description": "Add a comment to a Jira issue.", "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "body": {"type": "string"}}, "required": ["key", "body"]}}},
            {"type": "function", "function": {"name": "jira_list_sprints", "description": "List sprints for a Jira board.", "parameters": {"type": "object", "properties": {"board_id": {"type": "string"}}, "required": ["board_id"]}}},
        ]
