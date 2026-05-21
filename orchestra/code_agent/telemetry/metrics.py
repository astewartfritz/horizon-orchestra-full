from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

llm_calls = Counter("llm_calls_total", "LLM calls", ["provider", "model", "status"])
llm_duration = Histogram("llm_call_duration_seconds", "LLM call latency", ["provider", "model"],
                         buckets=(1, 5, 10, 30, 60, 120, 300, 600))
llm_tokens = Counter("llm_tokens_total", "LLM tokens used", ["provider", "model", "type"])

agent_runs = Counter("agent_runs_total", "Agent runs", ["status"])
agent_duration = Histogram("agent_run_duration_seconds", "Agent run latency",
                           buckets=(10, 30, 60, 120, 300, 600, 1800))

tool_calls = Counter("tool_calls_total", "Tool calls", ["tool", "status"])
tool_duration = Histogram("tool_call_duration_seconds", "Tool call latency", ["tool"],
                          buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60))

requests_total = Counter("http_requests_total", "HTTP requests", ["method", "path", "status"])


def metrics_text() -> tuple[str, str]:
    return generate_latest().decode("utf-8"), CONTENT_TYPE_LATEST


def instrument_llm(provider: str, model: str):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                dur = time.time() - start
                llm_calls.labels(provider=provider, model=model, status="ok").inc()
                llm_duration.labels(provider=provider, model=model).observe(dur)
                return result
            except Exception as e:
                dur = time.time() - start
                llm_calls.labels(provider=provider, model=model, status="error").inc()
                llm_duration.labels(provider=provider, model=model).observe(dur)
                raise
        return wrapper
    return decorator


class LLMMetrics:
    _provider: str = ""
    _model: str = ""

    @classmethod
    def configure(cls, provider: str, model: str) -> None:
        cls._provider = provider
        cls._model = model

    @classmethod
    def record_call(cls, duration: float, status: str = "ok", prompt_tokens: int = 0,
                    completion_tokens: int = 0) -> None:
        llm_calls.labels(provider=cls._provider, model=cls._model, status=status).inc()
        llm_duration.labels(provider=cls._provider, model=cls._model).observe(duration)
        if prompt_tokens:
            llm_tokens.labels(provider=cls._provider, model=cls._model, type="prompt").inc(prompt_tokens)
        if completion_tokens:
            llm_tokens.labels(provider=cls._provider, model=cls._model, type="completion").inc(completion_tokens)

    @classmethod
    def record_tool(cls, name: str, duration: float, status: str = "ok") -> None:
        tool_calls.labels(tool=name, status=status).inc()
        tool_duration.labels(tool=name).observe(duration)
