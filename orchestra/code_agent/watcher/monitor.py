"""Git-aware file and repository monitor.

Replaces the old polling-only FileWatcher with a two-layer monitor:

1. **Filesystem layer** — uses `watchdog` (inotify/FSEvents/kqueue) when
   installed; falls back to 1-second polling on platforms where watchdog
   isn't available.
2. **Git layer** — alongside filesystem events, polls `git status --porcelain`
   and `git log` to surface commit, branch, and staging events that don't
   always produce a filesystem event (e.g. `git stash`, `git cherry-pick`).

Events are **debounced** (default 0.5 s) so a burst of saves from an editor
fires one callback, not hundreds.

Usage::

    from orchestra.code_agent.watcher.monitor import RepoMonitor, WatchEvent

    monitor = RepoMonitor("/path/to/repo")
    monitor.on_event(lambda ev: print(ev))
    monitor.start()
    ...
    monitor.stop()
"""
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from typing import Callable

log = logging.getLogger("orchestra.watcher")

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

FS_EVENTS   = frozenset({"created", "modified", "deleted", "moved"})
GIT_EVENTS  = frozenset({"commit", "branch_change", "staged", "push", "pull"})
ALL_EVENTS  = FS_EVENTS | GIT_EVENTS


@dataclass
class WatchEvent:
    path: str            # file path or repo root for git events
    event_type: str      # one of ALL_EVENTS
    timestamp: float = field(default_factory=time.time)
    # Git-specific extras
    commit_sha: str  = ""
    branch: str      = ""
    message: str     = ""

    def __str__(self) -> str:
        if self.event_type in GIT_EVENTS:
            return f"[git:{self.event_type}] {self.branch} {self.commit_sha[:8]} — {self.message}"
        return f"[fs:{self.event_type}] {self.path}"


# ---------------------------------------------------------------------------
# Debouncer
# ---------------------------------------------------------------------------

class _Debouncer:
    """Collapse bursts of events within *window* seconds into one callback call."""

    def __init__(self, window: float = 0.5) -> None:
        self._window  = window
        self._pending: dict[str, tuple[WatchEvent, float]] = {}
        self._lock    = Lock()
        self._thread  = Thread(target=self._flush_loop, daemon=True)
        self._running = False
        self._callbacks: list[Callable[[WatchEvent], None]] = []

    def start(self, callbacks: list[Callable[[WatchEvent], None]]) -> None:
        self._callbacks = callbacks
        self._running   = True
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def push(self, event: WatchEvent) -> None:
        key = f"{event.event_type}:{event.path}"
        with self._lock:
            self._pending[key] = (event, time.monotonic())

    def _flush_loop(self) -> None:
        while self._running:
            now  = time.monotonic()
            fire = []
            with self._lock:
                done = [k for k, (_, ts) in self._pending.items()
                        if now - ts >= self._window]
                for k in done:
                    fire.append(self._pending.pop(k)[0])
            for ev in fire:
                for cb in self._callbacks:
                    try:
                        cb(ev)
                    except Exception as exc:
                        log.warning("Watcher callback error: %s", exc, exc_info=True)
            time.sleep(0.05)


# ---------------------------------------------------------------------------
# Filesystem layer
# ---------------------------------------------------------------------------

def _try_watchdog(paths: list[str], debouncer: _Debouncer) -> Any | None:
    """Return a running watchdog Observer, or None if watchdog isn't installed."""
    try:
        from watchdog.observers import Observer  # type: ignore[import]
        from watchdog.events import FileSystemEventHandler, FileSystemEvent  # type: ignore[import]

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event: FileSystemEvent) -> None:
                if event.is_directory:
                    return
                etype = event.event_type  # "created" / "modified" / "deleted" / "moved"
                if etype not in FS_EVENTS:
                    return
                debouncer.push(WatchEvent(
                    path=getattr(event, "dest_path", event.src_path),
                    event_type=etype,
                ))

        observer = Observer()
        handler  = _Handler()
        for p in paths:
            observer.schedule(handler, p, recursive=True)
        observer.start()
        log.info("Watchdog observer started on %d path(s)", len(paths))
        return observer
    except ImportError:
        return None


class _PollingLayer:
    """1-second mtime polling fallback when watchdog is unavailable."""

    def __init__(self, debouncer: _Debouncer) -> None:
        self._debouncer   = debouncer
        self._watched: dict[str, float] = {}
        self._lock        = Lock()
        self._thread: Thread | None = None
        self._running     = False

    def add(self, path: str) -> None:
        p = Path(path)
        with self._lock:
            if p.is_file():
                self._watched[str(p)] = p.stat().st_mtime if p.exists() else 0
            else:
                for f in p.rglob("*"):
                    if f.is_file():
                        self._watched[str(f)] = f.stat().st_mtime

    def remove(self, path: str) -> None:
        with self._lock:
            for k in [k for k in self._watched if k.startswith(path)]:
                del self._watched[k]

    def start(self) -> None:
        self._running = True
        self._thread  = Thread(target=self._loop, daemon=True, name="orch-fs-poll")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            with self._lock:
                snapshot = dict(self._watched)
            for path, last_mtime in snapshot.items():
                p = Path(path)
                if not p.exists():
                    self._debouncer.push(WatchEvent(path=path, event_type="deleted"))
                    with self._lock:
                        self._watched.pop(path, None)
                    continue
                mtime = p.stat().st_mtime
                if mtime != last_mtime:
                    etype = "created" if last_mtime == 0 else "modified"
                    self._debouncer.push(WatchEvent(path=path, event_type=etype))
                    with self._lock:
                        self._watched[path] = mtime
            time.sleep(1.0)


# ---------------------------------------------------------------------------
# Git layer
# ---------------------------------------------------------------------------

class _GitLayer:
    """Polls git status and log to detect commit/branch/staged changes."""

    def __init__(self, repo_root: str, debouncer: _Debouncer, poll_interval: float = 2.0) -> None:
        self._root     = repo_root
        self._debouncer = debouncer
        self._interval = poll_interval
        self._thread: Thread | None = None
        self._running  = False
        self._last_sha    = ""
        self._last_branch = ""
        self._last_staged: set[str] = set()

    def start(self) -> None:
        if not self._is_git_repo():
            log.debug("Not a git repo — git layer disabled for %s", self._root)
            return
        # Seed initial state
        self._last_sha    = self._current_sha()
        self._last_branch = self._current_branch()
        self._last_staged = self._staged_files()
        self._running     = True
        self._thread       = Thread(target=self._loop, daemon=True, name="orch-git-poll")
        self._thread.start()
        log.info("Git layer started on %s (branch=%s sha=%s)", self._root, self._last_branch, self._last_sha[:8])

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                self._check()
            except Exception as exc:
                log.warning("Git poll error: %s", exc)
            time.sleep(self._interval)

    def _check(self) -> None:
        sha    = self._current_sha()
        branch = self._current_branch()
        staged = self._staged_files()

        if sha and sha != self._last_sha:
            msg = self._commit_message(sha)
            self._debouncer.push(WatchEvent(
                path=self._root, event_type="commit",
                commit_sha=sha, branch=branch, message=msg,
            ))
            self._last_sha = sha

        if branch and branch != self._last_branch:
            self._debouncer.push(WatchEvent(
                path=self._root, event_type="branch_change",
                branch=branch, message=f"switched from {self._last_branch} to {branch}",
            ))
            self._last_branch = branch

        if staged != self._last_staged:
            new_files = staged - self._last_staged
            if new_files:
                self._debouncer.push(WatchEvent(
                    path=self._root, event_type="staged",
                    branch=branch, message=f"staged: {', '.join(sorted(new_files)[:5])}",
                ))
            self._last_staged = staged

    def _run(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self._root, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()

    def _is_git_repo(self) -> bool:
        try:
            return bool(self._run("rev-parse", "--is-inside-work-tree"))
        except Exception:
            return False

    def _current_sha(self) -> str:
        try:
            return self._run("rev-parse", "HEAD")
        except Exception:
            return ""

    def _current_branch(self) -> str:
        try:
            return self._run("rev-parse", "--abbrev-ref", "HEAD")
        except Exception:
            return ""

    def _staged_files(self) -> set[str]:
        try:
            out = self._run("diff", "--name-only", "--cached")
            return set(out.splitlines()) if out else set()
        except Exception:
            return set()

    def _commit_message(self, sha: str) -> str:
        try:
            return self._run("log", "-1", "--pretty=%s", sha)
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Type alias (avoid importing Any at module level for older Pythons)
from typing import Any


class RepoMonitor:
    """Monitors a filesystem path (and its git repo) for changes.

    Combines watchdog (or polling fallback) for filesystem events with a
    git-state poller for commit/branch/staged events.  All events are
    debounced before reaching callbacks.

    Parameters
    ----------
    path:
        Directory to watch.  Should be the root of a git repository for
        git events to work.
    debounce_window:
        Seconds to wait after the last event before firing callbacks.
    git_poll_interval:
        Seconds between git-state checks.
    """

    def __init__(
        self,
        path: str,
        *,
        debounce_window: float = 0.5,
        git_poll_interval: float = 2.0,
    ) -> None:
        self._path      = str(Path(path).resolve())
        self._callbacks: list[Callable[[WatchEvent], None]] = []
        self._debouncer = _Debouncer(window=debounce_window)
        self._fs_observer: Any = None   # watchdog Observer or None
        self._fs_poll: _PollingLayer | None = None
        self._git = _GitLayer(self._path, self._debouncer, poll_interval=git_poll_interval)
        self._running = False

    # -- registration -------------------------------------------------------

    def on_event(self, callback: Callable[[WatchEvent], None]) -> "RepoMonitor":
        """Register an event callback. Returns self for chaining."""
        self._callbacks.append(callback)
        return self

    def on_commit(self, callback: Callable[[WatchEvent], None]) -> "RepoMonitor":
        """Register a callback that fires only on git commit events."""
        def _filtered(ev: WatchEvent) -> None:
            if ev.event_type == "commit":
                callback(ev)
        return self.on_event(_filtered)

    def on_file_change(self, callback: Callable[[WatchEvent], None]) -> "RepoMonitor":
        """Register a callback that fires only on filesystem events."""
        def _filtered(ev: WatchEvent) -> None:
            if ev.event_type in FS_EVENTS:
                callback(ev)
        return self.on_event(_filtered)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._debouncer.start(self._callbacks)

        # Try watchdog first; fall back to polling
        self._fs_observer = _try_watchdog([self._path], self._debouncer)
        if self._fs_observer is None:
            log.info("watchdog not installed — using polling fallback")
            self._fs_poll = _PollingLayer(self._debouncer)
            self._fs_poll.add(self._path)
            self._fs_poll.start()

        self._git.start()

    def stop(self) -> None:
        self._running = False
        self._debouncer.stop()
        if self._fs_observer is not None:
            self._fs_observer.stop()
            self._fs_observer.join(timeout=3)
        if self._fs_poll is not None:
            self._fs_poll.stop()
        self._git.stop()

    def __enter__(self) -> "RepoMonitor":
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# Legacy alias — keeps existing imports working
# ---------------------------------------------------------------------------

class FileWatcher(RepoMonitor):
    """Backward-compatible alias for RepoMonitor."""

    def __init__(self, callback: Callable[[WatchEvent], None] | None = None) -> None:
        super().__init__(".", debounce_window=0.5)
        if callback:
            self.on_event(callback)

    def watch(self, path: str) -> None:
        if self._fs_poll is not None:
            self._fs_poll.add(path)
        elif not self._running:
            self._path = str(Path(path).resolve())

    def unwatch(self, path: str) -> None:
        if self._fs_poll is not None:
            self._fs_poll.remove(path)

    def watched_files(self) -> list[str]:
        if self._fs_poll is not None:
            return list(self._fs_poll._watched.keys())
        return []
