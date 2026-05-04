"""Context Store — thread-safe shared state for all Frontier agents.

Multiple agents can read the store concurrently.  Write operations are
serialised via ``asyncio.Lock`` so that concurrent tasks never corrupt
shared state.  Entries carry a TTL for automatic expiry and are
namespaced by tab-id (per-page context) or the ``"global"`` namespace
for cross-page data.

Every write is tagged with the originating agent ID so actions can
be audited and reverted.

Usage::

    from orchestra.frontier.context_store import ContextStore
    store = ContextStore()
    await store.put("login_email", "user@example.com", source="agent-3",
                    entry_type="auth", ttl=300)
    entry = await store.get("login_email")
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ContextStore",
    "PageContext",
    "ContextEntry",
    "ContextStoreConfig",
]

log = logging.getLogger("orchestra.frontier.context_store")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ContextStoreConfig:
    """Configuration for the context store."""

    max_entries: int = 10_000
    max_entry_size_bytes: int = 1_048_576  # 1 MB
    cleanup_interval_seconds: float = 60.0
    enable_history: bool = True
    persist_path: str = ""  # Empty = in-memory only


@dataclass
class ContextEntry:
    """A single entry in the context store."""

    key: str
    value: Any
    source: str  # Which agent/task wrote this
    entry_type: str  # dom_snapshot | extracted_data | cookie | auth | memory | task_result | page_state
    timestamp: float
    ttl_seconds: float = 0  # 0 = no expiry
    tags: list[str] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        """Return ``True`` if this entry has exceeded its TTL."""
        if self.ttl_seconds <= 0:
            return False
        return time.time() > self.timestamp + self.ttl_seconds

    def size_bytes(self) -> int:
        """Approximate serialised size of the entry value."""
        try:
            return len(json.dumps(self.value, default=str))
        except (TypeError, ValueError):
            return len(str(self.value))

    def to_dict(self) -> dict[str, Any]:
        """Serialise the entry to a plain dict."""
        return {
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "entry_type": self.entry_type,
            "timestamp": self.timestamp,
            "ttl_seconds": self.ttl_seconds,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextEntry:
        """Deserialise a ``ContextEntry`` from a plain dict."""
        return cls(
            key=data["key"],
            value=data["value"],
            source=data.get("source", ""),
            entry_type=data.get("entry_type", ""),
            timestamp=data.get("timestamp", time.time()),
            ttl_seconds=data.get("ttl_seconds", 0),
            tags=data.get("tags", []),
        )


@dataclass
class PageContext:
    """Aggregated context for a specific page/tab."""

    url: str
    tab_id: str
    dom_snapshot: Any | None  # DOMSnapshot (avoid circular import)
    extracted_data: dict[str, Any]
    cookies: list[dict[str, str]]
    local_storage: dict[str, str]
    scroll_position: tuple[int, int]
    history: list[str]
    last_action: Any | None  # DOMAction
    last_updated: float

    def to_dict(self) -> dict[str, Any]:
        """Serialise page context to a plain dict."""
        return {
            "url": self.url,
            "tab_id": self.tab_id,
            "extracted_data": self.extracted_data,
            "cookies": self.cookies,
            "local_storage": self.local_storage,
            "scroll_position": list(self.scroll_position),
            "history": list(self.history),
            "last_updated": self.last_updated,
        }

    @classmethod
    def empty(cls, tab_id: str, url: str = "") -> PageContext:
        """Create an empty PageContext for a new tab."""
        return cls(
            url=url,
            tab_id=tab_id,
            dom_snapshot=None,
            extracted_data={},
            cookies=[],
            local_storage={},
            scroll_position=(0, 0),
            history=[],
            last_action=None,
            last_updated=time.time(),
        )


# ---------------------------------------------------------------------------
# ContextStore
# ---------------------------------------------------------------------------


class ContextStore:
    """Thread-safe shared context store for all Frontier agents.

    Design:
    - ``asyncio.Lock`` for write safety.
    - Multiple readers can proceed concurrently (reads do not acquire
      the lock).
    - Entries have TTL for automatic cleanup.
    - Namespaced by ``tab_id`` for per-page context.
    - ``"global"`` namespace for cross-page state.

    Every agent has read access to all context but writes are tagged
    with the agent's ID for audit/debugging.
    """

    def __init__(self, config: ContextStoreConfig | None = None) -> None:
        self.config = config or ContextStoreConfig()
        self._lock = asyncio.Lock()

        # namespace → key → ContextEntry
        self._store: dict[str, dict[str, ContextEntry]] = {"global": {}}

        # tab_id → PageContext
        self._pages: dict[str, PageContext] = {}

        # History: namespace → key → list[ContextEntry]
        self._history: dict[str, dict[str, list[ContextEntry]]] = {"global": {}}

        # Background cleanup task handle
        self._cleanup_task: asyncio.Task[None] | None = None

        # Load persisted state if configured
        if self.config.persist_path:
            self._load_from_disk()

        log.debug(
            "ContextStore initialised (max_entries=%d, persist=%s)",
            self.config.max_entries,
            bool(self.config.persist_path),
        )

    # ------------------------------------------------------------------
    # Read operations (no lock — concurrent safe)
    # ------------------------------------------------------------------

    async def get(self, key: str, namespace: str = "global") -> ContextEntry | None:
        """Retrieve a single context entry by key and namespace.

        Returns ``None`` if the key does not exist or has expired.
        """
        ns = self._store.get(namespace)
        if ns is None:
            return None
        entry = ns.get(key)
        if entry is None:
            return None
        if entry.expired:
            # Lazily evict
            await self._evict(key, namespace)
            return None
        return entry

    async def get_page_context(self, tab_id: str) -> PageContext | None:
        """Retrieve the aggregated context for a specific tab."""
        return self._pages.get(tab_id)

    async def search(
        self, query: str, entry_type: str = "", limit: int = 10
    ) -> list[ContextEntry]:
        """Search entries by substring match on key, value (stringified), or tags.

        Parameters
        ----------
        query:
            Case-insensitive search string.
        entry_type:
            Restrict to a specific ``entry_type`` (empty = all).
        limit:
            Maximum results to return.
        """
        query_lower = query.lower()
        results: list[ContextEntry] = []

        for ns_entries in self._store.values():
            for entry in ns_entries.values():
                if entry.expired:
                    continue
                if entry_type and entry.entry_type != entry_type:
                    continue

                # Match on key
                if query_lower in entry.key.lower():
                    results.append(entry)
                    if len(results) >= limit:
                        return results
                    continue

                # Match on tags
                if any(query_lower in t.lower() for t in entry.tags):
                    results.append(entry)
                    if len(results) >= limit:
                        return results
                    continue

                # Match on stringified value
                try:
                    val_str = json.dumps(entry.value, default=str).lower()
                except (TypeError, ValueError):
                    val_str = str(entry.value).lower()
                if query_lower in val_str:
                    results.append(entry)
                    if len(results) >= limit:
                        return results

        return results

    async def get_all(self, namespace: str = "global") -> dict[str, ContextEntry]:
        """Return all non-expired entries in a namespace."""
        ns = self._store.get(namespace)
        if ns is None:
            return {}
        return {k: v for k, v in ns.items() if not v.expired}

    # ------------------------------------------------------------------
    # Write operations (locked)
    # ------------------------------------------------------------------

    async def put(
        self,
        key: str,
        value: Any,
        source: str,
        entry_type: str,
        namespace: str = "global",
        ttl: float = 0,
        tags: list[str] | None = None,
    ) -> None:
        """Write a context entry.  Acquires the write lock.

        Parameters
        ----------
        key:
            Unique key within the namespace.
        value:
            Arbitrary data.
        source:
            Agent or task ID that is writing.
        entry_type:
            Classification — ``dom_snapshot``, ``extracted_data``, ``cookie``,
            ``auth``, ``memory``, ``task_result``, or ``page_state``.
        namespace:
            Namespace (typically ``"global"`` or a ``tab_id``).
        ttl:
            Time-to-live in seconds.  ``0`` = no expiry.
        tags:
            Optional tags for search/filtering.
        """
        entry = ContextEntry(
            key=key,
            value=value,
            source=source,
            entry_type=entry_type,
            timestamp=time.time(),
            ttl_seconds=ttl,
            tags=tags or [],
        )

        # Size check
        if entry.size_bytes() > self.config.max_entry_size_bytes:
            log.warning(
                "Entry '%s' exceeds max size (%d > %d bytes) — rejected",
                key,
                entry.size_bytes(),
                self.config.max_entry_size_bytes,
            )
            return

        async with self._lock:
            if namespace not in self._store:
                self._store[namespace] = {}
                self._history[namespace] = {}

            # Capacity check
            total = sum(len(ns) for ns in self._store.values())
            if total >= self.config.max_entries:
                evicted = self._evict_oldest()
                log.info("Store at capacity — evicted %d oldest entries", evicted)

            # Record history before overwriting
            if self.config.enable_history and key in self._store[namespace]:
                if namespace not in self._history:
                    self._history[namespace] = {}
                if key not in self._history[namespace]:
                    self._history[namespace][key] = []
                self._history[namespace][key].append(
                    copy.deepcopy(self._store[namespace][key])
                )

            self._store[namespace][key] = entry
            log.debug("PUT %s/%s (source=%s, type=%s)", namespace, key, source, entry_type)

            # Persist if configured
            if self.config.persist_path:
                self._persist_to_disk()

    async def update_page_context(self, tab_id: str, page_context: PageContext) -> None:
        """Store or replace the full page context for a tab."""
        async with self._lock:
            page_context.last_updated = time.time()
            self._pages[tab_id] = page_context
            log.debug("Updated page context for tab %s (%s)", tab_id, page_context.url)

    async def update_dom_snapshot(self, tab_id: str, snapshot: Any) -> None:
        """Update just the DOM snapshot for a tab's page context.

        Creates a new ``PageContext`` if one doesn't already exist.
        """
        async with self._lock:
            if tab_id not in self._pages:
                self._pages[tab_id] = PageContext.empty(tab_id, url=getattr(snapshot, "url", ""))
            self._pages[tab_id].dom_snapshot = snapshot
            self._pages[tab_id].last_updated = time.time()
            log.debug("Updated DOM snapshot for tab %s", tab_id)

    async def delete(self, key: str, namespace: str = "global") -> bool:
        """Delete a single entry.  Returns ``True`` if an entry was removed."""
        async with self._lock:
            ns = self._store.get(namespace)
            if ns is None or key not in ns:
                return False
            del ns[key]
            log.debug("DELETE %s/%s", namespace, key)
            if self.config.persist_path:
                self._persist_to_disk()
            return True

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    async def get_agent_writes(self, agent_id: str) -> list[ContextEntry]:
        """Return all entries written by a specific agent."""
        results: list[ContextEntry] = []
        for ns_entries in self._store.values():
            for entry in ns_entries.values():
                if entry.source == agent_id and not entry.expired:
                    results.append(entry)
        return results

    async def clear_namespace(self, namespace: str) -> int:
        """Delete all entries in a namespace.  Returns count removed."""
        async with self._lock:
            ns = self._store.get(namespace)
            if ns is None:
                return 0
            count = len(ns)
            ns.clear()
            # Also clear page context if this is a tab namespace
            if namespace in self._pages:
                del self._pages[namespace]
            log.info("Cleared namespace '%s' — %d entries removed", namespace, count)
            if self.config.persist_path:
                self._persist_to_disk()
            return count

    async def cleanup_expired(self) -> int:
        """Remove all expired entries across all namespaces.

        Returns the total number of entries removed.
        """
        removed = 0
        async with self._lock:
            for ns_name in list(self._store.keys()):
                ns = self._store[ns_name]
                expired_keys = [k for k, v in ns.items() if v.expired]
                for k in expired_keys:
                    del ns[k]
                    removed += 1
            if removed > 0:
                log.info("Cleanup: removed %d expired entries", removed)
                if self.config.persist_path:
                    self._persist_to_disk()
        return removed

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise the entire store to a plain dict (for persistence)."""
        data: dict[str, Any] = {"namespaces": {}, "pages": {}}
        for ns_name, ns_entries in self._store.items():
            data["namespaces"][ns_name] = {
                k: v.to_dict() for k, v in ns_entries.items() if not v.expired
            }
        for tab_id, pc in self._pages.items():
            data["pages"][tab_id] = pc.to_dict()
        return data

    def snapshot(self) -> dict[str, Any]:
        """Return a point-in-time deep copy of the store contents."""
        return copy.deepcopy(self.to_dict())

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the context store."""
        total_entries = 0
        expired_entries = 0
        ns_counts: dict[str, int] = {}

        for ns_name, ns_entries in self._store.items():
            active = 0
            for entry in ns_entries.values():
                total_entries += 1
                if entry.expired:
                    expired_entries += 1
                else:
                    active += 1
            ns_counts[ns_name] = active

        # Entry type distribution
        type_dist: dict[str, int] = {}
        for ns_entries in self._store.values():
            for entry in ns_entries.values():
                if not entry.expired:
                    type_dist[entry.entry_type] = type_dist.get(entry.entry_type, 0) + 1

        # Source distribution
        source_dist: dict[str, int] = {}
        for ns_entries in self._store.values():
            for entry in ns_entries.values():
                if not entry.expired:
                    source_dist[entry.source] = source_dist.get(entry.source, 0) + 1

        return {
            "total_entries": total_entries,
            "active_entries": total_entries - expired_entries,
            "expired_entries": expired_entries,
            "namespaces": ns_counts,
            "page_contexts": len(self._pages),
            "entry_types": type_dist,
            "sources": source_dist,
            "max_entries": self.config.max_entries,
            "persist_enabled": bool(self.config.persist_path),
            "history_enabled": self.config.enable_history,
        }

    # ------------------------------------------------------------------
    # Background cleanup
    # ------------------------------------------------------------------

    async def start_cleanup_loop(self) -> None:
        """Start a background task that periodically removes expired entries."""
        if self._cleanup_task is not None:
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        log.info("Cleanup loop started (interval=%.1fs)", self.config.cleanup_interval_seconds)

    async def stop_cleanup_loop(self) -> None:
        """Cancel the background cleanup task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            log.info("Cleanup loop stopped")

    async def _cleanup_loop(self) -> None:
        """Internal loop that runs ``cleanup_expired`` periodically."""
        while True:
            try:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                removed = await self.cleanup_expired()
                if removed:
                    log.debug("Periodic cleanup removed %d entries", removed)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Cleanup loop error: %s", exc)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_to_disk(self) -> None:
        """Write the store to disk as JSON (called under lock)."""
        if not self.config.persist_path:
            return
        try:
            data = self.to_dict()
            path = self.config.persist_path
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, default=str)
            os.replace(tmp_path, path)
            log.debug("Persisted store to %s", path)
        except Exception as exc:
            log.error("Failed to persist store: %s", exc)

    def _load_from_disk(self) -> None:
        """Load persisted store data from disk."""
        path = self.config.persist_path
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for ns_name, ns_entries in data.get("namespaces", {}).items():
                self._store[ns_name] = {}
                for k, v in ns_entries.items():
                    self._store[ns_name][k] = ContextEntry.from_dict(v)
            log.info("Loaded store from %s (%d namespaces)", path, len(self._store))
        except Exception as exc:
            log.error("Failed to load store from disk: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _evict(self, key: str, namespace: str) -> None:
        """Lazily evict a single expired entry (acquires lock)."""
        async with self._lock:
            ns = self._store.get(namespace)
            if ns and key in ns and ns[key].expired:
                del ns[key]

    def _evict_oldest(self) -> int:
        """Evict the oldest entries to make room (called under lock).

        Removes up to 10 % of ``max_entries`` to avoid evicting on
        every write.
        """
        all_entries: list[tuple[str, str, ContextEntry]] = []
        for ns_name, ns_entries in self._store.items():
            for k, v in ns_entries.items():
                all_entries.append((ns_name, k, v))

        # Sort by timestamp ascending (oldest first)
        all_entries.sort(key=lambda x: x[2].timestamp)
        to_remove = max(1, self.config.max_entries // 10)
        removed = 0
        for ns_name, key, _entry in all_entries[:to_remove]:
            ns = self._store.get(ns_name)
            if ns and key in ns:
                del ns[key]
                removed += 1
        return removed
