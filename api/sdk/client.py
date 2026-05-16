"""Python SDK client for the Orchestra RESTful API.

Connects the agent to the Express or C# backend for search, indexes, accounts, and RAG.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx


class OrchestraAPIClient:
    """Client for the Orchestra REST API (Express or .NET backend)."""

    def __init__(self, base_url: str = "http://localhost:4000", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(timeout=30, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "x-trace-id": uuid.uuid4().hex[:12]}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _trace(self) -> str:
        return uuid.uuid4().hex[:12]

    # ── Search ──────────────────────────────────────────────

    def query(self, index_name: str, query: str, filter: str = "",
              top: int = 10, facets: list[str] | None = None,
              conversation_history: list[dict] | None = None) -> dict[str, Any]:
        """POST /search/indexes/{indexName}/query"""
        body = {"query": query, "top": top}
        if filter:
            body["filter"] = filter
        if facets:
            body["facets"] = facets
        if conversation_history:
            body["conversation_history"] = conversation_history
        r = self._client.post(
            f"{self.base_url}/search/indexes/{index_name}/query",
            json=body, headers={"x-trace-id": self._trace()},
        )
        r.raise_for_status()
        return r.json()

    def index_documents(self, index_name: str, documents: list[dict]) -> dict[str, Any]:
        """POST /search/indexes/{indexName}/documents"""
        r = self._client.post(
            f"{self.base_url}/search/indexes/{index_name}/documents",
            json={"documents": documents}, headers={"x-trace-id": self._trace()},
        )
        r.raise_for_status()
        return r.json()

    # ── Indexes ─────────────────────────────────────────────

    def create_index(self, name: str, fields: list[dict]) -> dict[str, Any]:
        """POST /indexes"""
        r = self._client.post(
            f"{self.base_url}/indexes",
            json={"name": name, "fields": fields},
            headers={"x-trace-id": self._trace()},
        )
        r.raise_for_status()
        return r.json()

    def list_indexes(self) -> list[dict]:
        """GET /indexes"""
        r = self._client.get(f"{self.base_url}/indexes", headers={"x-trace-id": self._trace()})
        r.raise_for_status()
        return r.json().get("indexes", [])

    def get_index(self, name: str) -> dict[str, Any]:
        """GET /indexes/{indexName}"""
        r = self._client.get(f"{self.base_url}/indexes/{name}", headers={"x-trace-id": self._trace()})
        r.raise_for_status()
        return r.json()

    def delete_index(self, name: str) -> dict[str, Any]:
        """DELETE /indexes/{indexName}"""
        r = self._client.delete(f"{self.base_url}/indexes/{name}", headers={"x-trace-id": self._trace()})
        r.raise_for_status()
        return r.json()

    # ── Accounts (RAG) ──────────────────────────────────────

    def get_account(self, account_id: str) -> dict[str, Any]:
        """GET /accounts/{id} — for RAG-grounded responses"""
        r = self._client.get(f"{self.base_url}/accounts/{account_id}", headers={"x-trace-id": self._trace()})
        r.raise_for_status()
        return r.json()

    def list_accounts(self) -> list[dict]:
        """GET /accounts"""
        r = self._client.get(f"{self.base_url}/accounts", headers={"x-trace-id": self._trace()})
        r.raise_for_status()
        return r.json().get("accounts", [])

    def create_order(self, account_id: str, items: list[dict], total: float) -> dict[str, Any]:
        """POST /accounts/{id}/orders — action endpoint for agents"""
        r = self._client.post(
            f"{self.base_url}/accounts/{account_id}/orders",
            json={"items": items, "total": total},
            headers={"x-trace-id": self._trace()},
        )
        r.raise_for_status()
        return r.json()

    # ── Actions (schema discovery for agents) ──────────────

    def get_actions(self) -> list[dict]:
        """GET /actions — agent discovers available endpoints dynamically"""
        r = self._client.get(f"{self.base_url}/actions", headers={"x-trace-id": self._trace()})
        r.raise_for_status()
        return r.json().get("actions", [])

    def get_schema(self, index_name: str) -> dict[str, Any]:
        """GET /schemas/{indexName}"""
        r = self._client.get(f"{self.base_url}/schemas/{index_name}", headers={"x-trace-id": self._trace()})
        r.raise_for_status()
        return r.json()

    # ── Health ──────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        r = self._client.get(f"{self.base_url}/health", headers={"x-trace-id": self._trace()})
        r.raise_for_status()
        return r.json()
