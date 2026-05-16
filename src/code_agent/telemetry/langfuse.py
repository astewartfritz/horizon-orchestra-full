from __future__ import annotations

import os
import time
from typing import Any

from code_agent.llm.base import LLMError

_LANGFUSE_INITIALIZED = False
_LANGFUSE_CLIENT: Any = None


def _get_langfuse():
    global _LANGFUSE_INITIALIZED, _LANGFUSE_CLIENT
    if not _LANGFUSE_INITIALIZED:
        _LANGFUSE_INITIALIZED = True
        host = os.environ.get("LANGFUSE_HOST", "").strip()
        pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
        sk = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
        if host and pk and sk:
            try:
                from langfuse import Langfuse
                _LANGFUSE_CLIENT = Langfuse(
                    public_key=pk,
                    secret_key=sk,
                    host=host,
                    sdk_integration="orchestra",
                )
            except Exception:
                pass
    return _LANGFUSE_CLIENT


def is_configured() -> bool:
    return _get_langfuse() is not None


LANGFUSE_CONFIGURED = os.environ.get("LANGFUSE_HOST", "").strip() != ""


class LangFuseTracer:
    """Records LLM and agent traces to LangFuse. No-op when not configured."""

    def __init__(self) -> None:
        self._client = _get_langfuse()

    def generation(
        self,
        name: str = "llm_call",
        model: str = "",
        provider: str = "",
        messages: list[dict[str, Any]] | None = None,
        response: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency: float = 0.0,
        status: str = "ok",
        trace_id: str = "",
    ) -> None:
        if not self._client:
            return
        try:
            self._client.generation(
                name=name,
                model=model,
                model_parameters={"provider": provider},
                input=messages or [],
                output=response,
                usage={
                    "input": prompt_tokens,
                    "output": completion_tokens,
                    "unit": "TOKENS",
                },
                latency=latency,
                level="ERROR" if status == "error" else "DEFAULT",
                trace_id=trace_id or None,
            )
        except Exception:
            pass

    def trace(
        self,
        trace_id: str,
        name: str = "agent_run",
        input: str = "",
        output: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._client:
            return
        try:
            self._client.trace(
                id=trace_id,
                name=name,
                input=input,
                output=output,
                metadata=metadata or {},
            )
        except Exception:
            pass

    def score(
        self,
        trace_id: str,
        name: str = "user_feedback",
        value: float = 1.0,
        comment: str = "",
    ) -> None:
        if not self._client:
            return
        try:
            self._client.score(
                trace_id=trace_id,
                name=name,
                value=value,
                comment=comment,
            )
        except Exception:
            pass

    def flush(self) -> None:
        if self._client:
            try:
                self._client.flush()
            except Exception:
                pass


_tracer = LangFuseTracer()


def get_tracer() -> LangFuseTracer:
    return _tracer
