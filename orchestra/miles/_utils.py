"""Shared utilities for the MILES subsystem.

Centralises the router-call helper and JSON parsing so each module
doesn't carry its own copy.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("orchestra.miles")


async def router_chat(
    router: Any,
    messages: list[dict[str, str]],
    model: str = "kimi-k2.5",
    max_tokens: int = 1000,
    temperature: float = 0.7,
) -> Any:
    """Invoke the Orchestra ModelRouter and return the raw API response.

    Bridges the gap between Orchestra's ``router.get_client(model)`` interface
    and the call sites in MILES that need a simple ``await router_chat(...)``
    pattern.
    """
    client, model_id = router.get_client(model)
    return await client.chat.completions.create(
        model=model_id,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def extract_content(resp: Any) -> str:
    """Pull text content out of any OpenAI-compatible response object."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return resp.get("content", "") or ""
    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        pass
    try:
        return resp.content or ""
    except AttributeError:
        return str(resp)


def safe_json_loads(text: str, default: Any = None) -> Any:
    """Parse JSON, stripping markdown fences if present."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return default
