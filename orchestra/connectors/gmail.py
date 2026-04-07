"""Gmail connector — OAuth2 + search/read/send.

Requires: pip install google-auth google-auth-oauthlib google-api-python-client

Auth flow:
1. Call connect() with {"client_secret_file": "/path/to/credentials.json"}
   for first-time OAuth2, or {"token": "<serialised_token>"} for subsequent.
2. Token is cached at ~/.horizon/gmail_token.json for reuse.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from .base import Connector

__all__ = ["GmailConnector"]

log = logging.getLogger("orchestra.connectors.gmail")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

TOKEN_PATH = Path.home() / ".horizon" / "gmail_token.json"


class GmailConnector(Connector):
    """Full Gmail integration via the Gmail API."""

    name = "gmail"
    description = "Search, read, and send emails via Gmail."

    def __init__(self) -> None:
        self._creds: Any = None
        self._service: Any = None

    @property
    def connected(self) -> bool:
        return self._service is not None

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with Gmail.

        credentials can contain:
        - "client_secret_file": path to OAuth2 client secret JSON (first-time)
        - "token": raw serialised token JSON string
        - (empty): attempts to load cached token from ~/.horizon/gmail_token.json
        """
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            log.error(
                "Gmail connector requires: pip install "
                "google-auth google-auth-oauthlib google-api-python-client"
            )
            return False

        creds = None

        # Try cached token
        if TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            except Exception:
                pass

        # Try token from credentials dict
        if not creds and credentials.get("token"):
            try:
                info = json.loads(credentials["token"])
                creds = Credentials.from_authorized_user_info(info, SCOPES)
            except Exception:
                pass

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        # Full OAuth2 flow
        if not creds or not creds.valid:
            secret_file = credentials.get("client_secret_file", "")
            if not secret_file or not Path(secret_file).exists():
                log.error("No valid token and no client_secret_file for OAuth2 flow")
                return False
            flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
            creds = flow.run_local_server(port=0)

        # Cache token
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

        self._creds = creds
        self._service = build("gmail", "v1", credentials=creds)
        log.info("Gmail connected")
        return True

    async def disconnect(self) -> None:
        self._service = None
        self._creds = None

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._service:
            return {"error": "Gmail not connected."}

        dispatch = {
            "gmail_search": self._search,
            "gmail_read": self._read,
            "gmail_send": self._send,
            "gmail_list_labels": self._list_labels,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    async def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        max_results = params.get("max_results", 10)
        try:
            results = self._service.users().messages().list(
                userId="me", q=query, maxResults=max_results,
            ).execute()
            messages = results.get("messages", [])

            summaries = []
            for msg_ref in messages[:max_results]:
                msg = self._service.users().messages().get(
                    userId="me", id=msg_ref["id"], format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                ).execute()
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                summaries.append({
                    "id": msg["id"],
                    "subject": headers.get("Subject", ""),
                    "from": headers.get("From", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                })
            return {"count": len(summaries), "messages": summaries}
        except Exception as exc:
            return {"error": str(exc)}

    async def _read(self, params: dict[str, Any]) -> dict[str, Any]:
        msg_id = params.get("message_id", "")
        if not msg_id:
            return {"error": "message_id is required"}
        try:
            msg = self._service.users().messages().get(
                userId="me", id=msg_id, format="full",
            ).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

            # Extract body
            body = ""
            payload = msg.get("payload", {})
            if "body" in payload and payload["body"].get("data"):
                body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
            elif "parts" in payload:
                for part in payload["parts"]:
                    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                        break

            return {
                "id": msg["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "date": headers.get("Date", ""),
                "body": body[:10_000],
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def _send(self, params: dict[str, Any]) -> dict[str, Any]:
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        if not to or not subject:
            return {"error": "to and subject are required"}

        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
            sent = self._service.users().messages().send(
                userId="me", body={"raw": raw},
            ).execute()
            return {"sent": True, "id": sent.get("id", ""), "to": to}
        except Exception as exc:
            return {"error": str(exc)}

    async def _list_labels(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            results = self._service.users().labels().list(userId="me").execute()
            labels = [{"id": l["id"], "name": l["name"]} for l in results.get("labels", [])]
            return {"labels": labels}
        except Exception as exc:
            return {"error": str(exc)}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "gmail_search",
                    "description": "Search Gmail for emails. Uses Gmail search syntax (from:, subject:, has:attachment, etc).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Gmail search query"},
                            "max_results": {"type": "integer", "description": "Max results (default 10)"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gmail_read",
                    "description": "Read the full content of a specific email by message ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message_id": {"type": "string", "description": "Gmail message ID"},
                        },
                        "required": ["message_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gmail_send",
                    "description": "Send an email via Gmail.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string", "description": "Recipient email"},
                            "subject": {"type": "string", "description": "Email subject"},
                            "body": {"type": "string", "description": "Email body (plain text)"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gmail_list_labels",
                    "description": "List all Gmail labels/folders.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]
