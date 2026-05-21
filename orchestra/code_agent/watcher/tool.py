from __future__ import annotations

import asyncio
from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec
from orchestra.code_agent.watcher.monitor import FileWatcher


class WatchTool(Tool):
    spec = ToolSpec(
        name="watch",
        description="Watch files/directories for changes and optionally run a command on change.",
        parameters={
            "path": {"type": "string", "description": "File or directory to watch"},
            "action": {
                "type": "string",
                "description": "Action: start, stop, status",
                "default": "start",
            },
            "timeout": {
                "type": "integer",
                "description": "Watch duration in seconds (0 = forever)",
                "default": 0,
            },
        },
    )

    _watchers: dict[str, FileWatcher] = {}

    async def __call__(self, path: str, action: str = "start", timeout: int = 0) -> ToolResult:
        try:
            if action == "start":
                watcher = FileWatcher()
                watcher.watch(path)

                events: list[str] = []

                def on_change(event):
                    events.append(f"[{event.event_type}] {event.file_path}")

                watcher.on_event(on_change)
                watcher.start()
                self._watchers[path] = watcher

                if timeout > 0:
                    await asyncio.sleep(timeout)
                    watcher.stop()
                    del self._watchers[path]

                if events:
                    return ToolResult(
                        output=f"Watched {path} for {timeout}s. Events:\n" + "\n".join(events)
                    )
                return ToolResult(output=f"Watching {path} (running in background)")

            elif action == "stop":
                watcher = self._watchers.pop(path, None)
                if watcher:
                    watcher.stop()
                    return ToolResult(output=f"Stopped watching {path}")
                return ToolResult(error=f"Not watching: {path}")

            elif action == "status":
                if self._watchers:
                    watched = "\n".join(f"  {p}" for p in self._watchers)
                    return ToolResult(output=f"Active watchers:\n{watched}")
                return ToolResult(output="No active watchers")

            else:
                return ToolResult(error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(error=str(e))
