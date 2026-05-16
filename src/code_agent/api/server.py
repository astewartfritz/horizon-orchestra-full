from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from code_agent.agent import Agent
from code_agent.config import AgentConfig, LLMConfig
from code_agent.session import SessionManager


class RunRequest(BaseModel):
    task: str
    model: str = "gpt-4o"
    provider: str = "openai"
    max_iterations: int = 50
    session_id: str = ""
    stream: bool = False


class ReviewRequest(BaseModel):
    code: str
    model: str = "gpt-4o"
    provider: str = "openai"


class ReviewDiffRequest(BaseModel):
    diff: str
    repo_path: str | None = None


class ReviewPRRequest(BaseModel):
    title: str
    description: str
    diff: str


class SessionListResponse(BaseModel):
    sessions: list[dict[str, Any]] = []


class AgentAPI:
    def __init__(self, title: str = "Code Agent API"):
        self.app = FastAPI(title=title, version="0.4.0")
        self._active_agent: Agent | None = None
        self._register_routes()

    def _register_routes(self) -> None:
        app = self.app

        @app.get("/")
        async def root():
            return {
                "service": "Code Agent API",
                "version": "0.4.0",
                "endpoints": {
                    "GET /": "Service info",
                    "GET /health": "Health check",
                    "POST /run": "Run a code agent task",
                    "GET /agent/status": "Get active agent status",
                    "POST /review": "Review a piece of code",
                    "POST /review/diff": "Review a git diff",
                    "POST /review/pr": "Review a pull request",
                    "GET /sessions": "List sessions",
                    "GET /sessions/{session_id}": "Get session details",
                    "GET /tools": "List available tools",
                    "POST /knowledge/search": "Search knowledge base",
                    "GET /metrics": "Cost metrics",
                    "GET /logs": "Recent logs",
                },
            }

        @app.get("/health")
        async def health():
            return {"status": "ok", "version": "0.4.0"}

        @app.post("/run")
        async def run(req: RunRequest):
            llm = LLMConfig(provider=req.provider, model=req.model)
            cfg = AgentConfig(llm=llm, max_iterations=req.max_iterations)
            agent = Agent(cfg)
            self._active_agent = agent
            try:
                result = await asyncio.wait_for(agent.run(req.task, stream=False), timeout=300)
            except asyncio.TimeoutError:
                raise HTTPException(status_code=408, detail="Agent timed out after 300s")
            mgr = SessionManager()
            try:
                session = mgr.load(req.session_id) if req.session_id else None
            except Exception:
                session = None
            return {"result": result, "session_id": getattr(session, "id", "") if session else ""}

        @app.get("/agent/status")
        async def agent_status():
            if not self._active_agent:
                return {"status": "no_active_session"}
            s = self._active_agent.state
            return {
                "status": "running" if not s.finished else "finished",
                "iterations": s.iterations,
                "tool_rounds": s.tool_rounds,
                "finished": s.finished,
                "last_error": s.last_error,
            }

        @app.post("/review")
        async def review(req: ReviewRequest):
            from code_agent.reviewer import CodeReviewer
            reviewer = CodeReviewer()
            result = await reviewer.review(req.code)
            return {"review": result}

        @app.post("/review/diff")
        async def review_diff(req: ReviewDiffRequest):
            from code_agent.reviewer import CodeReviewer
            reviewer = CodeReviewer()
            result = await reviewer.review_diff(req.diff, repo_path=req.repo_path)
            return {"review": result}

        @app.post("/review/pr")
        async def review_pr(req: ReviewPRRequest):
            from code_agent.reviewer import CodeReviewer
            reviewer = CodeReviewer()
            result = await reviewer.review_pr(req.title, req.description, req.diff)
            return {"review": result}

        @app.get("/sessions")
        async def list_sessions():
            mgr = SessionManager()
            sessions = mgr.list_sessions()
            return {"sessions": sessions}

        @app.get("/sessions/{session_id}")
        async def get_session(session_id: str):
            mgr = SessionManager()
            session = mgr.load(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            return {
                "id": session.id,
                "task": session.task,
                "result": session.result,
                "created_at": session.created_at,
                "finished": session.finished,
            }

        @app.get("/tools")
        async def list_tools():
            from code_agent.tools import get_all_tools
            tools = get_all_tools()
            return {
                "tools": [
                    {"name": t.spec.name, "description": t.spec.description,
                     "parameters": t.spec.parameters}
                    for t in tools
                ]
            }

        @app.post("/knowledge/search")
        async def knowledge_search(query: str = "", top_k: int = 5):
            from code_agent.knowledge.base import KnowledgeBase
            kb = KnowledgeBase()
            results = kb.search(query, top_k=top_k)
            return {"results": [
                {"key": r.entry.key, "content": r.entry.content[:200],
                 "source": r.entry.source, "score": r.score}
                for r in results
            ]}

        @app.get("/metrics")
        async def metrics():
            from code_agent.cost.tracker import CostTracker
            tracker = CostTracker()
            return tracker.summary()

        @app.get("/logs")
        async def logs(n: int = 50):
            from code_agent.logbook import AgentLogger
            logger = AgentLogger.get()
            entries = logger.recent(n)
            from dataclasses import asdict
            return {"logs": [asdict(e) for e in entries]}

    async def run_server(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)
