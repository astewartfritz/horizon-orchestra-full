from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CalendarEvent:
    summary: str
    start: str
    end: str
    description: str = ""
    location: str = ""
    attendees: list[str] = field(default_factory=list)
    source: str = ""


class CalendarIntegration:
    def __init__(self, calendar_dir: str = ".agent-calendar"):
        self.calendar_dir = Path(calendar_dir)
        self.calendar_dir.mkdir(parents=True, exist_ok=True)

    def add_event(self, event: CalendarEvent) -> str:
        events = self._load_events()
        events.append(event)
        self._save_events(events)
        return event.summary

    def list_events(self, date: Optional[str] = None) -> list[CalendarEvent]:
        events = self._load_events()
        if date:
            return [e for e in events if e.start.startswith(date)]
        today = datetime.date.today().isoformat()
        return [e for e in events if e.start >= today]

    def today(self) -> list[CalendarEvent]:
        today = datetime.date.today().isoformat()
        return self.list_events(today)

    def parse_natural_language(self, text: str) -> Optional[CalendarEvent]:
        date_patterns = [
            (r"today", datetime.date.today()),
            (r"tomorrow", datetime.date.today() + datetime.timedelta(days=1)),
            (r"next monday", self._next_weekday(0)),
            (r"next tuesday", self._next_weekday(1)),
            (r"next wednesday", self._next_weekday(2)),
            (r"next thursday", self._next_weekday(3)),
            (r"next friday", self._next_weekday(4)),
        ]

        matched_date = datetime.date.today()
        text_lower = text.lower()
        for pattern, date_val in date_patterns:
            if pattern in text_lower:
                matched_date = date_val
                break

        time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text_lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            ampm = time_match.group(3)
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            start_time = datetime.datetime(matched_date.year, matched_date.month, matched_date.day, hour, minute)
            end_time = start_time + datetime.timedelta(hours=1)
        else:
            start_time = datetime.datetime(matched_date.year, matched_date.month, matched_date.day, 9, 0)
            end_time = start_time + datetime.timedelta(hours=1)

        title = text_lower
        for word in ["add", "create", "schedule", "event", "meeting", "appointment", "for", "on", "at", "tomorrow", "today"]:
            title = title.replace(word, "")
        title = title.strip().title()
        if not title:
            title = "Event"

        return CalendarEvent(
            summary=title,
            start=start_time.isoformat(),
            end=end_time.isoformat(),
        )

    def _load_events(self) -> list[CalendarEvent]:
        path = self.calendar_dir / "events.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [CalendarEvent(**e) for e in data]
        except (json.JSONDecodeError, Exception):
            return []

    def _save_events(self, events: list[CalendarEvent]) -> None:
        path = self.calendar_dir / "events.json"
        data = [{
            "summary": e.summary, "start": e.start, "end": e.end,
            "description": e.description, "location": e.location,
            "attendees": e.attendees, "source": e.source,
        } for e in events]
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _next_weekday(self, weekday: int) -> datetime.date:
        today = datetime.date.today()
        days_ahead = weekday - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return today + datetime.timedelta(days=days_ahead)
