from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Notification:
    title: str
    body: str
    level: str = "info"
    metadata: dict[str, Any] | None = None


class Notifier(ABC):
    @abstractmethod
    async def send(self, notification: Notification) -> bool:
        ...

    async def info(self, title: str, body: str, **meta: Any) -> bool:
        return await self.send(Notification(title, body, "info", meta or None))

    async def warn(self, title: str, body: str, **meta: Any) -> bool:
        return await self.send(Notification(title, body, "warning", meta or None))

    async def error(self, title: str, body: str, **meta: Any) -> bool:
        return await self.send(Notification(title, body, "error", meta or None))

    async def success(self, title: str, body: str, **meta: Any) -> bool:
        return await self.send(Notification(title, body, "success", meta or None))
