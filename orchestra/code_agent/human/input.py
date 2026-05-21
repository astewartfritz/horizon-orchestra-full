from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HumanRequest:
    id: str = ""
    question: str = ""
    context: str = ""
    options: list[str] = field(default_factory=list)
    response: str = ""
    answered: bool = False
    timeout: float = 0.0


class HumanInputHandler:
    """Pause agent execution and request human input."""

    def __init__(self):
        self._pending_requests: list[HumanRequest] = []
        self._request_id = 0

    async def ask(self, question: str, context: str = "",
                  options: list[str] | None = None,
                  timeout: float = 300.0) -> str:
        self._request_id += 1
        req = HumanRequest(
            id=f"req_{self._request_id}",
            question=question,
            context=context,
            options=options or [],
            timeout=timeout,
        )
        self._pending_requests.append(req)

        # In CLI mode, read from stdin
        print(f"\n[HUMAN INPUT REQUIRED] {question}")
        if context:
            print(f"Context: {context[:500]}")
        if options:
            print(f"Options: {', '.join(options)}")
        print("Enter response (or 'skip' to continue): ", end="", flush=True)

        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(None, input),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            response = "(timeout)"
        except (EOFError, KeyboardInterrupt):
            response = "(cancelled)"

        req.response = response
        req.answered = True
        return response

    def get_pending(self) -> list[HumanRequest]:
        return [r for r in self._pending_requests if not r.answered]

    def answer(self, request_id: str, response: str) -> bool:
        for req in self._pending_requests:
            if req.id == request_id and not req.answered:
                req.response = response
                req.answered = True
                return True
        return False

    async def confirm(self, action: str, details: str = "") -> bool:
        response = await self.ask(
            f"Confirm: {action}",
            context=details,
            options=["yes", "no", "skip"],
        )
        return response.strip().lower() in ("yes", "y", "confirm")

    def requests(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "question": r.question,
                 "answered": r.answered, "response": r.response}
                for r in self._pending_requests]
