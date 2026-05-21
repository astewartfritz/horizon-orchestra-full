from __future__ import annotations

from typing import Any

from orchestra.code_agent.cache.base import Cache, DiskCache
from orchestra.code_agent.llm.base import LLM, Message


class CachedLLM(LLM):
    def __init__(self, llm: LLM, cache: Cache | None = None):
        self._llm = llm
        self.cache = cache or DiskCache()

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> Message:
        if tools:
            return await self._llm.chat(messages, tools, tool_choice)

        raw = [{"role": m.role, "content": m.content} for m in messages]
        key = DiskCache.make_key(raw, self._llm.model)
        cached = self.cache.get(key)
        if cached is not None:
            return Message(role="assistant", content=cached)

        result = await self._llm.chat(messages, tools, tool_choice)
        if result.content:
            self.cache.set(key, result.content)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)
