"""Airtable connector — Personal access token + REST API.

Bases, tables, records, views.
Requires: AIRTABLE_TOKEN env var or pass {"token": "pat..."} to connect().
"""

from __future__ import annotations

import json, logging, os
from typing import Any
import httpx
from .base import Connector

__all__ = ["AirtableConnector"]
log = logging.getLogger("orchestra.connectors.airtable")
API = "https://api.airtable.com/v0"
META = "https://api.airtable.com/v0/meta"


class AirtableConnector(Connector):
    name = "airtable"
    description = "Manage bases, tables, and records in Airtable."

    def __init__(self) -> None:
        self._token: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._token)

    @property
    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", "") or os.environ.get("AIRTABLE_TOKEN", "")
        if not self._token:
            log.error("No Airtable token.")
            return False
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{META}/bases", headers=self._h)
            if r.status_code == 200:
                log.info("Airtable connected")
                return True
        self._token = ""
        return False

    async def disconnect(self) -> None:
        self._token = ""

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._token: return {"error": "Airtable not connected."}
        d = {
            "airtable_list_bases": self._list_bases, "airtable_list_tables": self._list_tables,
            "airtable_list_records": self._list_records, "airtable_create_record": self._create_record,
            "airtable_update_record": self._update_record,
        }
        h = d.get(action)
        return await h(params) if h else {"error": f"Unknown: {action}"}

    async def _list_bases(self, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{META}/bases", headers=self._h)
            data = r.json()
        return {"bases": [{"id": b["id"], "name": b["name"]} for b in data.get("bases", [])]}

    async def _list_tables(self, params: dict[str, Any]) -> dict[str, Any]:
        base_id = params.get("base_id", "")
        if not base_id: return {"error": "base_id required"}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{META}/bases/{base_id}/tables", headers=self._h)
            data = r.json()
        return {"tables": [
            {"id": t["id"], "name": t["name"], "fields": [{"name": f["name"], "type": f["type"]} for f in t.get("fields", [])]}
            for t in data.get("tables", [])
        ]}

    async def _list_records(self, params: dict[str, Any]) -> dict[str, Any]:
        base_id = params.get("base_id", "")
        table = params.get("table", "")
        if not base_id or not table: return {"error": "base_id and table required"}
        limit = params.get("limit", 20)
        view = params.get("view", "")
        url = f"{API}/{base_id}/{table}?maxRecords={limit}"
        if view: url += f"&view={view}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers=self._h)
            data = r.json()
        return {"records": [{"id": rec["id"], "fields": rec.get("fields", {})} for rec in data.get("records", [])]}

    async def _create_record(self, params: dict[str, Any]) -> dict[str, Any]:
        base_id = params.get("base_id", "")
        table = params.get("table", "")
        fields = params.get("fields", {})
        if not all([base_id, table, fields]): return {"error": "base_id, table, fields required"}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{API}/{base_id}/{table}", headers=self._h, json={"records": [{"fields": fields}]})
            data = r.json()
        recs = data.get("records", [])
        return {"created": True, "id": recs[0]["id"]} if recs else {"error": data}

    async def _update_record(self, params: dict[str, Any]) -> dict[str, Any]:
        base_id = params.get("base_id", "")
        table = params.get("table", "")
        record_id = params.get("record_id", "")
        fields = params.get("fields", {})
        if not all([base_id, table, record_id, fields]): return {"error": "base_id, table, record_id, fields required"}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.patch(f"{API}/{base_id}/{table}/{record_id}", headers=self._h, json={"fields": fields})
            data = r.json()
        return {"updated": True, "id": data.get("id")} if "id" in data else {"error": data}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "airtable_list_bases", "description": "List all Airtable bases.", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "airtable_list_tables", "description": "List tables in an Airtable base.", "parameters": {"type": "object", "properties": {"base_id": {"type": "string"}}, "required": ["base_id"]}}},
            {"type": "function", "function": {"name": "airtable_list_records", "description": "List records from an Airtable table.", "parameters": {"type": "object", "properties": {"base_id": {"type": "string"}, "table": {"type": "string"}, "limit": {"type": "integer"}, "view": {"type": "string"}}, "required": ["base_id", "table"]}}},
            {"type": "function", "function": {"name": "airtable_create_record", "description": "Create a record in Airtable.", "parameters": {"type": "object", "properties": {"base_id": {"type": "string"}, "table": {"type": "string"}, "fields": {"type": "object"}}, "required": ["base_id", "table", "fields"]}}},
            {"type": "function", "function": {"name": "airtable_update_record", "description": "Update an Airtable record.", "parameters": {"type": "object", "properties": {"base_id": {"type": "string"}, "table": {"type": "string"}, "record_id": {"type": "string"}, "fields": {"type": "object"}}, "required": ["base_id", "table", "record_id", "fields"]}}},
        ]
