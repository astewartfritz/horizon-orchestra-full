"""
intelligence.py — Proactive intelligence layer for MILES.

Anticipates user needs, learns from past behaviour, and predicts
likely next actions using n-gram modelling + LLM reasoning.
"""
from __future__ import annotations

__all__ = [
    "Suggestion",
    "Pattern",
    "ProactiveEngine",
    "ActionPredictor",
]

import json
import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Suggestion:
    """A proactive action suggestion surfaced to the user."""

    action: str
    reasoning: str
    confidence: float  # 0.0–1.0
    category: str      # e.g. "workflow", "communication", "focus"
    priority: str      # "low" | "medium" | "high"


@dataclass
class Pattern:
    """A learned workflow pattern derived from past behaviour."""

    trigger: str        # context / time-of-day / prior action
    action: str         # recommended action
    frequency: int      # how many times seen
    last_seen: float    # unix timestamp
    success_rate: float # 0.0–1.0


# ---------------------------------------------------------------------------
# ProactiveEngine
# ---------------------------------------------------------------------------


class ProactiveEngine:
    """
    Reads the user's memory and session history to suggest next actions
    and learns from outcomes to refine future suggestions.
    """

    _MEMORY_CATEGORY = "workflow"

    def __init__(
        self,
        memory_manager: Any,
        router: Any,
        user_id: str,
    ) -> None:
        self._memory = memory_manager
        self._router = router
        self._user_id = user_id
        logger.info("ProactiveEngine initialised for user_id=%s", user_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def suggest(self, current_context: str) -> list[Suggestion]:
        """
        Analyse *current_context* (plus memory/patterns) and return 1–3
        proactive action suggestions.
        """
        patterns = await self.get_patterns(limit=20)
        recent_memories = await self._fetch_recent_memories(limit=10)

        pattern_text = self._format_patterns(patterns)
        memory_text = self._format_memories(recent_memories)

        prompt = f"""You are a proactive AI assistant called MILES. Your job is to
anticipate what the user needs next and suggest helpful actions.

Current context:
{current_context}

Recent workflow patterns the user has established:
{pattern_text}

Recent activities and memories:
{memory_text}

Based on this information, suggest 1-3 proactive actions the user might want to
take right now. Return ONLY a JSON array (no markdown fences) of objects with
these fields:
  action       - concise description of the suggested action (str)
  reasoning    - why you're suggesting this (str)
  confidence   - float 0.0-1.0
  category     - one of: workflow, communication, focus, research, health
  priority     - one of: low, medium, high
"""
        suggestions: list[Suggestion] = []
        try:
            resp = await self._router.chat(
                messages=[{"role": "user", "content": prompt}],
                model="kimi-k2.5",
                max_tokens=800,
            )
            raw = _extract_content(resp)
            data = _safe_json_loads(raw, default=[])
            if isinstance(data, list):
                for item in data[:3]:
                    if not isinstance(item, dict):
                        continue
                    suggestions.append(
                        Suggestion(
                            action=str(item.get("action", "")),
                            reasoning=str(item.get("reasoning", "")),
                            confidence=float(item.get("confidence", 0.5)),
                            category=str(item.get("category", "workflow")),
                            priority=str(item.get("priority", "medium")),
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error("ProactiveEngine.suggest failed: %s", exc)

        logger.debug("Generated %d suggestions for context snippet='%.60s'", len(suggestions), current_context)
        return suggestions

    async def learn_pattern(
        self,
        action: str,
        context: str,
        outcome: str,
    ) -> None:
        """
        Persist a (trigger → action → outcome) triple into memory so that
        future calls to :meth:`suggest` can surface it.
        """
        key = f"pattern:{self._user_id}:{context[:40]}"
        # Load existing pattern if present
        existing: Optional[dict[str, Any]] = None
        try:
            existing = await self._memory.get(key)
        except Exception:  # noqa: BLE001
            pass

        success = outcome.strip().lower() not in ("fail", "error", "bad", "rejected")

        if existing and isinstance(existing, dict):
            freq = existing.get("frequency", 1) + 1
            old_sr = existing.get("success_rate", 1.0)
            # Rolling average
            new_sr = (old_sr * (freq - 1) + (1.0 if success else 0.0)) / freq
            pattern_data: dict[str, Any] = {
                **existing,
                "frequency": freq,
                "success_rate": round(new_sr, 4),
                "last_seen": time.time(),
            }
        else:
            pattern_data = {
                "trigger": context,
                "action": action,
                "outcome": outcome,
                "frequency": 1,
                "success_rate": 1.0 if success else 0.0,
                "last_seen": time.time(),
                "category": self._MEMORY_CATEGORY,
                "user_id": self._user_id,
            }

        try:
            await self._memory.set(key, pattern_data, category=self._MEMORY_CATEGORY)
            logger.debug("Pattern stored: key=%s action=%s", key, action)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to store pattern: %s", exc)

    async def get_patterns(self, limit: int = 20) -> list[Pattern]:
        """Retrieve stored workflow patterns, most-frequent first."""
        try:
            raw_patterns = await self._memory.search(
                category=self._MEMORY_CATEGORY,
                user_id=self._user_id,
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_patterns memory search failed: %s", exc)
            return []

        patterns: list[Pattern] = []
        for item in raw_patterns or []:
            data = item if isinstance(item, dict) else getattr(item, "__dict__", {})
            try:
                patterns.append(
                    Pattern(
                        trigger=str(data.get("trigger", "")),
                        action=str(data.get("action", "")),
                        frequency=int(data.get("frequency", 1)),
                        last_seen=float(data.get("last_seen", 0.0)),
                        success_rate=float(data.get("success_rate", 1.0)),
                    )
                )
            except (TypeError, ValueError):
                continue

        patterns.sort(key=lambda p: p.frequency, reverse=True)
        return patterns

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_recent_memories(self, limit: int = 10) -> list[dict[str, Any]]:
        try:
            return await self._memory.search(
                user_id=self._user_id,
                limit=limit,
            ) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("_fetch_recent_memories failed: %s", exc)
            return []

    @staticmethod
    def _format_patterns(patterns: list[Pattern]) -> str:
        if not patterns:
            return "(none yet)"
        lines = []
        for p in patterns:
            lines.append(
                f"- trigger='{p.trigger}' → action='{p.action}'"
                f" (seen {p.frequency}×, success_rate={p.success_rate:.0%})"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_memories(memories: list[dict[str, Any]]) -> str:
        if not memories:
            return "(none)"
        lines = []
        for m in memories:
            content = m.get("content") or m.get("text") or str(m)[:120]
            lines.append(f"- {content}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ActionPredictor
# ---------------------------------------------------------------------------


class ActionPredictor:
    """
    Predicts the user's next likely actions using:

    1. **N-gram model** — trained over the user's action history stored
       in memory (fast, interpretable).
    2. **LLM fallback** — for novel / ambiguous situations.
    """

    _N = 2  # bigram by default
    _MEMORY_KEY_PREFIX = "ngram_model"

    def __init__(self, memory_manager: Any, router: Any, user_id: str) -> None:
        self._memory = memory_manager
        self._router = router
        self._user_id = user_id
        # In-memory n-gram store: (context_tuple) -> Counter[next_action]
        self._ngrams: dict[tuple[str, ...], Counter] = defaultdict(Counter)
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def predict_next(self, history: list[str]) -> list[str]:
        """
        Given a sequence of recent actions in *history*, return up to 5
        predictions for what the user is likely to do next.

        Tries n-gram lookup first; falls back to LLM if confidence is low.
        """
        await self._ensure_loaded()

        predictions: list[str] = []

        # N-gram lookup
        if len(history) >= self._N:
            context = tuple(history[-self._N :])
            counter = self._ngrams.get(context, Counter())
            if counter:
                predictions = [action for action, _ in counter.most_common(5)]
                logger.debug(
                    "N-gram predictions for context=%s: %s",
                    context,
                    predictions,
                )

        # Update n-gram store with new observations
        await self._update_ngrams(history)

        # LLM fallback if n-gram has no data
        if not predictions:
            predictions = await self._llm_predict(history)

        return predictions[:5]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        key = f"{self._MEMORY_KEY_PREFIX}:{self._user_id}"
        try:
            data = await self._memory.get(key)
            if isinstance(data, dict):
                for ctx_str, counts in data.items():
                    ctx = tuple(ctx_str.split("\x00"))
                    self._ngrams[ctx] = Counter(counts)
            logger.debug("N-gram model loaded from memory.")
        except Exception as exc:  # noqa: BLE001
            logger.debug("N-gram load failed (fresh start): %s", exc)
        self._loaded = True

    async def _update_ngrams(self, history: list[str]) -> None:
        """Incorporate the new history window into the n-gram model."""
        if len(history) < self._N + 1:
            return
        dirty = False
        for i in range(len(history) - self._N):
            context = tuple(history[i : i + self._N])
            next_action = history[i + self._N]
            self._ngrams[context][next_action] += 1
            dirty = True
        if dirty:
            await self._persist_ngrams()

    async def _persist_ngrams(self) -> None:
        key = f"{self._MEMORY_KEY_PREFIX}:{self._user_id}"
        serialisable = {
            "\x00".join(ctx): dict(counter)
            for ctx, counter in self._ngrams.items()
        }
        try:
            await self._memory.set(key, serialisable, category="ngram")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist n-gram model: %s", exc)

    async def _llm_predict(self, history: list[str]) -> list[str]:
        recent = history[-10:] if len(history) > 10 else history
        history_text = "\n".join(f"{i+1}. {a}" for i, a in enumerate(recent))
        prompt = f"""You are an AI assistant helping predict what a user will do next
based on their recent action history.

Recent actions (oldest to newest):
{history_text}

List the 3-5 most likely next actions this user will take. Return ONLY a JSON
array of action strings, e.g. ["open email", "review PR", "check calendar"].
"""
        try:
            resp = await self._router.chat(
                messages=[{"role": "user", "content": prompt}],
                model="kimi-k2.5",
                max_tokens=200,
            )
            raw = _extract_content(resp)
            data = _safe_json_loads(raw, default=[])
            if isinstance(data, list):
                return [str(a) for a in data[:5]]
        except Exception as exc:  # noqa: BLE001
            logger.error("LLM action prediction failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Utility helpers (private)
# ---------------------------------------------------------------------------


def _extract_content(resp: Any) -> str:
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return resp.get("content", "") or ""
    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        pass
    try:
        return resp.content or ""
    except AttributeError:
        return str(resp)


def _safe_json_loads(text: str, default: Any = None) -> Any:
    """Parse JSON, stripping markdown fences if present."""
    import re
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return default
