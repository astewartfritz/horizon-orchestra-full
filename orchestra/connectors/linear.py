"""Linear connector — API key auth + GraphQL API.

Full project management: issues, projects, cycles, teams, labels.
Requires: LINEAR_API_KEY env var or pass {"token": "lin_api_..."} to connect().
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .base import Connector

__all__ = ["LinearConnector"]

log = logging.getLogger("orchestra.connectors.linear")

API_URL = "https://api.linear.app/graphql"


class LinearConnector(Connector):
    """Linear integration via GraphQL API."""

    name = "linear"
    description = "Manage issues, projects, cycles, and teams in Linear."

    def __init__(self) -> None:
        self._token: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._token)

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", "") or os.environ.get("LINEAR_API_KEY", "")
        if not self._token:
            log.error("No Linear token. Set LINEAR_API_KEY or pass token.")
            return False
        result = await self._gql("{ viewer { id name email } }")
        if result.get("data", {}).get("viewer"):
            viewer = result["data"]["viewer"]
            log.info("Linear connected as: %s (%s)", viewer.get("name"), viewer.get("email"))
            return True
        log.error("Linear auth failed: %s", result.get("errors"))
        self._token = ""
        return False

    async def disconnect(self) -> None:
        self._token = ""

    async def _gql(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        headers = {
            "Authorization": self._token,
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(API_URL, headers=headers, json=body)
            if resp.status_code >= 400:
                return {"errors": [{"message": f"HTTP {resp.status_code}: {resp.text[:300]}"}]}
            return resp.json()

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._token:
            return {"error": "Linear not connected."}
        dispatch = {
            "linear_search_issues": self._search_issues,
            "linear_create_issue": self._create_issue,
            "linear_update_issue": self._update_issue,
            "linear_list_projects": self._list_projects,
            "linear_list_cycles": self._list_cycles,
            "linear_list_teams": self._list_teams,
            "linear_get_issue": self._get_issue,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    async def _search_issues(self, params: dict[str, Any]) -> dict[str, Any]:
        query_str = params.get("query", "")
        state = params.get("state", "")
        limit = params.get("limit", 20)

        filters: list[str] = []
        if state:
            filters.append(f'state: {{ name: {{ eq: "{state}" }} }}')

        filter_block = f", filter: {{ {', '.join(filters)} }}" if filters else ""

        gql = f"""{{
            issueSearch(query: "{query_str}", first: {limit}{filter_block}) {{
                nodes {{
                    id identifier title
                    state {{ name }}
                    priority priorityLabel
                    assignee {{ name }}
                    project {{ name }}
                    createdAt updatedAt
                    url
                }}
            }}
        }}"""
        result = await self._gql(gql)
        nodes = result.get("data", {}).get("issueSearch", {}).get("nodes", [])
        return {
            "count": len(nodes),
            "issues": [
                {
                    "id": n.get("id"),
                    "identifier": n.get("identifier"),
                    "title": n.get("title"),
                    "state": (n.get("state") or {}).get("name"),
                    "priority": n.get("priorityLabel"),
                    "assignee": (n.get("assignee") or {}).get("name"),
                    "project": (n.get("project") or {}).get("name"),
                    "url": n.get("url"),
                }
                for n in nodes
            ],
        }

    async def _get_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        issue_id = params.get("identifier", "")
        if not issue_id:
            return {"error": "identifier is required (e.g. HOR-123)"}
        gql = f"""{{
            issueSearch(query: "{issue_id}", first: 1) {{
                nodes {{
                    id identifier title description
                    state {{ name }}
                    priority priorityLabel
                    assignee {{ name }}
                    project {{ name }}
                    labels {{ nodes {{ name }} }}
                    comments {{ nodes {{ body user {{ name }} createdAt }} }}
                    createdAt updatedAt url
                }}
            }}
        }}"""
        result = await self._gql(gql)
        nodes = result.get("data", {}).get("issueSearch", {}).get("nodes", [])
        if not nodes:
            return {"error": f"Issue {issue_id} not found"}
        n = nodes[0]
        return {
            "identifier": n.get("identifier"),
            "title": n.get("title"),
            "description": (n.get("description") or "")[:5000],
            "state": (n.get("state") or {}).get("name"),
            "priority": n.get("priorityLabel"),
            "assignee": (n.get("assignee") or {}).get("name"),
            "labels": [l.get("name") for l in (n.get("labels") or {}).get("nodes", [])],
            "comments": [
                {"author": (c.get("user") or {}).get("name"), "body": c.get("body", "")[:500]}
                for c in (n.get("comments") or {}).get("nodes", [])[:10]
            ],
            "url": n.get("url"),
        }

    async def _create_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title", "")
        team_id = params.get("team_id", "")
        description = params.get("description", "")
        priority = params.get("priority", 0)
        project_id = params.get("project_id", "")

        if not title or not team_id:
            return {"error": "title and team_id are required"}

        input_fields = [f'title: "{title}"', f'teamId: "{team_id}"']
        if description:
            input_fields.append(f'description: "{description}"')
        if priority:
            input_fields.append(f"priority: {priority}")
        if project_id:
            input_fields.append(f'projectId: "{project_id}"')

        gql = f"""mutation {{
            issueCreate(input: {{ {', '.join(input_fields)} }}) {{
                success
                issue {{ id identifier title url }}
            }}
        }}"""
        result = await self._gql(gql)
        data = result.get("data", {}).get("issueCreate", {})
        if data.get("success"):
            issue = data.get("issue", {})
            return {"created": True, "identifier": issue.get("identifier"), "url": issue.get("url")}
        return {"error": "Failed to create issue", "details": result.get("errors")}

    async def _update_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        issue_id = params.get("issue_id", "")
        if not issue_id:
            return {"error": "issue_id is required"}

        updates: list[str] = []
        if params.get("title"):
            updates.append(f'title: "{params["title"]}"')
        if params.get("description"):
            updates.append(f'description: "{params["description"]}"')
        if params.get("state_id"):
            updates.append(f'stateId: "{params["state_id"]}"')
        if params.get("priority") is not None:
            updates.append(f'priority: {params["priority"]}')
        if params.get("assignee_id"):
            updates.append(f'assigneeId: "{params["assignee_id"]}"')

        if not updates:
            return {"error": "No fields to update"}

        gql = f"""mutation {{
            issueUpdate(id: "{issue_id}", input: {{ {', '.join(updates)} }}) {{
                success
                issue {{ id identifier title state {{ name }} url }}
            }}
        }}"""
        result = await self._gql(gql)
        data = result.get("data", {}).get("issueUpdate", {})
        if data.get("success"):
            issue = data.get("issue", {})
            return {"updated": True, "identifier": issue.get("identifier"), "url": issue.get("url")}
        return {"error": "Failed to update issue", "details": result.get("errors")}

    async def _list_projects(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit", 20)
        gql = f"""{{
            projects(first: {limit}) {{
                nodes {{
                    id name description state
                    progress startDate targetDate
                    teams {{ nodes {{ name }} }}
                    url
                }}
            }}
        }}"""
        result = await self._gql(gql)
        nodes = result.get("data", {}).get("projects", {}).get("nodes", [])
        return {
            "count": len(nodes),
            "projects": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "state": p.get("state"),
                    "progress": p.get("progress"),
                    "start": p.get("startDate"),
                    "target": p.get("targetDate"),
                    "teams": [t.get("name") for t in (p.get("teams") or {}).get("nodes", [])],
                    "url": p.get("url"),
                }
                for p in nodes
            ],
        }

    async def _list_cycles(self, params: dict[str, Any]) -> dict[str, Any]:
        gql = """{
            cycles(first: 10, orderBy: updatedAt) {
                nodes {
                    id number name
                    startsAt endsAt
                    progress { completed total }
                }
            }
        }"""
        result = await self._gql(gql)
        nodes = result.get("data", {}).get("cycles", {}).get("nodes", [])
        return {
            "count": len(nodes),
            "cycles": [
                {
                    "id": c.get("id"),
                    "number": c.get("number"),
                    "name": c.get("name"),
                    "starts": c.get("startsAt"),
                    "ends": c.get("endsAt"),
                    "progress": c.get("progress"),
                }
                for c in nodes
            ],
        }

    async def _list_teams(self, params: dict[str, Any]) -> dict[str, Any]:
        gql = """{
            teams {
                nodes {
                    id name key description
                    members { nodes { name email } }
                }
            }
        }"""
        result = await self._gql(gql)
        nodes = result.get("data", {}).get("teams", {}).get("nodes", [])
        return {
            "count": len(nodes),
            "teams": [
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "key": t.get("key"),
                    "members": [
                        {"name": m.get("name"), "email": m.get("email")}
                        for m in (t.get("members") or {}).get("nodes", [])
                    ],
                }
                for t in nodes
            ],
        }

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {
                "name": "linear_search_issues",
                "description": "Search for issues in Linear.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "state": {"type": "string", "description": "Filter by state (e.g. 'In Progress')"},
                    "limit": {"type": "integer", "description": "Max results (default 20)"},
                }, "required": ["query"]},
            }},
            {"type": "function", "function": {
                "name": "linear_get_issue",
                "description": "Get full details of a Linear issue by identifier (e.g. HOR-123).",
                "parameters": {"type": "object", "properties": {
                    "identifier": {"type": "string", "description": "Issue identifier (e.g. HOR-123)"},
                }, "required": ["identifier"]},
            }},
            {"type": "function", "function": {
                "name": "linear_create_issue",
                "description": "Create a new issue in Linear.",
                "parameters": {"type": "object", "properties": {
                    "title": {"type": "string"},
                    "team_id": {"type": "string", "description": "Team ID to create in"},
                    "description": {"type": "string"},
                    "priority": {"type": "integer", "description": "0=none, 1=urgent, 2=high, 3=medium, 4=low"},
                    "project_id": {"type": "string"},
                }, "required": ["title", "team_id"]},
            }},
            {"type": "function", "function": {
                "name": "linear_update_issue",
                "description": "Update an existing Linear issue.",
                "parameters": {"type": "object", "properties": {
                    "issue_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "state_id": {"type": "string"},
                    "priority": {"type": "integer"},
                    "assignee_id": {"type": "string"},
                }, "required": ["issue_id"]},
            }},
            {"type": "function", "function": {
                "name": "linear_list_projects",
                "description": "List all projects in the Linear workspace.",
                "parameters": {"type": "object", "properties": {
                    "limit": {"type": "integer"},
                }},
            }},
            {"type": "function", "function": {
                "name": "linear_list_cycles",
                "description": "List recent cycles (sprints) in Linear.",
                "parameters": {"type": "object", "properties": {}},
            }},
            {"type": "function", "function": {
                "name": "linear_list_teams",
                "description": "List all teams and their members.",
                "parameters": {"type": "object", "properties": {}},
            }},
        ]
