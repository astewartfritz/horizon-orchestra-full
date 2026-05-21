from __future__ import annotations

import asyncio
import json
import signal
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from orchestra.code_agent.scheduler.scheduler import AgentScheduler, ScheduledTask


@dataclass
class DaemonConfig:
    scheduler_file: str = ".agent-scheduler.json"
    host: str = "127.0.0.1"
    api_port: int = 8100
    dashboard_port: int = 9090
    webhook_port: int = 8200
    enable_api: bool = True
    enable_dashboard: bool = True
    enable_scheduler: bool = True
    enable_webhook: bool = False
    poll_interval: int = 10


class AgentDaemon:
    """Run code-agent as a background service."""

    def __init__(self, config: DaemonConfig | None = None):
        self.config = config or DaemonConfig()
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._start_time = time.time()

        if self.config.enable_scheduler:
            self._tasks.append(asyncio.create_task(self._run_scheduler()))

        if self.config.enable_api:
            self._tasks.append(asyncio.create_task(self._run_api()))

        if self.config.enable_dashboard:
            self._tasks.append(asyncio.create_task(self._run_dashboard()))

        if self.config.enable_webhook:
            self._tasks.append(asyncio.create_task(self._run_webhook()))

        print(f"Agent daemon started (PID: {self._get_pid()})")
        print(f"  API:      http://{self.config.host}:{self.config.api_port}")
        print(f"  Dashboard: http://{self.config.host}:{self.config.dashboard_port}")
        print(f"  Scheduler: {'enabled' if self.config.enable_scheduler else 'disabled'}")

        # Wait for all tasks
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _get_pid(self) -> int:
        try:
            return __import__("os").getpid()
        except Exception:
            return 0

    async def _run_scheduler(self) -> None:
        sched = AgentScheduler(storage_path=self.config.scheduler_file)
        while self._running:
            tasks = sched.list()
            for t in tasks:
                if t.enabled and time.time() >= t.next_run:
                    try:
                        from orchestra.code_agent.agent import Agent
                        from orchestra.code_agent.profiles.base import load_profile
                        cfg = load_profile(t.profile)
                        agent = Agent(cfg)
                        await agent.run(t.task)
                        t.last_run = time.time()
                        t.next_run = time.time() + t.interval_seconds
                    except Exception as e:
                        print(f"  Scheduler task '{t.name}' failed: {e}")
            await asyncio.sleep(self.config.poll_interval)

    async def _run_api(self) -> None:
        try:
            from orchestra.code_agent.api.server import AgentAPI
            api = AgentAPI()
            import uvicorn
            cfg = uvicorn.Config(api.app, host=self.config.host, port=self.config.api_port, log_level="info")
            server = uvicorn.Server(cfg)
            await server.serve()
        except Exception as e:
            print(f"  API server error: {e}")

    async def _run_dashboard(self) -> None:
        try:
            from orchestra.code_agent.dashboard.server import DashboardServer
            server = DashboardServer()
            await server.run_server(host=self.config.host, port=self.config.dashboard_port)
        except Exception as e:
            print(f"  Dashboard error: {e}")

    async def _run_webhook(self) -> None:
        try:
            from orchestra.code_agent.github.webhook import GitHubWebhookHandler
            import uvicorn
            handler = GitHubWebhookHandler()
            cfg = uvicorn.Config(handler.app, host=self.config.host, port=self.config.webhook_port, log_level="info")
            server = uvicorn.Server(cfg)
            await server.serve()
        except Exception as e:
            print(f"  Webhook error: {e}")

    def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()

    def status(self) -> dict[str, Any]:
        uptime = time.time() - self._start_time if hasattr(self, '_start_time') else 0
        return {
            "running": self._running,
            "uptime_seconds": round(uptime, 1),
            "pid": self._get_pid(),
            "api": self.config.enable_api,
            "dashboard": self.config.enable_dashboard,
            "scheduler": self.config.enable_scheduler,
            "webhook": self.config.enable_webhook,
        }


async def run_daemon(config_path: str = "") -> None:
    cfg = DaemonConfig()
    if config_path and Path(config_path).exists():
        data = json.loads(Path(config_path).read_text())
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

    daemon = AgentDaemon(cfg)

    def shutdown():
        daemon.stop()
        sys.exit(0)

    try:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, shutdown)
            except (NotImplementedError, AttributeError):
                pass
        await daemon.start()
    except asyncio.CancelledError:
        pass
