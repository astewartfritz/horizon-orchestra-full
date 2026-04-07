"""
awareness.py — Ambient awareness layer for MILES.

Gathers calendar, email, task, weather, and time context and surfaces
urgent items requiring the user's attention.
"""
from __future__ import annotations

__all__ = [
    "AwarenessState",
    "UrgentItem",
    "AmbientAwareness",
]

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AwarenessState:
    """Complete snapshot of the user's ambient environment."""

    calendar_events: list[dict[str, Any]] = field(default_factory=list)
    unread_emails: int = 0
    urgent_emails: list[dict[str, Any]] = field(default_factory=list)
    open_tasks: list[dict[str, Any]] = field(default_factory=list)
    current_time: str = ""         # ISO-8601 formatted
    time_of_day: str = ""          # "morning" | "afternoon" | "evening" | "night"
    day_of_week: str = ""          # "Monday" … "Sunday"
    weather: str = ""
    custom: dict[str, Any] = field(default_factory=dict)


@dataclass
class UrgentItem:
    """An item that requires prompt user attention."""

    source: str          # "email" | "calendar" | "task"
    title: str
    urgency_reason: str
    action_needed: str
    deadline: str        # ISO-8601 or human-readable


# ---------------------------------------------------------------------------
# AmbientAwareness
# ---------------------------------------------------------------------------

_URGENCY_KEYWORDS = frozenset([
    "urgent", "urgently", "asap", "as soon as possible",
    "immediately", "critical", "blocker", "blocking", "p0", "p1",
    "emergency", "help needed", "action required",
])

_MORNING_HOURS = range(5, 12)
_AFTERNOON_HOURS = range(12, 17)
_EVENING_HOURS = range(17, 21)


class AmbientAwareness:
    """
    Gathers ambient context from all connected services and presents
    a unified :class:`AwarenessState` for injection into agent prompts.
    """

    def __init__(
        self,
        connectors: dict[str, Any],
        memory_manager: Any,
        router: Any,
        user_id: str,
        timezone_str: str = "America/Chicago",
    ) -> None:
        self._connectors = connectors
        self._memory = memory_manager
        self._router = router
        self._user_id = user_id
        self._tz = ZoneInfo(timezone_str)
        logger.info(
            "AmbientAwareness initialised for user=%s timezone=%s connectors=%s",
            user_id,
            timezone_str,
            list(connectors.keys()),
        )

    # ------------------------------------------------------------------
    # Core scan
    # ------------------------------------------------------------------

    async def scan(self) -> AwarenessState:
        """
        Concurrently gather all context sources and return a unified
        :class:`AwarenessState`.
        """
        now = datetime.now(tz=self._tz)

        (
            calendar_events,
            (unread_emails, urgent_emails),
            open_tasks,
            weather,
        ) = await asyncio.gather(
            self._fetch_calendar(now),
            self._fetch_email(),
            self._fetch_tasks(),
            self._fetch_weather(),
        )

        time_of_day = self._classify_time(now.hour)
        state = AwarenessState(
            calendar_events=calendar_events,
            unread_emails=unread_emails,
            urgent_emails=urgent_emails,
            open_tasks=open_tasks,
            current_time=now.isoformat(),
            time_of_day=time_of_day,
            day_of_week=now.strftime("%A"),
            weather=weather,
        )
        logger.info(
            "AwarenessState: events=%d unread=%d tasks=%d time_of_day=%s",
            len(calendar_events),
            unread_emails,
            len(open_tasks),
            time_of_day,
        )
        return state

    # ------------------------------------------------------------------
    # Derived views
    # ------------------------------------------------------------------

    async def get_briefing_context(self) -> str:
        """
        Return a compact, pre-formatted context block suitable for
        injecting into LLM agent prompts.
        """
        state = await self.scan()
        lines: list[str] = [
            f"## Ambient Context ({state.current_time})",
            f"Day: {state.day_of_week}, Time of day: {state.time_of_day}",
            f"Weather: {state.weather or 'unavailable'}",
            "",
            f"### Calendar — today ({len(state.calendar_events)} events)",
        ]
        for evt in state.calendar_events[:5]:
            title = evt.get("title") or evt.get("summary", "Untitled")
            start = evt.get("start", "")
            lines.append(f"  - {start}: {title}")
        if not state.calendar_events:
            lines.append("  (no events)")

        lines += [
            "",
            f"### Email — {state.unread_emails} unread",
        ]
        for email in state.urgent_emails[:3]:
            subj = email.get("subject", "No subject")
            sender = email.get("from", "Unknown")
            lines.append(f"  - [URGENT] From {sender}: {subj}")

        lines += [
            "",
            f"### Open Tasks ({len(state.open_tasks)})",
        ]
        for task in state.open_tasks[:5]:
            task_title = task.get("title") or task.get("name", "Untitled")
            due = task.get("due") or task.get("due_date", "")
            lines.append(f"  - {task_title}" + (f" (due {due})" if due else ""))
        if not state.open_tasks:
            lines.append("  (no open tasks)")

        return "\n".join(lines)

    async def detect_urgency(self) -> list[UrgentItem]:
        """
        Identify items requiring immediate attention:

        * Emails containing urgency keywords
        * Calendar meetings starting within 30 minutes
        * Tasks that are overdue
        """
        state = await self.scan()
        now_iso = state.current_time
        urgent: list[UrgentItem] = []

        # Urgent emails
        for email in state.urgent_emails:
            urgent.append(
                UrgentItem(
                    source="email",
                    title=email.get("subject", "No subject"),
                    urgency_reason="Contains urgency keywords or flagged as important",
                    action_needed="Read and respond",
                    deadline="ASAP",
                )
            )

        # Calendar meetings starting within 30 minutes
        now_dt = datetime.fromisoformat(now_iso)
        for evt in state.calendar_events:
            start_str = evt.get("start", "")
            if not start_str:
                continue
            try:
                start_dt = _parse_dt(start_str, self._tz)
                diff_min = (start_dt - now_dt).total_seconds() / 60
                if 0 <= diff_min <= 30:
                    urgent.append(
                        UrgentItem(
                            source="calendar",
                            title=evt.get("title") or evt.get("summary", "Meeting"),
                            urgency_reason=f"Starts in {int(diff_min)} minutes",
                            action_needed="Prepare and join",
                            deadline=start_str,
                        )
                    )
            except (ValueError, TypeError, OverflowError):
                continue

        # Overdue tasks
        for task in state.open_tasks:
            due_str = task.get("due") or task.get("due_date", "")
            if not due_str:
                continue
            try:
                due_dt = _parse_dt(due_str, self._tz)
                if due_dt < now_dt:
                    urgent.append(
                        UrgentItem(
                            source="task",
                            title=task.get("title") or task.get("name", "Task"),
                            urgency_reason="Past due date",
                            action_needed="Complete or reschedule",
                            deadline=due_str,
                        )
                    )
            except (ValueError, TypeError, OverflowError):
                continue

        logger.info("detect_urgency found %d urgent items", len(urgent))
        return urgent

    async def suggest_from_awareness(self, state: AwarenessState) -> list[str]:
        """
        Use the LLM to derive actionable suggestions from the current
        :class:`AwarenessState`.
        """
        context = _state_to_text(state)
        prompt = f"""You are a proactive AI assistant (MILES). Based on the user's
current environment and schedule, suggest 3-5 specific, actionable things the user
should focus on or do right now.

Environment snapshot:
{context}

Return ONLY a JSON array of suggestion strings.
Example: ["Review the agenda for your 2 PM meeting", "Follow up on John's email"]
"""
        try:
            resp = await self._router.chat(
                messages=[{"role": "user", "content": prompt}],
                model="kimi-k2.5",
                max_tokens=400,
            )
            raw = _extract_content(resp)
            import json as _json, re as _re
            cleaned = _re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
            data = _json.loads(cleaned)
            if isinstance(data, list):
                return [str(s) for s in data[:5]]
        except Exception as exc:  # noqa: BLE001
            logger.error("suggest_from_awareness LLM call failed: %s", exc)
        return []

    # ------------------------------------------------------------------
    # Private data-fetching helpers
    # ------------------------------------------------------------------

    async def _fetch_calendar(self, now: datetime) -> list[dict[str, Any]]:
        """Fetch today's calendar events from the gcal connector if available."""
        gcal = self._connectors.get("gcal") or self._connectors.get("google_calendar")
        if gcal is None:
            logger.debug("No gcal connector — skipping calendar fetch")
            return []
        try:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
            events = await _call_connector(
                gcal,
                "list_events",
                time_min=today_start,
                time_max=today_end,
                max_results=20,
            )
            return events if isinstance(events, list) else []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Calendar fetch failed: %s", exc)
            return []

    async def _fetch_email(self) -> tuple[int, list[dict[str, Any]]]:
        """Fetch unread count and urgent emails from the Gmail connector."""
        gmail = self._connectors.get("gmail")
        if gmail is None:
            logger.debug("No gmail connector — skipping email fetch")
            return 0, []
        try:
            result = await _call_connector(
                gmail,
                "search_email",
                query="is:unread",
                max_results=50,
            )
            emails = result if isinstance(result, list) else []
            unread_count = len(emails)
            urgent = [
                e for e in emails
                if _is_urgent_email(e)
            ]
            return unread_count, urgent
        except Exception as exc:  # noqa: BLE001
            logger.warning("Email fetch failed: %s", exc)
            return 0, []

    async def _fetch_tasks(self) -> list[dict[str, Any]]:
        """Fetch open tasks from Linear, Jira, or Monday connector."""
        for key in ("linear", "jira", "monday"):
            connector = self._connectors.get(key)
            if connector is None:
                continue
            try:
                tasks = await _call_connector(
                    connector,
                    "list_tasks",
                    status="open",
                    assigned_to="me",
                    max_results=30,
                )
                return tasks if isinstance(tasks, list) else []
            except Exception as exc:  # noqa: BLE001
                logger.warning("Task fetch from %s failed: %s", key, exc)
        return []

    async def _fetch_weather(self) -> str:
        """Use web search to get current weather conditions."""
        try:
            # Lazy import to avoid circular deps in non-web environments
            from orchestra.tools.search import web_search  # type: ignore[import]
            results = await web_search("current weather conditions today")
            if results:
                return str(results[0].get("snippet", ""))[:200]
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("Weather fetch via search failed: %s", exc)
        return ""

    @staticmethod
    def _classify_time(hour: int) -> str:
        if hour in _MORNING_HOURS:
            return "morning"
        if hour in _AFTERNOON_HOURS:
            return "afternoon"
        if hour in _EVENING_HOURS:
            return "evening"
        return "night"


# ---------------------------------------------------------------------------
# Utilities (private)
# ---------------------------------------------------------------------------


def _is_urgent_email(email: dict[str, Any]) -> bool:
    text = " ".join([
        str(email.get("subject", "")),
        str(email.get("snippet", "")),
        str(email.get("body_preview", "")),
    ]).lower()
    return any(kw in text for kw in _URGENCY_KEYWORDS)


def _state_to_text(state: AwarenessState) -> str:
    lines = [
        f"Time: {state.current_time} ({state.time_of_day}, {state.day_of_week})",
        f"Weather: {state.weather or 'N/A'}",
        f"Unread emails: {state.unread_emails}  Urgent: {len(state.urgent_emails)}",
        f"Calendar events today: {len(state.calendar_events)}",
        f"Open tasks: {len(state.open_tasks)}",
    ]
    for evt in state.calendar_events[:3]:
        lines.append(f"  - Event: {evt.get('summary') or evt.get('title', 'Untitled')} @ {evt.get('start', '?')}")
    for t in state.open_tasks[:3]:
        lines.append(f"  - Task: {t.get('name') or t.get('title', 'Untitled')}")
    return "\n".join(lines)


def _extract_content(resp: Any) -> str:
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return resp.get("content", "") or ""
    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        pass
    try:
        return resp.content or ""
    except AttributeError:
        return str(resp)


def _parse_dt(value: str, tz: Any) -> datetime:
    """Parse an ISO-8601 string into a timezone-aware datetime."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


async def _call_connector(connector: Any, method: str, **kwargs: Any) -> Any:
    """
    Invoke a connector method that may be sync or async.
    Tries ``connector.<method>(**kwargs)`` first, then
    ``connector.call(method, **kwargs)``.
    """
    fn = getattr(connector, method, None)
    if fn is not None:
        result = fn(**kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result
    # Generic call interface
    fn = getattr(connector, "call", None)
    if fn is not None:
        result = fn(method, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result
    raise AttributeError(f"Connector has no method '{method}' or 'call'")
