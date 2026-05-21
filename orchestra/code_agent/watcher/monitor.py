from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Callable


@dataclass
class WatchEvent:
    file_path: str
    event_type: str  # created, modified, deleted
    timestamp: float


class FileWatcher:
    def __init__(self, callback: Callable[[WatchEvent], None] | None = None):
        self._callbacks: list[Callable[[WatchEvent], None]] = []
        self._watched: dict[str, float] = {}
        self._running = False
        self._thread: Thread | None = None
        self._poll_interval = 1.0
        if callback:
            self._callbacks.append(callback)

    def on_event(self, callback: Callable[[WatchEvent], None]) -> None:
        self._callbacks.append(callback)

    def watch(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            if p.is_file():
                self._watched[str(p)] = p.stat().st_mtime
            else:
                for f in p.rglob("*"):
                    if f.is_file():
                        self._watched[str(f)] = f.stat().st_mtime
        else:
            self._watched[path] = 0

    def unwatch(self, path: str) -> None:
        keys_to_remove = [k for k in self._watched if k.startswith(path)]
        for k in keys_to_remove:
            del self._watched[k]

    def start(self) -> None:
        self._running = True
        self._thread = Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _poll_loop(self) -> None:
        while self._running:
            for path, last_mtime in list(self._watched.items()):
                p = Path(path)
                if not p.exists():
                    event = WatchEvent(path, "deleted", time.time())
                    self._emit(event)
                    del self._watched[path]
                    continue
                current_mtime = p.stat().st_mtime
                if current_mtime != last_mtime:
                    self._watched[path] = current_mtime
                    if last_mtime == 0:
                        event_type = "created"
                    else:
                        event_type = "modified"
                    event = WatchEvent(path, event_type, time.time())
                    self._emit(event)
            time.sleep(self._poll_interval)

    def _emit(self, event: WatchEvent) -> None:
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass

    def watched_files(self) -> list[str]:
        return list(self._watched.keys())
