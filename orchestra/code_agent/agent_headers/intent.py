from __future__ import annotations

from typing import Any, Callable

from orchestra.code_agent.agent_headers.models import Intent

__all__ = [
    "Intent",
    "IntentRouter",
    "parse_intent",
]

_INTENT_HEADER = "X-Agent-Intent"


def parse_intent(headers: dict[str, str]) -> Intent:
    raw = headers.get(_INTENT_HEADER) or headers.get(_INTENT_HEADER.lower(), "")
    try:
        return Intent(raw.lower().strip())
    except ValueError:
        return Intent.UNKNOWN


class IntentRouter:
    """Maps agent intents (from ``X-Agent-Intent``) to handler functions.

    Allows agents to declare their goal in a single header,
    minimizing the number of endpoint calls needed.
    """

    def __init__(self) -> None:
        self._handlers: dict[Intent, Callable[..., Any]] = {}

    def register(self, intent: Intent, handler: Callable[..., Any]) -> None:
        self._handlers[intent] = handler

    def dispatch(self, intent: Intent, *args: Any, **kwargs: Any) -> Any:
        handler = self._handlers.get(intent)
        if handler is None:
            handler = self._handlers.get(Intent.UNKNOWN)
        if handler is None:
            raise KeyError(f"No handler registered for intent: {intent.value}")
        return handler(*args, **kwargs)

    def has_handler(self, intent: Intent) -> bool:
        return intent in self._handlers

    @staticmethod
    def header_name() -> str:
        return _INTENT_HEADER
