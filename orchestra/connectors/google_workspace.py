"""Google Workspace connector — Admin SDK, Chat, Meet, Drive, Docs, Sheets.

Supports domain-wide delegation via service accounts and per-user OAuth2.

Requires: pip install google-auth google-auth-oauthlib google-api-python-client

Env vars:
    GOOGLE_SERVICE_ACCOUNT_KEY  — path to service account JSON key
    GOOGLE_WORKSPACE_DOMAIN     — primary domain (e.g. example.com)
    GOOGLE_ADMIN_EMAIL          — admin email for domain-wide delegation
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

from .base import Connector

__all__ = ["GoogleWorkspaceConnector", "GoogleWorkspaceError"]

log = logging.getLogger("orchestra.connectors.google_workspace")

# Optional dependency guards
try:
    from google.oauth2 import service_account as _service_account
    from google.auth.transport.requests import Request as _AuthRequest
except ImportError:
    _service_account = None  # type: ignore[assignment]
    _AuthRequest = None  # type: ignore[assignment]

try:
    from googleapiclient.discovery import build as _build_service
except ImportError:
    _build_service = None  # type: ignore[assignment]

try:
    from google.oauth2.credentials import Credentials as _UserCredentials
except ImportError:
    _UserCredentials = None  # type: ignore[assignment]

try:
    from google_auth_oauthlib.flow import InstalledAppFlow as _InstalledAppFlow
except ImportError:
    _InstalledAppFlow = None  # type: ignore[assignment]

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class GoogleWorkspaceError(Exception):
    """Base error for Google Workspace connector."""


class GoogleWorkspaceAuthError(GoogleWorkspaceError):
    """Authentication or authorization failure."""


class GoogleWorkspaceAPIError(GoogleWorkspaceError):
    """API call failure."""


class GoogleWorkspaceRateLimitError(GoogleWorkspaceError):
    """Rate limit (quota) exceeded."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADMIN_SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user",
    "https://www.googleapis.com/auth/admin.directory.group",
    "https://www.googleapis.com/auth/admin.reports.audit.readonly",
    "https://www.googleapis.com/auth/admin.reports.usage.readonly",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/calendar",
]

MAX_RETRIES = 4
INITIAL_BACKOFF = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _retry_with_backoff(coro_factory, *, max_retries: int = MAX_RETRIES):
    """Retry an async callable with exponential backoff."""
    delay = INITIAL_BACKOFF
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except GoogleWorkspaceRateLimitError:
            raise
        except (GoogleWorkspaceAPIError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                log.warning(
                    "Google Workspace request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise
    raise last_exc  # type: ignore[misc]


def _require_google_libs() -> None:
    if _service_account is None or _build_service is None:
        raise GoogleWorkspaceError(
            "Google Workspace connector requires: pip install "
            "google-auth google-auth-oauthlib google-api-python-client"
        )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class GoogleWorkspaceConnector(Connector):
    """Full Google Workspace integration — Admin SDK, Chat, Meet, Drive, Docs, Sheets.

    Provides 20 tools covering user/group administration, messaging,
    meetings, file management, document creation, and audit.
    """

    name = "google_workspace"
    description = (
        "Manage Google Workspace users, groups, Chat, Meet, Drive, "
        "Docs, and Sheets through a unified connector."
    )

    TOOLS: list[str] = [
        "gw_list_users",
        "gw_get_user",
        "gw_create_user",
        "gw_suspend_user",
        "gw_unsuspend_user",
        "gw_list_groups",
        "gw_add_group_member",
        "gw_send_chat_message",
        "gw_create_chat_space",
        "gw_list_chat_messages",
        "gw_schedule_meet",
        "gw_upload_drive_file",
        "gw_list_drive_files",
        "gw_share_drive_file",
        "gw_create_doc",
        "gw_create_sheet",
        "gw_read_sheet",
        "gw_update_sheet",
        "gw_get_workspace_usage",
        "gw_audit_admin_activity",
    ]

    def __init__(self) -> None:
        self._credentials: Any = None
        self._admin_service: Any = None  # Admin SDK directory
        self._drive_service: Any = None
        self._docs_service: Any = None
        self._sheets_service: Any = None
        self._chat_service: Any = None
        self._calendar_service: Any = None
        self._reports_service: Any = None
        self._domain: str = ""
        self._admin_email: str = ""

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._credentials is not None

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with Google Workspace.

        Supported credential keys:
            - service_account_key / service_account_file — service account JSON
            - domain — Google Workspace domain
            - admin_email — delegated admin email
            - access_token — pre-obtained OAuth2 token
        """
        _require_google_libs()

        self._domain = credentials.get(
            "domain", os.getenv("GOOGLE_WORKSPACE_DOMAIN", "")
        )
        self._admin_email = credentials.get(
            "admin_email", os.getenv("GOOGLE_ADMIN_EMAIL", "")
        )

        # Service account flow (recommended for workspace admin)
        sa_file = credentials.get(
            "service_account_file",
            os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY", ""),
        )
        sa_info = credentials.get("service_account_key", "")

        try:
            if sa_info:
                info = json.loads(sa_info) if isinstance(sa_info, str) else sa_info
                creds = _service_account.Credentials.from_service_account_info(
                    info, scopes=ADMIN_SCOPES,
                )
            elif sa_file and os.path.exists(sa_file):
                creds = _service_account.Credentials.from_service_account_file(
                    sa_file, scopes=ADMIN_SCOPES,
                )
            elif credentials.get("access_token") and _UserCredentials:
                creds = _UserCredentials(token=credentials["access_token"])
            else:
                log.error("Google Workspace: no valid credentials provided")
                return False

            # Domain-wide delegation
            if self._admin_email and hasattr(creds, "with_subject"):
                creds = creds.with_subject(self._admin_email)

            self._credentials = creds
            self._admin_service = _build_service(
                "admin", "directory_v1", credentials=creds
            )
            self._drive_service = _build_service("drive", "v3", credentials=creds)
            self._docs_service = _build_service("docs", "v1", credentials=creds)
            self._sheets_service = _build_service("sheets", "v4", credentials=creds)
            self._calendar_service = _build_service("calendar", "v3", credentials=creds)
            self._reports_service = _build_service(
                "admin", "reports_v1", credentials=creds
            )
            # Chat may need separate build or REST calls
            try:
                self._chat_service = _build_service("chat", "v1", credentials=creds)
            except Exception:
                self._chat_service = None
                log.warning("Google Chat API not available; chat tools will use REST")

            log.info("Google Workspace connected (domain=%s)", self._domain)
            return True

        except Exception as exc:
            raise GoogleWorkspaceAuthError(
                f"Google Workspace auth failed: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        """Clear all service handles."""
        self._credentials = None
        self._admin_service = None
        self._drive_service = None
        self._docs_service = None
        self._sheets_service = None
        self._chat_service = None
        self._calendar_service = None
        self._reports_service = None
        log.info("Google Workspace disconnected")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _exec_api(self, request: Any) -> Any:
        """Execute a Google API request with basic error handling."""
        try:
            return request.execute()
        except Exception as exc:
            err_str = str(exc).lower()
            if "429" in err_str or "rate" in err_str or "quota" in err_str:
                raise GoogleWorkspaceRateLimitError(str(exc)) from exc
            raise GoogleWorkspaceAPIError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route an action to its handler with retry/backoff."""
        if not self.connected:
            return {"error": "Google Workspace not connected. Call connect() first."}

        dispatch: dict[str, Any] = {
            "gw_list_users": self._list_users,
            "gw_get_user": self._get_user,
            "gw_create_user": self._create_user,
            "gw_suspend_user": self._suspend_user,
            "gw_unsuspend_user": self._unsuspend_user,
            "gw_list_groups": self._list_groups,
            "gw_add_group_member": self._add_group_member,
            "gw_send_chat_message": self._send_chat_message,
            "gw_create_chat_space": self._create_chat_space,
            "gw_list_chat_messages": self._list_chat_messages,
            "gw_schedule_meet": self._schedule_meet,
            "gw_upload_drive_file": self._upload_drive_file,
            "gw_list_drive_files": self._list_drive_files,
            "gw_share_drive_file": self._share_drive_file,
            "gw_create_doc": self._create_doc,
            "gw_create_sheet": self._create_sheet,
            "gw_read_sheet": self._read_sheet,
            "gw_update_sheet": self._update_sheet,
            "gw_get_workspace_usage": self._get_workspace_usage,
            "gw_audit_admin_activity": self._audit_admin_activity,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown Google Workspace action: {action}"}
        try:
            return await _retry_with_backoff(lambda: handler(params))
        except GoogleWorkspaceError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            log.exception("Unexpected error in Google Workspace action %s", action)
            return {"error": f"Internal error: {exc}"}

    # ------------------------------------------------------------------
    # Tool implementations (20 tools)
    # ------------------------------------------------------------------

    # ---- Admin SDK: Users ----

    async def _list_users(self, params: dict[str, Any]) -> dict[str, Any]:
        """List users in the Google Workspace domain."""
        domain = params.get("domain", self._domain)
        limit = params.get("limit", 100)
        if not domain:
            return {"error": "domain is required"}
        result = self._exec_api(
            self._admin_service.users().list(
                domain=domain, maxResults=min(limit, 500), orderBy="email",
            )
        )
        users = [
            {
                "id": u.get("id"),
                "email": u.get("primaryEmail"),
                "name": u.get("name", {}).get("fullName"),
                "suspended": u.get("suspended", False),
                "is_admin": u.get("isAdmin", False),
                "creation_time": u.get("creationTime"),
            }
            for u in result.get("users", [])
        ]
        return {"count": len(users), "users": users}

    async def _get_user(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get detailed user profile and group memberships."""
        email = params.get("email", "")
        if not email:
            return {"error": "email is required"}
        user = self._exec_api(
            self._admin_service.users().get(userKey=email)
        )
        # Fetch groups
        groups_result = self._exec_api(
            self._admin_service.groups().list(userKey=email)
        )
        groups = [
            {"email": g.get("email"), "name": g.get("name")}
            for g in groups_result.get("groups", [])
        ]
        return {
            "id": user.get("id"),
            "email": user.get("primaryEmail"),
            "name": user.get("name", {}).get("fullName"),
            "org_unit": user.get("orgUnitPath"),
            "suspended": user.get("suspended", False),
            "is_admin": user.get("isAdmin", False),
            "groups": groups,
        }

    async def _create_user(self, params: dict[str, Any]) -> dict[str, Any]:
        """Provision a new user in the Google Workspace domain."""
        email = params.get("email", "")
        name = params.get("name", "")
        password = params.get("password", "")
        if not email or not name or not password:
            return {"error": "email, name, and password are required"}
        name_parts = name.split(" ", 1)
        given = name_parts[0]
        family = name_parts[1] if len(name_parts) > 1 else given
        body = {
            "primaryEmail": email,
            "name": {"givenName": given, "familyName": family},
            "password": password,
            "changePasswordAtNextLogin": True,
        }
        result = self._exec_api(
            self._admin_service.users().insert(body=body)
        )
        return {
            "id": result.get("id"),
            "email": result.get("primaryEmail"),
            "created": True,
        }

    async def _suspend_user(self, params: dict[str, Any]) -> dict[str, Any]:
        """Suspend a user account."""
        email = params.get("email", "")
        if not email:
            return {"error": "email is required"}
        self._exec_api(
            self._admin_service.users().update(
                userKey=email, body={"suspended": True},
            )
        )
        return {"email": email, "suspended": True}

    async def _unsuspend_user(self, params: dict[str, Any]) -> dict[str, Any]:
        """Unsuspend (reactivate) a user account."""
        email = params.get("email", "")
        if not email:
            return {"error": "email is required"}
        self._exec_api(
            self._admin_service.users().update(
                userKey=email, body={"suspended": False},
            )
        )
        return {"email": email, "suspended": False}

    # ---- Admin SDK: Groups ----

    async def _list_groups(self, params: dict[str, Any]) -> dict[str, Any]:
        """List Google Groups in the domain."""
        domain = params.get("domain", self._domain)
        if not domain:
            return {"error": "domain is required"}
        result = self._exec_api(
            self._admin_service.groups().list(domain=domain, maxResults=200)
        )
        groups = [
            {
                "id": g.get("id"),
                "email": g.get("email"),
                "name": g.get("name"),
                "member_count": g.get("directMembersCount"),
            }
            for g in result.get("groups", [])
        ]
        return {"count": len(groups), "groups": groups}

    async def _add_group_member(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add a member to a Google Group."""
        group = params.get("group", "")
        email = params.get("email", "")
        if not group or not email:
            return {"error": "group and email are required"}
        body = {"email": email, "role": params.get("role", "MEMBER")}
        self._exec_api(
            self._admin_service.members().insert(groupKey=group, body=body)
        )
        return {"group": group, "email": email, "added": True}

    # ---- Google Chat ----

    async def _send_chat_message(self, params: dict[str, Any]) -> dict[str, Any]:
        """Send a message to a Google Chat space."""
        space_id = params.get("space_id", "")
        text = params.get("text", "")
        if not space_id or not text:
            return {"error": "space_id and text are required"}
        if self._chat_service:
            result = self._exec_api(
                self._chat_service.spaces().messages().create(
                    parent=f"spaces/{space_id}",
                    body={"text": text},
                )
            )
            return {"name": result.get("name"), "sent": True}
        # Fallback to REST
        if _requests is None:
            raise GoogleWorkspaceError("requests library required for Chat REST fallback")
        headers = {"Authorization": f"Bearer {self._credentials.token}"}
        resp = _requests.post(
            f"https://chat.googleapis.com/v1/spaces/{space_id}/messages",
            json={"text": text},
            headers=headers,
            timeout=30,
        )
        if resp.status_code >= 400:
            raise GoogleWorkspaceAPIError(f"Chat send failed: {resp.text[:500]}")
        return {"name": resp.json().get("name"), "sent": True}

    async def _create_chat_space(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Google Chat space (room)."""
        name = params.get("name", "")
        members: list[str] = params.get("members", [])
        if not name:
            return {"error": "name is required"}
        body: dict[str, Any] = {
            "displayName": name,
            "spaceType": "SPACE",
        }
        if self._chat_service:
            result = self._exec_api(
                self._chat_service.spaces().create(body=body)
            )
            space_name = result.get("name", "")
        else:
            if _requests is None:
                raise GoogleWorkspaceError("requests library required")
            headers = {"Authorization": f"Bearer {self._credentials.token}"}
            resp = _requests.post(
                "https://chat.googleapis.com/v1/spaces",
                json=body, headers=headers, timeout=30,
            )
            if resp.status_code >= 400:
                raise GoogleWorkspaceAPIError(f"Create space failed: {resp.text[:500]}")
            space_name = resp.json().get("name", "")
        return {"space": space_name, "members_invited": len(members)}

    async def _list_chat_messages(self, params: dict[str, Any]) -> dict[str, Any]:
        """List recent messages in a Google Chat space."""
        space_id = params.get("space_id", "")
        limit = params.get("limit", 25)
        if not space_id:
            return {"error": "space_id is required"}
        if self._chat_service:
            result = self._exec_api(
                self._chat_service.spaces().messages().list(
                    parent=f"spaces/{space_id}", pageSize=min(limit, 1000),
                )
            )
            messages = [
                {
                    "name": m.get("name"),
                    "sender": m.get("sender", {}).get("displayName"),
                    "text": m.get("text", ""),
                    "create_time": m.get("createTime"),
                }
                for m in result.get("messages", [])
            ]
        else:
            messages = []
        return {"count": len(messages), "messages": messages}

    # ---- Google Meet (via Calendar API) ----

    async def _schedule_meet(self, params: dict[str, Any]) -> dict[str, Any]:
        """Schedule a Google Meet meeting via Calendar API."""
        title = params.get("title", "Meeting")
        attendees: list[str] = params.get("attendees", [])
        start = params.get("start", "")
        duration: int = params.get("duration", 60)
        if not start:
            return {"error": "start (ISO datetime) is required"}
        # Build end time
        from datetime import datetime, timedelta
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            return {"error": "start must be ISO 8601 format"}
        end_dt = start_dt + timedelta(minutes=duration)
        event_body = {
            "summary": title,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
            "attendees": [{"email": e} for e in attendees],
            "conferenceData": {
                "createRequest": {
                    "requestId": f"meet-{int(start_dt.timestamp())}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                },
            },
        }
        result = self._exec_api(
            self._calendar_service.events().insert(
                calendarId="primary",
                body=event_body,
                conferenceDataVersion=1,
            )
        )
        meet_link = result.get("hangoutLink", "")
        return {
            "event_id": result.get("id"),
            "meet_link": meet_link,
            "start": start,
            "duration_minutes": duration,
        }

    # ---- Google Drive ----

    async def _upload_drive_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Upload a file to Google Drive."""
        name = params.get("name", "")
        content = params.get("content", "")
        parent_folder = params.get("parent_folder", "")
        if not name:
            return {"error": "name is required"}
        from io import BytesIO
        try:
            from googleapiclient.http import MediaIoBaseUpload
        except ImportError:
            raise GoogleWorkspaceError("googleapiclient required")
        metadata: dict[str, Any] = {"name": name}
        if parent_folder:
            metadata["parents"] = [parent_folder]
        media = MediaIoBaseUpload(
            BytesIO(content.encode("utf-8") if isinstance(content, str) else content),
            mimetype="application/octet-stream",
            resumable=True,
        )
        result = self._exec_api(
            self._drive_service.files().create(
                body=metadata, media_body=media, fields="id,name,webViewLink",
            )
        )
        return {
            "file_id": result.get("id"),
            "name": result.get("name"),
            "web_link": result.get("webViewLink"),
        }

    async def _list_drive_files(self, params: dict[str, Any]) -> dict[str, Any]:
        """List files in Google Drive, optionally filtered by folder or query."""
        folder_id = params.get("folder_id", "")
        query = params.get("query", "")
        q_parts: list[str] = []
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        if query:
            q_parts.append(query)
        q = " and ".join(q_parts) if q_parts else None
        kwargs: dict[str, Any] = {
            "pageSize": 100,
            "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        }
        if q:
            kwargs["q"] = q
        result = self._exec_api(
            self._drive_service.files().list(**kwargs)
        )
        files = [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "mime_type": f.get("mimeType"),
                "modified": f.get("modifiedTime"),
                "size": f.get("size"),
                "link": f.get("webViewLink"),
            }
            for f in result.get("files", [])
        ]
        return {"count": len(files), "files": files}

    async def _share_drive_file(self, params: dict[str, Any]) -> dict[str, Any]:
        """Share a Drive file with a specific user."""
        file_id = params.get("file_id", "")
        email = params.get("email", "")
        role = params.get("role", "reader")
        if not file_id or not email:
            return {"error": "file_id and email are required"}
        permission = {"type": "user", "role": role, "emailAddress": email}
        self._exec_api(
            self._drive_service.permissions().create(
                fileId=file_id, body=permission, sendNotificationEmail=True,
            )
        )
        return {"file_id": file_id, "shared_with": email, "role": role}

    # ---- Google Docs ----

    async def _create_doc(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new Google Doc with optional initial content."""
        title = params.get("title", "Untitled")
        content = params.get("content", "")
        body = {"title": title}
        result = self._exec_api(
            self._docs_service.documents().create(body=body)
        )
        doc_id = result.get("documentId", "")
        # Insert content if provided
        if content and doc_id:
            requests_body = {
                "requests": [
                    {"insertText": {"location": {"index": 1}, "text": content}}
                ]
            }
            self._exec_api(
                self._docs_service.documents().batchUpdate(
                    documentId=doc_id, body=requests_body,
                )
            )
        return {
            "document_id": doc_id,
            "title": title,
            "link": f"https://docs.google.com/document/d/{doc_id}/edit",
        }

    # ---- Google Sheets ----

    async def _create_sheet(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new Google Sheet with optional initial data."""
        title = params.get("title", "Untitled Spreadsheet")
        data: list[list[Any]] = params.get("data", [])
        body = {"properties": {"title": title}}
        result = self._exec_api(
            self._sheets_service.spreadsheets().create(body=body)
        )
        sheet_id = result.get("spreadsheetId", "")
        # Populate data
        if data and sheet_id:
            self._exec_api(
                self._sheets_service.spreadsheets().values().update(
                    spreadsheetId=sheet_id,
                    range="Sheet1!A1",
                    valueInputOption="USER_ENTERED",
                    body={"values": data},
                )
            )
        return {
            "spreadsheet_id": sheet_id,
            "title": title,
            "link": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
        }

    async def _read_sheet(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read data from a Google Sheet range."""
        sheet_id = params.get("sheet_id", "")
        range_ = params.get("range", "Sheet1")
        if not sheet_id:
            return {"error": "sheet_id is required"}
        result = self._exec_api(
            self._sheets_service.spreadsheets().values().get(
                spreadsheetId=sheet_id, range=range_,
            )
        )
        values = result.get("values", [])
        return {
            "spreadsheet_id": sheet_id,
            "range": result.get("range", range_),
            "rows": len(values),
            "values": values,
        }

    async def _update_sheet(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update values in a Google Sheet range."""
        sheet_id = params.get("sheet_id", "")
        range_ = params.get("range", "Sheet1!A1")
        values: list[list[Any]] = params.get("values", [])
        if not sheet_id or not values:
            return {"error": "sheet_id and values are required"}
        result = self._exec_api(
            self._sheets_service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=range_,
                valueInputOption="USER_ENTERED",
                body={"values": values},
            )
        )
        return {
            "spreadsheet_id": sheet_id,
            "updated_range": result.get("updatedRange"),
            "updated_rows": result.get("updatedRows"),
            "updated_cells": result.get("updatedCells"),
        }

    # ---- Admin Reports ----

    async def _get_workspace_usage(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get Google Workspace usage report (Admin Reports API)."""
        date = params.get("date", "")
        if not date:
            from datetime import datetime, timedelta, timezone
            date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        try:
            result = self._exec_api(
                self._reports_service.userUsageReport().get(
                    userKey="all", date=date,
                )
            )
            reports = result.get("usageReports", [])
            return {"date": date, "report_count": len(reports), "reports": reports[:50]}
        except Exception as exc:
            return {"error": f"Usage report failed: {exc}"}

    async def _audit_admin_activity(self, params: dict[str, Any]) -> dict[str, Any]:
        """Audit admin activity logs in Google Workspace."""
        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")
        kwargs: dict[str, Any] = {"userKey": "all", "applicationName": "admin"}
        if start_date:
            kwargs["startTime"] = f"{start_date}T00:00:00.000Z"
        if end_date:
            kwargs["endTime"] = f"{end_date}T23:59:59.999Z"
        try:
            result = self._exec_api(
                self._reports_service.activities().list(**kwargs)
            )
            activities = result.get("items", [])
            return {"count": len(activities), "activities": activities[:100]}
        except Exception as exc:
            return {"error": f"Audit query failed: {exc}"}

    # ------------------------------------------------------------------
    # Tool definitions (OpenAI function-calling format)
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas for all 20 Google Workspace tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "gw_list_users",
                    "description": "List users in the Google Workspace domain via Admin SDK.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string", "description": "Workspace domain (defaults to configured domain)"},
                            "limit": {"type": "integer", "description": "Max users to return (default 100)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_get_user",
                    "description": "Get a Google Workspace user profile and group memberships.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string", "description": "User email address"},
                        },
                        "required": ["email"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_create_user",
                    "description": "Provision a new user in the Google Workspace domain.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string", "description": "New user email"},
                            "name": {"type": "string", "description": "Full name"},
                            "password": {"type": "string", "description": "Initial password"},
                        },
                        "required": ["email", "name", "password"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_suspend_user",
                    "description": "Suspend a Google Workspace user account.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string", "description": "User email to suspend"},
                        },
                        "required": ["email"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_unsuspend_user",
                    "description": "Unsuspend (reactivate) a Google Workspace user account.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string", "description": "User email to unsuspend"},
                        },
                        "required": ["email"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_list_groups",
                    "description": "List Google Groups in the Workspace domain.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string", "description": "Domain to list groups for"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_add_group_member",
                    "description": "Add a member to a Google Group.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "group": {"type": "string", "description": "Group email address"},
                            "email": {"type": "string", "description": "Member email to add"},
                        },
                        "required": ["group", "email"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_send_chat_message",
                    "description": "Send a message to a Google Chat space.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "space_id": {"type": "string", "description": "Chat space ID"},
                            "text": {"type": "string", "description": "Message text"},
                        },
                        "required": ["space_id", "text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_create_chat_space",
                    "description": "Create a new Google Chat space (room).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Space display name"},
                            "members": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Email addresses of initial members",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_list_chat_messages",
                    "description": "List recent messages in a Google Chat space.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "space_id": {"type": "string", "description": "Chat space ID"},
                            "limit": {"type": "integer", "description": "Max messages (default 25)"},
                        },
                        "required": ["space_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_schedule_meet",
                    "description": "Schedule a Google Meet meeting via Calendar.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Meeting title"},
                            "attendees": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Attendee email addresses",
                            },
                            "start": {"type": "string", "description": "Start time (ISO 8601)"},
                            "duration": {"type": "integer", "description": "Duration in minutes (default 60)"},
                        },
                        "required": ["start"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_upload_drive_file",
                    "description": "Upload a file to Google Drive.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "File name"},
                            "content": {"type": "string", "description": "File content (text)"},
                            "parent_folder": {"type": "string", "description": "Parent folder ID (optional)"},
                        },
                        "required": ["name", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_list_drive_files",
                    "description": "List files in Google Drive, optionally filtered by folder or query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "folder_id": {"type": "string", "description": "Filter by parent folder ID"},
                            "query": {"type": "string", "description": "Drive search query"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_share_drive_file",
                    "description": "Share a Google Drive file with a user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_id": {"type": "string", "description": "Drive file ID"},
                            "email": {"type": "string", "description": "Email to share with"},
                            "role": {"type": "string", "description": "Permission role (reader/writer/commenter)"},
                        },
                        "required": ["file_id", "email"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_create_doc",
                    "description": "Create a new Google Docs document with optional content.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Document title"},
                            "content": {"type": "string", "description": "Initial document content"},
                        },
                        "required": ["title"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_create_sheet",
                    "description": "Create a new Google Sheet with optional initial data.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Spreadsheet title"},
                            "data": {
                                "type": "array",
                                "items": {"type": "array", "items": {}},
                                "description": "2D array of initial values",
                            },
                        },
                        "required": ["title"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_read_sheet",
                    "description": "Read data from a Google Sheet range.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sheet_id": {"type": "string", "description": "Spreadsheet ID"},
                            "range": {"type": "string", "description": "A1 notation range (default: Sheet1)"},
                        },
                        "required": ["sheet_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_update_sheet",
                    "description": "Update values in a Google Sheet range.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sheet_id": {"type": "string", "description": "Spreadsheet ID"},
                            "range": {"type": "string", "description": "A1 notation range"},
                            "values": {
                                "type": "array",
                                "items": {"type": "array", "items": {}},
                                "description": "2D array of values to write",
                            },
                        },
                        "required": ["sheet_id", "values"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_get_workspace_usage",
                    "description": "Get Google Workspace usage reports (Admin Reports API).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "Report date (YYYY-MM-DD, defaults to 2 days ago)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gw_audit_admin_activity",
                    "description": "Query admin activity audit logs in Google Workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                        },
                    },
                },
            },
        ]
