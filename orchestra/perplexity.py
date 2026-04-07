"""Horizon Orchestra — Perplexity API Integration.

Two wrappers:

* :class:`PerplexitySearch` — Sonar API for web-grounded search with
  citations (``/chat/completions``).
* :class:`PerplexityAgent` — Agent API for multi-model access with
  built-in ``web_search`` / ``fetch_url`` tools and custom function
  calling (``/v1/responses``).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

__all__ = [
    "SearchResult",
    "AgentResponse",
    "PerplexitySearch",
    "PerplexityAgent",
]

log = logging.getLogger("orchestra.perplexity")

_DEFAULT_AGENT_MODELS = [
    "openai/gpt-5.4",
    "anthropic/claude-opus-4-6",
    "perplexity/sonar-pro",
]


# ---------------------------------------------------------------------------
# Response dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """Result from a Sonar search."""
    content: str
    citations: list[str] = field(default_factory=list)
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """Result from the Agent API."""
    text: str
    model: str = ""
    citations: list[str] = field(default_factory=list)
    annotations: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sonar search
# ---------------------------------------------------------------------------

class PerplexitySearch:
    """Web-grounded search via the Perplexity Sonar API.

    Uses the ``/chat/completions`` endpoint with Sonar models.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "PERPLEXITY_API_KEY is not set. "
                    "Pass api_key= or export PERPLEXITY_API_KEY."
                )
            self._client = AsyncOpenAI(
                base_url="https://api.perplexity.ai",
                api_key=self.api_key,
            )
        return self._client

    async def search(
        self,
        query: str,
        model: str = "sonar",
        recency: str | None = None,
        domain_filter: list[str] | None = None,
        return_citations: bool = True,
    ) -> SearchResult:
        """Run a web-grounded search."""
        extra_body: dict[str, Any] = {}
        if recency:
            extra_body["search_recency_filter"] = recency
        if domain_filter:
            extra_body["search_domain_filter"] = domain_filter
        if return_citations:
            extra_body["return_citations"] = True

        try:
            resp = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": query}],
                extra_body=extra_body if extra_body else None,
            )
        except Exception as exc:
            log.error("Sonar search failed: %s", exc)
            return SearchResult(content=f"Search error: {exc}")

        content = resp.choices[0].message.content or ""
        citations = getattr(resp, "citations", []) or []
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }

        return SearchResult(
            content=content,
            citations=citations,
            model=resp.model or model,
            usage=usage,
        )

    async def deep_research(self, query: str) -> SearchResult:
        """Multi-step research using ``sonar-reasoning-pro``."""
        return await self.search(query, model="sonar-reasoning-pro")


# ---------------------------------------------------------------------------
# Agent API
# ---------------------------------------------------------------------------

class PerplexityAgent:
    """Multi-model Agent API with built-in web tools.

    Uses the ``/v1/responses`` endpoint (OpenAI Responses API compatible).
    Gives access to GPT-5.4, Claude, Grok, and Sonar through a single
    Perplexity API key.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "PERPLEXITY_API_KEY is not set. "
                    "Pass api_key= or export PERPLEXITY_API_KEY."
                )
            self._client = AsyncOpenAI(
                base_url="https://api.perplexity.ai/v1",
                api_key=self.api_key,
            )
        return self._client

    async def run(
        self,
        prompt: str,
        model: str = "openai/gpt-5.4",
        tools: list[dict[str, Any]] | None = None,
        instructions: str = "",
    ) -> AgentResponse:
        """Execute a task through the Agent API.

        Default tools are ``web_search`` + ``fetch_url``.  Pass custom
        function definitions via *tools* to add your own.
        """
        if tools is None:
            tools = [{"type": "web_search"}, {"type": "fetch_url"}]

        kwargs: dict[str, Any] = {
            "model": model,
            "input": prompt,
            "tools": tools,
        }
        if instructions:
            kwargs["instructions"] = instructions

        try:
            resp = await self.client.responses.create(**kwargs)
        except AttributeError:
            # Fallback: if the SDK version doesn't expose .responses,
            # use raw HTTP via the client.
            return await self._fallback_run(prompt, model, tools, instructions)
        except Exception as exc:
            log.error("Agent API call failed: %s", exc)
            return AgentResponse(text=f"Agent API error: {exc}", model=model)

        text = getattr(resp, "output_text", "") or ""
        citations: list[str] = []
        annotations: list[dict[str, Any]] = []

        # Parse structured output
        for item in getattr(resp, "output", []):
            if hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "annotations"):
                        for ann in block.annotations:
                            ann_dict = ann.model_dump() if hasattr(ann, "model_dump") else dict(ann)
                            annotations.append(ann_dict)
                            if ann_dict.get("type") == "citation" and "url" in ann_dict:
                                citations.append(ann_dict["url"])

        usage = {}
        if hasattr(resp, "usage") and resp.usage:
            usage = resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage)

        return AgentResponse(
            text=text,
            model=getattr(resp, "model", model),
            citations=citations,
            annotations=annotations,
            usage=usage,
        )

    async def _fallback_run(
        self,
        prompt: str,
        model: str,
        tools: list[dict[str, Any]],
        instructions: str,
    ) -> AgentResponse:
        """HTTP fallback if the SDK lacks ``.responses``."""
        import httpx

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model,
            "input": prompt,
            "tools": tools,
        }
        if instructions:
            body["instructions"] = instructions

        try:
            async with httpx.AsyncClient(timeout=120) as http:
                r = await http.post(
                    "https://api.perplexity.ai/v1/responses",
                    headers=headers,
                    json=body,
                )
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            return AgentResponse(text=f"Agent API fallback error: {exc}", model=model)

        # Parse the OpenAI Responses API format
        text = ""
        citations: list[str] = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        text += block.get("text", "")
                        for ann in block.get("annotations", []):
                            if ann.get("type") == "citation" and "url" in ann:
                                citations.append(ann["url"])

        return AgentResponse(
            text=text,
            model=data.get("model", model),
            citations=citations,
            annotations=[],
            usage=data.get("usage", {}),
        )

    async def multi_model_council(
        self,
        prompt: str,
        models: list[str] | None = None,
    ) -> list[AgentResponse]:
        """Query multiple models in parallel and return all responses.

        Useful for consensus-based or comparative analysis.
        """
        models = models or _DEFAULT_AGENT_MODELS
        import asyncio

        coros = [self.run(prompt, model=m) for m in models]
        results = await asyncio.gather(*coros, return_exceptions=True)

        responses: list[AgentResponse] = []
        for model_name, result in zip(models, results):
            if isinstance(result, Exception):
                responses.append(AgentResponse(
                    text=f"Error from {model_name}: {result}",
                    model=model_name,
                ))
            else:
                responses.append(result)
        return responses
