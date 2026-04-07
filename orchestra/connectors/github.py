"""GitHub connector — REST API v3 + token auth.

Supports repos, issues, PRs, code search, and file operations.
Requires: GITHUB_TOKEN env var or pass {"token": "ghp_..."} to connect().
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .base import Connector

__all__ = ["GitHubConnector"]

log = logging.getLogger("orchestra.connectors.github")

API_BASE = "https://api.github.com"


class GitHubConnector(Connector):
    """GitHub integration via REST API v3."""

    name = "github"
    description = "Manage repos, issues, PRs, and code on GitHub."

    def __init__(self) -> None:
        self._token: str = ""
        self._headers: dict[str, str] = {}

    @property
    def connected(self) -> bool:
        return bool(self._token)

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", "") or os.environ.get("GITHUB_TOKEN", "")
        if not self._token:
            log.error("No GitHub token. Set GITHUB_TOKEN or pass token in credentials.")
            return False
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "HorizonOrchestra/1.0",
        }
        # Verify token
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{API_BASE}/user", headers=self._headers)
            if resp.status_code == 200:
                user = resp.json().get("login", "")
                log.info("GitHub connected as: %s", user)
                return True
            log.error("GitHub token invalid: %s", resp.status_code)
            self._token = ""
            return False

    async def disconnect(self) -> None:
        self._token = ""
        self._headers = {}

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._token:
            return {"error": "GitHub not connected."}

        dispatch = {
            "github_list_repos": self._list_repos,
            "github_get_repo": self._get_repo,
            "github_search_code": self._search_code,
            "github_list_issues": self._list_issues,
            "github_create_issue": self._create_issue,
            "github_list_prs": self._list_prs,
            "github_get_file": self._get_file,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    async def _api(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method, f"{API_BASE}{path}", headers=self._headers, json=body,
            )
            if resp.status_code >= 400:
                return {"error": f"GitHub API {resp.status_code}: {resp.text[:500]}"}
            return resp.json() if resp.content else {}

    async def _list_repos(self, params: dict[str, Any]) -> dict[str, Any]:
        owner = params.get("owner", "")
        path = f"/users/{owner}/repos?per_page=30&sort=updated" if owner else "/user/repos?per_page=30&sort=updated"
        data = await self._api("GET", path)
        if isinstance(data, dict) and "error" in data:
            return data
        return {
            "count": len(data),
            "repos": [
                {
                    "full_name": r.get("full_name"),
                    "description": (r.get("description") or "")[:100],
                    "language": r.get("language"),
                    "stars": r.get("stargazers_count"),
                    "updated": r.get("updated_at"),
                }
                for r in (data if isinstance(data, list) else [])
            ],
        }

    async def _get_repo(self, params: dict[str, Any]) -> dict[str, Any]:
        repo = params.get("repo", "")  # "owner/repo"
        if not repo:
            return {"error": "repo is required (format: owner/repo)"}
        return await self._api("GET", f"/repos/{repo}")

    async def _search_code(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        repo = params.get("repo", "")
        if not query:
            return {"error": "query is required"}
        q = f"{query} repo:{repo}" if repo else query
        data = await self._api("GET", f"/search/code?q={q}&per_page=10")
        if isinstance(data, dict) and "error" in data:
            return data
        items = data.get("items", [])
        return {
            "total": data.get("total_count", 0),
            "results": [
                {
                    "name": i.get("name"),
                    "path": i.get("path"),
                    "repo": i.get("repository", {}).get("full_name"),
                    "url": i.get("html_url"),
                }
                for i in items[:10]
            ],
        }

    async def _list_issues(self, params: dict[str, Any]) -> dict[str, Any]:
        repo = params.get("repo", "")
        state = params.get("state", "open")
        if not repo:
            return {"error": "repo is required"}
        data = await self._api("GET", f"/repos/{repo}/issues?state={state}&per_page=20")
        if isinstance(data, dict) and "error" in data:
            return data
        return {
            "count": len(data),
            "issues": [
                {
                    "number": i.get("number"),
                    "title": i.get("title"),
                    "state": i.get("state"),
                    "author": i.get("user", {}).get("login"),
                    "labels": [l.get("name") for l in i.get("labels", [])],
                    "created": i.get("created_at"),
                }
                for i in (data if isinstance(data, list) else [])
            ],
        }

    async def _create_issue(self, params: dict[str, Any]) -> dict[str, Any]:
        repo = params.get("repo", "")
        title = params.get("title", "")
        body = params.get("body", "")
        labels = params.get("labels", [])
        if not repo or not title:
            return {"error": "repo and title are required"}
        data = await self._api("POST", f"/repos/{repo}/issues", {
            "title": title, "body": body, "labels": labels,
        })
        return {
            "created": True,
            "number": data.get("number"),
            "url": data.get("html_url"),
        }

    async def _list_prs(self, params: dict[str, Any]) -> dict[str, Any]:
        repo = params.get("repo", "")
        state = params.get("state", "open")
        if not repo:
            return {"error": "repo is required"}
        data = await self._api("GET", f"/repos/{repo}/pulls?state={state}&per_page=20")
        if isinstance(data, dict) and "error" in data:
            return data
        return {
            "count": len(data),
            "pull_requests": [
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "author": pr.get("user", {}).get("login"),
                    "branch": pr.get("head", {}).get("ref"),
                    "created": pr.get("created_at"),
                }
                for pr in (data if isinstance(data, list) else [])
            ],
        }

    async def _get_file(self, params: dict[str, Any]) -> dict[str, Any]:
        repo = params.get("repo", "")
        path = params.get("path", "")
        ref = params.get("ref", "")
        if not repo or not path:
            return {"error": "repo and path are required"}
        endpoint = f"/repos/{repo}/contents/{path}"
        if ref:
            endpoint += f"?ref={ref}"
        data = await self._api("GET", endpoint)
        if isinstance(data, dict) and "error" in data:
            return data
        import base64 as b64
        content = ""
        if data.get("encoding") == "base64" and data.get("content"):
            content = b64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return {
            "name": data.get("name"),
            "path": data.get("path"),
            "size": data.get("size"),
            "content": content[:50_000],
        }

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "github_list_repos",
                    "description": "List repositories for a user or the authenticated user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "owner": {"type": "string", "description": "GitHub username (omit for authenticated user)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_search_code",
                    "description": "Search code across GitHub repositories.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Code search query"},
                            "repo": {"type": "string", "description": "Limit to owner/repo"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_list_issues",
                    "description": "List issues for a repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "owner/repo"},
                            "state": {"type": "string", "enum": ["open", "closed", "all"]},
                        },
                        "required": ["repo"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_create_issue",
                    "description": "Create a new issue in a repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "owner/repo"},
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                            "labels": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["repo", "title"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_list_prs",
                    "description": "List pull requests for a repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "owner/repo"},
                            "state": {"type": "string", "enum": ["open", "closed", "all"]},
                        },
                        "required": ["repo"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_get_file",
                    "description": "Read a file from a GitHub repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "owner/repo"},
                            "path": {"type": "string", "description": "File path in the repo"},
                            "ref": {"type": "string", "description": "Branch or commit SHA"},
                        },
                        "required": ["repo", "path"],
                    },
                },
            },
        ]
