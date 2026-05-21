"""Python logging.Handler that persists WARNING+ records to the Orchestra log store."""
from __future__ import annotations

import logging
import traceback

from .store import add_event, init_db

_NOISY_LOGGERS = {"uvicorn.access", "uvicorn.error", "watchfiles.main"}


class OrchestraLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.name in _NOISY_LOGGERS:
            return
        try:
            details: dict = {}
            if record.exc_info and record.exc_info[0] is not None:
                details["traceback"] = "".join(
                    traceback.format_exception(*record.exc_info)
                )
            if record.stack_info:
                details["stack_info"] = record.stack_info
            add_event(
                level=record.levelname,
                source=record.name,
                message=self.format(record),
                details=details or None,
            )
        except Exception:
            pass


def install_handler() -> None:
    """Wire the Orchestra log handler into the root logger (idempotent)."""
    init_db()
    root = logging.getLogger()
    if any(isinstance(h, OrchestraLogHandler) for h in root.handlers):
        return
    handler = OrchestraLogHandler(level=logging.WARNING)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
