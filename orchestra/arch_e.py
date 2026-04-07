"""Architecture E — Full Production Stack.

Complete system integrating:

* **API Gateway** — FastAPI server with WebSocket streaming, auth, sessions.
* **Orchestrator Service** — Architecture A or C as the execution backend.
* **Connector Layer** — Pluggable external service integrations (Gmail,
  Slack, GitHub, Notion, etc.).
* **Task Queue** — Async job dispatch for background and scheduled work.
* **Memory Service** — Persistent cross-session memory with embedding search.
* **Code Sandbox** — Isolated subprocess execution (Docker in production).

This module provides:
1. ``ProductionOrchestrator`` — wires A/C + memory + connectors together.
2. ``ConnectorRegistry`` — pluggable external service integrations.
3. ``TaskQueue`` — asyncio-based task queue (swap to Celery/Temporal in prod).
4. ``create_app()`` — FastAPI application factory.
5. Docker Compose template generation.

Usage (development)::

    from orchestra.arch_e import ProductionOrchestrator
    orch = ProductionOrchestrator(user_id="ashton")
    result = await orch.run("Search my Gmail for investor emails and summarise")

Usage (server)::

    uvicorn orchestra.arch_e:app --host 0.0.0.0 --port 3000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

from .router import ModelRouter
from .agent_loop import (
    AgentConfig,
    AgentEvent,
    AgentLoop,
    FinalAnswerEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolRegistry,
    create_default_tools,
)
from .memory import (
    MemoryStore,
    MemoryManager,
    SessionContext,
    register_memory_tools,
)
from .arch_a import MonolithicAgent, MonolithicConfig
from .arch_c import SwarmAgent, SwarmConfig
from .perplexity import PerplexitySearch, PerplexityAgent

__all__ = [
    "ProductionOrchestrator",
    "ProductionConfig",
    "Connector",
    "ConnectorRegistry",
    "TaskQueue",
    "TaskJob",
    "create_app",
    "generate_docker_compose",
]

log = logging.getLogger("orchestra.arch_e")


# ===========================================================================
# Configuration
# ===========================================================================

@dataclass
class ProductionConfig:
    """Master configuration for Architecture E."""
    # -- execution mode --
    architecture: str = "A"               # "A" (monolithic) or "C" (swarm)
    model: str = "kimi-k2.5"
    user_id: str = "default"

    # -- memory --
    memory_db: str = ""                   # SQLite path; empty = default
    auto_extract_memory: bool = True

    # -- infrastructure --
    workspace_dir: str = "/tmp/horizon_workspace"
    host: str = "0.0.0.0"
    port: int = 3000
    api_key: str = ""                     # for authenticating inbound requests
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    # -- task queue --
    max_concurrent_jobs: int = 20
    job_timeout: int = 600                # seconds

    # -- logging --
    verbose: bool = False


# ===========================================================================
# Connector system
# ===========================================================================

class Connector(ABC):
    """Base class for external service integrations."""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with the service."""
        ...

    @abstractmethod
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an action on the service."""
        ...

    @abstractmethod
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas for this connector."""
        ...

    @property
    def connected(self) -> bool:
        return False


class GmailConnector(Connector):
    """Gmail integration (requires google-auth + gmail API)."""

    name = "gmail"
    description = "Search, read, and send emails via Gmail."

    def __init__(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, credentials: dict[str, str]) -> bool:
        # In production: OAuth2 flow with google-auth-oauthlib
        self._connected = bool(credentials.get("token"))
        return self._connected

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"error": "Gmail not connected. Call connect() first."}
        # Stub — implement with google-api-python-client
        return {"note": f"Gmail {action} stub", "params": params}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "gmail_search",
                    "description": "Search Gmail for emails matching a query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Gmail search query"},
                            "max_results": {"type": "integer", "description": "Max results (default 10)"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gmail_send",
                    "description": "Send an email via Gmail.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string"},
                            "subject": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
            },
        ]


class SlackConnector(Connector):
    """Slack integration stub."""

    name = "slack"
    description = "Post messages and search Slack channels."

    def __init__(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._connected = bool(credentials.get("token"))
        return self._connected

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"note": f"Slack {action} stub", "params": params}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "slack_post",
                    "description": "Post a message to a Slack channel.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string"},
                            "message": {"type": "string"},
                        },
                        "required": ["channel", "message"],
                    },
                },
            },
        ]


class GitHubConnector(Connector):
    """GitHub integration stub."""

    name = "github"
    description = "Manage repos, issues, PRs, and code on GitHub."

    def __init__(self) -> None:
        self._connected = False
        self._token = ""

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, credentials: dict[str, str]) -> bool:
        self._token = credentials.get("token", os.environ.get("GITHUB_TOKEN", ""))
        self._connected = bool(self._token)
        return self._connected

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"note": f"GitHub {action} stub", "params": params}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "github_create_issue",
                    "description": "Create a GitHub issue.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string", "description": "owner/repo"},
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["repo", "title"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "github_search_code",
                    "description": "Search code across GitHub repositories.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "repo": {"type": "string", "description": "Limit to a specific repo"},
                        },
                        "required": ["query"],
                    },
                },
            },
        ]


class ConnectorRegistry:
    """Registry of external service connectors.

    Connectors register themselves and their tools are dynamically
    injected into the agent's tool surface.
    """

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.name] = connector
        log.info("Registered connector: %s", connector.name)

    def get(self, name: str) -> Connector | None:
        return self._connectors.get(name)

    @property
    def all(self) -> dict[str, Connector]:
        return dict(self._connectors)

    def register_tools(self, tool_registry: ToolRegistry) -> None:
        """Inject all connected services' tools into the agent's tool surface."""
        for conn in self._connectors.values():
            if not conn.connected:
                continue
            for tool_def in conn.get_tool_definitions():
                fn = tool_def.get("function", {})
                tool_name = fn.get("name", "")
                if not tool_name:
                    continue

                # Create a handler closure for this connector + action
                async def _handler(
                    _conn=conn,
                    _action=tool_name,
                    **kwargs: Any,
                ) -> str:
                    result = await _conn.execute(_action, kwargs)
                    return json.dumps(result)

                tool_registry.register(
                    name=tool_name,
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters", {}),
                    handler=_handler,
                )

    def list_connectors(self) -> list[dict[str, Any]]:
        return [
            {
                "name": c.name,
                "description": c.description,
                "connected": c.connected,
                "tools": [t["function"]["name"] for t in c.get_tool_definitions()],
            }
            for c in self._connectors.values()
        ]

    @classmethod
    def default(cls) -> "ConnectorRegistry":
        """Create a registry with all built-in connectors."""
        reg = cls()
        reg.register(GmailConnector())
        reg.register(SlackConnector())
        reg.register(GitHubConnector())
        return reg


# ===========================================================================
# Task queue
# ===========================================================================

@dataclass
class TaskJob:
    """A queued task job."""
    id: str = ""
    task: str = ""
    user_id: str = "default"
    architecture: str = "A"
    status: str = "pending"       # pending | running | complete | failed
    result: str = ""
    error: str = ""
    created_at: float = 0.0
    completed_at: float = 0.0
    duration: float = 0.0


class TaskQueue:
    """Asyncio-based in-memory task queue.

    For production, replace with Celery + Redis or Temporal.
    """

    def __init__(self, max_concurrent: int = 20) -> None:
        self._jobs: dict[str, TaskJob] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._orchestrator_factory: Any = None

    def set_orchestrator_factory(self, factory: Any) -> None:
        """Set the callable that creates a ProductionOrchestrator per job."""
        self._orchestrator_factory = factory

    async def submit(
        self,
        task: str,
        user_id: str = "default",
        architecture: str = "A",
    ) -> str:
        """Submit a task and return the job ID."""
        job_id = str(uuid.uuid4())[:12]
        job = TaskJob(
            id=job_id,
            task=task,
            user_id=user_id,
            architecture=architecture,
            created_at=time.time(),
        )
        self._jobs[job_id] = job
        asyncio.create_task(self._execute(job))
        return job_id

    async def _execute(self, job: TaskJob) -> None:
        async with self._semaphore:
            job.status = "running"
            try:
                if self._orchestrator_factory:
                    orch = self._orchestrator_factory(
                        user_id=job.user_id,
                        architecture=job.architecture,
                    )
                    job.result = await orch.run(job.task)
                else:
                    job.result = "[No orchestrator configured]"
                job.status = "complete"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
            finally:
                job.completed_at = time.time()
                job.duration = job.completed_at - job.created_at

    def get(self, job_id: str) -> TaskJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self, user_id: str | None = None, limit: int = 50) -> list[TaskJob]:
        jobs = list(self._jobs.values())
        if user_id:
            jobs = [j for j in jobs if j.user_id == user_id]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]


# ===========================================================================
# Production orchestrator (unifies A + C + memory + connectors)
# ===========================================================================

class ProductionOrchestrator:
    """Architecture E: full production stack.

    Wraps Architecture A or C with:
    - Persistent memory
    - External service connectors
    - Task queue integration
    - Structured logging
    """

    def __init__(
        self,
        config: ProductionConfig | None = None,
        router: ModelRouter | None = None,
        connectors: ConnectorRegistry | None = None,
    ) -> None:
        self.config = config or ProductionConfig()
        self.router = router or ModelRouter()
        self.connectors = connectors or ConnectorRegistry.default()

        # Build the underlying architecture
        if self.config.architecture == "C":
            swarm_cfg = SwarmConfig(
                coordinator_model=self.config.model,
                user_id=self.config.user_id,
                workspace_dir=self.config.workspace_dir,
                memory_db=self.config.memory_db,
                auto_extract_memory=self.config.auto_extract_memory,
                verbose=self.config.verbose,
            )
            self._backend = SwarmAgent(config=swarm_cfg, router=self.router)
        else:
            mono_cfg = MonolithicConfig(
                model=self.config.model,
                user_id=self.config.user_id,
                workspace_dir=self.config.workspace_dir,
                memory_db=self.config.memory_db,
                auto_extract_memory=self.config.auto_extract_memory,
                verbose=self.config.verbose,
            )
            self._backend = MonolithicAgent(config=mono_cfg, router=self.router)

        # Inject connector tools into the backend's tool registry
        if hasattr(self._backend, "tools"):
            self.connectors.register_tools(self._backend.tools)

    async def run(self, task: str, context: str = "") -> str:
        """Execute a task through the full production stack."""
        return await self._backend.run(task, context=context)

    async def stream(self, task: str, context: str = "") -> AsyncGenerator[AgentEvent, None]:
        """Stream events from the backend."""
        async for event in self._backend.stream(task, context=context):
            yield event

    @property
    def stats(self) -> dict[str, Any]:
        base = self._backend.stats if hasattr(self._backend, "stats") else {}
        return {
            **base,
            "architecture_mode": f"E ({self.config.architecture})",
            "connectors": self.connectors.list_connectors(),
        }


# ===========================================================================
# FastAPI application
# ===========================================================================

def create_app(config: ProductionConfig | None = None) -> Any:
    """Create a FastAPI application for Architecture E.

    Returns the app object.  Run with:
        uvicorn orchestra.arch_e:app --host 0.0.0.0 --port 3000
    """
    try:
        from fastapi import FastAPI, WebSocket, HTTPException, Depends, Header
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError:
        raise ImportError(
            "FastAPI is required for the production server. "
            "Install with: pip install fastapi uvicorn"
        )

    config = config or ProductionConfig()
    app = FastAPI(
        title="Horizon Orchestra",
        description="Agentic AI harness — Architecture E production stack",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- state --------------------------------------------------------------
    router = ModelRouter()
    connectors = ConnectorRegistry.default()
    task_queue = TaskQueue(max_concurrent=config.max_concurrent_jobs)

    def make_orchestrator(user_id: str = "default", architecture: str = "A"):
        cfg = ProductionConfig(
            architecture=architecture,
            model=config.model,
            user_id=user_id,
            memory_db=config.memory_db,
            workspace_dir=config.workspace_dir,
            verbose=config.verbose,
        )
        return ProductionOrchestrator(cfg, router=router, connectors=connectors)

    task_queue.set_orchestrator_factory(
        lambda user_id, architecture: make_orchestrator(user_id, architecture)
    )

    # -- auth ---------------------------------------------------------------
    async def verify_api_key(authorization: str = Header(default="")):
        if config.api_key and authorization != f"Bearer {config.api_key}":
            raise HTTPException(status_code=401, detail="Invalid API key")

    # -- request models -----------------------------------------------------
    class RunRequest(BaseModel):
        task: str
        user_id: str = "default"
        architecture: str = "A"
        context: str = ""

    class JobSubmitRequest(BaseModel):
        task: str
        user_id: str = "default"
        architecture: str = "A"

    class ConnectRequest(BaseModel):
        connector: str
        credentials: dict[str, str]

    class MemoryStoreRequest(BaseModel):
        user_id: str = "default"
        content: str
        category: str = "fact"

    class MemorySearchRequest(BaseModel):
        user_id: str = "default"
        query: str
        limit: int = 10

    # -- routes -------------------------------------------------------------

    @app.post("/v1/run")
    async def run_task(req: RunRequest, _=Depends(verify_api_key)):
        """Run a task synchronously and return the result."""
        orch = make_orchestrator(req.user_id, req.architecture)
        result = await orch.run(req.task, context=req.context)
        return {"result": result, "stats": orch.stats}

    @app.websocket("/v1/stream")
    async def stream_task(ws: WebSocket):
        """Stream task events over WebSocket."""
        await ws.accept()
        data = await ws.receive_json()
        task = data.get("task", "")
        user_id = data.get("user_id", "default")
        arch = data.get("architecture", "A")

        orch = make_orchestrator(user_id, arch)
        async for event in orch.stream(task):
            event_data: dict[str, Any] = {"type": type(event).__name__}
            if isinstance(event, ToolCallEvent):
                event_data.update({
                    "tool": event.tool_name,
                    "iteration": event.iteration,
                })
            elif isinstance(event, ToolResultEvent):
                event_data.update({
                    "tool": event.tool_name,
                    "success": event.success,
                    "duration": event.duration,
                })
            elif isinstance(event, FinalAnswerEvent):
                event_data.update({
                    "content": event.content,
                    "iterations": event.total_iterations,
                    "tool_calls": event.total_tool_calls,
                })
            elif isinstance(event, ErrorEvent):
                event_data.update({
                    "message": event.message,
                    "recoverable": event.recoverable,
                })
            await ws.send_json(event_data)
        await ws.close()

    @app.post("/v1/jobs/submit")
    async def submit_job(req: JobSubmitRequest, _=Depends(verify_api_key)):
        """Submit a task to the background queue."""
        job_id = await task_queue.submit(
            task=req.task, user_id=req.user_id, architecture=req.architecture,
        )
        return {"job_id": job_id, "status": "submitted"}

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str, _=Depends(verify_api_key)):
        """Check status of a background job."""
        job = task_queue.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "id": job.id, "status": job.status,
            "result": job.result if job.status == "complete" else None,
            "error": job.error if job.status == "failed" else None,
            "duration": job.duration,
        }

    @app.get("/v1/jobs")
    async def list_jobs(user_id: str = "default", _=Depends(verify_api_key)):
        """List recent jobs."""
        jobs = task_queue.list_jobs(user_id=user_id)
        return [
            {"id": j.id, "task": j.task[:100], "status": j.status, "duration": j.duration}
            for j in jobs
        ]

    @app.post("/v1/connectors/connect")
    async def connect_service(req: ConnectRequest, _=Depends(verify_api_key)):
        """Connect an external service."""
        conn = connectors.get(req.connector)
        if not conn:
            raise HTTPException(status_code=404, detail=f"Unknown connector: {req.connector}")
        success = await conn.connect(req.credentials)
        return {"connector": req.connector, "connected": success}

    @app.get("/v1/connectors")
    async def list_connectors(_=Depends(verify_api_key)):
        """List available connectors."""
        return connectors.list_connectors()

    @app.post("/v1/memory/store")
    async def store_memory(req: MemoryStoreRequest, _=Depends(verify_api_key)):
        """Store a memory."""
        store = MemoryStore(db_path=config.memory_db or None)
        entry = await store.store(req.user_id, req.content, category=req.category)
        return {"id": entry.id, "stored": True}

    @app.post("/v1/memory/search")
    async def search_memory(req: MemorySearchRequest, _=Depends(verify_api_key)):
        """Search memories."""
        store = MemoryStore(db_path=config.memory_db or None)
        results = await store.search(req.user_id, req.query, limit=req.limit)
        return [
            {"content": r.content, "category": r.category, "relevance": round(r.relevance_score, 3)}
            for r in results
        ]

    @app.get("/v1/models")
    async def list_models(_=Depends(verify_api_key)):
        return router.list_models()

    @app.get("/health")
    async def health():
        return {"status": "ok", "architecture": "E", "version": "0.1.0"}

    return app


# Convenience: create app at module level for `uvicorn orchestra.arch_e:app`
try:
    app = create_app()
except ImportError:
    app = None  # FastAPI not installed; library-only mode


# ===========================================================================
# Docker Compose generator
# ===========================================================================

DOCKER_COMPOSE_TEMPLATE = """\
# Horizon Orchestra — Architecture E Production Stack
# Generated by orchestra.arch_e.generate_docker_compose()

version: "3.9"

services:
  # ── Kimi K2.5 Self-Hosted Inference ─────────────────────────────────────
  kimi-vllm:
    image: vllm/vllm-openai:nightly
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 8
              capabilities: [gpu]
    command: >
      --model moonshotai/Kimi-K2.5
      --tensor-parallel-size 8
      --tool-call-parser kimi_k2
      --reasoning-parser kimi_k2
      --max-model-len 262144
      --trust-remote-code
      --host 0.0.0.0
      --port 8000
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # ── API Gateway ─────────────────────────────────────────────────────────
  api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - KIMI_BASE_URL=http://kimi-vllm:8000/v1
      - MOONSHOT_API_KEY=${{MOONSHOT_API_KEY:-}}
      - PERPLEXITY_API_KEY=${{PERPLEXITY_API_KEY:-}}
      - OPENROUTER_API_KEY=${{OPENROUTER_API_KEY:-}}
      - OPENAI_API_KEY=${{OPENAI_API_KEY:-}}
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgresql://postgres:horizon@postgres:5432/orchestra
      - HORIZON_API_KEY=${{HORIZON_API_KEY:-}}
    depends_on:
      kimi-vllm:
        condition: service_healthy
      redis:
        condition: service_started
      postgres:
        condition: service_started
    restart: unless-stopped
    command: >
      uvicorn orchestra.arch_e:app
      --host 0.0.0.0
      --port 3000
      --workers 4

  # ── Code Execution Sandbox ──────────────────────────────────────────────
  sandbox:
    image: python:3.12-slim
    volumes:
      - workspace:/workspace
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:size=512M
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"

  # ── Browser Automation ──────────────────────────────────────────────────
  playwright:
    image: mcr.microsoft.com/playwright:v1.50.0-noble
    ports:
      - "3001:3001"
    restart: unless-stopped

  # ── Memory / State (PostgreSQL + pgvector) ──────────────────────────────
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_DB: orchestra
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: horizon
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped

  # ── Session Cache / Task Queue ──────────────────────────────────────────
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped
    volumes:
      - redisdata:/data

volumes:
  workspace:
  pgdata:
  redisdata:
"""

DOCKERFILE_TEMPLATE = """\
FROM python:3.12-slim

WORKDIR /app

# System deps for playwright and native packages
RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl build-essential && \\
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \\
    pip install --no-cache-dir fastapi uvicorn[standard]

COPY . .

EXPOSE 3000

CMD ["uvicorn", "orchestra.arch_e:app", "--host", "0.0.0.0", "--port", "3000"]
"""

ENV_TEMPLATE = """\
# Horizon Orchestra — Environment Variables
# Copy to .env and fill in your keys.

# Required: at least one model provider
MOONSHOT_API_KEY=
PERPLEXITY_API_KEY=
OPENROUTER_API_KEY=
OPENAI_API_KEY=

# Optional: API authentication for the Horizon Orchestra server
HORIZON_API_KEY=

# Optional: connector credentials
GITHUB_TOKEN=
SLACK_TOKEN=
GMAIL_TOKEN=
"""


def generate_docker_compose(output_dir: str = ".") -> dict[str, str]:
    """Write docker-compose.yml, Dockerfile, and .env.example to *output_dir*."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    files = {
        "docker-compose.yml": DOCKER_COMPOSE_TEMPLATE,
        "Dockerfile": DOCKERFILE_TEMPLATE,
        ".env.example": ENV_TEMPLATE,
    }

    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")
        log.info("Generated: %s", out / name)

    return {name: str(out / name) for name in files}
