from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TestResult:
    success: bool = False
    output: str = ""
    duration_ms: float = 0.0
    command: str = ""


class TestWatcher:
    """Watch files and auto-run tests on changes."""

    def __init__(self, test_command: str = "python -m pytest", watch_patterns: list[str] | None = None):
        self.test_command = test_command
        self.watch_patterns = watch_patterns or ["**/*.py", "**/*.js", "**/*.ts"]
        self._running = False
        self._last_run: float = 0
        self._debounce_seconds = 2.0

    async def run_tests(self) -> TestResult:
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_shell(
                self.test_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode("utf-8", errors="ignore")
            duration = (time.time() - start) * 1000
            return TestResult(
                success=proc.returncode == 0,
                output=output[-2000:],
                duration_ms=round(duration, 1),
                command=self.test_command,
            )
        except Exception as e:
            return TestResult(success=False, output=str(e))

    async def watch_and_run(self, path: str = ".", interval: float = 2.0) -> None:
        self._running = True
        self._last_run = time.time()
        watched = Path(path)

        while self._running:
            changed = False
            for pattern in self.watch_patterns:
                for f in watched.glob(pattern):
                    if f.is_file():
                        mtime = f.stat().st_mtime
                        if mtime > self._last_run:
                            changed = True
                            break
                if changed:
                    break

            if changed and (time.time() - self._last_run) > self._debounce_seconds:
                self._last_run = time.time()
                result = await self.run_tests()
                status = "PASS" if result.success else "FAIL"
                print(f"[{status}] {result.command} ({result.duration_ms:.0f}ms)")
                if not result.success:
                    print(result.output[:500])

            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False
