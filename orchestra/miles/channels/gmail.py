"""MILES Gmail channel adapter.

Extends the existing orchestra.connectors.gmail connector to normalise
emails into ChannelMessages and reply in-thread.

Requires: GMAIL_CREDENTIALS_PATH env var (path to OAuth2 credentials JSON).
Token is cached at ~/.horizon/gmail_token.json.

For service-account deployments set GOOGLE_APPLICATION_CREDENTIALS and
set use_service_account=True in the constructor.
"""
from __future__ import annotations

import base64
import email as email_lib
import email.mime.text
import logging
import os
import time
from typing import Any

from orchestra.miles.channels.base import ChannelAdapter, ChannelMessage, ChannelResponse

__all__ = ["GmailChannelAdapter"]

log = logging.getLogger("orchestra.miles.channels.gmail")


def _get_service(credentials_path: str, token_path: str) -> Any:
    """Build a gmail service object using google-auth / google-api-python-client."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ]

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as tok:
            tok.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


class GmailChannelAdapter(ChannelAdapter):
    """Poll Gmail inbox and send replies via the Gmail API."""

    channel_name = "gmail"
    supports_polling = True
    supports_webhook = False

    def __init__(
        self,
        credentials_path: str = "",
        token_path: str = "",
        poll_labels: list[str] | None = None,
        since_ts: float | None = None,
        max_results: int = 20,
    ) -> None:
        self._credentials_path = credentials_path or os.environ.get(
            "GMAIL_CREDENTIALS_PATH", ""
        )
        self._token_path = token_path or str(
            __import__("pathlib").Path.home() / ".horizon" / "gmail_token.json"
        )
        self._poll_labels = poll_labels or ["INBOX", "UNREAD"]
        self._since_ts: float = since_ts or time.time()
        self._max_results = max_results
        self._service: Any = None
        self._my_email: str = ""

    async def connect(self) -> bool:
        if not self._credentials_path:
            log.error("GMAIL_CREDENTIALS_PATH not set.")
            return False
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            self._service = await loop.run_in_executor(
                None, _get_service, self._credentials_path, self._token_path
            )
            profile = self._service.users().getProfile(userId="me").execute()
            self._my_email = profile.get("emailAddress", "")
            log.info("Gmail connected: %s", self._my_email)
            return True
        except ImportError:
            log.error(
                "google-auth / google-api-python-client required: "
                "pip install google-auth google-auth-oauthlib google-api-python-client"
            )
            return False
        except Exception as exc:
            log.error("Gmail connection failed: %s", exc)
            return False

    async def poll(self) -> list[ChannelMessage]:
        if not self._service:
            return []
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(None, self._poll_sync)

    def _poll_sync(self) -> list[ChannelMessage]:
        messages: list[ChannelMessage] = []
        try:
            after_epoch = int(self._since_ts)
            query = f"after:{after_epoch} -from:{self._my_email}"
            label_ids = [l for l in self._poll_labels]

            result = (
                self._service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    labelIds=label_ids,
                    maxResults=self._max_results,
                )
                .execute()
            )

            raw_msgs = result.get("messages", [])
            new_ts = self._since_ts

            for meta in raw_msgs:
                try:
                    full = (
                        self._service.users()
                        .messages()
                        .get(userId="me", id=meta["id"], format="full")
                        .execute()
                    )
                    msg = self._parse_message(full)
                    if msg:
                        if msg.timestamp > new_ts:
                            new_ts = msg.timestamp
                        messages.append(msg)
                        # Mark as read
                        self._service.users().messages().modify(
                            userId="me",
                            id=meta["id"],
                            body={"removeLabelIds": ["UNREAD"]},
                        ).execute()
                except Exception as exc:
                    log.warning("Gmail message parse error: %s", exc)

            if new_ts > self._since_ts:
                self._since_ts = new_ts + 1.0

        except Exception as exc:
            log.error("Gmail poll error: %s", exc)
        return messages

    def _parse_message(self, raw: dict[str, Any]) -> ChannelMessage | None:
        headers = {
            h["name"].lower(): h["value"]
            for h in raw.get("payload", {}).get("headers", [])
        }
        sender = headers.get("from", "unknown")
        subject = headers.get("subject", "")
        date_str = headers.get("date", "")
        msg_id = raw.get("id", "")
        thread_id = raw.get("threadId", msg_id)

        # Parse unix timestamp from internal date
        internal_ts = raw.get("internalDate")
        ts = (int(internal_ts) / 1000) if internal_ts else time.time()

        # Skip messages from self
        if self._my_email and self._my_email in sender:
            return None

        text = self._extract_body(raw.get("payload", {}))
        if not text.strip():
            return None

        # Sender display name
        sender_name = sender
        if "<" in sender:
            sender_name = sender.split("<")[0].strip().strip('"')

        sender_id = sender
        if "<" in sender:
            sender_id = sender.split("<")[1].rstrip(">").strip()

        return ChannelMessage(
            id=msg_id,
            channel="gmail",
            sender_id=sender_id,
            sender_name=sender_name,
            text=text,
            timestamp=ts,
            thread_id=thread_id,
            subject=subject,
            raw=raw,
        )

    def _extract_body(self, payload: dict[str, Any]) -> str:
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if body_data and mime_type in ("text/plain", "text/html"):
            decoded = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
            if mime_type == "text/html":
                # Strip HTML tags
                import re
                decoded = re.sub(r"<[^>]+>", "", decoded)
            return decoded.strip()

        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text
        return ""

    async def send(self, response: ChannelResponse) -> bool:
        if not self._service:
            return False
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._send_sync, response
        )

    def _send_sync(self, response: ChannelResponse) -> bool:
        try:
            msg = email_lib.mime.text.MIMEText(response.text)
            msg["to"] = response.recipient_id
            msg["from"] = self._my_email
            msg["subject"] = response.subject or "Re: (no subject)"

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            body: dict[str, Any] = {"raw": raw}
            if response.thread_id:
                body["threadId"] = response.thread_id

            self._service.users().messages().send(userId="me", body=body).execute()
            return True
        except Exception as exc:
            log.error("Gmail send failed: %s", exc)
            return False
