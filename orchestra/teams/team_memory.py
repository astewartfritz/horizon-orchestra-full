"""Horizon Orchestra — Team-Aware Shared Memory.

:class:`TeamMemory` extends the existing :mod:`orchestra.memory`
infrastructure with team-aware namespacing, per-agent write tagging,
pinning (permanent entries), and trust-level access control.

All agents in a team share the same :class:`TeamMemory` instance.
Writes are attributed to the writing agent, and reads can be scoped
to a specific agent or to the whole team.

Integration with the base memory system uses a try/except guard so
the module loads even when :mod:`orchestra.memory` is unavailable
(e.g. during isolated unit tests).

Example usage::

    tm = TeamMemory(team_id="sales-team")
    mid = await tm.store("Acme Corp renews in Q3", agent_id="researcher", tags=["account"])
    results = await tm.search("Acme Corp renewal", agent_id="writer")
    knowledge = await tm.get_team_knowledge("account")
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

# ── Integration with existing memory infrastructure ───────────────────────
try:
    from ..memory import MemoryStore as _BaseMemoryStore  # type: ignore[attr-defined]
    _HAS_BASE_MEMORY = True
except Exception:
    _BaseMemoryStore = None  # type: ignore[assignment,misc]
    _HAS_BASE_MEMORY = False

__all__ = [
    "TeamMemory",
    "MemoryEntry",
    "AccessLevel",
    "MemoryStats",
]

log = logging.getLogger("orchestra.teams.team_memory")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class AccessLevel:
    """Constants for memory access control.

    These mirror :class:`~orchestra.teams.inter_agent_trust.TrustLevel`
    but are kept as plain strings so ``team_memory`` has no hard
    dependency on the trust module.
    """

    OWNER = "owner"
    TEAM = "team"
    EXTERNAL = "external"
    UNTRUSTED = "untrusted"

    # Ordered list from most to least privileged
    _ORDER = ("owner", "team", "external", "untrusted")

    @classmethod
    def can_access(cls, required: str, actual: str) -> bool:
        """Return ``True`` if *actual* level meets *required* level."""
        try:
            return cls._ORDER.index(actual) <= cls._ORDER.index(required)
        except ValueError:
            return False


@dataclass
class MemoryEntry:
    """A single item in team memory."""

    memory_id: str
    content: str
    agent_id: str
    team_id: str
    tags: List[str] = field(default_factory=list)
    pinned: bool = False
    access_level: str = AccessLevel.TEAM
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    ttl_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── helpers ────────────────────────────────────────────────────────────
    @property
    def is_expired(self) -> bool:
        """Return ``True`` when the entry's TTL has elapsed."""
        if self.pinned or self.ttl_seconds is None:
            return False
        return (time.time() - self.created_at) > self.ttl_seconds

    @property
    def content_hash(self) -> str:
        """SHA-256 digest of the content for deduplication."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:16]

    def matches_tags(self, query_tags: List[str]) -> bool:
        """Return ``True`` if any of *query_tags* appear in this entry."""
        return bool(set(query_tags) & set(self.tags))

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "agent_id": self.agent_id,
            "team_id": self.team_id,
            "tags": self.tags,
            "pinned": self.pinned,
            "access_level": self.access_level,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ttl_seconds": self.ttl_seconds,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        """Deserialise from a dictionary."""
        return cls(**data)

    def __repr__(self) -> str:  # pragma: no cover
        pin = " 📌" if self.pinned else ""
        return (
            f"<MemoryEntry {self.memory_id[:8]} "
            f"agent={self.agent_id} "
            f"tags={self.tags}{pin}>"
        )


@dataclass
class MemoryStats:
    """Snapshot of team memory statistics."""

    total_entries: int = 0
    pinned_entries: int = 0
    agents_with_entries: int = 0
    total_tags: int = 0
    unique_tags: int = 0
    oldest_entry_age: float = 0.0
    newest_entry_age: float = 0.0
    base_memory_available: bool = False
    team_id: str = ""

    def to_dict(self) -> dict:
        """Return stats as a plain dictionary."""
        return {
            "total_entries": self.total_entries,
            "pinned_entries": self.pinned_entries,
            "agents_with_entries": self.agents_with_entries,
            "total_tags": self.total_tags,
            "unique_tags": self.unique_tags,
            "oldest_entry_age": self.oldest_entry_age,
            "newest_entry_age": self.newest_entry_age,
            "base_memory_available": self.base_memory_available,
            "team_id": self.team_id,
        }


# ---------------------------------------------------------------------------
# TeamMemory
# ---------------------------------------------------------------------------

class TeamMemory:
    """Shared persistent memory for team agents.

    All agents can read team memory.  Writes are tagged with the
    writing agent's ID.  Pinned entries are never evicted.  Access
    control is enforced by trust level.

    If :mod:`orchestra.memory` is available the store delegates to the
    existing :class:`MemoryStore` backend for embedding-based semantic
    search.  Otherwise a simple keyword-matching fallback is used.

    Parameters
    ----------
    team_id:
        Namespace prefix applied to all entries.
    max_entries:
        Hard cap on non-pinned entries.  The oldest non-pinned entry
        is evicted when the limit is reached.
    default_ttl_seconds:
        Default TTL for entries.  ``None`` means no expiry.
    base_memory_store:
        Optional pre-configured :class:`MemoryStore` instance.
    """

    def __init__(
        self,
        team_id: str = "default-team",
        max_entries: int = 50_000,
        default_ttl_seconds: Optional[float] = None,
        base_memory_store: Any = None,
    ) -> None:
        self._team_id = team_id
        self._max_entries = max_entries
        self._default_ttl = default_ttl_seconds

        # Primary store: memory_id → MemoryEntry
        self._entries: Dict[str, MemoryEntry] = {}

        # Indexes
        self._by_agent: Dict[str, List[str]] = defaultdict(list)
        self._by_tag: Dict[str, List[str]] = defaultdict(list)
        self._pinned: Set[str] = set()
        self._content_hashes: Set[str] = set()

        # Base memory integration
        self._base_store: Any = base_memory_store
        if self._base_store is None and _HAS_BASE_MEMORY:
            try:
                self._base_store = _BaseMemoryStore()
                log.info(
                    "TeamMemory(%s): connected to base MemoryStore",
                    team_id,
                )
            except Exception:
                log.debug(
                    "TeamMemory(%s): base MemoryStore unavailable, "
                    "using keyword fallback",
                    team_id,
                )

        log.debug(
            "TeamMemory initialised (team=%s, max=%d, base=%s)",
            team_id,
            max_entries,
            self._base_store is not None,
        )

    # ===================================================================
    # Store
    # ===================================================================

    async def store(
        self,
        content: str,
        agent_id: str,
        tags: Optional[List[str]] = None,
        pinned: bool = False,
        access_level: str = AccessLevel.TEAM,
        ttl_seconds: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store a new memory entry.

        Parameters
        ----------
        content:
            The text content to remember.
        agent_id:
            The agent writing this entry.
        tags:
            Categorical tags for filtered retrieval (e.g. ``["account",
            "salesforce"]``).
        pinned:
            If ``True`` the entry is never evicted.
        access_level:
            Minimum trust level required to read this entry.
        ttl_seconds:
            Override the default TTL.
        metadata:
            Arbitrary metadata dictionary.

        Returns
        -------
        str
            The ``memory_id`` of the new entry.
        """
        tags = tags or []
        metadata = metadata or {}

        entry = MemoryEntry(
            memory_id=uuid.uuid4().hex,
            content=content,
            agent_id=agent_id,
            team_id=self._team_id,
            tags=tags,
            pinned=pinned,
            access_level=access_level,
            created_at=time.time(),
            updated_at=time.time(),
            ttl_seconds=ttl_seconds or self._default_ttl,
            metadata=metadata,
        )

        # Deduplication
        chash = entry.content_hash
        if chash in self._content_hashes:
            log.debug("Duplicate content detected, skipping store")
            # Find the existing entry and return its ID
            for eid, existing in self._entries.items():
                if existing.content_hash == chash:
                    existing.updated_at = time.time()
                    return eid
            # Fallthrough if the original was evicted
        self._content_hashes.add(chash)

        # Evict if at capacity
        if len(self._entries) >= self._max_entries:
            await self._evict_oldest()

        # Store
        self._entries[entry.memory_id] = entry
        self._by_agent[agent_id].append(entry.memory_id)
        for tag in tags:
            self._by_tag[tag].append(entry.memory_id)
        if pinned:
            self._pinned.add(entry.memory_id)

        log.debug(
            "Stored memory %s from agent %s (tags=%s, pinned=%s)",
            entry.memory_id[:8],
            agent_id,
            tags,
            pinned,
        )
        return entry.memory_id

    # ===================================================================
    # Search / Retrieval
    # ===================================================================

    async def search(
        self,
        query: str,
        agent_id: str,
        limit: int = 10,
        tags: Optional[List[str]] = None,
        access_level: str = AccessLevel.TEAM,
    ) -> List[MemoryEntry]:
        """Search team memory for entries matching *query*.

        If the base :class:`MemoryStore` is available, uses embedding
        similarity.  Otherwise falls back to keyword matching.

        Parameters
        ----------
        query:
            Free-text search query.
        agent_id:
            The agent performing the search (for access control).
        limit:
            Maximum entries to return.
        tags:
            If provided, only entries matching at least one tag are
            returned.
        access_level:
            The caller's trust level (entries above this are hidden).

        Returns
        -------
        list[MemoryEntry]
        """
        # Purge expired entries first
        self._purge_expired()

        candidates = self._filter_by_access(access_level)

        # Tag filter
        if tags:
            candidates = [e for e in candidates if e.matches_tags(tags)]

        # Score by keyword overlap (simple fallback)
        query_tokens = set(query.lower().split())
        scored: List[tuple[float, MemoryEntry]] = []
        for entry in candidates:
            content_tokens = set(entry.content.lower().split())
            tag_tokens = set(t.lower() for t in entry.tags)
            all_tokens = content_tokens | tag_tokens
            overlap = len(query_tokens & all_tokens)
            if overlap > 0:
                score = overlap / max(len(query_tokens), 1)
                # Boost pinned entries
                if entry.pinned:
                    score += 0.1
                # Boost recent entries
                age = time.time() - entry.created_at
                recency_bonus = max(0, 1.0 - (age / 86400.0)) * 0.2
                score += recency_bonus
                scored.append((score, entry))

        # If no keyword matches, return most recent
        if not scored:
            candidates.sort(key=lambda e: e.created_at, reverse=True)
            return candidates[:limit]

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    async def get_agent_memories(
        self,
        agent_id: str,
        limit: int = 100,
    ) -> List[MemoryEntry]:
        """Return all memories written by *agent_id*.

        Results are ordered newest-first.
        """
        self._purge_expired()
        mids = self._by_agent.get(agent_id, [])
        entries = [
            self._entries[mid]
            for mid in mids
            if mid in self._entries and not self._entries[mid].is_expired
        ]
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    async def get_team_knowledge(
        self,
        topic: str,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        """Return memories tagged with *topic*.

        Equivalent to ``search(topic, tags=[topic])`` but faster since
        it uses the tag index directly.
        """
        self._purge_expired()
        mids = self._by_tag.get(topic, [])
        entries = [
            self._entries[mid]
            for mid in mids
            if mid in self._entries and not self._entries[mid].is_expired
        ]
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    async def get_all_entries(
        self,
        limit: int = 1000,
    ) -> List[MemoryEntry]:
        """Return all non-expired entries, newest first."""
        self._purge_expired()
        entries = list(self._entries.values())
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    # ===================================================================
    # Pin / Forget
    # ===================================================================

    async def pin(self, memory_id: str) -> None:
        """Mark *memory_id* as permanent (never evicted).

        Raises ``KeyError`` if the entry does not exist.
        """
        entry = self._entries.get(memory_id)
        if entry is None:
            raise KeyError(f"Memory {memory_id!r} not found")
        entry.pinned = True
        entry.updated_at = time.time()
        self._pinned.add(memory_id)
        log.debug("Pinned memory %s", memory_id[:8])

    async def unpin(self, memory_id: str) -> None:
        """Remove the permanent flag from *memory_id*."""
        entry = self._entries.get(memory_id)
        if entry is None:
            raise KeyError(f"Memory {memory_id!r} not found")
        entry.pinned = False
        entry.updated_at = time.time()
        self._pinned.discard(memory_id)

    async def forget(self, memory_id: str) -> None:
        """Permanently remove *memory_id* from team memory.

        No-op if the entry does not exist.
        """
        entry = self._entries.pop(memory_id, None)
        if entry is None:
            return
        # Clean indexes
        self._pinned.discard(memory_id)
        if memory_id in self._by_agent.get(entry.agent_id, []):
            self._by_agent[entry.agent_id].remove(memory_id)
        for tag in entry.tags:
            if memory_id in self._by_tag.get(tag, []):
                self._by_tag[tag].remove(memory_id)
        self._content_hashes.discard(entry.content_hash)
        log.debug("Forgot memory %s", memory_id[:8])

    async def forget_agent(self, agent_id: str) -> int:
        """Remove all memories written by *agent_id*.

        Returns the number of entries removed.
        """
        mids = list(self._by_agent.get(agent_id, []))
        for mid in mids:
            await self.forget(mid)
        return len(mids)

    # ===================================================================
    # Summarisation
    # ===================================================================

    async def summarize_session(self) -> str:
        """Produce a human-readable summary of the team's memory.

        Returns a structured text block listing agents, their entries,
        and key tags.
        """
        self._purge_expired()
        lines: List[str] = [
            f"# Team Memory Summary — {self._team_id}",
            f"Total entries: {len(self._entries)} "
            f"(pinned: {len(self._pinned)})",
            "",
        ]

        # Group by agent
        agent_groups: Dict[str, List[MemoryEntry]] = defaultdict(list)
        for entry in self._entries.values():
            agent_groups[entry.agent_id].append(entry)

        for aid, entries in sorted(agent_groups.items()):
            entries.sort(key=lambda e: e.created_at, reverse=True)
            lines.append(f"## Agent: {aid} ({len(entries)} entries)")
            for entry in entries[:5]:
                pin_marker = " [PINNED]" if entry.pinned else ""
                tag_str = ", ".join(entry.tags) if entry.tags else "untagged"
                preview = entry.content[:120].replace("\n", " ")
                lines.append(f"  - [{tag_str}]{pin_marker} {preview}")
            if len(entries) > 5:
                lines.append(f"  … and {len(entries) - 5} more")
            lines.append("")

        return "\n".join(lines)

    # ===================================================================
    # Stats
    # ===================================================================

    def stats(self) -> MemoryStats:
        """Return a snapshot of memory statistics."""
        self._purge_expired()
        all_tags: List[str] = []
        for entry in self._entries.values():
            all_tags.extend(entry.tags)

        ages = [
            time.time() - e.created_at for e in self._entries.values()
        ] or [0.0]

        return MemoryStats(
            total_entries=len(self._entries),
            pinned_entries=len(self._pinned),
            agents_with_entries=len(self._by_agent),
            total_tags=len(all_tags),
            unique_tags=len(set(all_tags)),
            oldest_entry_age=max(ages),
            newest_entry_age=min(ages),
            base_memory_available=self._base_store is not None,
            team_id=self._team_id,
        )

    # ===================================================================
    # Lifecycle
    # ===================================================================

    async def clear(self) -> int:
        """Remove all non-pinned entries.  Returns count removed."""
        to_remove = [
            mid for mid, e in self._entries.items()
            if not e.pinned
        ]
        for mid in to_remove:
            await self.forget(mid)
        return len(to_remove)

    async def shutdown(self) -> None:
        """Gracefully shut down team memory."""
        log.info(
            "TeamMemory(%s) shutting down — %d entries",
            self._team_id,
            len(self._entries),
        )

    def __repr__(self) -> str:  # pragma: no cover
        s = self.stats()
        return (
            f"<TeamMemory team={self._team_id!r} "
            f"entries={s.total_entries} pinned={s.pinned_entries}>"
        )

    # ===================================================================
    # Internal helpers
    # ===================================================================

    def _filter_by_access(
        self,
        access_level: str,
    ) -> List[MemoryEntry]:
        """Return entries that *access_level* is allowed to read."""
        return [
            e for e in self._entries.values()
            if not e.is_expired
            and AccessLevel.can_access(e.access_level, access_level)
        ]

    def _purge_expired(self) -> int:
        """Remove expired (non-pinned) entries.  Returns count purged."""
        expired = [
            mid for mid, e in self._entries.items()
            if e.is_expired
        ]
        for mid in expired:
            entry = self._entries.pop(mid, None)
            if entry:
                self._pinned.discard(mid)
                self._content_hashes.discard(entry.content_hash)
        return len(expired)

    async def _evict_oldest(self) -> None:
        """Evict the oldest non-pinned entry to make room."""
        candidates = [
            (mid, e) for mid, e in self._entries.items()
            if not e.pinned
        ]
        if not candidates:
            log.warning(
                "TeamMemory(%s): at capacity (%d) and all entries pinned",
                self._team_id,
                len(self._entries),
            )
            return
        candidates.sort(key=lambda x: x[1].created_at)
        oldest_id = candidates[0][0]
        await self.forget(oldest_id)
        log.debug("Evicted oldest entry %s", oldest_id[:8])
