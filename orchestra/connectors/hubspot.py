"""HubSpot CRM connector — API key or OAuth token.

Contacts, deals, companies, activities.
Requires: HUBSPOT_API_KEY env var or pass {"token": "pat-..."} to connect().
"""

from __future__ import annotations

import json, logging, os
from typing import Any
import httpx
from .base import Connector

__all__ = ["HubSpotConnector"]
log = logging.getLogger("orchestra.connectors.hubspot")
API = "https://api.hubapi.com"


class HubSpotConnector(Connector):
    name = "hubspot"
    description = "Manage contacts, deals, companies, and activities in HubSpot CRM."

    def __init__(self) -> None:
        self._token: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._token)

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", "") or os.environ.get("HUBSPOT_API_KEY", "")
        if not self._token:
            log.error("No HubSpot token.")
            return False
        r = await self._api("GET", "/crm/v3/objects/contacts?limit=1")
        if "error" not in r:
            log.info("HubSpot connected")
            return True
        self._token = ""
        return False

    async def disconnect(self) -> None:
        self._token = ""

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def _api(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.request(method, f"{API}{path}", headers=self._headers, json=body)
            if resp.status_code >= 400:
                return {"error": f"HubSpot {resp.status_code}: {resp.text[:500]}"}
            return resp.json() if resp.content else {}

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._token: return {"error": "HubSpot not connected."}
        d = {
            "hubspot_search_contacts": self._search_contacts, "hubspot_create_contact": self._create_contact,
            "hubspot_list_deals": self._list_deals, "hubspot_create_deal": self._create_deal,
            "hubspot_list_companies": self._list_companies, "hubspot_create_note": self._create_note,
        }
        h = d.get(action)
        return await h(params) if h else {"error": f"Unknown: {action}"}

    async def _search_contacts(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        r = await self._api("POST", "/crm/v3/objects/contacts/search", {
            "query": query, "limit": params.get("limit", 10),
            "properties": ["firstname", "lastname", "email", "phone", "company"],
        })
        if "error" in r: return r
        return {"contacts": [
            {"id": c["id"], **{k: v for k, v in c.get("properties", {}).items()}}
            for c in r.get("results", [])
        ]}

    async def _create_contact(self, params: dict[str, Any]) -> dict[str, Any]:
        props: dict[str, str] = {}
        for k in ("email", "firstname", "lastname", "phone", "company"):
            if params.get(k): props[k] = params[k]
        if not props.get("email"): return {"error": "email required"}
        r = await self._api("POST", "/crm/v3/objects/contacts", {"properties": props})
        return {"created": True, "id": r.get("id")} if "id" in r else r

    async def _list_deals(self, params: dict[str, Any]) -> dict[str, Any]:
        r = await self._api("GET", f"/crm/v3/objects/deals?limit={params.get('limit', 20)}&properties=dealname,amount,dealstage,closedate")
        if "error" in r: return r
        return {"deals": [{"id": d["id"], **d.get("properties", {})} for d in r.get("results", [])]}

    async def _create_deal(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        if not name: return {"error": "name required"}
        props = {"dealname": name}
        for k in ("amount", "dealstage", "closedate", "pipeline"):
            if params.get(k): props[k] = str(params[k])
        r = await self._api("POST", "/crm/v3/objects/deals", {"properties": props})
        return {"created": True, "id": r.get("id")} if "id" in r else r

    async def _list_companies(self, params: dict[str, Any]) -> dict[str, Any]:
        r = await self._api("GET", f"/crm/v3/objects/companies?limit={params.get('limit', 20)}&properties=name,domain,industry,numberofemployees")
        if "error" in r: return r
        return {"companies": [{"id": c["id"], **c.get("properties", {})} for c in r.get("results", [])]}

    async def _create_note(self, params: dict[str, Any]) -> dict[str, Any]:
        body = params.get("body", "")
        contact_id = params.get("contact_id", "")
        if not body: return {"error": "body required"}
        r = await self._api("POST", "/crm/v3/objects/notes", {"properties": {"hs_note_body": body, "hs_timestamp": str(int(__import__("time").time() * 1000))}})
        if "error" in r: return r
        if contact_id:
            await self._api("PUT", f"/crm/v3/objects/notes/{r['id']}/associations/contacts/{contact_id}/202")
        return {"created": True, "id": r.get("id")}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "hubspot_search_contacts", "description": "Search HubSpot contacts.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "hubspot_create_contact", "description": "Create a HubSpot contact.", "parameters": {"type": "object", "properties": {"email": {"type": "string"}, "firstname": {"type": "string"}, "lastname": {"type": "string"}, "phone": {"type": "string"}, "company": {"type": "string"}}, "required": ["email"]}}},
            {"type": "function", "function": {"name": "hubspot_list_deals", "description": "List HubSpot deals.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "hubspot_create_deal", "description": "Create a HubSpot deal.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "amount": {"type": "string"}, "dealstage": {"type": "string"}, "closedate": {"type": "string"}}, "required": ["name"]}}},
            {"type": "function", "function": {"name": "hubspot_list_companies", "description": "List HubSpot companies.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "hubspot_create_note", "description": "Create a note on a HubSpot contact.", "parameters": {"type": "object", "properties": {"body": {"type": "string"}, "contact_id": {"type": "string"}}, "required": ["body"]}}},
        ]
