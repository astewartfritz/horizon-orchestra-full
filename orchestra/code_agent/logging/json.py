from __future__ import annotations

import json
import logging
import time
import traceback
from typing import Any


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter.

    Produces single-line JSON records parsable by Logstash,
    Datadog, Splunk, etc.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "value": str(record.exc_info[1]),
                "traceback": "".join(traceback.format_exception(*record.exc_info)),
            }
        if hasattr(record, "props"):
            entry["props"] = record.props
        return json.dumps(entry, default=str)


def setup_json_logging(level: int = logging.INFO) -> None:
    """Replace all root handlers with structured JSON output to stderr."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
