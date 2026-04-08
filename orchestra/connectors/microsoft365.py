"""Microsoft 365 connector — Graph API, Teams, SharePoint, Outlook, Azure AD.

Uses MSAL (Microsoft Authentication Library) for client credentials and
delegated auth flows against Microsoft Graph API v1.0 and beta endpoints.

Requires: pip install msal requests

Env vars:
    AZURE_CLIENT_ID       — Azure AD app registration client ID
    AZURE_CLIENT_SECRET   — Azure AD app registration client secret
    AZURE_TENANT_ID       — Azure AD tenant ID
    M365_ADMIN_EMAIL      — Admin UPN for delegated operations
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

from .base import Connector

__all__ = ["Microsoft365Connector", "Microsoft365Error"]

log = logging.getLogger("orchestra.connectors.microsoft365")

# Optional dependency guards
try:
    import msal as _msal
except ImportError:
    _msal = None  # type: ignore[assignment]

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class Microsoft365Error(Exception):
    """Base error for Microsoft 365 connector."""


class Microsoft365AuthError(Microsoft365Error):
    """Authentication failure against Azure AD / Entra."""


class Microsoft365APIError(Microsoft365Error):
    """Graph API call failure."""


class Microsoft365RateLimitError(Microsoft365Error):
    """Graph API throttling (429)."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_BETA = "https://graph.microsoft.com/beta"
AUTHORITY_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}"
DEFAULT_SCOPES = ["https://graph.microsoft.com/.default"]
MAX_RETRIES = 4
INITIAL_BACKOFF = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _retry_with_backoff(coro_factory, *, max_retries: int = MAX_RETRIES):
    """Retry with exponential backoff on transient errors."""
    delay = INITIAL_BACKOFF
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Microsoft365RateLimitError:
            if attempt < max_retries:
                log.warning("Graph API rate limited, retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise
        except (Microsoft365APIError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                log.warning(
                    "Graph request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise
    raise last_exc  # type: ignore[misc]


def _require_deps() -> tuple[Any, Any]:
    if _msal is None:
        raise Microsoft365Error("Microsoft 365 connector requires: pip install msal")
    if _requests is None:
        raise Microsoft365Error("Microsoft 365 connector requires: pip install requests")
    return _msal, _requests


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class Microsoft365Connector(Connector):
    """Full Microsoft 365 integration — Graph API, Teams, SharePoint, Outlook, Azure AD.

    Provides 22 tools covering user/group management, Teams messaging,
    SharePoint files, Outlook mail/calendar, OneDrive, and Azure resources.
    """

    name = "microsoft365"
    description = (
        "Manage Microsoft 365 users, Teams, SharePoint, Outlook, "
        "OneDrive, and Azure AD via Microsoft Graph API."
    )

    TOOLS: list[str] = [
        "m365_list_users",
        "m365_get_user",
        "m365_create_user",
        "m365_assign_license",
        "m365_list_teams",
        "m365_create_team",
        "m365_send_teams_message",
        "m365_create_teams_channel",
        "m365_list_channels",
        "m365_schedule_teams_meeting",
        "m365_upload_sharepoint_file",
        "m365_list_sharepoint_files",
        "m365_create_sharepoint_list",
        "m365_add_sharepoint_list_item",
        "m365_send_outlook_email",
        "m365_list_outlook_emails",
        "m365_create_outlook_event",
        "m365_list_outlook_events",
        "m365_get_onedrive_files",
        "m365_list_azure_resources",
        "m365_get_azure_ad_groups",
        "m365_audit_signin_logs",
    ]

    def __init__(self) -> None:
        self._access_token: str = ""
        self._tenant_id: str = ""
        self._client_id: str = ""
        self._msal_app: Any = None
        self._session: Any = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return bool(self._access_token)

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with Microsoft Graph API.

        Credential keys:
            - client_id, client_secret, tenant_id — client credentials flow
            - access_token — pre-obtained Bearer token
        """
        msal, requests = _require_deps()

        # Direct token
        if credentials.get("access_token"):
            self._access_token = credentials["access_token"]
            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            })
            log.info("Microsoft 365 connected (pre-obtained token)")
            return True

        self._client_id = credentials.get("client_id", os.getenv("AZURE_CLIENT_ID", ""))
        client_secret = credentials.get("client_secret", os.getenv("AZURE_CLIENT_SECRET", ""))
        self._tenant_id = credentials.get("tenant_id", os.getenv("AZURE_TENANT_ID", ""))

        if not self._client_id or not client_secret or not self._tenant_id:
            log.error("Microsoft 365: client_id, client_secret, and tenant_id required")
            return False

        authority = AUTHORITY_TEMPLATE.format(tenant_id=self._tenant_id)

        try:
            app = msal.ConfidentialClientApplication(
                self._client_id,
                authority=authority,
                client_credential=client_secret,
            )
            result = app.acquire_token_for_client(scopes=DEFAULT_SCOPES)
            if "access_token" not in result:
                raise Microsoft365AuthError(
                    f"Token acquisition failed: {result.get('error_description', result)}"
                )
            self._access_token = result["access_token"]
            self._msal_app = app
            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            })
            log.info("Microsoft 365 connected (client credentials, tenant=%s)", self._tenant_id)
            return True
        except Microsoft365AuthError:
            raise
        except Exception as exc:
            raise Microsoft365AuthError(f"MSAL auth failed: {exc}") from exc

    async def disconnect(self) -> None:
        """Clear all authentication state."""
        self._access_token = ""
        self._msal_app = None
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        log.info("Microsoft 365 disconnected")

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _refresh_token_if_needed(self) -> None:
        """Attempt token refresh via MSAL if available."""
        if self._msal_app:
            try:
                result = self._msal_app.acquire_token_for_client(scopes=DEFAULT_SCOPES)
                if "access_token" in result:
                    self._access_token = result["access_token"]
                    if self._session:
                        self._session.headers["Authorization"] = f"Bearer {self._access_token}"
            except Exception:
                pass

    def _graph_get(self, path: str, params: dict[str, Any] | None = None, *, beta: bool = False) -> Any:
        """Execute a GET against the Graph API."""
        base = GRAPH_BETA if beta else GRAPH_BASE
        url = f"{base}/{path.lstrip('/')}"
        resp = self._session.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            self._refresh_token_if_needed()
            resp = self._session.get(url, params=params, timeout=30)
        if resp.status_code == 429:
            raise Microsoft365RateLimitError("Graph API throttled (429)")
        if resp.status_code >= 400:
            raise Microsoft365APIError(f"GET {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else {}

    def _graph_post(self, path: str, json_data: Any = None, *, beta: bool = False) -> Any:
        """Execute a POST against the Graph API."""
        base = GRAPH_BETA if beta else GRAPH_BASE
        url = f"{base}/{path.lstrip('/')}"
        resp = self._session.post(url, json=json_data, timeout=30)
        if resp.status_code == 401:
            self._refresh_token_if_needed()
            resp = self._session.post(url, json=json_data, timeout=30)
        if resp.status_code == 429:
            raise Microsoft365RateLimitError("Graph API throttled (429)")
        if resp.status_code >= 400:
            raise Microsoft365APIError(f"POST {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else {}

    def _graph_put(self, path: str, data: Any = None, content_type: str = "application/json", *, beta: bool = False) -> Any:
        """Execute a PUT against the Graph API."""
        base = GRAPH_BETA if beta else GRAPH_BASE
        url = f"{base}/{path.lstrip('/')}"
        headers = {"Content-Type": content_type}
        if content_type == "application/json":
            resp = self._session.put(url, json=data, headers=headers, timeout=60)
        else:
            resp = self._session.put(url, data=data, headers=headers, timeout=60)
        if resp.status_code == 429:
            raise Microsoft365RateLimitError("Graph API throttled (429)")
        if resp.status_code >= 400:
            raise Microsoft365APIError(f"PUT {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else {}

    def _graph_patch(self, path: str, json_data: Any = None) -> Any:
        """Execute a PATCH against the Graph API."""
        url = f"{GRAPH_BASE}/{path.lstrip('/')}"
        resp = self._session.patch(url, json=json_data, timeout=30)
        if resp.status_code == 429:
            raise Microsoft365RateLimitError("Graph API throttled (429)")
        if resp.status_code >= 400:
            raise Microsoft365APIError(f"PATCH {path} → {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route an action to its handler with retry/backoff."""
        if not self.connected:
            return {"error": "Microsoft 365 not connected. Call connect() first."}

        dispatch: dict[str, Any] = {
            "m365_list_users": self._list_users,
            "m365_get_user": self._get_user,
            "m365_create_user": self._create_user,
            "m365_assign_license": self._assign_license,
            "m365_list_teams": self._list_teams,
            "m365_create_team": self._create_team,
            "m365_send_teams_message": self._send_teams_message,
            "m365_create_teams_channel": self._create_teams_channel,
            "m365_list_channels": self._list_channels,
            "m365_schedule_teams_meeting": self._schedule_teams_meeting,
            "m365_upload_sharepoint_file": self._upload_sharepoint_file,
            "m365_list_sharepoint_files": self._list_sharepoint_files,
            "m365_create_sharepoint_list": self._create_sharepoint_list,
            "m365_add_sharepoint_list_item": self._add_sharepoint_list_item,
            "m365_send_outlook_email": self._send_outlook_email,
            "m365_list_outlook_emails": self._list_outlook_emails,
            "m365_create_outlook_event": self._create_outlook_event,
            "m365_list_outlook_events": self._list_outlook_events,
            "m365_get_onedrive_files": self._get_onedrive_files,
            "m365_list_azure_resources": self._list_azure_resources,
            "m365_get_azure_ad_groups": self._get_azure_ad_groups,
            "m365_audit_signin_logs": self._audit_signin_logs,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown Microsoft 365 action: {action}"}
        try:
            return await _retry_with_backoff(lambda: handler(params))
        except Microsoft365Error as exc:
            return {"error": str(exc)}
        except Exception as exc:
            log.exception("Unexpected error in Microsoft 365 action %s", action)
            return {"error": f"Internal error: {exc}"}

    # ------------------------------------------------------------------
    # Tool implementations (22 tools)
    # ------------------------------------------------------------------

    # ---- Azure AD / Entra Users ----

    async def _list_users(self, params: dict[str, Any]) -> dict[str, Any]:
        """List Azure AD / Entra users."""
        filter_str = params.get("filter", "")
        query: dict[str, Any] = {
            "$top": 100,
            "$select": "id,displayName,userPrincipalName,mail,accountEnabled,jobTitle",
        }
        if filter_str:
            query["$filter"] = filter_str
        data = self._graph_get("users", params=query)
        users = [
            {
                "id": u.get("id"),
                "display_name": u.get("displayName"),
                "upn": u.get("userPrincipalName"),
                "email": u.get("mail"),
                "enabled": u.get("accountEnabled"),
                "job_title": u.get("jobTitle"),
            }
            for u in data.get("value", [])
        ]
        return {"count": len(users), "users": users}

    async def _get_user(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get user profile by UPN or ID."""
        upn = params.get("upn", "")
        if not upn:
            return {"error": "upn (user principal name or ID) is required"}
        data = self._graph_get(f"users/{upn}")
        return {
            "id": data.get("id"),
            "display_name": data.get("displayName"),
            "upn": data.get("userPrincipalName"),
            "email": data.get("mail"),
            "job_title": data.get("jobTitle"),
            "department": data.get("department"),
            "office_location": data.get("officeLocation"),
            "enabled": data.get("accountEnabled"),
        }

    async def _create_user(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new Azure AD user."""
        display_name = params.get("display_name", "")
        upn = params.get("upn", "")
        password = params.get("password", "")
        if not display_name or not upn or not password:
            return {"error": "display_name, upn, and password are required"}
        body = {
            "displayName": display_name,
            "userPrincipalName": upn,
            "mailNickname": upn.split("@")[0],
            "accountEnabled": True,
            "passwordProfile": {
                "password": password,
                "forceChangePasswordNextSignIn": True,
            },
        }
        result = self._graph_post("users", json_data=body)
        return {
            "id": result.get("id"),
            "upn": result.get("userPrincipalName"),
            "created": True,
        }

    async def _assign_license(self, params: dict[str, Any]) -> dict[str, Any]:
        """Assign a license SKU to a user."""
        user_id = params.get("user_id", "")
        license_sku = params.get("license_sku", "")
        if not user_id or not license_sku:
            return {"error": "user_id and license_sku are required"}
        body = {
            "addLicenses": [{"skuId": license_sku, "disabledPlans": []}],
            "removeLicenses": [],
        }
        self._graph_post(f"users/{user_id}/assignLicense", json_data=body)
        return {"user_id": user_id, "license_sku": license_sku, "assigned": True}

    # ---- Microsoft Teams ----

    async def _list_teams(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all Teams the authenticated app can see."""
        data = self._graph_get("groups", params={
            "$filter": "resourceProvisioningOptions/Any(x:x eq 'Team')",
            "$select": "id,displayName,description,mail",
            "$top": 100,
        })
        teams = [
            {
                "id": g.get("id"),
                "name": g.get("displayName"),
                "description": g.get("description"),
                "mail": g.get("mail"),
            }
            for g in data.get("value", [])
        ]
        return {"count": len(teams), "teams": teams}

    async def _create_team(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new Microsoft Team."""
        name = params.get("name", "")
        description = params.get("description", "")
        members: list[str] = params.get("members", [])
        if not name:
            return {"error": "name is required"}
        body: dict[str, Any] = {
            "template@odata.bind": "https://graph.microsoft.com/v1.0/teamsTemplates('standard')",
            "displayName": name,
            "description": description,
        }
        if members:
            body["members"] = [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["member"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{m}')",
                }
                for m in members
            ]
        result = self._graph_post("teams", json_data=body)
        return {"team_id": result.get("id", "created"), "name": name}

    async def _send_teams_message(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send a message to a Teams channel."""
        team_id = params.get("team_id", "")
        channel_id = params.get("channel_id", "")
        text = params.get("text", "")
        if not team_id or not channel_id or not text:
            return {"error": "team_id, channel_id, and text are required"}
        body = {
            "body": {"contentType": "text", "content": text},
        }
        result = self._graph_post(
            f"teams/{team_id}/channels/{channel_id}/messages", json_data=body,
        )
        return {"message_id": result.get("id"), "sent": True}

    async def _create_teams_channel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new channel in a Team."""
        team_id = params.get("team_id", "")
        name = params.get("name", "")
        description = params.get("description", "")
        if not team_id or not name:
            return {"error": "team_id and name are required"}
        body = {"displayName": name, "description": description}
        result = self._graph_post(f"teams/{team_id}/channels", json_data=body)
        return {"channel_id": result.get("id"), "name": name}

    async def _list_channels(self, params: dict[str, Any]) -> dict[str, Any]:
        """List channels in a Team."""
        team_id = params.get("team_id", "")
        if not team_id:
            return {"error": "team_id is required"}
        data = self._graph_get(f"teams/{team_id}/channels")
        channels = [
            {
                "id": ch.get("id"),
                "name": ch.get("displayName"),
                "description": ch.get("description"),
                "membership_type": ch.get("membershipType"),
            }
            for ch in data.get("value", [])
        ]
        return {"count": len(channels), "channels": channels}

    async def _schedule_teams_meeting(self, params: dict[str, Any]) -> dict[str, Any]:
        """Schedule an online Teams meeting."""
        subject = params.get("subject", "Teams Meeting")
        attendees: list[str] = params.get("attendees", [])
        start = params.get("start", "")
        duration: int = params.get("duration", 60)
        if not start:
            return {"error": "start (ISO datetime) is required"}
        from datetime import datetime, timedelta
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            return {"error": "start must be ISO 8601 format"}
        end_dt = start_dt + timedelta(minutes=duration)
        body = {
            "subject": subject,
            "startDateTime": start_dt.isoformat(),
            "endDateTime": end_dt.isoformat(),
            "participants": {
                "attendees": [
                    {
                        "upn": a,
                        "role": "attendee",
                    }
                    for a in attendees
                ],
            },
        }
        result = self._graph_post("me/onlineMeetings", json_data=body)
        return {
            "meeting_id": result.get("id"),
            "join_url": result.get("joinWebUrl"),
            "subject": subject,
        }

    # ---- SharePoint ----

    async def _upload_sharepoint_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Upload a file to a SharePoint document library."""
        site_url = params.get("site_url", "")
        lib = params.get("lib", "Documents")
        name = params.get("name", "")
        content = params.get("content", "")
        if not site_url or not name:
            return {"error": "site_url and name are required"}
        # Resolve site ID
        site_data = self._graph_get(f"sites/{site_url}")
        site_id = site_data.get("id", site_url)
        # Get drive for the library
        drives = self._graph_get(f"sites/{site_id}/drives")
        drive_id = ""
        for d in drives.get("value", []):
            if d.get("name", "").lower() == lib.lower():
                drive_id = d["id"]
                break
        if not drive_id and drives.get("value"):
            drive_id = drives["value"][0]["id"]
        if not drive_id:
            return {"error": f"Could not find drive for library '{lib}'"}
        # Upload
        encoded = content.encode("utf-8") if isinstance(content, str) else content
        result = self._graph_put(
            f"drives/{drive_id}/root:/{name}:/content",
            data=encoded,
            content_type="application/octet-stream",
        )
        return {
            "file_id": result.get("id"),
            "name": result.get("name"),
            "web_url": result.get("webUrl"),
        }

    async def _list_sharepoint_files(self, params: dict[str, Any]) -> dict[str, Any]:
        """List files in a SharePoint document library."""
        site_url = params.get("site_url", "")
        lib = params.get("lib", "Documents")
        folder = params.get("folder", "")
        if not site_url:
            return {"error": "site_url is required"}
        site_data = self._graph_get(f"sites/{site_url}")
        site_id = site_data.get("id", site_url)
        drives = self._graph_get(f"sites/{site_id}/drives")
        drive_id = ""
        for d in drives.get("value", []):
            if d.get("name", "").lower() == lib.lower():
                drive_id = d["id"]
                break
        if not drive_id and drives.get("value"):
            drive_id = drives["value"][0]["id"]
        path = f"drives/{drive_id}/root"
        if folder:
            path += f":/{folder}:"
        path += "/children"
        data = self._graph_get(path)
        files = [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "size": f.get("size"),
                "web_url": f.get("webUrl"),
                "last_modified": f.get("lastModifiedDateTime"),
            }
            for f in data.get("value", [])
        ]
        return {"count": len(files), "files": files}

    async def _create_sharepoint_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a SharePoint list with defined columns."""
        site_url = params.get("site_url", "")
        name = params.get("name", "")
        columns: list[dict[str, Any]] = params.get("columns", [])
        if not site_url or not name:
            return {"error": "site_url and name are required"}
        site_data = self._graph_get(f"sites/{site_url}")
        site_id = site_data.get("id", site_url)
        body: dict[str, Any] = {
            "displayName": name,
            "list": {"template": "genericList"},
        }
        if columns:
            body["columns"] = columns
        result = self._graph_post(f"sites/{site_id}/lists", json_data=body)
        return {"list_id": result.get("id"), "name": name, "created": True}

    async def _add_sharepoint_list_item(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add an item to a SharePoint list."""
        site_url = params.get("site_url", "")
        list_name = params.get("list_name", "")
        data_fields: dict[str, Any] = params.get("data", {})
        if not site_url or not list_name or not data_fields:
            return {"error": "site_url, list_name, and data are required"}
        site_data = self._graph_get(f"sites/{site_url}")
        site_id = site_data.get("id", site_url)
        # Find list by name
        lists = self._graph_get(f"sites/{site_id}/lists")
        list_id = ""
        for lst in lists.get("value", []):
            if lst.get("displayName", "").lower() == list_name.lower():
                list_id = lst["id"]
                break
        if not list_id:
            return {"error": f"List '{list_name}' not found"}
        body = {"fields": data_fields}
        result = self._graph_post(f"sites/{site_id}/lists/{list_id}/items", json_data=body)
        return {"item_id": result.get("id"), "created": True}

    # ---- Outlook (Mail & Calendar) ----

    async def _send_outlook_email(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send an email via Outlook / Microsoft Graph."""
        to: str | list[str] = params.get("to", "")
        subject = params.get("subject", "")
        body_text = params.get("body", "")
        attachments: list[dict[str, Any]] = params.get("attachments", [])
        if not to or not subject:
            return {"error": "to and subject are required"}
        recipients = [to] if isinstance(to, str) else to
        message: dict[str, Any] = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": [
                {"emailAddress": {"address": r}} for r in recipients
            ],
        }
        if attachments:
            message["attachments"] = attachments
        self._graph_post("me/sendMail", json_data={"message": message})
        return {"sent": True, "to": recipients, "subject": subject}

    async def _list_outlook_emails(self, params: dict[str, Any]) -> dict[str, Any]:
        """List emails from Outlook inbox or specified folder."""
        folder = params.get("folder", "inbox")
        filter_str = params.get("filter", "")
        limit = params.get("limit", 25)
        query: dict[str, Any] = {
            "$top": min(limit, 50),
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
            "$orderby": "receivedDateTime desc",
        }
        if filter_str:
            query["$filter"] = filter_str
        data = self._graph_get(f"me/mailFolders/{folder}/messages", params=query)
        emails = [
            {
                "id": m.get("id"),
                "subject": m.get("subject"),
                "from": m.get("from", {}).get("emailAddress", {}).get("address"),
                "received": m.get("receivedDateTime"),
                "is_read": m.get("isRead"),
                "preview": m.get("bodyPreview", "")[:200],
            }
            for m in data.get("value", [])
        ]
        return {"count": len(emails), "emails": emails}

    async def _create_outlook_event(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create an Outlook calendar event."""
        subject = params.get("subject", "")
        attendees: list[str] = params.get("attendees", [])
        start = params.get("start", "")
        end = params.get("end", "")
        if not subject or not start or not end:
            return {"error": "subject, start, and end are required"}
        body = {
            "subject": subject,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
            "attendees": [
                {
                    "emailAddress": {"address": a},
                    "type": "required",
                }
                for a in attendees
            ],
        }
        result = self._graph_post("me/events", json_data=body)
        return {
            "event_id": result.get("id"),
            "subject": subject,
            "web_link": result.get("webLink"),
        }

    async def _list_outlook_events(self, params: dict[str, Any]) -> dict[str, Any]:
        """List Outlook calendar events in a date range."""
        start = params.get("start", "")
        end = params.get("end", "")
        query: dict[str, Any] = {
            "$top": 50,
            "$select": "id,subject,start,end,organizer,isOnlineMeeting",
            "$orderby": "start/dateTime",
        }
        if start and end:
            query["$filter"] = (
                f"start/dateTime ge '{start}' and end/dateTime le '{end}'"
            )
        data = self._graph_get("me/events", params=query)
        events = [
            {
                "id": e.get("id"),
                "subject": e.get("subject"),
                "start": e.get("start", {}).get("dateTime"),
                "end": e.get("end", {}).get("dateTime"),
                "organizer": e.get("organizer", {}).get("emailAddress", {}).get("address"),
                "is_online": e.get("isOnlineMeeting", False),
            }
            for e in data.get("value", [])
        ]
        return {"count": len(events), "events": events}

    # ---- OneDrive ----

    async def _get_onedrive_files(self, params: dict[str, Any]) -> dict[str, Any]:
        """List files in a user's OneDrive."""
        user_id = params.get("user_id", "me")
        path = params.get("path", "")
        endpoint = f"users/{user_id}/drive/root"
        if path:
            endpoint += f":/{path}:"
        endpoint += "/children"
        data = self._graph_get(endpoint)
        files = [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "size": f.get("size"),
                "web_url": f.get("webUrl"),
                "last_modified": f.get("lastModifiedDateTime"),
                "is_folder": "folder" in f,
            }
            for f in data.get("value", [])
        ]
        return {"count": len(files), "files": files}

    # ---- Azure Resources (via management API proxy) ----

    async def _list_azure_resources(self, params: dict[str, Any]) -> dict[str, Any]:
        """List Azure resources in a subscription/resource group (via Graph beta)."""
        subscription_id = params.get("subscription_id", "")
        resource_group = params.get("resource_group", "")
        if not subscription_id:
            return {"error": "subscription_id is required"}
        # Note: Azure Resource Manager is a separate API; here we provide a Graph-based stub
        # For full ARM, use the Azure Management REST API separately
        path = f"subscriptions/{subscription_id}"
        if resource_group:
            path += f"/resourceGroups/{resource_group}"
        path += "/resources"
        try:
            data = self._graph_get(path, beta=True)
            return {"resources": data.get("value", [])}
        except Microsoft365APIError:
            return {
                "info": "Azure resource listing requires ARM API. Use Azure SDK for full support.",
                "subscription_id": subscription_id,
            }

    # ---- Azure AD Groups ----

    async def _get_azure_ad_groups(self, params: dict[str, Any]) -> dict[str, Any]:
        """List Azure AD / Entra groups."""
        filter_str = params.get("filter", "")
        query: dict[str, Any] = {
            "$top": 100,
            "$select": "id,displayName,mail,groupTypes,membershipRule",
        }
        if filter_str:
            query["$filter"] = filter_str
        data = self._graph_get("groups", params=query)
        groups = [
            {
                "id": g.get("id"),
                "name": g.get("displayName"),
                "mail": g.get("mail"),
                "group_types": g.get("groupTypes", []),
            }
            for g in data.get("value", [])
        ]
        return {"count": len(groups), "groups": groups}

    # ---- Audit / Sign-in logs ----

    async def _audit_signin_logs(self, params: dict[str, Any]) -> dict[str, Any]:
        """Query Azure AD sign-in logs (beta endpoint)."""
        start_date = params.get("start_date", "")
        limit = params.get("limit", 50)
        query: dict[str, Any] = {"$top": min(limit, 100)}
        if start_date:
            query["$filter"] = f"createdDateTime ge {start_date}T00:00:00Z"
        data = self._graph_get("auditLogs/signIns", params=query, beta=True)
        logs = [
            {
                "id": l.get("id"),
                "user": l.get("userDisplayName"),
                "upn": l.get("userPrincipalName"),
                "app": l.get("appDisplayName"),
                "status": l.get("status", {}).get("errorCode"),
                "ip": l.get("ipAddress"),
                "created": l.get("createdDateTime"),
            }
            for l in data.get("value", [])
        ]
        return {"count": len(logs), "logs": logs}

    # ------------------------------------------------------------------
    # Tool definitions (OpenAI function-calling format)
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas for all 22 Microsoft 365 tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "m365_list_users",
                    "description": "List Azure AD / Entra users with optional OData filter.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filter": {"type": "string", "description": "OData $filter expression"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_get_user",
                    "description": "Get a user profile by UPN or ID from Azure AD.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "upn": {"type": "string", "description": "User principal name or ID"},
                        },
                        "required": ["upn"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_create_user",
                    "description": "Create a new user in Azure AD / Entra.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "display_name": {"type": "string", "description": "Display name"},
                            "upn": {"type": "string", "description": "User principal name (email-like)"},
                            "password": {"type": "string", "description": "Initial password"},
                        },
                        "required": ["display_name", "upn", "password"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_assign_license",
                    "description": "Assign a license SKU to a Microsoft 365 user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "string", "description": "User ID or UPN"},
                            "license_sku": {"type": "string", "description": "License SKU ID"},
                        },
                        "required": ["user_id", "license_sku"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_list_teams",
                    "description": "List all Microsoft Teams visible to the app.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_create_team",
                    "description": "Create a new Microsoft Team.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Team name"},
                            "description": {"type": "string", "description": "Team description"},
                            "members": {
                                "type": "array", "items": {"type": "string"},
                                "description": "UPNs of initial members",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_send_teams_message",
                    "description": "Send a message to a Microsoft Teams channel.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "team_id": {"type": "string", "description": "Team ID"},
                            "channel_id": {"type": "string", "description": "Channel ID"},
                            "text": {"type": "string", "description": "Message text"},
                        },
                        "required": ["team_id", "channel_id", "text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_create_teams_channel",
                    "description": "Create a new channel in a Microsoft Team.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "team_id": {"type": "string", "description": "Team ID"},
                            "name": {"type": "string", "description": "Channel name"},
                            "description": {"type": "string", "description": "Channel description"},
                        },
                        "required": ["team_id", "name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_list_channels",
                    "description": "List channels in a Microsoft Team.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "team_id": {"type": "string", "description": "Team ID"},
                        },
                        "required": ["team_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_schedule_teams_meeting",
                    "description": "Schedule an online Teams meeting.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string", "description": "Meeting subject"},
                            "attendees": {
                                "type": "array", "items": {"type": "string"},
                                "description": "Attendee UPNs",
                            },
                            "start": {"type": "string", "description": "Start (ISO 8601)"},
                            "duration": {"type": "integer", "description": "Duration in minutes (default 60)"},
                        },
                        "required": ["start"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_upload_sharepoint_file",
                    "description": "Upload a file to a SharePoint document library.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "site_url": {"type": "string", "description": "SharePoint site URL or ID"},
                            "lib": {"type": "string", "description": "Document library name (default: Documents)"},
                            "name": {"type": "string", "description": "File name"},
                            "content": {"type": "string", "description": "File content"},
                        },
                        "required": ["site_url", "name", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_list_sharepoint_files",
                    "description": "List files in a SharePoint document library.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "site_url": {"type": "string", "description": "SharePoint site URL"},
                            "lib": {"type": "string", "description": "Library name"},
                            "folder": {"type": "string", "description": "Folder path within library"},
                        },
                        "required": ["site_url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_create_sharepoint_list",
                    "description": "Create a new SharePoint list with optional column definitions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "site_url": {"type": "string", "description": "SharePoint site URL"},
                            "name": {"type": "string", "description": "List name"},
                            "columns": {
                                "type": "array", "items": {"type": "object"},
                                "description": "Column definitions",
                            },
                        },
                        "required": ["site_url", "name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_add_sharepoint_list_item",
                    "description": "Add an item to a SharePoint list.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "site_url": {"type": "string", "description": "SharePoint site URL"},
                            "list_name": {"type": "string", "description": "List name"},
                            "data": {"type": "object", "description": "Field-value pairs"},
                        },
                        "required": ["site_url", "list_name", "data"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_send_outlook_email",
                    "description": "Send an email via Outlook / Microsoft Graph.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email (or array)"},
                            "subject": {"type": "string", "description": "Email subject"},
                            "body": {"type": "string", "description": "Email body (plain text)"},
                            "attachments": {
                                "type": "array", "items": {"type": "object"},
                                "description": "File attachments",
                            },
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_list_outlook_emails",
                    "description": "List emails from Outlook inbox or a specified folder.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "folder": {"type": "string", "description": "Mail folder (default: inbox)"},
                            "filter": {"type": "string", "description": "OData $filter expression"},
                            "limit": {"type": "integer", "description": "Max emails (default 25)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_create_outlook_event",
                    "description": "Create an Outlook calendar event.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string", "description": "Event subject"},
                            "attendees": {
                                "type": "array", "items": {"type": "string"},
                                "description": "Attendee emails",
                            },
                            "start": {"type": "string", "description": "Start datetime (ISO 8601)"},
                            "end": {"type": "string", "description": "End datetime (ISO 8601)"},
                        },
                        "required": ["subject", "start", "end"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_list_outlook_events",
                    "description": "List Outlook calendar events in a date range.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "description": "Start date (ISO 8601)"},
                            "end": {"type": "string", "description": "End date (ISO 8601)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_get_onedrive_files",
                    "description": "List files in a user's OneDrive.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "string", "description": "User ID or 'me' (default)"},
                            "path": {"type": "string", "description": "Folder path within OneDrive"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_list_azure_resources",
                    "description": "List Azure resources in a subscription/resource group.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subscription_id": {"type": "string", "description": "Azure subscription ID"},
                            "resource_group": {"type": "string", "description": "Resource group name (optional)"},
                        },
                        "required": ["subscription_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_get_azure_ad_groups",
                    "description": "List Azure AD / Entra groups with optional filter.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filter": {"type": "string", "description": "OData $filter expression"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "m365_audit_signin_logs",
                    "description": "Query Azure AD sign-in audit logs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "limit": {"type": "integer", "description": "Max results (default 50)"},
                        },
                    },
                },
            },
        ]
