from __future__ import annotations

"""Job dataclass for the Orchestra distributed job queue."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    """Represents a single unit of work in the queue."""

    id: str
    name: str
    payload: dict[str, Any]
    status: str = "pending"         # pending | running | done | failed | dead
    priority: int = 5               # 1 (highest) to 10 (lowest)
    max_retries: int = 3
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    retry_after: float | None = None  # epoch seconds; None means "ready now"

    @classmethod
    def new(
        cls,
        name: str,
        payload: dict[str, Any],
        priority: int = 5,
        max_retries: int = 3,
    ) -> "Job":
        """Create a new Job with a generated UUID."""
        return cls(
            id=uuid.uuid4().hex,
            name=name,
            payload=payload,
            priority=priority,
            max_retries=max_retries,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the job to a JSON-safe dict."""
        return {
            "id": self.id,
            "name": self.name,
            "payload": self.payload,
            "status": self.status,
            "priority": self.priority,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "retry_after": self.retry_after,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Job":
        """Deserialize a Job from a dict."""
        return cls(
            id=d["id"],
            name=d["name"],
            payload=d.get("payload", {}),
            status=d.get("status", "pending"),
            priority=d.get("priority", 5),
            max_retries=d.get("max_retries", 3),
            retry_count=d.get("retry_count", 0),
            created_at=d.get("created_at", time.time()),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            result=d.get("result"),
            error=d.get("error"),
            retry_after=d.get("retry_after"),
        )
