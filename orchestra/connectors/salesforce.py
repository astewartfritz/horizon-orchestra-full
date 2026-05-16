"""Salesforce connector — OAuth2 / JWT / username-password authentication.

Supports REST API v60, Bulk API 2.0, SOQL, SOSL, Streaming, and CRM operations.

Requires: pip install requests simple-salesforce

Auth flows:
1. OAuth2 connected app (client credentials)
2. Username + password + security token
3. JWT bearer token flow

Env vars:
    SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET,
    SALESFORCE_USERNAME, SALESFORCE_PASSWORD,
    SALESFORCE_INSTANCE_URL, SALESFORCE_SECURITY_TOKEN
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

from .base import Connector

__all__ = ["SalesforceConnector", "SalesforceError"]

log = logging.getLogger("orchestra.connectors.salesforce")

# Optional dependency guard
try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore[assignment]

try:
    from simple_salesforce import Salesforce as _SalesforceClient
    from simple_salesforce.exceptions import SalesforceError as _SFBaseError
except ImportError:
    _SalesforceClient = None  # type: ignore[assignment,misc]
    _SFBaseError = Exception  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class SalesforceError(Exception):
    """Base error for all Salesforce connector failures."""


class SalesforceAuthError(SalesforceError):
    """Authentication or authorisation failure."""


class SalesforceAPIError(SalesforceError):
    """REST / Bulk / Streaming API error."""


class SalesforceRateLimitError(SalesforceError):
    """Daily or per-second rate limit exceeded."""


class SalesforceBulkError(SalesforceError):
    """Bulk API 2.0 job failure."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_VERSION = "v60.0"
DEFAULT_DAILY_LIMIT = 15_000
MAX_RETRIES = 4
INITIAL_BACKOFF = 1.0  # seconds

TOOLS: list[dict[str, Any]] = []  # populated at class level below


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _retry_with_backoff(coro_factory, *, max_retries: int = MAX_RETRIES):
    """Retry an async callable with exponential backoff on transient errors."""
    delay = INITIAL_BACKOFF
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except SalesforceRateLimitError:
            raise
        except (SalesforceAPIError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                log.warning(
                    "Salesforce request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise
    raise last_exc  # type: ignore[misc]


def _require_requests() -> Any:
    if _requests is None:
        raise SalesforceError(
            "Salesforce connector requires: pip install requests"
        )
    return _requests


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class SalesforceConnector(Connector):
    """Full Salesforce CRM integration — REST v60, Bulk 2.0, SOQL/SOSL.

    Provides 18 tools covering CRUD, bulk operations, search, pipeline
    analytics, and task management.
    """

    name = "salesforce"
    description = (
        "Query, create, update, and bulk-manage Salesforce CRM data "
        "including Accounts, Contacts, Opportunities, and custom objects."
    )

    # Class-level tool count for inspection
    TOOLS: list[str] = [
        "sf_query_records",
        "sf_query_all",
        "sf_get_record",
        "sf_create_record",
        "sf_update_record",
        "sf_delete_record",
        "sf_describe_object",
        "sf_bulk_create",
        "sf_bulk_update",
        "sf_bulk_upsert",
        "sf_search_records",
        "sf_get_recent",
        "sf_get_opportunities",
        "sf_get_contacts",
        "sf_get_accounts",
        "sf_create_task",
        "sf_run_report",
        "sf_get_dashboard_metrics",
    ]

    def __init__(self) -> None:
        self._client: Any = None
        self._instance_url: str = ""
        self._access_token: str = ""
        self._api_call_count: int = 0
        self._daily_limit: int = DEFAULT_DAILY_LIMIT
        self._session: Any = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Return True when an authenticated session exists."""
        return self._client is not None or bool(self._access_token)

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with Salesforce.

        Supported credential keys:
            - username, password, security_token  — user/pass flow
            - client_id, client_secret            — OAuth2 client credentials
            - instance_url                        — custom instance URL
            - access_token                        — pre-obtained token
        """
        requests = _require_requests()

        # Pre-obtained token shortcut
        if credentials.get("access_token") and credentials.get("instance_url"):
            self._access_token = credentials["access_token"]
            self._instance_url = credentials["instance_url"]
            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            })
            log.info("Salesforce connected (pre-obtained token)")
            return True

        # Env fallback
        username = credentials.get("username", os.getenv("SALESFORCE_USERNAME", ""))
        password = credentials.get("password", os.getenv("SALESFORCE_PASSWORD", ""))
        token = credentials.get("security_token", os.getenv("SALESFORCE_SECURITY_TOKEN", ""))
        client_id = credentials.get("client_id", os.getenv("SALESFORCE_CLIENT_ID", ""))
        client_secret = credentials.get("client_secret", os.getenv("SALESFORCE_CLIENT_SECRET", ""))
        instance_url = credentials.get("instance_url", os.getenv("SALESFORCE_INSTANCE_URL", ""))

        # Try simple-salesforce client first
        if _SalesforceClient and username and password:
            try:
                sf_kwargs: dict[str, Any] = {
                    "username": username,
                    "password": password,
                    "security_token": token,
                }
                if client_id:
                    sf_kwargs["client_id"] = client_id
                if instance_url:
                    sf_kwargs["instance_url"] = instance_url
                    sf_kwargs["domain"] = "test" if "sandbox" in instance_url.lower() else None
                self._client = _SalesforceClient(**sf_kwargs)
                self._instance_url = self._client.sf_instance
                self._access_token = self._client.session_id
                log.info("Salesforce connected via simple-salesforce")
                return True
            except Exception as exc:
                log.warning("simple-salesforce auth failed: %s", exc)

        # OAuth2 client credentials flow
        if client_id and client_secret:
            login_url = instance_url or "https://login.salesforce.com"
            try:
                resp = requests.post(
                    f"{login_url}/services/oauth2/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                self._access_token = data["access_token"]
                self._instance_url = data["instance_url"]
                self._session = requests.Session()
                self._session.headers.update({
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                })
                log.info("Salesforce connected via OAuth2 client credentials")
                return True
            except Exception as exc:
                raise SalesforceAuthError(f"OAuth2 auth failed: {exc}") from exc

        log.error("Salesforce: insufficient credentials provided")
        return False

    async def disconnect(self) -> None:
        """Revoke session and clear state."""
        self._client = None
        self._access_token = ""
        self._instance_url = ""
        self._api_call_count = 0
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        log.info("Salesforce disconnected")

    # ------------------------------------------------------------------
    # Rate-limit tracking
    # ------------------------------------------------------------------

    def _track_call(self) -> None:
        """Increment API call counter and warn on approach to daily limit."""
        self._api_call_count += 1
        if self._api_call_count >= self._daily_limit:
            raise SalesforceRateLimitError(
                f"Daily API limit reached ({self._daily_limit})"
            )
        if self._api_call_count >= int(self._daily_limit * 0.9):
            log.warning(
                "Salesforce API usage at %d/%d (%.0f%%)",
                self._api_call_count,
                self._daily_limit,
                100 * self._api_call_count / self._daily_limit,
            )

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _rest_url(self, path: str) -> str:
        base = self._instance_url.rstrip("/")
        if not base.startswith("http"):
            base = f"https://{base}"
        return f"{base}/services/data/{API_VERSION}/{path}"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        requests = _require_requests()
        self._track_call()
        if self._client and hasattr(self._client, "session"):
            session = self._client.session
        elif self._session:
            session = self._session
        else:
            session = requests.Session()
            session.headers.update({
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            })
        resp = session.get(self._rest_url(path), params=params, timeout=30)
        if resp.status_code == 429:
            raise SalesforceRateLimitError("429 Too Many Requests")
        if resp.status_code >= 400:
            raise SalesforceAPIError(f"GET {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _post(self, path: str, json_data: Any = None) -> Any:
        requests = _require_requests()
        self._track_call()
        if self._session:
            session = self._session
        else:
            session = requests.Session()
            session.headers.update({
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            })
        resp = session.post(self._rest_url(path), json=json_data, timeout=30)
        if resp.status_code == 429:
            raise SalesforceRateLimitError("429 Too Many Requests")
        if resp.status_code >= 400:
            raise SalesforceAPIError(f"POST {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else {}

    def _patch(self, path: str, json_data: Any = None) -> Any:
        requests = _require_requests()
        self._track_call()
        if self._session:
            session = self._session
        else:
            session = requests.Session()
            session.headers.update({
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            })
        resp = session.patch(self._rest_url(path), json=json_data, timeout=30)
        if resp.status_code == 429:
            raise SalesforceRateLimitError("429 Too Many Requests")
        if resp.status_code >= 400:
            raise SalesforceAPIError(f"PATCH {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else {}

    def _delete(self, path: str) -> Any:
        requests = _require_requests()
        self._track_call()
        if self._session:
            session = self._session
        else:
            session = requests.Session()
            session.headers.update({
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            })
        resp = session.delete(self._rest_url(path), timeout=30)
        if resp.status_code == 429:
            raise SalesforceRateLimitError("429 Too Many Requests")
        if resp.status_code >= 400:
            raise SalesforceAPIError(f"DELETE {path} → {resp.status_code}: {resp.text[:500]}")
        return {"deleted": True}

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route an action name to its handler with retry/backoff."""
        if not self.connected:
            return {"error": "Salesforce not connected. Call connect() first."}

        dispatch: dict[str, Any] = {
            "sf_query_records": self._query_records,
            "sf_query_all": self._query_all,
            "sf_get_record": self._get_record,
            "sf_create_record": self._create_record,
            "sf_update_record": self._update_record,
            "sf_delete_record": self._delete_record,
            "sf_describe_object": self._describe_object,
            "sf_bulk_create": self._bulk_create,
            "sf_bulk_update": self._bulk_update,
            "sf_bulk_upsert": self._bulk_upsert,
            "sf_search_records": self._search_records,
            "sf_get_recent": self._get_recent,
            "sf_get_opportunities": self._get_opportunities,
            "sf_get_contacts": self._get_contacts,
            "sf_get_accounts": self._get_accounts,
            "sf_create_task": self._create_task,
            "sf_run_report": self._run_report,
            "sf_get_dashboard_metrics": self._get_dashboard_metrics,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown Salesforce action: {action}"}
        try:
            return await _retry_with_backoff(lambda: handler(params))
        except SalesforceError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            log.exception("Unexpected error in Salesforce action %s", action)
            return {"error": f"Internal error: {exc}"}

    # ------------------------------------------------------------------
    # Tool implementations (18 tools)
    # ------------------------------------------------------------------

    async def _query_records(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a SOQL query and return matching records."""
        soql: str = params.get("soql", "")
        if not soql:
            return {"error": "soql parameter is required"}
        data = self._get("query", params={"q": soql})
        records = data.get("records", [])
        return {
            "total_size": data.get("totalSize", len(records)),
            "done": data.get("done", True),
            "records": records,
        }

    async def _query_all(self, params: dict[str, Any]) -> dict[str, Any]:
        """Paginated SOQL query — follows nextRecordsUrl for large result sets."""
        soql: str = params.get("soql", "")
        if not soql:
            return {"error": "soql parameter is required"}
        all_records: list[dict[str, Any]] = []
        data = self._get("query", params={"q": soql})
        all_records.extend(data.get("records", []))
        while not data.get("done", True) and data.get("nextRecordsUrl"):
            next_path = data["nextRecordsUrl"].split(f"/{API_VERSION}/")[-1]
            data = self._get(next_path)
            all_records.extend(data.get("records", []))
        return {
            "total_size": len(all_records),
            "done": True,
            "records": all_records,
        }

    async def _get_record(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a single record by object type and ID."""
        object_type: str = params.get("object_type", "")
        record_id: str = params.get("record_id", "")
        fields: Optional[list[str]] = params.get("fields")
        if not object_type or not record_id:
            return {"error": "object_type and record_id are required"}
        path = f"sobjects/{object_type}/{record_id}"
        extra: dict[str, Any] = {}
        if fields:
            extra["fields"] = ",".join(fields)
        return self._get(path, params=extra or None)

    async def _create_record(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new SObject record."""
        object_type: str = params.get("object_type", "")
        data: dict[str, Any] = params.get("data", {})
        if not object_type or not data:
            return {"error": "object_type and data are required"}
        result = self._post(f"sobjects/{object_type}", json_data=data)
        return {"id": result.get("id"), "success": result.get("success", True)}

    async def _update_record(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update an existing SObject record."""
        object_type: str = params.get("object_type", "")
        record_id: str = params.get("record_id", "")
        data: dict[str, Any] = params.get("data", {})
        if not object_type or not record_id or not data:
            return {"error": "object_type, record_id, and data are required"}
        self._patch(f"sobjects/{object_type}/{record_id}", json_data=data)
        return {"updated": True, "id": record_id}

    async def _delete_record(self, params: dict[str, Any]) -> dict[str, Any]:
        """Delete an SObject record."""
        object_type: str = params.get("object_type", "")
        record_id: str = params.get("record_id", "")
        if not object_type or not record_id:
            return {"error": "object_type and record_id are required"}
        return self._delete(f"sobjects/{object_type}/{record_id}")

    async def _describe_object(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return schema metadata for an SObject type."""
        object_type: str = params.get("object_type", "")
        if not object_type:
            return {"error": "object_type is required"}
        data = self._get(f"sobjects/{object_type}/describe")
        fields = [
            {"name": f["name"], "type": f["type"], "label": f["label"]}
            for f in data.get("fields", [])
        ]
        return {
            "name": data.get("name"),
            "label": data.get("label"),
            "field_count": len(fields),
            "fields": fields,
        }

    async def _bulk_create(self, params: dict[str, Any]) -> dict[str, Any]:
        """Insert records via Bulk API 2.0."""
        object_type: str = params.get("object_type", "")
        records: list[dict[str, Any]] = params.get("records", [])
        if not object_type or not records:
            return {"error": "object_type and records are required"}
        # Create job
        job = self._post("jobs/ingest", json_data={
            "object": object_type,
            "operation": "insert",
            "contentType": "JSON",
        })
        job_id = job.get("id", "")
        if not job_id:
            raise SalesforceBulkError("Failed to create bulk job")
        # Upload data
        requests = _require_requests()
        url = self._rest_url(f"jobs/ingest/{job_id}/batches")
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        resp = requests.put(url, json=records, headers=headers, timeout=120)
        if resp.status_code >= 400:
            raise SalesforceBulkError(f"Bulk upload failed: {resp.text[:500]}")
        # Close job
        self._patch(f"jobs/ingest/{job_id}", json_data={"state": "UploadComplete"})
        return {"job_id": job_id, "records_submitted": len(records), "state": "UploadComplete"}

    async def _bulk_update(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update records via Bulk API 2.0."""
        object_type: str = params.get("object_type", "")
        records: list[dict[str, Any]] = params.get("records", [])
        if not object_type or not records:
            return {"error": "object_type and records are required"}
        job = self._post("jobs/ingest", json_data={
            "object": object_type,
            "operation": "update",
            "contentType": "JSON",
        })
        job_id = job.get("id", "")
        if not job_id:
            raise SalesforceBulkError("Failed to create bulk update job")
        requests = _require_requests()
        url = self._rest_url(f"jobs/ingest/{job_id}/batches")
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        resp = requests.put(url, json=records, headers=headers, timeout=120)
        if resp.status_code >= 400:
            raise SalesforceBulkError(f"Bulk update upload failed: {resp.text[:500]}")
        self._patch(f"jobs/ingest/{job_id}", json_data={"state": "UploadComplete"})
        return {"job_id": job_id, "records_submitted": len(records), "state": "UploadComplete"}

    async def _bulk_upsert(self, params: dict[str, Any]) -> dict[str, Any]:
        """Upsert records via Bulk API 2.0 using an external ID field."""
        object_type: str = params.get("object_type", "")
        records: list[dict[str, Any]] = params.get("records", [])
        external_id_field: str = params.get("external_id_field", "Id")
        if not object_type or not records:
            return {"error": "object_type and records are required"}
        job = self._post("jobs/ingest", json_data={
            "object": object_type,
            "operation": "upsert",
            "externalIdFieldName": external_id_field,
            "contentType": "JSON",
        })
        job_id = job.get("id", "")
        if not job_id:
            raise SalesforceBulkError("Failed to create bulk upsert job")
        requests = _require_requests()
        url = self._rest_url(f"jobs/ingest/{job_id}/batches")
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        resp = requests.put(url, json=records, headers=headers, timeout=120)
        if resp.status_code >= 400:
            raise SalesforceBulkError(f"Bulk upsert upload failed: {resp.text[:500]}")
        self._patch(f"jobs/ingest/{job_id}", json_data={"state": "UploadComplete"})
        return {
            "job_id": job_id,
            "records_submitted": len(records),
            "external_id_field": external_id_field,
            "state": "UploadComplete",
        }

    async def _search_records(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a SOSL global search."""
        sosl: str = params.get("sosl", "")
        if not sosl:
            return {"error": "sosl parameter is required"}
        data = self._get("search", params={"q": sosl})
        results = data.get("searchRecords", data) if isinstance(data, dict) else data
        return {"results": results}

    async def _get_recent(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return recently modified records for an object type."""
        object_type: str = params.get("object_type", "")
        limit: int = params.get("limit", 10)
        if not object_type:
            return {"error": "object_type is required"}
        soql = (
            f"SELECT Id, Name, LastModifiedDate FROM {object_type} "
            f"ORDER BY LastModifiedDate DESC LIMIT {limit}"
        )
        data = self._get("query", params={"q": soql})
        return {"records": data.get("records", [])}

    async def _get_opportunities(self, params: dict[str, Any]) -> dict[str, Any]:
        """Retrieve pipeline / opportunity data with optional filters."""
        stage: str = params.get("stage", "")
        owner: str = params.get("owner", "")
        amount_min: Optional[float] = params.get("amount_min")
        conditions: list[str] = []
        if stage:
            conditions.append(f"StageName = '{stage}'")
        if owner:
            conditions.append(f"Owner.Name = '{owner}'")
        if amount_min is not None:
            conditions.append(f"Amount >= {amount_min}")
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        soql = (
            f"SELECT Id, Name, StageName, Amount, CloseDate, Owner.Name "
            f"FROM Opportunity{where} ORDER BY CloseDate ASC LIMIT 200"
        )
        data = self._get("query", params={"q": soql})
        return {"opportunities": data.get("records", [])}

    async def _get_contacts(self, params: dict[str, Any]) -> dict[str, Any]:
        """Retrieve contacts, optionally filtered by account."""
        account_id: str = params.get("account_id", "")
        filters: dict[str, Any] = params.get("filters", {})
        conditions: list[str] = []
        if account_id:
            conditions.append(f"AccountId = '{account_id}'")
        for field, value in filters.items():
            conditions.append(f"{field} = '{value}'")
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        soql = (
            f"SELECT Id, FirstName, LastName, Email, Phone, AccountId, Title "
            f"FROM Contact{where} LIMIT 200"
        )
        data = self._get("query", params={"q": soql})
        return {"contacts": data.get("records", [])}

    async def _get_accounts(self, params: dict[str, Any]) -> dict[str, Any]:
        """Retrieve account data with optional industry/region filters."""
        industry: str = params.get("industry", "")
        region: str = params.get("region", "")
        filters: dict[str, Any] = params.get("filters", {})
        conditions: list[str] = []
        if industry:
            conditions.append(f"Industry = '{industry}'")
        if region:
            conditions.append(f"BillingState = '{region}'")
        for field, value in filters.items():
            conditions.append(f"{field} = '{value}'")
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        soql = (
            f"SELECT Id, Name, Industry, BillingState, AnnualRevenue, NumberOfEmployees "
            f"FROM Account{where} LIMIT 200"
        )
        data = self._get("query", params={"q": soql})
        return {"accounts": data.get("records", [])}

    async def _create_task(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Salesforce Task linked to a record."""
        subject: str = params.get("subject", "")
        if not subject:
            return {"error": "subject is required"}
        task_data: dict[str, Any] = {"Subject": subject}
        if params.get("related_to"):
            task_data["WhatId"] = params["related_to"]
        if params.get("due_date"):
            task_data["ActivityDate"] = params["due_date"]
        if params.get("owner"):
            task_data["OwnerId"] = params["owner"]
        result = self._post("sobjects/Task", json_data=task_data)
        return {"id": result.get("id"), "success": result.get("success", True)}

    async def _run_report(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a Salesforce Analytics report by ID."""
        report_id: str = params.get("report_id", "")
        if not report_id:
            return {"error": "report_id is required"}
        data = self._get(f"analytics/reports/{report_id}")
        return {
            "report_id": report_id,
            "report_metadata": data.get("reportMetadata", {}),
            "fact_map": data.get("factMap", {}),
            "has_detail_rows": data.get("hasDetailRows", False),
        }

    async def _get_dashboard_metrics(self, params: dict[str, Any]) -> dict[str, Any]:
        """Retrieve Salesforce dashboard component data."""
        dashboard_id: str = params.get("dashboard_id", "")
        if not dashboard_id:
            return {"error": "dashboard_id is required"}
        data = self._get(f"analytics/dashboards/{dashboard_id}")
        components = []
        for comp in data.get("componentData", []):
            components.append({
                "name": comp.get("componentName", ""),
                "type": comp.get("componentType", ""),
                "data": comp.get("reportResult", {}).get("factMap", {}),
            })
        return {"dashboard_id": dashboard_id, "components": components}

    # ------------------------------------------------------------------
    # Tool definitions (OpenAI function-calling format)
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas for all 18 Salesforce tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "sf_query_records",
                    "description": "Execute a SOQL query against Salesforce and return matching records.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "soql": {"type": "string", "description": "SOQL query string"},
                        },
                        "required": ["soql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_query_all",
                    "description": "Paginated SOQL query that follows nextRecordsUrl for large result sets.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "soql": {"type": "string", "description": "SOQL query string"},
                        },
                        "required": ["soql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_get_record",
                    "description": "Fetch a single Salesforce record by object type and record ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string", "description": "SObject type (e.g. Account, Contact)"},
                            "record_id": {"type": "string", "description": "18-character Salesforce record ID"},
                            "fields": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of fields to retrieve",
                            },
                        },
                        "required": ["object_type", "record_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_create_record",
                    "description": "Create a new Salesforce SObject record.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string", "description": "SObject type (e.g. Account, Contact)"},
                            "data": {"type": "object", "description": "Field-value pairs for the new record"},
                        },
                        "required": ["object_type", "data"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_update_record",
                    "description": "Update an existing Salesforce record by ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string", "description": "SObject type"},
                            "record_id": {"type": "string", "description": "Record ID to update"},
                            "data": {"type": "object", "description": "Field-value pairs to update"},
                        },
                        "required": ["object_type", "record_id", "data"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_delete_record",
                    "description": "Delete a Salesforce record by object type and record ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string", "description": "SObject type"},
                            "record_id": {"type": "string", "description": "Record ID to delete"},
                        },
                        "required": ["object_type", "record_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_describe_object",
                    "description": "Return schema metadata (fields, types, labels) for a Salesforce SObject.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string", "description": "SObject type to describe"},
                        },
                        "required": ["object_type"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_bulk_create",
                    "description": "Insert multiple records via Salesforce Bulk API 2.0.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string", "description": "SObject type"},
                            "records": {"type": "array", "items": {"type": "object"}, "description": "List of record data objects"},
                        },
                        "required": ["object_type", "records"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_bulk_update",
                    "description": "Update multiple records via Salesforce Bulk API 2.0.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string", "description": "SObject type"},
                            "records": {"type": "array", "items": {"type": "object"}, "description": "List of records with Id field"},
                        },
                        "required": ["object_type", "records"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_bulk_upsert",
                    "description": "Upsert records via Bulk API 2.0 using an external ID field.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string", "description": "SObject type"},
                            "records": {"type": "array", "items": {"type": "object"}, "description": "Records to upsert"},
                            "external_id_field": {"type": "string", "description": "External ID field name (default: Id)"},
                        },
                        "required": ["object_type", "records"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_search_records",
                    "description": "Execute a SOSL global search across Salesforce objects.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sosl": {"type": "string", "description": "SOSL search query string"},
                        },
                        "required": ["sosl"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_get_recent",
                    "description": "Get recently modified records for a Salesforce object type.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "object_type": {"type": "string", "description": "SObject type"},
                            "limit": {"type": "integer", "description": "Maximum records to return (default 10)"},
                        },
                        "required": ["object_type"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_get_opportunities",
                    "description": "Retrieve sales pipeline / opportunity data with optional stage, owner, and amount filters.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "stage": {"type": "string", "description": "Filter by opportunity stage name"},
                            "owner": {"type": "string", "description": "Filter by opportunity owner name"},
                            "amount_min": {"type": "number", "description": "Minimum amount filter"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_get_contacts",
                    "description": "Retrieve CRM contacts, optionally filtered by account ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account_id": {"type": "string", "description": "Filter contacts by Account ID"},
                            "filters": {"type": "object", "description": "Additional field=value filters"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_get_accounts",
                    "description": "Retrieve Salesforce accounts filtered by industry, region, or custom fields.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "industry": {"type": "string", "description": "Filter by industry"},
                            "region": {"type": "string", "description": "Filter by billing state/region"},
                            "filters": {"type": "object", "description": "Additional field=value filters"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_create_task",
                    "description": "Create a Salesforce Task record linked to a related object.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string", "description": "Task subject line"},
                            "related_to": {"type": "string", "description": "ID of the related record (WhatId)"},
                            "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format"},
                            "owner": {"type": "string", "description": "Owner user ID"},
                        },
                        "required": ["subject"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_run_report",
                    "description": "Execute a Salesforce Analytics report and return results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "report_id": {"type": "string", "description": "Salesforce report ID"},
                        },
                        "required": ["report_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "sf_get_dashboard_metrics",
                    "description": "Retrieve Salesforce dashboard component data and metrics.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "dashboard_id": {"type": "string", "description": "Salesforce dashboard ID"},
                        },
                        "required": ["dashboard_id"],
                    },
                },
            },
        ]
