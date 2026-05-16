from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Insight:
    category: str
    content: str
    source: str = ""
    confidence: float = 0.5
    timestamp: str = ""
    tags: list[str] = field(default_factory=list)
    times_applied: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class LearningStore:
    insights: list[Insight] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)
    patterns: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "insights": [asdict(i) for i in self.insights],
            "preferences": self.preferences,
            "patterns": self.patterns,
        }


_LEARNING_CATEGORIES = [
    "coding_style", "project_convention", "user_preference",
    "tool_preference", "error_pattern", "success_pattern",
    "domain_knowledge", "workflow_pattern", "security_insight",
]


class SelfLearningEngine:
    def __init__(self, store_path: str = ".agent-learnings.json"):
        self.store_path = Path(store_path)
        self.store = LearningStore()
        self._load()

    def record_insight(self, category: str, content: str, source: str = "", tags: Optional[list[str]] = None) -> Insight:
        existing = [i for i in self.store.insights if i.category == category and i.content == content]

        if existing:
            existing[0].times_applied += 1
            existing[0].confidence = min(1.0, existing[0].confidence + 0.1)
            self._save()
            return existing[0]

        insight = Insight(
            category=category,
            content=content,
            source=source,
            tags=tags or [],
            times_applied=1,
        )
        self.store.insights.append(insight)
        self._save()
        return insight

    def record_preference(self, key: str, value: str) -> None:
        self.store.preferences[key] = {"value": value, "recorded_at": datetime.now().isoformat()}
        self._save()

    def record_pattern(self, name: str, data: dict) -> None:
        self.store.patterns[name] = {**data, "recorded_at": datetime.now().isoformat()}
        self._save()

    def get_insights(self, category: Optional[str] = None, min_confidence: float = 0.0) -> list[Insight]:
        results = self.store.insights
        if category:
            results = [i for i in results if i.category == category]
        return [i for i in results if i.confidence >= min_confidence]

    def get_preference(self, key: str, default: str = "") -> str:
        pref = self.store.preferences.get(key)
        return pref["value"] if pref else default

    def extract_insights_from_conversation(self, conversation: list[dict]) -> list[Insight]:
        insights: list[Insight] = []

        for msg in conversation:
            content = msg.get("content", "")
            role = msg.get("role", "")

            if role == "assistant":
                continue

            # Coding style patterns
            for pattern, category in [
                (r"\bI (prefer|like|use|always) (\w+)", "tool_preference"),
                (r"\bdon'?t (use|like|want) (\w+)", "user_preference"),
                (r"\balways use (\w+)", "coding_style"),
                (r"\bnever use (\w+)", "coding_style"),
                (r"\bproject uses (\w+)", "project_convention"),
            ]:
                for m in re.finditer(pattern, content, re.IGNORECASE):
                    insight = Insight(category=category, content=m.group(), source="conversation")
                    insights.append(insight)

            # Error patterns
            if any(w in content.lower() for w in ["error", "failed", "bug", "issue", "broken"]):
                insights.append(Insight(
                    category="error_pattern",
                    content=content[:200],
                    source="conversation",
                    confidence=0.3,
                ))

        for i in insights:
            self.record_insight(i.category, i.content, i.source)
        return self.get_insights(min_confidence=0.1)

    def summarize_learnings(self) -> str:
        lines = [
            f"Self-Learning Summary",
            f"{'=' * 50}",
            f"Total insights: {len(self.store.insights)}",
            f"Preferences: {len(self.store.preferences)}",
            f"Patterns: {len(self.store.patterns)}",
            "",
        ]

        categories = set(i.category for i in self.store.insights)
        for cat in sorted(categories):
            cat_insights = [i for i in self.store.insights if i.category == cat]
            lines.append(f"\n{cat} ({len(cat_insights)}):")
            for i in sorted(cat_insights, key=lambda x: x.confidence, reverse=True)[:3]:
                lines.append(f"  [{i.confidence:.0%}] {i.content[:80]}")

        if self.store.preferences:
            lines.append(f"\nPreferences:")
            for k, v in self.store.preferences.items():
                lines.append(f"  {k}: {v['value']}")

        return "\n".join(lines)

    def _load(self) -> None:
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                self.store.insights = [Insight(**i) for i in data.get("insights", [])]
                self.store.preferences = data.get("preferences", {})
                self.store.patterns = data.get("patterns", {})
            except (json.JSONDecodeError, Exception):
                pass

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(
            json.dumps(self.store.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
