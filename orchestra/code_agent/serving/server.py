from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from orchestra.code_agent.config import AgentConfig, LLMConfig
from orchestra.code_agent.serving.base import ProviderConfig
from orchestra.code_agent.serving.factory import ProviderFactory
from orchestra.code_agent.serving.health import ModelHealthChecker
from orchestra.code_agent.serving.registry import ModelRegistry
from orchestra.code_agent.serving.router import ModelRouter


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    model: str = "gpt-4o"
    provider: str = "openai"
    stream: bool = False
    max_tokens: int = 8192
    temperature: float = 0.0
    tools: list[dict[str, Any]] | None = None


class ChatResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: dict[str, Any] = field(default_factory=dict)


class RegisterModelRequest(BaseModel):
    model_id: str
    provider: str
    capabilities: list[str] = []
    context_window: int = 8192
    max_output_tokens: int = 4096
    cost_per_million_input: float = 0.0
    cost_per_million_output: float = 0.0
    aliases: list[str] = []


class ServingServer:
    def __init__(
        self,
        registry: ModelRegistry | None = None,
        router: ModelRouter | None = None,
        health_checker: ModelHealthChecker | None = None,
        title: str = "Code Agent Serving API",
    ):
        self.app = FastAPI(title=title, version="0.4.0")
        self.registry = registry or ModelRegistry()
        self.router = router or ModelRouter(self.registry)
        self.health = health_checker or ModelHealthChecker()
        self._register_routes()

    def _register_routes(self) -> None:
        app = self.app

        @app.get("/health")
        async def health():
            return {"status": "ok", "service": "model-serving", "version": "0.4.0"}

        @app.post("/v1/chat/completions")
        async def chat_completions(req: ChatRequest):
            from orchestra.code_agent.llm.base import Message

            messages = [Message(**m) for m in req.messages]
            cfg = ProviderConfig(
                max_tokens=req.max_tokens,
                temperature=req.temperature,
            )

            if req.stream:
                return StreamingResponse(
                    self._stream_chat(req.provider, req.model, messages, req.tools, cfg),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )

            provider = ProviderFactory.create(req.provider, req.model, cfg)
            result = await provider.chat(messages, req.tools)

            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "model": req.model,
                "provider": req.provider,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": result.content,
                        "tool_calls": result.tool_calls,
                    },
                    "finish_reason": "stop",
                }],
                "usage": {"total_tokens": len(result.content)},
            }

        @app.post("/v1/chat/router")
        async def chat_router(req: ChatRequest):
            from orchestra.code_agent.llm.base import Message

            messages = [Message(**m) for m in req.messages]
            result = await self.router.route_chat(
                messages,
                req.tools,
                task=messages[-1].content if messages else "",
            )
            if not result.success:
                raise HTTPException(status_code=502, detail=f"All routing attempts failed: {result.attempts}")
            return {
                "content": result.output,
                "provider": result.provider,
                "model": result.model,
                "attempts": len(result.attempts),
                "latency_seconds": round(result.total_latency, 3),
            }

        @app.post("/v1/models/register")
        async def register_model(req: RegisterModelRequest):
            entry = self.registry.register(
                model_id=req.model_id,
                provider=req.provider,
                capabilities=req.capabilities,
                context_window=req.context_window,
                max_output_tokens=req.max_output_tokens,
                cost_per_million_input=req.cost_per_million_input,
                cost_per_million_output=req.cost_per_million_output,
                aliases=req.aliases,
            )
            return {"status": "registered", "model_id": entry.model_id}

        @app.delete("/v1/models/{model_id}")
        async def unregister_model(model_id: str):
            if self.registry.unregister(model_id):
                return {"status": "unregistered", "model_id": model_id}
            raise HTTPException(status_code=404, detail=f"Model {model_id} not found")

        @app.get("/v1/models")
        async def list_models(provider: str | None = None):
            models = self.registry.list_models(provider=provider)
            return {"models": [
                {
                    "id": m.model_id,
                    "provider": m.provider,
                    "capabilities": [c.value for c in m.capabilities],
                    "context_window": m.context_window,
                    "cost_per_million_input": m.cost_per_million_input,
                    "cost_per_million_output": m.cost_per_million_output,
                    "health_status": m.health_status,
                    "aliases": m.aliases,
                }
                for m in models
            ]}

        @app.get("/v1/models/{model_id}")
        async def get_model(model_id: str):
            entry = self.registry.get(model_id)
            if not entry:
                raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
            return {
                "id": entry.model_id,
                "provider": entry.provider,
                "capabilities": [c.value for c in entry.capabilities],
                "context_window": entry.context_window,
                "cost_per_million_input": entry.cost_per_million_input,
                "cost_per_million_output": entry.cost_per_million_output,
                "health_status": entry.health_status,
                "aliases": entry.aliases,
            }

        @app.get("/v1/health/probes")
        async def health_probes():
            results = self.health.get_all_results()
            return {
                "probes": {
                    k: {"healthy": r.healthy, "latency_ms": r.latency_ms, "error": r.error, "checked_at": r.checked_at}
                    for k, r in results.items()
                }
            }

        @app.post("/v1/health/probe")
        async def health_probe(provider: str, model: str):
            result = await self.health.probe(provider, model)
            return {
                "provider": result.provider,
                "model": result.model,
                "healthy": result.healthy,
                "latency_ms": result.latency_ms,
                "error": result.error,
            }

        @app.get("/v1/registry/summary")
        async def registry_summary():
            return self.registry.summary()

        @app.post("/v1/provider/{provider}/chat")
        async def provider_chat(provider: str, req: ChatRequest):
            from orchestra.code_agent.llm.base import Message

            messages = [Message(**m) for m in req.messages]
            cfg = ProviderConfig(
                max_tokens=req.max_tokens,
                temperature=req.temperature,
            )
            instance = ProviderFactory.create(provider, req.model, cfg)
            result = await instance.chat(messages, req.tools)
            return {
                "content": result.content,
                "tool_calls": result.tool_calls,
            }

    async def _stream_chat(
        self,
        provider: str,
        model: str,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        cfg: ProviderConfig,
    ) -> AsyncGenerator[str, None]:
        instance = ProviderFactory.create(provider, model, cfg)
        try:
            async for token in instance.chat_stream(messages, tools):
                data = json.dumps({
                    "choices": [{"delta": {"content": token}, "index": 0}],
                })
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            error_data = json.dumps({"error": str(e)})
            yield f"data: {error_data}\n\n"
            yield "data: [DONE]\n\n"

    async def run_server(self, host: str = "127.0.0.1", port: int = 8300) -> None:
        import uvicorn
        self.health.start()
        try:
            uvicorn.run(self.app, host=host, port=port)
        finally:
            await self.health.stop()
