from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


ERROR_CATEGORIES = {
    "syntax": {"keywords": ["syntaxerror", "syntax error", "unexpected token", "invalid syntax"]},
    "import": {"keywords": ["importerror", "modulenotfound", "import error", "cannot import"]},
    "type": {"keywords": ["typeerror", "type error", "cannot unpack", "argument mismatch"]},
    "attribute": {"keywords": ["attributeerror", "has no attribute"]},
    "index": {"keywords": ["indexerror", "index out of", "keyerror"]},
    "file": {"keywords": ["filenotfound", "permission denied", "ioerror"]},
    "network": {"keywords": ["timeouterror", "connectionerror", "httperror", "requests"]},
    "api": {"keywords": ["rate limit", "429", "401", "403", "api key"]},
    "memory": {"keywords": ["memoryerror", "out of memory", "oom"]},
    "llm": {"keywords": ["context length", "max_tokens", "token limit", "content_filter"]},
}


@dataclass
class ErrorRecord:
    error_text: str = ""
    category: str = "unknown"
    source: str = ""
    timestamp: float = 0.0
    solution: str = ""
    count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ErrorLearner:
    """Learn from errors: categorize, store, suggest solutions."""

    def __init__(self, storage_path: str = ".agent-errors.json"):
        self.path = Path(storage_path)
        self.records: list[ErrorRecord] = []
        self._load()

    def _classify(self, error_text: str) -> str:
        lower = error_text.lower()
        for category, rules in ERROR_CATEGORIES.items():
            for kw in rules["keywords"]:
                if kw in lower:
                    return category
        return "unknown"

    def _get_solution(self, category: str, error_text: str) -> str:
        solutions = {
            "syntax": "Check for missing parentheses, brackets, or quotes. Use a linter.",
            "import": "Install missing package: `pip install <package>`. Check import path.",
            "type": "Verify argument types and function signatures. Add type hints.",
            "attribute": "Check object has the attribute before accessing. Verify spelling.",
            "index": "Check list/dict bounds before access. Use .get() for dicts.",
            "file": "Verify file path exists and has correct permissions.",
            "network": "Check internet connection, retry with backoff, increase timeout.",
            "api": "Check API key validity, rate limits, and authentication headers.",
            "memory": "Process data in chunks, use generators, reduce batch size.",
            "llm": "Reduce prompt length, use conversation summarization, increase max_tokens.",
        }
        return solutions.get(category, "Review the error message and traceback for clues.")

    def record(self, error_text: str, source: str = "") -> ErrorRecord:
        category = self._classify(error_text)

        for existing in self.records:
            if existing.category == category and existing.source == source:
                existing.count += 1
                existing.timestamp = time.time()
                self._save()
                return existing

        rec = ErrorRecord(
            error_text=error_text[:500],
            category=category,
            source=source,
            timestamp=time.time(),
            solution=self._get_solution(category, error_text),
        )
        self.records.append(rec)
        self._save()
        return rec

    def suggest(self, error_text: str) -> str:
        category = self._classify(error_text)
        solution = self._get_solution(category, error_text)
        similar = [r for r in self.records if r.category == category]

        parts = [f"[{category}] {solution}"]
        if similar:
            parts.append(f"\nPreviously seen {len(similar)} times in category '{category}'")
            if similar[-1].source:
                parts.append(f"Last source: {similar[-1].source}")

        return "\n".join(parts)

    def stats(self) -> dict[str, Any]:
        categories: dict[str, int] = {}
        for r in self.records:
            categories[r.category] = categories.get(r.category, 0) + r.count
        return {
            "total_errors": sum(r.count for r in self.records),
            "unique_errors": len(self.records),
            "categories": categories,
            "file": str(self.path),
        }

    def clear(self) -> None:
        self.records.clear()
        self._save()

    def _save(self) -> None:
        data = [r.to_dict() for r in self.records]
        self.path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self.records = [ErrorRecord(**d) for d in data]
            except (json.JSONDecodeError, TypeError):
                self.records = []
