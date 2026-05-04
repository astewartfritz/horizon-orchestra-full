"""Google Drive connector — OAuth2 + Drive API v3.

Search, read, create, and share files in Google Drive.
Requires: pip install google-auth google-auth-oauthlib google-api-python-client
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
from typing import Any

from .base import Connector

__all__ = ["GoogleDriveConnector"]

log = logging.getLogger("orchestra.connectors.gdrive")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
]
TOKEN_PATH = Path.home() / ".horizon" / "gdrive_token.json"


class GoogleDriveConnector(Connector):
    name = "gdrive"
    description = "Search, read, create, and share files in Google Drive."

    def __init__(self) -> None:
        self._creds: Any = None
        self._service: Any = None

    @property
    def connected(self) -> bool:
        return self._service is not None

    async def connect(self, credentials: dict[str, str]) -> bool:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            log.error("pip install google-auth google-auth-oauthlib google-api-python-client")
            return False

        creds = None
        if TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            except Exception:
                                import logging as _log; _log.getLogger('connectors.gdrive').debug('Suppressed exception', exc_info=True)
        if not creds and credentials.get("token"):
            try:
                creds = Credentials.from_authorized_user_info(json.loads(credentials["token"]), SCOPES)
            except Exception:
                                import logging as _log; _log.getLogger('connectors.gdrive').debug('Suppressed exception', exc_info=True)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            sf = credentials.get("client_secret_file", "")
            if not sf or not Path(sf).exists():
                return False
            flow = InstalledAppFlow.from_client_secrets_file(sf, SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())
        self._creds = creds
        self._service = build("drive", "v3", credentials=creds)
        log.info("Google Drive connected")
        return True

    async def disconnect(self) -> None:
        self._service = None; self._creds = None

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._service:
            return {"error": "Google Drive not connected."}
        dispatch = {
            "gdrive_search": self._search,
            "gdrive_read": self._read,
            "gdrive_create": self._create,
            "gdrive_share": self._share,
        }
        handler = dispatch.get(action)
        return await handler(params) if handler else {"error": f"Unknown action: {action}"}

    async def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        limit = params.get("limit", 10)
        try:
            q = f"fullText contains '{query}'" if query else ""
            results = self._service.files().list(
                q=q, pageSize=limit, fields="files(id,name,mimeType,modifiedTime,size,webViewLink)",
            ).execute()
            return {"files": [
                {"id": f["id"], "name": f["name"], "type": f.get("mimeType", ""), "modified": f.get("modifiedTime", ""), "link": f.get("webViewLink", "")}
                for f in results.get("files", [])
            ]}
        except Exception as exc:
            return {"error": str(exc)}

    async def _read(self, params: dict[str, Any]) -> dict[str, Any]:
        file_id = params.get("file_id", "")
        if not file_id:
            return {"error": "file_id required"}
        try:
            meta = self._service.files().get(fileId=file_id, fields="name,mimeType").execute()
            mime = meta.get("mimeType", "")
            if "google-apps" in mime:
                export_map = {
                    "application/vnd.google-apps.document": "text/plain",
                    "application/vnd.google-apps.spreadsheet": "text/csv",
                    "application/vnd.google-apps.presentation": "text/plain",
                }
                export_mime = export_map.get(mime, "text/plain")
                content = self._service.files().export(fileId=file_id, mimeType=export_mime).execute()
                text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
            else:
                content = self._service.files().get_media(fileId=file_id).execute()
                text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
            return {"name": meta["name"], "content": text[:50_000]}
        except Exception as exc:
            return {"error": str(exc)}

    async def _create(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "Untitled")
        content = params.get("content", "")
        mime = params.get("mime_type", "text/plain")
        folder_id = params.get("folder_id", "")
        try:
            from googleapiclient.http import MediaInMemoryUpload
            meta: dict[str, Any] = {"name": name}
            if folder_id:
                meta["parents"] = [folder_id]
            media = MediaInMemoryUpload(content.encode(), mimetype=mime)
            f = self._service.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
            return {"created": True, "id": f["id"], "link": f.get("webViewLink", "")}
        except Exception as exc:
            return {"error": str(exc)}

    async def _share(self, params: dict[str, Any]) -> dict[str, Any]:
        file_id = params.get("file_id", "")
        email = params.get("email", "")
        role = params.get("role", "reader")
        if not file_id or not email:
            return {"error": "file_id and email required"}
        try:
            self._service.permissions().create(fileId=file_id, body={"type": "user", "role": role, "emailAddress": email}).execute()
            return {"shared": True, "file_id": file_id, "email": email, "role": role}
        except Exception as exc:
            return {"error": str(exc)}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "gdrive_search", "description": "Search Google Drive files.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "gdrive_read", "description": "Read a Google Drive file by ID.", "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"]}}},
            {"type": "function", "function": {"name": "gdrive_create", "description": "Create a file in Google Drive.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "content": {"type": "string"}, "mime_type": {"type": "string"}, "folder_id": {"type": "string"}}, "required": ["name", "content"]}}},
            {"type": "function", "function": {"name": "gdrive_share", "description": "Share a Drive file with someone.", "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}, "email": {"type": "string"}, "role": {"type": "string", "enum": ["reader", "writer", "commenter"]}}, "required": ["file_id", "email"]}}},
        ]
