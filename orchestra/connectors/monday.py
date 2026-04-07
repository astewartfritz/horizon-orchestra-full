"""Monday.com connector — API token auth + GraphQL API v2.

Full project management: boards, items, columns, groups, updates,
subitems, and automations.

Requires: MONDAY_API_KEY env var or pass {"token": "..."} to connect().
API docs: https://developer.monday.com/api-reference
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .base import Connector

__all__ = ["MondayConnector"]

log = logging.getLogger("orchestra.connectors.monday")

API_URL = "https://api.monday.com/v2"


class MondayConnector(Connector):
    """Monday.com integration via GraphQL API v2."""

    name = "monday"
    description = "Manage boards, items, columns, groups, and updates in Monday.com."

    def __init__(self) -> None:
        self._token: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._token)

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", "") or os.environ.get("MONDAY_API_KEY", "")
        if not self._token:
            log.error("No Monday.com token. Set MONDAY_API_KEY or pass token.")
            return False
        result = await self._gql("{ me { id name email } }")
        me = result.get("data", {}).get("me")
        if me:
            log.info("Monday.com connected as: %s (%s)", me.get("name"), me.get("email"))
            return True
        log.error("Monday.com auth failed: %s", result.get("errors"))
        self._token = ""
        return False

    async def disconnect(self) -> None:
        self._token = ""

    async def _gql(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        headers = {
            "Authorization": self._token,
            "Content-Type": "application/json",
            "API-Version": "2024-10",
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
            return {"error": "Monday.com not connected."}
        dispatch = {
            "monday_list_boards": self._list_boards,
            "monday_get_board": self._get_board,
            "monday_list_items": self._list_items,
            "monday_get_item": self._get_item,
            "monday_create_item": self._create_item,
            "monday_update_item": self._update_item,
            "monday_add_update": self._add_update,
            "monday_create_subitem": self._create_subitem,
            "monday_move_item": self._move_item,
            "monday_search": self._search,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    async def _list_boards(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit", 20)
        gql = f"""{{
            boards(limit: {limit}, order_by: used_at) {{
                id name description state
                board_folder_id
                columns {{ id title type }}
                groups {{ id title }}
                items_count
            }}
        }}"""
        result = await self._gql(gql)
        boards = result.get("data", {}).get("boards", [])
        return {
            "count": len(boards),
            "boards": [
                {
                    "id": b.get("id"),
                    "name": b.get("name"),
                    "description": (b.get("description") or "")[:200],
                    "state": b.get("state"),
                    "items_count": b.get("items_count"),
                    "columns": [{"id": c["id"], "title": c["title"], "type": c["type"]} for c in b.get("columns", [])],
                    "groups": [{"id": g["id"], "title": g["title"]} for g in b.get("groups", [])],
                }
                for b in boards
            ],
        }

    async def _get_board(self, params: dict[str, Any]) -> dict[str, Any]:
        board_id = params.get("board_id", "")
        if not board_id:
            return {"error": "board_id required"}
        gql = f"""{{
            boards(ids: [{board_id}]) {{
                id name description state
                columns {{ id title type settings_str }}
                groups {{ id title color }}
                items_count
                owners {{ id name }}
            }}
        }}"""
        result = await self._gql(gql)
        boards = result.get("data", {}).get("boards", [])
        return boards[0] if boards else {"error": f"Board {board_id} not found"}

    async def _list_items(self, params: dict[str, Any]) -> dict[str, Any]:
        board_id = params.get("board_id", "")
        group_id = params.get("group_id", "")
        limit = params.get("limit", 25)
        if not board_id:
            return {"error": "board_id required"}

        group_filter = f', query_params: {{rules: [{{column_id: "group", compare_value: ["{group_id}"]}}]}}' if group_id else ""

        gql = f"""{{
            boards(ids: [{board_id}]) {{
                items_page(limit: {limit}{group_filter}) {{
                    items {{
                        id name
                        group {{ id title }}
                        column_values {{
                            id title text type value
                        }}
                        created_at updated_at
                        creator {{ name }}
                    }}
                }}
            }}
        }}"""
        result = await self._gql(gql)
        boards = result.get("data", {}).get("boards", [])
        if not boards:
            return {"error": "Board not found"}
        items = boards[0].get("items_page", {}).get("items", [])
        return {
            "count": len(items),
            "items": [
                {
                    "id": i.get("id"),
                    "name": i.get("name"),
                    "group": (i.get("group") or {}).get("title"),
                    "columns": {
                        cv.get("title", cv.get("id")): cv.get("text", "")
                        for cv in i.get("column_values", [])
                        if cv.get("text")
                    },
                    "created": i.get("created_at"),
                    "updated": i.get("updated_at"),
                }
                for i in items
            ],
        }

    async def _get_item(self, params: dict[str, Any]) -> dict[str, Any]:
        item_id = params.get("item_id", "")
        if not item_id:
            return {"error": "item_id required"}
        gql = f"""{{
            items(ids: [{item_id}]) {{
                id name
                board {{ id name }}
                group {{ id title }}
                column_values {{
                    id title text type value
                }}
                subitems {{
                    id name
                    column_values {{ id title text }}
                }}
                updates(limit: 5) {{
                    id body text_body
                    creator {{ name }}
                    created_at
                }}
                created_at updated_at
            }}
        }}"""
        result = await self._gql(gql)
        items = result.get("data", {}).get("items", [])
        if not items:
            return {"error": f"Item {item_id} not found"}
        i = items[0]
        return {
            "id": i.get("id"),
            "name": i.get("name"),
            "board": (i.get("board") or {}).get("name"),
            "group": (i.get("group") or {}).get("title"),
            "columns": {
                cv.get("title", cv.get("id")): cv.get("text", "")
                for cv in i.get("column_values", [])
            },
            "subitems": [
                {"id": s["id"], "name": s["name"]}
                for s in i.get("subitems", [])
            ],
            "updates": [
                {
                    "author": (u.get("creator") or {}).get("name"),
                    "body": u.get("text_body", "")[:500],
                    "created": u.get("created_at"),
                }
                for u in i.get("updates", [])
            ],
        }

    async def _create_item(self, params: dict[str, Any]) -> dict[str, Any]:
        board_id = params.get("board_id", "")
        name = params.get("name", "")
        group_id = params.get("group_id", "")
        column_values = params.get("column_values", {})
        if not board_id or not name:
            return {"error": "board_id and name required"}

        group_arg = f', group_id: "{group_id}"' if group_id else ""
        col_json = json.dumps(json.dumps(column_values)) if column_values else '"{}"'

        gql = f"""mutation {{
            create_item(
                board_id: {board_id},
                item_name: "{name}"{group_arg},
                column_values: {col_json}
            ) {{
                id name
            }}
        }}"""
        result = await self._gql(gql)
        item = result.get("data", {}).get("create_item")
        if item:
            return {"created": True, "id": item.get("id"), "name": item.get("name")}
        return {"error": "Failed to create item", "details": result.get("errors")}

    async def _update_item(self, params: dict[str, Any]) -> dict[str, Any]:
        board_id = params.get("board_id", "")
        item_id = params.get("item_id", "")
        column_values = params.get("column_values", {})
        if not board_id or not item_id or not column_values:
            return {"error": "board_id, item_id, column_values required"}

        col_json = json.dumps(json.dumps(column_values))
        gql = f"""mutation {{
            change_multiple_column_values(
                board_id: {board_id},
                item_id: {item_id},
                column_values: {col_json}
            ) {{
                id name
            }}
        }}"""
        result = await self._gql(gql)
        item = result.get("data", {}).get("change_multiple_column_values")
        if item:
            return {"updated": True, "id": item.get("id")}
        return {"error": "Failed to update item", "details": result.get("errors")}

    async def _add_update(self, params: dict[str, Any]) -> dict[str, Any]:
        item_id = params.get("item_id", "")
        body = params.get("body", "")
        if not item_id or not body:
            return {"error": "item_id and body required"}
        gql = f"""mutation {{
            create_update(item_id: {item_id}, body: "{body}") {{
                id
            }}
        }}"""
        result = await self._gql(gql)
        update = result.get("data", {}).get("create_update")
        if update:
            return {"created": True, "update_id": update.get("id")}
        return {"error": "Failed", "details": result.get("errors")}

    async def _create_subitem(self, params: dict[str, Any]) -> dict[str, Any]:
        parent_id = params.get("parent_id", "")
        name = params.get("name", "")
        if not parent_id or not name:
            return {"error": "parent_id and name required"}
        gql = f"""mutation {{
            create_subitem(parent_item_id: {parent_id}, item_name: "{name}") {{
                id name board {{ id }}
            }}
        }}"""
        result = await self._gql(gql)
        sub = result.get("data", {}).get("create_subitem")
        if sub:
            return {"created": True, "id": sub.get("id"), "name": sub.get("name")}
        return {"error": "Failed", "details": result.get("errors")}

    async def _move_item(self, params: dict[str, Any]) -> dict[str, Any]:
        item_id = params.get("item_id", "")
        group_id = params.get("group_id", "")
        if not item_id or not group_id:
            return {"error": "item_id and group_id required"}
        gql = f"""mutation {{
            move_item_to_group(item_id: {item_id}, group_id: "{group_id}") {{
                id
            }}
        }}"""
        result = await self._gql(gql)
        moved = result.get("data", {}).get("move_item_to_group")
        return {"moved": True, "id": moved.get("id")} if moved else {"error": "Failed"}

    async def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        limit = params.get("limit", 10)
        if not query:
            return {"error": "query required"}
        gql = f"""{{
            items_page_by_column_values(
                limit: {limit},
                board_id: {params.get("board_id", 0)},
                columns: [{{column_id: "name", column_values: ["{query}"]}}]
            ) {{
                items {{
                    id name
                    board {{ id name }}
                    group {{ title }}
                    column_values {{ id title text }}
                }}
            }}
        }}"""
        # Fallback: use boards_page search if no board_id
        if not params.get("board_id"):
            gql = f"""{{
                boards(limit: 50) {{
                    id name
                    items_page(limit: 5, query_params: {{rules: [{{column_id: "name", compare_value: ["{query}"]}}]}}) {{
                        items {{ id name group {{ title }} }}
                    }}
                }}
            }}"""
        result = await self._gql(gql)
        # Parse depending on query structure
        items = []
        if "boards" in result.get("data", {}):
            for b in result["data"]["boards"]:
                for i in b.get("items_page", {}).get("items", []):
                    items.append({"id": i["id"], "name": i["name"], "board": b["name"], "group": (i.get("group") or {}).get("title")})
        else:
            page = result.get("data", {}).get("items_page_by_column_values", {})
            items = [{"id": i["id"], "name": i["name"]} for i in page.get("items", [])]
        return {"count": len(items), "items": items[:limit]}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "monday_list_boards", "description": "List Monday.com boards with columns and groups.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}, }}},
            {"type": "function", "function": {"name": "monday_get_board", "description": "Get full details of a Monday.com board.", "parameters": {"type": "object", "properties": {"board_id": {"type": "string"}}, "required": ["board_id"]}}},
            {"type": "function", "function": {"name": "monday_list_items", "description": "List items in a Monday.com board, optionally filtered by group.", "parameters": {"type": "object", "properties": {"board_id": {"type": "string"}, "group_id": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["board_id"]}}},
            {"type": "function", "function": {"name": "monday_get_item", "description": "Get full details of a Monday.com item including subitems and updates.", "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]}}},
            {"type": "function", "function": {"name": "monday_create_item", "description": "Create a new item in a Monday.com board.", "parameters": {"type": "object", "properties": {"board_id": {"type": "string"}, "name": {"type": "string"}, "group_id": {"type": "string"}, "column_values": {"type": "object", "description": "Column ID to value map"}}, "required": ["board_id", "name"]}}},
            {"type": "function", "function": {"name": "monday_update_item", "description": "Update column values on a Monday.com item.", "parameters": {"type": "object", "properties": {"board_id": {"type": "string"}, "item_id": {"type": "string"}, "column_values": {"type": "object"}}, "required": ["board_id", "item_id", "column_values"]}}},
            {"type": "function", "function": {"name": "monday_add_update", "description": "Add a comment/update to a Monday.com item.", "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}, "body": {"type": "string"}}, "required": ["item_id", "body"]}}},
            {"type": "function", "function": {"name": "monday_create_subitem", "description": "Create a subitem under a Monday.com item.", "parameters": {"type": "object", "properties": {"parent_id": {"type": "string"}, "name": {"type": "string"}}, "required": ["parent_id", "name"]}}},
            {"type": "function", "function": {"name": "monday_move_item", "description": "Move an item to a different group.", "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}, "group_id": {"type": "string"}}, "required": ["item_id", "group_id"]}}},
            {"type": "function", "function": {"name": "monday_search", "description": "Search for items across Monday.com boards.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "board_id": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
        ]
