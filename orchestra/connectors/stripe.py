"""Stripe connector — API key auth.

Payments, customers, invoices, subscriptions.
Requires: STRIPE_API_KEY env var or pass {"token": "sk_..."} to connect().
"""

from __future__ import annotations

import json, logging, os
from typing import Any
import httpx
from .base import Connector

__all__ = ["StripeConnector"]
log = logging.getLogger("orchestra.connectors.stripe")
API = "https://api.stripe.com/v1"


class StripeConnector(Connector):
    name = "stripe"
    description = "Manage payments, customers, invoices, and subscriptions in Stripe."

    def __init__(self) -> None:
        self._token: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._token)

    @property
    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", "") or os.environ.get("STRIPE_API_KEY", "")
        if not self._token:
            log.error("No Stripe key.")
            return False
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{API}/balance", headers=self._h)
            if r.status_code == 200:
                log.info("Stripe connected")
                return True
        self._token = ""
        return False

    async def disconnect(self) -> None:
        self._token = ""

    async def _api(self, method: str, path: str, data: dict | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.request(method, f"{API}{path}", headers=self._h, data=data)
            if resp.status_code >= 400:
                return {"error": f"Stripe {resp.status_code}: {resp.text[:500]}"}
            return resp.json()

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._token: return {"error": "Stripe not connected."}
        d = {
            "stripe_list_customers": self._list_customers, "stripe_create_customer": self._create_customer,
            "stripe_list_invoices": self._list_invoices, "stripe_list_payments": self._list_payments,
            "stripe_list_subscriptions": self._list_subs, "stripe_get_balance": self._balance,
        }
        h = d.get(action)
        return await h(params) if h else {"error": f"Unknown: {action}"}

    async def _list_customers(self, p: dict) -> dict[str, Any]:
        r = await self._api("GET", f"/customers?limit={p.get('limit', 20)}")
        if "error" in r: return r
        return {"customers": [
            {"id": c["id"], "email": c.get("email"), "name": c.get("name"), "created": c.get("created")}
            for c in r.get("data", [])
        ]}

    async def _create_customer(self, p: dict) -> dict[str, Any]:
        data: dict[str, str] = {}
        for k in ("email", "name", "phone", "description"):
            if p.get(k): data[k] = p[k]
        if not data.get("email"): return {"error": "email required"}
        r = await self._api("POST", "/customers", data)
        return {"created": True, "id": r.get("id")} if "id" in r else r

    async def _list_invoices(self, p: dict) -> dict[str, Any]:
        r = await self._api("GET", f"/invoices?limit={p.get('limit', 20)}")
        if "error" in r: return r
        return {"invoices": [
            {"id": i["id"], "customer": i.get("customer"), "amount_due": i.get("amount_due"), "currency": i.get("currency"), "status": i.get("status"), "due_date": i.get("due_date")}
            for i in r.get("data", [])
        ]}

    async def _list_payments(self, p: dict) -> dict[str, Any]:
        r = await self._api("GET", f"/payment_intents?limit={p.get('limit', 20)}")
        if "error" in r: return r
        return {"payments": [
            {"id": pi["id"], "amount": pi.get("amount"), "currency": pi.get("currency"), "status": pi.get("status"), "customer": pi.get("customer")}
            for pi in r.get("data", [])
        ]}

    async def _list_subs(self, p: dict) -> dict[str, Any]:
        r = await self._api("GET", f"/subscriptions?limit={p.get('limit', 20)}")
        if "error" in r: return r
        return {"subscriptions": [
            {"id": s["id"], "customer": s.get("customer"), "status": s.get("status"), "plan": (s.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", "") if s.get("items") else "")}
            for s in r.get("data", [])
        ]}

    async def _balance(self, p: dict) -> dict[str, Any]:
        return await self._api("GET", "/balance")

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "stripe_list_customers", "description": "List Stripe customers.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "stripe_create_customer", "description": "Create a Stripe customer.", "parameters": {"type": "object", "properties": {"email": {"type": "string"}, "name": {"type": "string"}, "phone": {"type": "string"}}, "required": ["email"]}}},
            {"type": "function", "function": {"name": "stripe_list_invoices", "description": "List Stripe invoices.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "stripe_list_payments", "description": "List Stripe payment intents.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "stripe_list_subscriptions", "description": "List Stripe subscriptions.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "stripe_get_balance", "description": "Get Stripe account balance.", "parameters": {"type": "object", "properties": {}}}},
        ]
