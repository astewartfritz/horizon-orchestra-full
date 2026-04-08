"""Threat Intelligence — Live threat-pattern management and auto-update.

Maintains a database of known attack patterns, injection techniques,
and adversarial strategies.  New patterns can be ingested from:

    * Local YAML/JSON threat feeds
    * Remote HTTP endpoints (auto-update on a configurable interval)
    * Manual additions via the API

When new patterns are ingested, they are automatically pushed to the
:class:`BeyondGuardrails` instance so detection is updated without
restart.

Beyond NemoClaw: NemoClaw's detection patterns are static and baked
in at build time.  This system supports live updates, pattern scoring,
TTL-based expiry, and structured metadata for every threat.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

__all__ = [
    "ThreatPattern",
    "ThreatFeed",
    "ThreatIntelligence",
]

log = logging.getLogger("orchestra.guardian.threat_intelligence")


# ---------------------------------------------------------------------------
# ThreatPattern
# ---------------------------------------------------------------------------

@dataclass
class ThreatPattern:
    """A single threat pattern with metadata.

    Attributes
    ----------
    pattern_id : str
        Unique identifier (auto-generated if not provided).
    pattern : str
        Regex pattern string for detection.
    category : str
        Attack category: ``injection``, ``jailbreak``, ``exfiltration``,
        ``encoding``, ``tool_abuse``, ``dos``, ``supply_chain``.
    severity : str
        ``low``, ``medium``, ``high``, ``critical``.
    language : str
        ISO 639-1 code or ``"*"`` for language-agnostic.
    description : str
        Human-readable explanation of the threat.
    source : str
        Where the pattern was obtained.
    confidence : float
        Expected true-positive rate (0.0–1.0).
    added_at : float
        Timestamp when ingested.
    ttl_hours : float
        Time-to-live in hours.  ``0`` = never expires.
    active : bool
        Whether the pattern is currently active.
    tags : list[str]
        Free-form tags for filtering.
    """

    pattern_id: str = ""
    pattern: str = ""
    category: str = "injection"
    severity: str = "medium"
    language: str = "*"
    description: str = ""
    source: str = "manual"
    confidence: float = 0.8
    added_at: float = 0.0
    ttl_hours: float = 0.0
    active: bool = True
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.pattern_id:
            self.pattern_id = uuid.uuid4().hex[:12]
        if not self.added_at:
            self.added_at = time.time()

    @property
    def expired(self) -> bool:
        """Return ``True`` if the pattern has expired."""
        if self.ttl_hours <= 0:
            return False
        return time.time() > self.added_at + self.ttl_hours * 3600

    def to_dict(self) -> dict[str, Any]:
        """Serialise to dict."""
        return {
            "pattern_id": self.pattern_id,
            "pattern": self.pattern,
            "category": self.category,
            "severity": self.severity,
            "language": self.language,
            "description": self.description,
            "source": self.source,
            "confidence": self.confidence,
            "added_at": self.added_at,
            "ttl_hours": self.ttl_hours,
            "active": self.active,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThreatPattern":
        """Deserialise from dict."""
        return cls(
            pattern_id=data.get("pattern_id", ""),
            pattern=data.get("pattern", ""),
            category=data.get("category", "injection"),
            severity=data.get("severity", "medium"),
            language=data.get("language", "*"),
            description=data.get("description", ""),
            source=data.get("source", "unknown"),
            confidence=data.get("confidence", 0.8),
            added_at=data.get("added_at", 0.0),
            ttl_hours=data.get("ttl_hours", 0.0),
            active=data.get("active", True),
            tags=data.get("tags", []),
        )


# ---------------------------------------------------------------------------
# ThreatFeed
# ---------------------------------------------------------------------------

@dataclass
class ThreatFeed:
    """Configuration for a threat intelligence feed.

    Attributes
    ----------
    feed_id : str
        Unique identifier for this feed.
    name : str
        Human-readable name.
    url : str
        URL to fetch patterns from (JSON).  Empty for local-only feeds.
    enabled : bool
        Whether auto-update should poll this feed.
    interval_hours : float
        Polling interval in hours.
    last_updated : float
        Timestamp of last successful update.
    patterns_count : int
        Number of patterns currently loaded from this feed.
    """

    feed_id: str = ""
    name: str = ""
    url: str = ""
    enabled: bool = True
    interval_hours: float = 6.0
    last_updated: float = 0.0
    patterns_count: int = 0

    def __post_init__(self) -> None:
        if not self.feed_id:
            self.feed_id = uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# ThreatIntelligence
# ---------------------------------------------------------------------------

class ThreatIntelligence:
    """Real-time threat intelligence for agent security.

    Manages a database of :class:`ThreatPattern` objects and supports:

        * Manual pattern addition / removal.
        * Bulk import from JSON files or remote feeds.
        * Auto-update via an asyncio background task.
        * Pattern expiry (TTL-based).
        * Push to :class:`BeyondGuardrails` on ingest.

    Parameters
    ----------
    guardrails : object, optional
        A :class:`BeyondGuardrails` instance.  New patterns are
        automatically pushed via ``add_injection_pattern()``.
    on_update : callable, optional
        ``async (count: int)`` called after each successful update.
    """

    def __init__(
        self,
        guardrails: Any = None,
        on_update: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._patterns: dict[str, ThreatPattern] = {}
        self._feeds: dict[str, ThreatFeed] = {}
        self._guardrails = guardrails
        self._on_update = on_update
        self._auto_update_task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()

        # Built-in default feed (local patterns, always present)
        default_feed = ThreatFeed(
            feed_id="builtin",
            name="Built-in patterns",
            url="",
            enabled=True,
            interval_hours=0,
        )
        self._feeds[default_feed.feed_id] = default_feed

    # -- pattern management -------------------------------------------------

    async def add_pattern(self, pattern: ThreatPattern) -> str:
        """Add a single pattern.  Returns the ``pattern_id``."""
        async with self._lock:
            self._patterns[pattern.pattern_id] = pattern
            log.info(
                "Added threat pattern %s: %s [%s/%s]",
                pattern.pattern_id, pattern.description[:50],
                pattern.category, pattern.severity,
            )

        # Push to guardrails
        if self._guardrails and pattern.category == "injection" and pattern.active:
            try:
                await self._guardrails.add_injection_pattern(
                    pattern.pattern,
                    description=pattern.description,
                    language=pattern.language,
                )
            except Exception:
                log.exception("Failed to push pattern to guardrails")

        return pattern.pattern_id

    async def add_patterns(self, patterns: Sequence[ThreatPattern]) -> int:
        """Add multiple patterns.  Returns count added."""
        count = 0
        for p in patterns:
            await self.add_pattern(p)
            count += 1
        return count

    async def remove_pattern(self, pattern_id: str) -> bool:
        """Remove a pattern by ID.  Returns ``True`` if found."""
        async with self._lock:
            removed = self._patterns.pop(pattern_id, None)
        return removed is not None

    async def deactivate_pattern(self, pattern_id: str) -> bool:
        """Set a pattern to inactive.  Returns ``True`` if found."""
        async with self._lock:
            p = self._patterns.get(pattern_id)
            if p:
                p.active = False
                return True
        return False

    def get_pattern(self, pattern_id: str) -> Optional[ThreatPattern]:
        """Return a single pattern by ID."""
        return self._patterns.get(pattern_id)

    def get_latest_patterns(
        self,
        since: Optional[float] = None,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[ThreatPattern]:
        """Return patterns matching the given filters, newest first."""
        result: list[ThreatPattern] = []
        for p in sorted(self._patterns.values(), key=lambda x: x.added_at, reverse=True):
            if active_only and not p.active:
                continue
            if active_only and p.expired:
                continue
            if since and p.added_at < since:
                continue
            if category and p.category != category:
                continue
            if severity and p.severity != severity:
                continue
            result.append(p)
            if len(result) >= limit:
                break
        return result

    # -- feed management ----------------------------------------------------

    async def add_feed(self, feed: ThreatFeed) -> str:
        """Register a threat feed.  Returns ``feed_id``."""
        async with self._lock:
            self._feeds[feed.feed_id] = feed
        log.info("Registered feed: %s (%s)", feed.name, feed.url or "local")
        return feed.feed_id

    async def remove_feed(self, feed_id: str) -> bool:
        """Remove a threat feed.  Returns ``True`` if found."""
        async with self._lock:
            removed = self._feeds.pop(feed_id, None)
        return removed is not None

    def list_feeds(self) -> list[ThreatFeed]:
        """Return all registered feeds."""
        return list(self._feeds.values())

    # -- update (local & remote) --------------------------------------------

    async def update(self) -> int:
        """Fetch latest patterns from all enabled feeds.  Returns count added.

        For feeds with a URL, attempts an HTTP fetch using ``urllib``
        (stdlib).  For local feeds, this is a no-op unless patterns are
        loaded via :meth:`load_from_file`.
        """
        total = 0
        for feed in self._feeds.values():
            if not feed.enabled or not feed.url:
                continue
            try:
                count = await self._fetch_feed(feed)
                feed.last_updated = time.time()
                feed.patterns_count += count
                total += count
                log.info(
                    "Updated feed %s: +%d patterns", feed.name, count
                )
            except Exception:
                log.exception("Failed to update feed %s", feed.name)

        # Expire old patterns
        expired = await self._expire_patterns()
        if expired:
            log.info("Expired %d patterns", expired)

        if self._on_update and total:
            try:
                await self._on_update(total)
            except Exception:
                log.exception("on_update callback failed")

        return total

    async def _fetch_feed(self, feed: ThreatFeed) -> int:
        """Fetch patterns from a remote feed URL."""
        import urllib.request

        loop = asyncio.get_event_loop()

        def _do_fetch() -> bytes:
            req = urllib.request.Request(
                feed.url,
                headers={"User-Agent": "HorizonOrchestra-ThreatIntel/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()

        try:
            data = await loop.run_in_executor(None, _do_fetch)
            patterns_data = json.loads(data)

            if isinstance(patterns_data, dict):
                patterns_data = patterns_data.get("patterns", [])

            count = 0
            for pd in patterns_data:
                tp = ThreatPattern.from_dict(pd)
                tp.source = feed.name
                await self.add_pattern(tp)
                count += 1
            return count
        except Exception:
            log.exception("HTTP fetch failed for %s", feed.url)
            return 0

    async def _expire_patterns(self) -> int:
        """Remove expired patterns.  Returns count removed."""
        async with self._lock:
            expired_ids = [
                pid for pid, p in self._patterns.items() if p.expired
            ]
            for pid in expired_ids:
                del self._patterns[pid]
        return len(expired_ids)

    # -- file import --------------------------------------------------------

    async def load_from_file(self, path: str) -> int:
        """Load patterns from a JSON or YAML file.  Returns count loaded."""
        if not os.path.exists(path):
            log.warning("Threat file not found: %s", path)
            return 0

        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()

        # Try JSON first
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try YAML
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(raw)
            except ImportError:
                log.warning("pyyaml not available; cannot parse %s", path)
                return 0
            except Exception:
                log.exception("Failed to parse %s", path)
                return 0

        if isinstance(data, dict):
            data = data.get("patterns", [])

        count = 0
        for item in data:
            tp = ThreatPattern.from_dict(item)
            tp.source = f"file:{os.path.basename(path)}"
            await self.add_pattern(tp)
            count += 1

        log.info("Loaded %d patterns from %s", count, path)
        return count

    # -- auto-update --------------------------------------------------------

    async def start_auto_update(self, interval_hours: float = 6.0) -> None:
        """Start a background task that periodically updates all feeds.

        Parameters
        ----------
        interval_hours : float
            How often to poll feeds (default: every 6 hours).
        """
        if self._auto_update_task and not self._auto_update_task.done():
            log.warning("Auto-update already running")
            return

        async def _loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_hours * 3600)
                    count = await self.update()
                    if count:
                        log.info("Auto-update: +%d patterns", count)
                except asyncio.CancelledError:
                    break
                except Exception:
                    log.exception("Auto-update cycle failed")

        self._auto_update_task = asyncio.create_task(_loop())
        log.info("Started auto-update (interval=%.1fh)", interval_hours)

    async def stop_auto_update(self) -> None:
        """Stop the auto-update background task."""
        if self._auto_update_task and not self._auto_update_task.done():
            self._auto_update_task.cancel()
            try:
                await self._auto_update_task
            except asyncio.CancelledError:
                pass
            self._auto_update_task = None
            log.info("Stopped auto-update")

    # -- statistics ---------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics."""
        by_category: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_source: dict[str, int] = {}
        active = 0
        expired = 0

        for p in self._patterns.values():
            by_category[p.category] = by_category.get(p.category, 0) + 1
            by_severity[p.severity] = by_severity.get(p.severity, 0) + 1
            by_source[p.source] = by_source.get(p.source, 0) + 1
            if p.active and not p.expired:
                active += 1
            if p.expired:
                expired += 1

        return {
            "total_patterns": len(self._patterns),
            "active_patterns": active,
            "expired_patterns": expired,
            "feeds": len(self._feeds),
            "by_category": by_category,
            "by_severity": by_severity,
            "by_source": by_source,
            "auto_update_running": (
                self._auto_update_task is not None
                and not self._auto_update_task.done()
            ),
        }

    # -- export -------------------------------------------------------------

    async def export_patterns(self, path: str) -> int:
        """Export all patterns to a JSON file.  Returns count."""
        patterns = [p.to_dict() for p in self._patterns.values()]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"patterns": patterns}, fh, indent=2, default=str)
        return len(patterns)

    def __repr__(self) -> str:
        return (
            f"<ThreatIntelligence patterns={len(self._patterns)} "
            f"feeds={len(self._feeds)}>"
        )
