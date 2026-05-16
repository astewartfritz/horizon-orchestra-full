from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ReasoningModule:
    """A saved reasoning pattern for reuse."""
    name: str
    description: str
    strategy: str
    plan_template: str
    prompt_template: str
    tags: list[str] = field(default_factory=list)
    success_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ReasoningModule:
        return cls(**d)


@dataclass
class ErrorPattern:
    """A recurring error and its solution."""
    error_pattern: str
    solution: str
    count: int = 1
    tags: list[str] = field(default_factory=list)
    strategy: str = "reflect"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ErrorPattern:
        return cls(**d)


MODULES_DIR = Path(".agent-reasoning-modules")
ERRORS_FILE = Path(".agent-error-patterns.json")


class ModuleSaver:
    """Save and reuse reasoning modules — plans, strategies, error patterns."""

    def __init__(self, modules_dir: str | Path = MODULES_DIR):
        self.dir = Path(modules_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._errors_path = self.dir.parent / ERRORS_FILE

    # === Reasoning Modules ===

    def save_module(
        self,
        name: str,
        description: str,
        strategy: str,
        plan_template: str,
        prompt_template: str,
        tags: list[str] | None = None,
    ) -> ReasoningModule:
        mod = ReasoningModule(
            name=name,
            description=description,
            strategy=strategy,
            plan_template=plan_template,
            prompt_template=prompt_template,
            tags=tags or [],
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
        self._write_module(mod)
        return mod

    def update_module(self, name: str, **kwargs) -> ReasoningModule | None:
        mod = self.load_module(name)
        if not mod:
            return None
        for k, v in kwargs.items():
            if hasattr(mod, k):
                setattr(mod, k, v)
        mod.updated_at = datetime.utcnow().isoformat()
        self._write_module(mod)
        return mod

    def load_module(self, name: str) -> ReasoningModule | None:
        path = self.dir / f"{name}.json"
        if path.exists():
            return ReasoningModule.from_dict(json.loads(path.read_text("utf-8")))
        return None

    def delete_module(self, name: str) -> bool:
        path = self.dir / f"{name}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def list_modules(self) -> list[dict[str, Any]]:
        results = []
        for p in sorted(self.dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text("utf-8"))
                results.append({
                    "name": data.get("name", p.stem),
                    "strategy": data.get("strategy", "cot"),
                    "description": data.get("description", "")[:80],
                    "tags": data.get("tags", []),
                    "success_count": data.get("success_count", 0),
                })
            except Exception:
                continue
        return results

    def _write_module(self, mod: ReasoningModule) -> None:
        path = self.dir / f"{mod.name}.json"
        path.write_text(json.dumps(mod.to_dict(), indent=2), encoding="utf-8")

    # === Error Patterns ===

    def _load_errors(self) -> list[ErrorPattern]:
        if not self._errors_path.exists():
            return []
        try:
            data = json.loads(self._errors_path.read_text("utf-8"))
            return [ErrorPattern.from_dict(e) for e in data]
        except Exception:
            return []

    def _save_errors(self, errors: list[ErrorPattern]) -> None:
        self._errors_path.write_text(
            json.dumps([e.to_dict() for e in errors], indent=2),
            encoding="utf-8",
        )

    def record_error(
        self, error_text: str, solution: str, tags: list[str] | None = None
    ) -> ErrorPattern:
        errors = self._load_errors()
        # Find matching pattern
        for e in errors:
            if e.error_pattern.lower() in error_text.lower():
                e.count += 1
                e.solution = solution
                if tags:
                    e.tags = list(set(e.tags + tags))
                self._save_errors(errors)
                return e

        pattern = ErrorPattern(
            error_pattern=error_text[:200],
            solution=solution,
            tags=tags or [],
            created_at=datetime.utcnow().isoformat(),
        )
        errors.append(pattern)
        self._save_errors(errors)
        return pattern

    def find_solution(self, error_text: str) -> str | None:
        errors = self._load_errors()
        for e in errors:
            if e.error_pattern.lower() in error_text.lower():
                return e.solution
        return None

    def list_error_patterns(self) -> list[dict[str, Any]]:
        return [
            {
                "pattern": e.error_pattern[:80],
                "solution": e.solution[:120],
                "count": e.count,
                "tags": e.tags,
            }
            for e in self._load_errors()
        ]

    # === Session-to-Module Conversion ===

    def save_from_session(
        self, session_data: dict, name: str | None = None
    ) -> ReasoningModule | None:
        """Convert a successful reasoning session into a reusable module."""
        task = session_data.get("task", "")
        strategy = session_data.get("strategy", "cot")
        plan = session_data.get("plan", "")
        traces = session_data.get("traces", [])

        if not task:
            return None

        mod_name = name or f"plan_{task.replace(' ', '_')[:30]}"
        description = f"Reusable plan for: {task[:80]}"
        prompt_template = f"Follow this plan: {plan[:500]}" if plan else task

        return self.save_module(
            name=mod_name,
            description=description,
            strategy=strategy,
            plan_template=plan or "",
            prompt_template=prompt_template,
            tags=[strategy, "auto-saved"],
        )
