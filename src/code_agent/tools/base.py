from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    output: str = ""
    error: str | None = None
    base64_image: str | None = None
    system: str | None = None

    def __bool__(self) -> bool:
        return self.error is None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False


class Tool:
    spec: ToolSpec

    async def __call__(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError
