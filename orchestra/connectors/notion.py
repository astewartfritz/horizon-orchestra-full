"""Notion connector — Integration token auth + REST API.

Requires: NOTION_TOKEN env var or pass {"token": "ntn_..."} to connect().
Uses the Notion API v2022-06-28.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .base import Connector

__all__ = ["NotionConnector"]

log = logging.getLogger("orchestra.connectors.notion")

API_BASE = "https://api.notion.com/v1"
API_VERSION = "2022-06-28"


class NotionConnector(Connector):
    """Notion integration via REST API."""

    name = "notion"
    description = "Search, read, and create pages and databases in Notion."

    def __init__(self) -> None:
        self._token: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._token)

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", "") or os.environ.get("NOTION_TOKEN", "")
        if not self._token:
            log.error("No Notion token. Set NOTION_TOKEN or pass token.")
            return False
        # Verify
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{API_BASE}/users/me", headers=self._headers)
            if resp.status_code == 200:
                data = resp.json()
                log.info("Notion connected: %s", data.get("name", ""))
                return True
        log.error("Notion token invalid")
        self._token = ""
        return False

    async def disconnect(self) -> None:
        self._token = ""

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Notion-Version": API_VERSION,
        }

    async def _api(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method, f"{API_BASE}{path}", headers=self._headers, json=body,
            )
            if resp.status_code >= 400:
                return {"error": f"Notion API {resp.status_code}: {resp.text[:500]}"}
            return resp.json()

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._token:
            return {"error": "Notion not connected."}
        dispatch = {
            "notion_search": self._search,
            "notion_read_page": self._read_page,
            "notion_create_page": self._create_page,
            "notion_query_database": self._query_database,
            "notion_list_databases": self._list_databases,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    async def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        filter_type = params.get("filter_type", "")  # "page" or "database"
        body: dict[str, Any] = {"query": query, "page_size": 10}
        if filter_type in ("page", "database"):
            body["filter"] = {"value": filter_type, "property": "object"}
        data = await self._api("POST", "/search", body)
        if "error" in data:
            return data
        results = data.get("results", [])
        return {
            "count": len(results),
            "results": [
                {
                    "id": r.get("id"),
                    "type": r.get("object"),
                    "title": self._extract_title(r),
                    "url": r.get("url"),
                    "last_edited": r.get("last_edited_time"),
                }
                for r in results
            ],
        }

    async def _read_page(self, params: dict[str, Any]) -> dict[str, Any]:
        page_id = params.get("page_id", "")
        if not page_id:
            return {"error": "page_id is required"}

        # Get page metadata
        page = await self._api("GET", f"/pages/{page_id}")
        if "error" in page:
            return page

        # Get page content (blocks)
        blocks = await self._api("GET", f"/blocks/{page_id}/children?page_size=100")
        content_parts: list[str] = []
        for block in blocks.get("results", []):
            text = self._extract_block_text(block)
            if text:
                content_parts.append(text)

        return {
            "id": page_id,
            "title": self._extract_title(page),
            "url": page.get("url"),
            "content": "\n".join(content_parts)[:20_000],
        }

    async def _create_page(self, params: dict[str, Any]) -> dict[str, Any]:
        parent_id = params.get("parent_id", "")
        title = params.get("title", "")
        content = params.get("content", "")
        parent_type = params.get("parent_type", "page")  # "page" or "database"

        if not parent_id or not title:
            return {"error": "parent_id and title are required"}

        parent: dict[str, Any]
        if parent_type == "database":
            parent = {"database_id": parent_id}
            properties = {
                "title": {"title": [{"text": {"content": title}}]},
            }
        else:
            parent = {"page_id": parent_id}
            properties = {
                "title": {"title": [{"text": {"content": title}}]},
            }

        children: list[dict[str, Any]] = []
        if content:
            # Split content into paragraph blocks
            for para in content.split("\n\n"):
                if para.strip():
                    children.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": para.strip()}}],
                        },
                    })

        body: dict[str, Any] = {
            "parent": parent,
            "properties": properties,
        }
        if children:
            body["children"] = children[:100]  # Notion limit

        data = await self._api("POST", "/pages", body)
        if "error" in data:
            return data
        return {
            "created": True,
            "id": data.get("id"),
            "url": data.get("url"),
        }

    async def _query_database(self, params: dict[str, Any]) -> dict[str, Any]:
        database_id = params.get("database_id", "")
        if not database_id:
            return {"error": "database_id is required"}

        body: dict[str, Any] = {"page_size": params.get("limit", 20)}
        # Optional filter and sort
        if params.get("filter"):
            body["filter"] = params["filter"]
        if params.get("sort"):
            body["sorts"] = params["sort"] if isinstance(params["sort"], list) else [params["sort"]]

        data = await self._api("POST", f"/databases/{database_id}/query", body)
        if "error" in data:
            return data
        results = data.get("results", [])
        return {
            "count": len(results),
            "rows": [
                {
                    "id": r.get("id"),
                    "title": self._extract_title(r),
                    "properties": self._flatten_properties(r.get("properties", {})),
                    "url": r.get("url"),
                }
                for r in results
            ],
        }

    async def _list_databases(self, params: dict[str, Any]) -> dict[str, Any]:
        data = await self._api("POST", "/search", {
            "filter": {"value": "database", "property": "object"},
            "page_size": 20,
        })
        if "error" in data:
            return data
        return {
            "count": len(data.get("results", [])),
            "databases": [
                {
                    "id": r.get("id"),
                    "title": self._extract_title(r),
                    "url": r.get("url"),
                }
                for r in data.get("results", [])
            ],
        }

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _extract_title(obj: dict[str, Any]) -> str:
        props = obj.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                titles = prop.get("title", [])
                if titles:
                    return titles[0].get("plain_text", "")
        # Fallback for databases
        title_list = obj.get("title", [])
        if title_list and isinstance(title_list, list):
            return title_list[0].get("plain_text", "")
        return ""

    @staticmethod
    def _extract_block_text(block: dict[str, Any]) -> str:
        btype = block.get("type", "")
        bdata = block.get(btype, {})
        rich_text = bdata.get("rich_text", [])
        texts = [t.get("plain_text", "") for t in rich_text]
        return "".join(texts)

    @staticmethod
    def _flatten_properties(properties: dict[str, Any]) -> dict[str, Any]:
        flat: dict[str, Any] = {}
        for key, prop in properties.items():
            ptype = prop.get("type", "")
            if ptype == "title":
                titles = prop.get("title", [])
                flat[key] = titles[0].get("plain_text", "") if titles else ""
            elif ptype == "rich_text":
                texts = prop.get("rich_text", [])
                flat[key] = texts[0].get("plain_text", "") if texts else ""
            elif ptype == "number":
                flat[key] = prop.get("number")
            elif ptype == "select":
                sel = prop.get("select")
                flat[key] = sel.get("name", "") if sel else ""
            elif ptype == "multi_select":
                flat[key] = [s.get("name", "") for s in prop.get("multi_select", [])]
            elif ptype == "checkbox":
                flat[key] = prop.get("checkbox", False)
            elif ptype == "date":
                date = prop.get("date")
                flat[key] = date.get("start", "") if date else ""
            elif ptype == "url":
                flat[key] = prop.get("url", "")
            else:
                flat[key] = f"({ptype})"
        return flat

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "notion_search",
                    "description": "Search across all Notion pages and databases.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "filter_type": {
                                "type": "string",
                                "enum": ["page", "database", ""],
                                "description": "Filter by type",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_read_page",
                    "description": "Read the full content of a Notion page.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_id": {"type": "string", "description": "Notion page ID"},
                        },
                        "required": ["page_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_create_page",
                    "description": "Create a new Notion page under a parent page or database.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "parent_id": {"type": "string", "description": "Parent page or database ID"},
                            "parent_type": {"type": "string", "enum": ["page", "database"]},
                            "title": {"type": "string"},
                            "content": {"type": "string", "description": "Page content (paragraphs separated by double newlines)"},
                        },
                        "required": ["parent_id", "title"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_query_database",
                    "description": "Query a Notion database and return rows.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "database_id": {"type": "string", "description": "Notion database ID"},
                            "limit": {"type": "integer", "description": "Max rows (default 20)"},
                        },
                        "required": ["database_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notion_list_databases",
                    "description": "List all Notion databases accessible to the integration.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]
