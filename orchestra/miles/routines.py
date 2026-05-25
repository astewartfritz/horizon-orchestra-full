"""
routines.py — Personal assistant routines for MILES.

Provides morning briefings, evening summaries, and smart reminders
driven by the AmbientAwareness layer and session memory.
"""
from __future__ import annotations

__all__ = [
    "RoutineConfig",
    "Briefing",
    "Summary",
    "Reminder",
    "MorningBriefing",
    "DailySummary",
    "SmartReminder",
    "RoutineManager",
]

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from orchestra.miles.awareness import AmbientAwareness, AwarenessState, UrgentItem
from orchestra.miles._utils import extract_content, router_chat, safe_json_loads

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RoutineConfig:
    """User-specific routine configuration."""

    user_id: str
    timezone: str = "America/Chicago"
    morning_briefing_time: str = "08:00"  # HH:MM
    evening_summary_time: str = "18:00"   # HH:MM
    enable_smart_reminders: bool = True


# ---------------------------------------------------------------------------
# Briefing dataclass
# ---------------------------------------------------------------------------


@dataclass
class Briefing:
    """Output of the morning briefing generator."""

    summary: str
    calendar: list[dict[str, Any]] = field(default_factory=list)
    priority_emails: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    weather: str = ""
    generated_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Summary dataclass
# ---------------------------------------------------------------------------


@dataclass
class Summary:
    """Output of the daily summary generator."""

    accomplishments: list[str] = field(default_factory=list)
    unfinished: list[str] = field(default_factory=list)
    tomorrow_priorities: list[str] = field(default_factory=list)
    summary_text: str = ""


# ---------------------------------------------------------------------------
# Reminder dataclass
# ---------------------------------------------------------------------------


@dataclass
class Reminder:
    """A smart reminder surfaced to the user."""

    type: str      # "meeting" | "task" | "follow_up" | "pattern"
    title: str
    body: str
    urgency: str   # "low" | "medium" | "high" | "critical"
    action: str    # suggested action for the user
    due_at: str    # ISO-8601 or human-readable


# ---------------------------------------------------------------------------
# Morning Briefing
# ---------------------------------------------------------------------------


class MorningBriefing:
    """Generates a concise morning briefing from ambient context."""

    def __init__(self, router: Any) -> None:
        self._router = router

    async def generate(self, awareness: AmbientAwareness) -> Briefing:
        """
        Scan ambient state and synthesize a morning briefing.

        Returns:
            A :class:`Briefing` with summary text, calendar, emails, tasks,
            weather, and 2–3 focus suggestions.
        """
        logger.info("Generating morning briefing…")
        state = await awareness.scan()

        calendar = state.calendar_events
        priority_emails = state.urgent_emails
        tasks = state.open_tasks
        weather = state.weather

        # Use LLM to produce a natural-language summary
        context_block = _format_briefing_context(state)
        prompt = f"""You are MILES, a proactive personal AI assistant. Generate a
concise, natural, friendly morning briefing for the user.

Current environment:
{context_block}

Structure:
1. One-sentence overview of the day ahead.
2. Key calendar events to be aware of (if any).
3. Priority emails needing attention (if any).
4. Top tasks to focus on today.
5. Two or three specific focus suggestions tailored to today's schedule.

Write in second person ("You have…"). Keep it under 200 words. Be energetic and helpful.
"""
        summary = ""
        suggestions: list[str] = []
        try:
            resp = await router_chat(
                self._router,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
            )
            summary = extract_content(resp).strip()
            # Extract suggestions from LLM response via a second targeted call
            suggestions = await self._generate_suggestions(state)
        except Exception as exc:  # noqa: BLE001
            logger.error("MorningBriefing LLM call failed: %s", exc)
            summary = _fallback_briefing(state)
            suggestions = _fallback_suggestions(state)

        briefing = Briefing(
            summary=summary,
            calendar=calendar,
            priority_emails=priority_emails,
            tasks=tasks,
            suggestions=suggestions,
            weather=weather,
            generated_at=time.time(),
        )
        logger.info("Morning briefing generated: %d chars", len(summary))
        return briefing

    async def _generate_suggestions(self, state: AwarenessState) -> list[str]:
        """Ask the LLM for 2-3 focus area suggestions."""
        ctx = _format_briefing_context(state)
        prompt = f"""Based on this person's schedule and context:
{ctx}

List exactly 2-3 specific focus areas or tasks they should prioritise today.
Return ONLY a JSON array of strings.
"""
        try:
            resp = await router_chat(
                self._router,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            raw = extract_content(resp)
            data = safe_json_loads(raw, default=[])
            if isinstance(data, list):
                return [str(s) for s in data[:3]]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Suggestion generation failed: %s", exc)
        return _fallback_suggestions(state)


# ---------------------------------------------------------------------------
# Daily Summary
# ---------------------------------------------------------------------------


class DailySummary:
    """Generates an end-of-day summary from session memory and ambient state."""

    def __init__(self, router: Any) -> None:
        self._router = router

    async def generate(
        self,
        awareness: AmbientAwareness,
        memory_manager: Any,
    ) -> Summary:
        """
        Review the day's work, summarise accomplishments, flag unfinished
        items, and suggest tomorrow's priorities.
        """
        logger.info("Generating daily summary…")
        state = await awareness.scan()
        completed_tasks = await self._fetch_completed_tasks(memory_manager)
        session_history = await self._fetch_session_history(memory_manager)

        context = _format_briefing_context(state)
        history_text = "\n".join(f"- {h}" for h in (session_history or [])[:20])
        completed_text = "\n".join(f"- {t}" for t in (completed_tasks or [])[:20])

        prompt = f"""You are MILES. Generate an end-of-day summary for the user.

Today's environment:
{context}

Completed work today:
{completed_text or "(none recorded)"}

Session activity:
{history_text or "(none recorded)"}

Remaining open tasks:
{chr(10).join("- " + (t.get("title") or t.get("name","Task")) for t in state.open_tasks[:10]) or "(none)"}

Return a JSON object with these exact keys:
  accomplishments     - list[str], bullet-point accomplishments
  unfinished          - list[str], incomplete items that need attention
  tomorrow_priorities - list[str], top 3-5 priorities for tomorrow
  summary_text        - str, 2-3 sentence human-readable summary
"""
        try:
            resp = await router_chat(
                self._router,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
            )
            raw = extract_content(resp)
            data = safe_json_loads(raw, default={})
            return Summary(
                accomplishments=[str(a) for a in data.get("accomplishments", [])],
                unfinished=[str(u) for u in data.get("unfinished", [])],
                tomorrow_priorities=[str(p) for p in data.get("tomorrow_priorities", [])],
                summary_text=str(data.get("summary_text", "")),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("DailySummary LLM call failed: %s", exc)
            unfinished = [
                (t.get("title") or t.get("name", "Task"))
                for t in state.open_tasks[:5]
            ]
            return Summary(
                accomplishments=completed_tasks[:5] if completed_tasks else [],
                unfinished=unfinished,
                tomorrow_priorities=unfinished[:3],
                summary_text="Here's a summary of your day. Some tasks remain open for tomorrow.",
            )

    async def _fetch_completed_tasks(self, memory_manager: Any) -> list[str]:
        try:
            results = await memory_manager.search(
                category="completed_task",
                limit=30,
            )
            return [
                r.get("content") or r.get("title", "Task")
                for r in (results or [])
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug("_fetch_completed_tasks failed: %s", exc)
            return []

    async def _fetch_session_history(self, memory_manager: Any) -> list[str]:
        try:
            results = await memory_manager.search(
                category="session",
                limit=20,
            )
            return [
                r.get("content") or r.get("text", "")
                for r in (results or [])
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug("_fetch_session_history failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Smart Reminder
# ---------------------------------------------------------------------------


class SmartReminder:
    """
    Surface contextual reminders:

    * Upcoming meetings (≤15 min)
    * Approaching task deadlines
    * Email follow-ups
    * Pattern-based ("you usually do X now")
    """

    def __init__(self, router: Any) -> None:
        self._router = router

    async def check(
        self,
        awareness: AmbientAwareness,
        memory_manager: Any,
    ) -> list[Reminder]:
        """Return a list of relevant reminders based on current state."""
        state = await awareness.scan()
        reminders: list[Reminder] = []

        # Meeting reminders
        reminders.extend(await self._meeting_reminders(state))

        # Task deadline reminders
        reminders.extend(await self._task_reminders(state))

        # Follow-up email reminders
        reminders.extend(await self._email_followup_reminders(state, memory_manager))

        # Pattern-based reminders
        reminders.extend(await self._pattern_reminders(state, memory_manager))

        logger.info("SmartReminder generated %d reminders", len(reminders))
        return reminders

    # ------------------------------------------------------------------
    # Reminder generators
    # ------------------------------------------------------------------

    async def _meeting_reminders(self, state: AwarenessState) -> list[Reminder]:
        reminders: list[Reminder] = []
        try:
            now_dt = datetime.fromisoformat(state.current_time)
        except ValueError:
            return reminders

        for evt in state.calendar_events:
            start_str = evt.get("start", "")
            if not start_str:
                continue
            try:
                from zoneinfo import ZoneInfo as _ZI
                tz = _ZI("America/Chicago")
                start_dt = _parse_dt_safe(start_str, tz)
                if start_dt is None:
                    continue
                diff_min = (start_dt - now_dt).total_seconds() / 60
                if 0 < diff_min <= 15:
                    title = evt.get("summary") or evt.get("title", "Meeting")
                    attendees = evt.get("attendees", [])
                    attendee_text = (
                        "with " + ", ".join(
                            a.get("email") or a.get("displayName", "?")
                            for a in attendees[:3]
                        )
                        if attendees else ""
                    )
                    reminders.append(
                        Reminder(
                            type="meeting",
                            title=f"Upcoming: {title}",
                            body=(
                                f"'{title}' starts in {int(diff_min)} minutes"
                                + (f" {attendee_text}" if attendee_text else "")
                                + ". Time to wrap up and prepare."
                            ),
                            urgency="high" if diff_min <= 5 else "medium",
                            action="Join meeting and review agenda",
                            due_at=start_str,
                        )
                    )
            except Exception:  # noqa: BLE001
                continue
        return reminders

    async def _task_reminders(self, state: AwarenessState) -> list[Reminder]:
        reminders: list[Reminder] = []
        try:
            now_dt = datetime.fromisoformat(state.current_time)
        except ValueError:
            return reminders

        for task in state.open_tasks:
            due_str = task.get("due") or task.get("due_date", "")
            if not due_str:
                continue
            try:
                from zoneinfo import ZoneInfo as _ZI
                tz = _ZI("America/Chicago")
                due_dt = _parse_dt_safe(due_str, tz)
                if due_dt is None:
                    continue
                diff_h = (due_dt - now_dt).total_seconds() / 3600
                task_name = task.get("title") or task.get("name", "Task")
                if diff_h < 0:
                    reminders.append(
                        Reminder(
                            type="task",
                            title=f"Overdue: {task_name}",
                            body=f"This task was due {abs(int(diff_h))} hours ago.",
                            urgency="high",
                            action="Complete or reschedule",
                            due_at=due_str,
                        )
                    )
                elif diff_h <= 2:
                    reminders.append(
                        Reminder(
                            type="task",
                            title=f"Due soon: {task_name}",
                            body=f"This task is due in {int(diff_h * 60)} minutes.",
                            urgency="medium",
                            action="Prioritise now",
                            due_at=due_str,
                        )
                    )
            except Exception:  # noqa: BLE001
                continue
        return reminders

    async def _email_followup_reminders(
        self,
        state: AwarenessState,
        memory_manager: Any,
    ) -> list[Reminder]:
        """Suggest following up on emails that were sent but not responded to."""
        reminders: list[Reminder] = []
        try:
            sent_emails = await memory_manager.search(
                category="sent_email",
                limit=20,
            )
        except Exception:  # noqa: BLE001
            return reminders

        for email in (sent_emails or []):
            # Check if a follow-up is needed (sent > 48h ago with no reply recorded)
            sent_at = email.get("sent_at") or email.get("timestamp", 0)
            try:
                sent_ts = float(sent_at)
            except (ValueError, TypeError):
                continue
            age_h = (time.time() - sent_ts) / 3600
            replied = email.get("replied", False) or email.get("has_reply", False)
            if age_h >= 48 and not replied:
                subj = email.get("subject", "Email")
                to = email.get("to", "recipient")
                reminders.append(
                    Reminder(
                        type="follow_up",
                        title=f"Follow up: {subj}",
                        body=(
                            f"You sent an email to {to} about '{subj}' "
                            f"{int(age_h / 24)} day(s) ago with no reply."
                        ),
                        urgency="low",
                        action="Send a follow-up email",
                        due_at="ASAP",
                    )
                )
        return reminders[:3]  # cap follow-up reminders

    async def _pattern_reminders(
        self,
        state: AwarenessState,
        memory_manager: Any,
    ) -> list[Reminder]:
        """Surface pattern-based reminders (e.g. 'you usually exercise now')."""
        reminders: list[Reminder] = []
        try:
            patterns = await memory_manager.search(
                category="workflow",
                limit=20,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("pattern_reminders memory search failed: %s", exc)
            return reminders

        # Ask the LLM to match patterns to the current context
        if not patterns:
            return reminders

        pattern_text = "\n".join(
            f"- trigger='{p.get('trigger','')}' → action='{p.get('action','')}'"
            for p in (patterns or [])[:10]
        )
        prompt = f"""You are MILES. The user has established the following workflow patterns:
{pattern_text}

Current context:
  Day: {state.day_of_week}
  Time of day: {state.time_of_day}
  Current time: {state.current_time}

Which pattern (if any) is most relevant RIGHT NOW? If one applies, return a JSON
object with: type="pattern", title, body, urgency ("low"|"medium"|"high"), action, due_at.
If none apply, return null.
"""
        try:
            resp = await router_chat(
                self._router,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            raw = extract_content(resp).strip()
            data = safe_json_loads(raw)
            if isinstance(data, dict) and data.get("title"):
                reminders.append(
                    Reminder(
                        type=str(data.get("type", "pattern")),
                        title=str(data.get("title", "")),
                        body=str(data.get("body", "")),
                        urgency=str(data.get("urgency", "low")),
                        action=str(data.get("action", "")),
                        due_at=str(data.get("due_at", "now")),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("pattern_reminders LLM call failed: %s", exc)
        return reminders


# ---------------------------------------------------------------------------
# Routine Manager
# ---------------------------------------------------------------------------


class RoutineManager:
    """
    Orchestrates morning briefings, evening summaries, and smart reminders.

    Designed to work with any scheduler that supports ``schedule(cron, fn)``
    or ``add_job(fn, trigger, …)`` semantics.
    """

    def __init__(
        self,
        config: RoutineConfig,
        awareness: AmbientAwareness,
        memory: Any,
        scheduler: Any,
        notifications: Any,
    ) -> None:
        self._config = config
        self._awareness = awareness
        self._memory = memory
        self._scheduler = scheduler
        self._notifications = notifications
        self._morning = None  # type: Optional[MorningBriefing]
        self._evening = None  # type: Optional[DailySummary]
        self._reminders = None  # type: Optional[SmartReminder]
        self._monitor_task: Optional[asyncio.Task[None]] = None
        self._running = False
        logger.info(
            "RoutineManager created for user=%s tz=%s",
            config.user_id,
            config.timezone,
        )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def setup_routines(self) -> None:
        """
        Lazily build helper objects and register timed routines with
        the scheduler.

        Router is obtained from the awareness object's internal router.
        """
        router = self._awareness._router  # type: ignore[attr-defined]
        self._morning = MorningBriefing(router)
        self._evening = DailySummary(router)
        self._reminders = SmartReminder(router)

        tz = ZoneInfo(self._config.timezone)
        morning_h, morning_m = _parse_hhmm(self._config.morning_briefing_time)
        evening_h, evening_m = _parse_hhmm(self._config.evening_summary_time)

        await self._register_scheduled_job(
            fn=self.run_morning,
            hour=morning_h,
            minute=morning_m,
            tz=tz,
            name="morning_briefing",
        )
        await self._register_scheduled_job(
            fn=self.run_evening,
            hour=evening_h,
            minute=evening_m,
            tz=tz,
            name="evening_summary",
        )
        logger.info(
            "Routines registered: morning=%s evening=%s",
            self._config.morning_briefing_time,
            self._config.evening_summary_time,
        )

    async def _register_scheduled_job(
        self,
        fn: Any,
        hour: int,
        minute: int,
        tz: Any,
        name: str,
    ) -> None:
        """Register *fn* with the scheduler at the given time-of-day."""
        if self._scheduler is None:
            logger.warning("No scheduler configured — skipping job registration for '%s'", name)
            return
        try:
            # APScheduler-style
            if hasattr(self._scheduler, "add_job"):
                self._scheduler.add_job(
                    fn,
                    trigger="cron",
                    hour=hour,
                    minute=minute,
                    timezone=tz,
                    id=f"miles_{name}_{self._config.user_id}",
                    replace_existing=True,
                )
            # Generic schedule(cron, fn)
            elif hasattr(self._scheduler, "schedule"):
                await self._scheduler.schedule(
                    f"{minute} {hour} * * *",
                    fn,
                    name=name,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to register scheduled job '%s': %s", name, exc)

    # ------------------------------------------------------------------
    # Routine runners
    # ------------------------------------------------------------------

    async def run_morning(self) -> None:
        """Generate morning briefing and send via notifications."""
        logger.info("Running morning briefing for user=%s", self._config.user_id)
        assert self._morning is not None, "Call setup_routines() first"
        try:
            briefing = await self._morning.generate(self._awareness)
            await self._send_notification(
                title="Good morning! Here's your briefing",
                body=briefing.summary,
                data={"type": "morning_briefing", "briefing": _briefing_to_dict(briefing)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("run_morning failed: %s", exc)

    async def run_evening(self) -> None:
        """Generate evening summary and send via notifications."""
        logger.info("Running evening summary for user=%s", self._config.user_id)
        assert self._evening is not None, "Call setup_routines() first"
        try:
            summary = await self._evening.generate(self._awareness, self._memory)
            await self._send_notification(
                title="End-of-day summary",
                body=summary.summary_text,
                data={"type": "evening_summary", "summary": _summary_to_dict(summary)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("run_evening failed: %s", exc)

    async def check_reminders(self) -> None:
        """Fetch smart reminders and dispatch urgent ones via notifications."""
        if not self._config.enable_smart_reminders:
            return
        assert self._reminders is not None, "Call setup_routines() first"
        try:
            reminders = await self._reminders.check(self._awareness, self._memory)
            urgent = [r for r in reminders if r.urgency in ("high", "critical")]
            for reminder in urgent:
                await self._send_notification(
                    title=reminder.title,
                    body=reminder.body,
                    data={"type": "reminder", "reminder": _reminder_to_dict(reminder)},
                )
            logger.info(
                "check_reminders: %d total, %d sent as urgent",
                len(reminders),
                len(urgent),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("check_reminders failed: %s", exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the reminder monitoring loop (checks every 5 minutes)."""
        if self._running:
            return
        self._running = True
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(),
            name=f"routine-monitor-{self._config.user_id}",
        )
        logger.info("RoutineManager monitoring loop started.")

    def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            logger.info("RoutineManager monitoring loop stopped.")

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        while self._running:
            try:
                await self.check_reminders()
            except Exception as exc:  # noqa: BLE001
                logger.error("monitor_loop iteration error: %s", exc)
            await asyncio.sleep(5 * 60)  # check every 5 minutes

    async def _send_notification(
        self,
        title: str,
        body: str,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        if self._notifications is None:
            logger.info("[notification] %s — %s", title, body[:100])
            return
        try:
            payload = {
                "user_id": self._config.user_id,
                "title": title,
                "body": body,
                "data": data or {},
            }
            fn = getattr(self._notifications, "send", None)
            if fn:
                result = fn(payload)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as exc:  # noqa: BLE001
            logger.error("Notification send failed: %s", exc)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _parse_hhmm(value: str) -> tuple[int, int]:
    """Parse ``"HH:MM"`` string into ``(hour, minute)`` ints."""
    try:
        parts = value.strip().split(":")
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        logger.warning("Invalid time string '%s', defaulting to 08:00", value)
        return 8, 0


def _format_briefing_context(state: AwarenessState) -> str:
    lines = [
        f"Time: {state.current_time} ({state.time_of_day}, {state.day_of_week})",
        f"Weather: {state.weather or 'unavailable'}",
        f"Unread emails: {state.unread_emails}  Urgent: {len(state.urgent_emails)}",
        f"Open tasks: {len(state.open_tasks)}",
        f"Calendar events: {len(state.calendar_events)}",
    ]
    for evt in state.calendar_events[:5]:
        t = evt.get("summary") or evt.get("title", "Untitled")
        s = evt.get("start", "")
        lines.append(f"  - {s}: {t}")
    for email in state.urgent_emails[:3]:
        lines.append(f"  - URGENT EMAIL: {email.get('subject','?')} from {email.get('from','?')}")
    for task in state.open_tasks[:5]:
        name = task.get("title") or task.get("name", "Task")
        due = task.get("due") or task.get("due_date", "")
        lines.append(f"  - TASK: {name}" + (f" (due {due})" if due else ""))
    return "\n".join(lines)


def _fallback_briefing(state: AwarenessState) -> str:
    return (
        f"Good {state.time_of_day}! Today is {state.day_of_week}. "
        f"You have {len(state.calendar_events)} calendar event(s), "
        f"{state.unread_emails} unread email(s), and "
        f"{len(state.open_tasks)} open task(s)."
    )


def _fallback_suggestions(state: AwarenessState) -> list[str]:
    suggestions = []
    if state.urgent_emails:
        suggestions.append(f"Review {len(state.urgent_emails)} urgent email(s)")
    if state.calendar_events:
        first = state.calendar_events[0]
        suggestions.append(f"Prepare for: {first.get('summary') or first.get('title','your first meeting')}")
    if state.open_tasks:
        task = state.open_tasks[0]
        suggestions.append(f"Work on: {task.get('title') or task.get('name','top priority task')}")
    return suggestions[:3]


def _parse_dt_safe(value: str, tz: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt
    except (ValueError, TypeError):
        return None


def _briefing_to_dict(b: Briefing) -> dict[str, Any]:
    return {
        "summary": b.summary,
        "calendar": b.calendar,
        "priority_emails": b.priority_emails,
        "tasks": b.tasks,
        "suggestions": b.suggestions,
        "weather": b.weather,
        "generated_at": b.generated_at,
    }


def _summary_to_dict(s: Summary) -> dict[str, Any]:
    return {
        "accomplishments": s.accomplishments,
        "unfinished": s.unfinished,
        "tomorrow_priorities": s.tomorrow_priorities,
        "summary_text": s.summary_text,
    }


def _reminder_to_dict(r: Reminder) -> dict[str, Any]:
    return {
        "type": r.type,
        "title": r.title,
        "body": r.body,
        "urgency": r.urgency,
        "action": r.action,
        "due_at": r.due_at,
    }
