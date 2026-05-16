from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel


def register_prince_routes(app: FastAPI) -> None:
    _prince_engine = None

    def _get_prince():
        nonlocal _prince_engine
        if _prince_engine is None:
            from code_agent.prince.engine import PrinceEngine
            _prince_engine = PrinceEngine(timeout=120)
        return _prince_engine

    class PrinceRequest(BaseModel):
        question: str
        provider: str = "ollama"
        model: str = "nemotron-mini"
        search_query: str = ""

    @app.post("/api/prince")
    async def prince_ask(req: PrinceRequest):
        eng = _get_prince()
        result = await eng.ask(req.question, search_query=req.search_query or None)
        return result
