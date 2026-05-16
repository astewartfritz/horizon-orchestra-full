from __future__ import annotations

from typing import Any


class ConversationSummarizer:
    """Compress and summarize long conversations to fit within context windows."""

    def __init__(self, max_tokens: int = 4000, model: str = "gpt-4"):
        self.max_tokens = max_tokens
        self._model = model
        self._encoder = None

    def _get_encoder(self):
        if self._encoder is None:
            try:
                import tiktoken
                try:
                    self._encoder = tiktoken.encoding_for_model(self._model)
                except Exception:
                    self._encoder = tiktoken.get_encoding("cl100k_base")
            except ImportError:
                self._encoder = None
        return self._encoder

    def count_tokens(self, text: str) -> int:
        enc = self._get_encoder()
        if enc:
            return len(enc.encode(text))
        return len(text) // 4

    def should_summarize(self, messages: list[dict[str, str]]) -> bool:
        total = sum(self.count_tokens(m.get("content", "")) for m in messages)
        return total > self.max_tokens

    def compress(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        if not self.should_summarize(messages):
            return messages

        # Strategy: keep system, first N exchanges, last N exchanges, summarize the middle
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if len(non_system) <= 6:
            return messages

        keep_first = 3
        keep_last = 3
        head = non_system[:keep_first]
        tail = non_system[-keep_last:]
        middle = non_system[keep_first:-keep_last]

        # Summarize the middle
        total_middle = sum(self.count_tokens(m.get("content", "")) for m in middle)
        summary = (
            f"[{len(middle)} messages ({total_middle} tokens) from earlier in conversation "
            f"summarized. Key topics: {self._extract_topics(middle)}]"
        )

        compressed = system_msgs + head + [{"role": "system", "content": f"Summary of earlier context: {summary}"}] + tail
        return compressed

    def _extract_topics(self, messages: list[dict[str, str]]) -> str:
        keywords = set()
        for m in messages:
            content = m.get("content", "")
            words = content.lower().split()[:100]
            for w in words:
                if len(w) > 5 and w not in ("the", "this", "that", "with", "from", "have", "been", "what", "when", "where"):
                    keywords.add(w)
        return ", ".join(list(keywords)[:15])
