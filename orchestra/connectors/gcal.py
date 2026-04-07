"""Google Calendar connector — OAuth2 auth + Calendar API v3.

Requires: pip install google-auth google-auth-oauthlib google-api-python-client
Same OAuth2 flow as Gmail. Cached token at ~/.horizon/gcal_token.json.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .base import Connector

__all__ = ["GoogleCalendarConnector"]

log = logging.getLogger("orchestra.connectors.gcal")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

TOKEN_PATH = Path.home() / ".horizon" / "gcal_token.json"


class GoogleCalendarConnector(Connector):
    """Google Calendar integration via Calendar API v3."""

    name = "gcal"
    description = "Manage calendar events, check availability, and schedule meetings."

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
            log.error(
                "Google Calendar connector requires: pip install "
                "google-auth google-auth-oauthlib google-api-python-client"
            )
            return False

        creds = None

        if TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            except Exception:
                pass

        if not creds and credentials.get("token"):
            try:
                info = json.loads(credentials["token"])
                creds = Credentials.from_authorized_user_info(info, SCOPES)
            except Exception:
                pass

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds or not creds.valid:
            secret_file = credentials.get("client_secret_file", "")
            if not secret_file or not Path(secret_file).exists():
                log.error("No valid token and no client_secret_file for OAuth2 flow")
                return False
            flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

        self._creds = creds
        self._service = build("calendar", "v3", credentials=creds)
        log.info("Google Calendar connected")
        return True

    async def disconnect(self) -> None:
        self._service = None
        self._creds = None

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._service:
            return {"error": "Google Calendar not connected."}
        dispatch = {
            "gcal_list_events": self._list_events,
            "gcal_create_event": self._create_event,
            "gcal_delete_event": self._delete_event,
            "gcal_find_free_time": self._find_free_time,
            "gcal_list_calendars": self._list_calendars,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    async def _list_events(self, params: dict[str, Any]) -> dict[str, Any]:
        days = params.get("days", 7)
        calendar_id = params.get("calendar_id", "primary")
        max_results = params.get("max_results", 20)
        query = params.get("query", "")

        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()

        try:
            kwargs: dict[str, Any] = {
                "calendarId": calendar_id,
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if query:
                kwargs["q"] = query

            result = self._service.events().list(**kwargs).execute()
            events = result.get("items", [])
            return {
                "count": len(events),
                "events": [
                    {
                        "id": e.get("id"),
                        "summary": e.get("summary", ""),
                        "start": (e.get("start") or {}).get("dateTime", (e.get("start") or {}).get("date", "")),
                        "end": (e.get("end") or {}).get("dateTime", (e.get("end") or {}).get("date", "")),
                        "location": e.get("location", ""),
                        "description": (e.get("description") or "")[:500],
                        "attendees": [
                            {"email": a.get("email"), "status": a.get("responseStatus")}
                            for a in e.get("attendees", [])
                        ],
                        "link": e.get("htmlLink"),
                    }
                    for e in events
                ],
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def _create_event(self, params: dict[str, Any]) -> dict[str, Any]:
        summary = params.get("summary", "")
        start = params.get("start", "")
        end = params.get("end", "")
        description = params.get("description", "")
        location = params.get("location", "")
        attendees = params.get("attendees", [])
        calendar_id = params.get("calendar_id", "primary")

        if not summary or not start or not end:
            return {"error": "summary, start, and end are required"}

        event_body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": params.get("timezone", "America/Chicago")},
            "end": {"dateTime": end, "timeZone": params.get("timezone", "America/Chicago")},
        }
        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if attendees:
            event_body["attendees"] = [{"email": e} for e in attendees]

        try:
            event = self._service.events().insert(
                calendarId=calendar_id, body=event_body,
                sendUpdates="all" if attendees else "none",
            ).execute()
            return {
                "created": True,
                "id": event.get("id"),
                "link": event.get("htmlLink"),
                "summary": event.get("summary"),
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def _delete_event(self, params: dict[str, Any]) -> dict[str, Any]:
        event_id = params.get("event_id", "")
        calendar_id = params.get("calendar_id", "primary")
        if not event_id:
            return {"error": "event_id is required"}
        try:
            self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return {"deleted": True, "event_id": event_id}
        except Exception as exc:
            return {"error": str(exc)}

    async def _find_free_time(self, params: dict[str, Any]) -> dict[str, Any]:
        days = params.get("days", 7)
        duration_minutes = params.get("duration_minutes", 60)
        start_hour = params.get("start_hour", 9)
        end_hour = params.get("end_hour", 17)
        calendar_id = params.get("calendar_id", "primary")

        # Get all events in the window
        events_result = await self._list_events({
            "days": days, "calendar_id": calendar_id, "max_results": 100,
        })
        if "error" in events_result:
            return events_result

        # Build busy blocks
        busy: list[tuple[datetime, datetime]] = []
        for e in events_result.get("events", []):
            try:
                s = datetime.fromisoformat(e["start"].replace("Z", "+00:00"))
                en = datetime.fromisoformat(e["end"].replace("Z", "+00:00"))
                busy.append((s, en))
            except (ValueError, KeyError):
                continue

        busy.sort(key=lambda x: x[0])

        # Find free slots
        now = datetime.now(timezone.utc)
        free_slots: list[dict[str, str]] = []
        duration = timedelta(minutes=duration_minutes)

        for day_offset in range(days):
            day = now + timedelta(days=day_offset)
            day_start = day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=end_hour, minute=0, second=0, microsecond=0)

            if day_start < now:
                day_start = now

            cursor = day_start
            for bs, be in busy:
                if be <= day_start or bs >= day_end:
                    continue
                if cursor + duration <= bs:
                    free_slots.append({
                        "start": cursor.isoformat(),
                        "end": bs.isoformat(),
                    })
                cursor = max(cursor, be)

            if cursor + duration <= day_end:
                free_slots.append({
                    "start": cursor.isoformat(),
                    "end": day_end.isoformat(),
                })

        return {
            "duration_minutes": duration_minutes,
            "days_checked": days,
            "free_slots": free_slots[:20],
        }

    async def _list_calendars(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service.calendarList().list().execute()
            calendars = result.get("items", [])
            return {
                "count": len(calendars),
                "calendars": [
                    {
                        "id": c.get("id"),
                        "summary": c.get("summary"),
                        "primary": c.get("primary", False),
                        "access_role": c.get("accessRole"),
                    }
                    for c in calendars
                ],
            }
        except Exception as exc:
            return {"error": str(exc)}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {
                "name": "gcal_list_events",
                "description": "List upcoming calendar events.",
                "parameters": {"type": "object", "properties": {
                    "days": {"type": "integer", "description": "Number of days ahead (default 7)"},
                    "query": {"type": "string", "description": "Search query to filter events"},
                    "max_results": {"type": "integer", "description": "Max events (default 20)"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                }},
            }},
            {"type": "function", "function": {
                "name": "gcal_create_event",
                "description": "Create a new calendar event.",
                "parameters": {"type": "object", "properties": {
                    "summary": {"type": "string", "description": "Event title"},
                    "start": {"type": "string", "description": "Start time ISO 8601 (e.g. 2026-04-07T10:00:00-05:00)"},
                    "end": {"type": "string", "description": "End time ISO 8601"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails"},
                    "timezone": {"type": "string", "description": "Timezone (default: America/Chicago)"},
                }, "required": ["summary", "start", "end"]},
            }},
            {"type": "function", "function": {
                "name": "gcal_delete_event",
                "description": "Delete a calendar event.",
                "parameters": {"type": "object", "properties": {
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string"},
                }, "required": ["event_id"]},
            }},
            {"type": "function", "function": {
                "name": "gcal_find_free_time",
                "description": "Find available time slots in the calendar.",
                "parameters": {"type": "object", "properties": {
                    "days": {"type": "integer", "description": "Days to check (default 7)"},
                    "duration_minutes": {"type": "integer", "description": "Meeting duration (default 60)"},
                    "start_hour": {"type": "integer", "description": "Working day start (default 9)"},
                    "end_hour": {"type": "integer", "description": "Working day end (default 17)"},
                }},
            }},
            {"type": "function", "function": {
                "name": "gcal_list_calendars",
                "description": "List all calendars accessible to the user.",
                "parameters": {"type": "object", "properties": {}},
            }},
        ]
