"""Horizon Orchestra — Text Chunking for Embeddings.

Splits text into overlapping chunks using configurable strategies:
fixed-token, sentence, paragraph, semantic, and recursive.

Token counting uses tiktoken when available, falling back to a simple
character-based estimator (len(text) // 4).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Literal, Optional, Sequence

__all__ = [
    "Chunk",
    "ChunkStrategy",
    "TextChunker",
]

log = logging.getLogger("orchestra.embeddings.chunker")


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

_tiktoken_encoder: Any = None


def _get_tiktoken_encoder() -> Any:
    """Lazily load the tiktoken encoder (or return None)."""
    global _tiktoken_encoder
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    try:
        import tiktoken
        _tiktoken_encoder = tiktoken.encoding_for_model("text-embedding-3-small")
        return _tiktoken_encoder
    except Exception:
        return None


def count_tokens(text: str) -> int:
    """Count tokens in *text*.

    Uses tiktoken if available, otherwise falls back to ``len(text) // 4``.
    """
    enc = _get_tiktoken_encoder()
    if enc is not None:
        return len(enc.encode(text))
    return max(1, len(text) // 4)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate *text* to at most *max_tokens*."""
    enc = _get_tiktoken_encoder()
    if enc is not None:
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return enc.decode(tokens[:max_tokens])
    # Fallback
    max_chars = max_tokens * 4
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Chunk dataclass
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """A single text chunk produced by the chunker."""

    text: str
    start: int         # character offset in original text
    end: int           # character offset (exclusive)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        """Estimated token count for this chunk."""
        return count_tokens(self.text)

    def __repr__(self) -> str:
        preview = self.text[:60].replace("\n", " ")
        return f"Chunk(start={self.start}, end={self.end}, tokens≈{self.token_count}, text={preview!r}…)"


# ---------------------------------------------------------------------------
# Strategy enum
# ---------------------------------------------------------------------------

class ChunkStrategy(str, Enum):
    """Available chunking strategies."""

    FIXED = "fixed"
    SENTENCE = "sentence"
    PARAGRAPH = "paragraph"
    SEMANTIC = "semantic"
    RECURSIVE = "recursive"


# ---------------------------------------------------------------------------
# Sentence / paragraph splitting helpers
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(
    r"(?<=[.!?])\s+|(?<=\.\")\s+|(?<=\.\u2019)\s+|\n{2,}"
)

_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence-like segments."""
    parts = _SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    parts = _PARAGRAPH_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Recursive separators (LangChain-style)
# ---------------------------------------------------------------------------

_DEFAULT_SEPARATORS: list[str] = [
    "\n\n",   # paragraphs
    "\n",     # lines
    ". ",     # sentences
    ", ",     # clauses
    " ",      # words
    "",       # characters (last resort)
]


def _split_on_separator(text: str, separator: str) -> list[str]:
    """Split text on a separator, keeping non-empty parts."""
    if separator == "":
        return list(text)
    parts = text.split(separator)
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# TextChunker
# ---------------------------------------------------------------------------

class TextChunker:
    """Configurable text chunker for embedding pipelines.

    Usage::

        chunker = TextChunker()
        chunks = chunker.chunk(
            "Long document text...",
            strategy="sentence",
            chunk_size=512,
            overlap=50,
        )
    """

    def __init__(
        self,
        *,
        default_chunk_size: int = 512,
        default_overlap: int = 50,
        default_strategy: ChunkStrategy | str = ChunkStrategy.RECURSIVE,
        embed_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        default_chunk_size:
            Default maximum tokens per chunk.
        default_overlap:
            Default overlap in tokens between adjacent chunks.
        default_strategy:
            Default chunking strategy.
        embed_fn:
            Optional synchronous embedding function for semantic chunking.
            Signature: ``(text) -> list[float]``.
        """
        if isinstance(default_strategy, str):
            default_strategy = ChunkStrategy(default_strategy)
        self.default_chunk_size = default_chunk_size
        self.default_overlap = default_overlap
        self.default_strategy = default_strategy
        self._embed_fn = embed_fn

    # -- public API ---------------------------------------------------------

    def chunk(
        self,
        text: str,
        strategy: ChunkStrategy | str | None = None,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[Chunk]:
        """Split *text* into chunks using the specified strategy.

        Parameters
        ----------
        text:
            The input text to chunk.
        strategy:
            Chunking strategy (defaults to instance default).
        chunk_size:
            Max tokens per chunk (defaults to instance default).
        overlap:
            Token overlap between consecutive chunks (defaults to instance default).

        Returns
        -------
        list[Chunk]
            Ordered list of non-overlapping-in-position chunks.
        """
        if not text or not text.strip():
            return []

        if strategy is None:
            strategy = self.default_strategy
        if isinstance(strategy, str):
            strategy = ChunkStrategy(strategy)
        if chunk_size is None:
            chunk_size = self.default_chunk_size
        if overlap is None:
            overlap = self.default_overlap

        # Dispatch to the strategy implementation
        dispatch = {
            ChunkStrategy.FIXED: self._chunk_fixed,
            ChunkStrategy.SENTENCE: self._chunk_sentence,
            ChunkStrategy.PARAGRAPH: self._chunk_paragraph,
            ChunkStrategy.SEMANTIC: self._chunk_semantic,
            ChunkStrategy.RECURSIVE: self._chunk_recursive,
        }
        fn = dispatch[strategy]
        chunks = fn(text, chunk_size, overlap)

        # Attach chunk index metadata
        for i, c in enumerate(chunks):
            c.metadata["chunk_index"] = i
            c.metadata["total_chunks"] = len(chunks)
            c.metadata["strategy"] = strategy.value

        return chunks

    # -- fixed strategy -----------------------------------------------------

    def _chunk_fixed(
        self,
        text: str,
        chunk_size: int,
        overlap: int,
    ) -> list[Chunk]:
        """Split text into fixed-token-count chunks with overlap."""
        chunks: list[Chunk] = []
        # Approximate character budget
        chars_per_token = max(1, len(text) / max(1, count_tokens(text)))
        char_chunk = int(chunk_size * chars_per_token)
        char_overlap = int(overlap * chars_per_token)
        step = max(1, char_chunk - char_overlap)

        pos = 0
        while pos < len(text):
            end = min(pos + char_chunk, len(text))
            # Try to break on whitespace
            if end < len(text):
                ws = text.rfind(" ", pos, end)
                if ws > pos:
                    end = ws + 1
            chunk_text = text[pos:end].strip()
            if chunk_text:
                chunks.append(Chunk(text=chunk_text, start=pos, end=end))
            pos += step
            if pos >= len(text):
                break

        return chunks

    # -- sentence strategy --------------------------------------------------

    def _chunk_sentence(
        self,
        text: str,
        chunk_size: int,
        overlap: int,
    ) -> list[Chunk]:
        """Split on sentence boundaries, merging until chunk_size."""
        sentences = _split_sentences(text)
        return self._merge_segments(text, sentences, chunk_size, overlap)

    # -- paragraph strategy -------------------------------------------------

    def _chunk_paragraph(
        self,
        text: str,
        chunk_size: int,
        overlap: int,
    ) -> list[Chunk]:
        """Split on paragraph boundaries, merging until chunk_size."""
        paragraphs = _split_paragraphs(text)
        return self._merge_segments(text, paragraphs, chunk_size, overlap)

    # -- semantic strategy --------------------------------------------------

    def _chunk_semantic(
        self,
        text: str,
        chunk_size: int,
        overlap: int,
    ) -> list[Chunk]:
        """Split on topic changes detected by embedding similarity.

        Falls back to sentence-based chunking if no embed_fn is configured.
        """
        if self._embed_fn is None:
            log.warning(
                "No embed_fn configured for semantic chunking — "
                "falling back to sentence strategy"
            )
            return self._chunk_sentence(text, chunk_size, overlap)

        sentences = _split_sentences(text)
        if len(sentences) <= 1:
            return self._chunk_sentence(text, chunk_size, overlap)

        # Embed each sentence
        embeddings = [self._embed_fn(s) for s in sentences]

        # Compute cosine similarity between consecutive sentences
        similarities: list[float] = []
        for i in range(len(embeddings) - 1):
            a, b = embeddings[i], embeddings[i + 1]
            dot = sum(x * y for x, y in zip(a, b))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(x * x for x in b) ** 0.5
            sim = dot / (na * nb) if (na > 0 and nb > 0) else 0.0
            similarities.append(sim)

        # Find split points where similarity drops significantly
        if not similarities:
            return self._chunk_sentence(text, chunk_size, overlap)

        mean_sim = sum(similarities) / len(similarities)
        std_sim = (
            sum((s - mean_sim) ** 2 for s in similarities) / len(similarities)
        ) ** 0.5
        threshold = mean_sim - std_sim  # split where sim is below 1 std

        # Group sentences into segments at split points
        segments: list[list[str]] = [[sentences[0]]]
        for i, sim in enumerate(similarities):
            if sim < threshold:
                segments.append([sentences[i + 1]])
            else:
                segments[-1].append(sentences[i + 1])

        merged_segments = [" ".join(seg) for seg in segments]
        return self._merge_segments(text, merged_segments, chunk_size, overlap)

    # -- recursive strategy -------------------------------------------------

    def _chunk_recursive(
        self,
        text: str,
        chunk_size: int,
        overlap: int,
    ) -> list[Chunk]:
        """Recursively split on a hierarchy of separators (LangChain-style)."""
        segments = self._recursive_split(text, _DEFAULT_SEPARATORS, chunk_size)
        return self._merge_segments(text, segments, chunk_size, overlap)

    def _recursive_split(
        self,
        text: str,
        separators: list[str],
        chunk_size: int,
    ) -> list[str]:
        """Recursively split text, trying each separator in order."""
        if count_tokens(text) <= chunk_size:
            return [text]

        for i, sep in enumerate(separators):
            parts = _split_on_separator(text, sep) if sep else [text[j:j+1] for j in range(len(text))]
            if len(parts) <= 1:
                continue
            # Recursively split any parts that are still too large
            result: list[str] = []
            for part in parts:
                if count_tokens(part) <= chunk_size:
                    result.append(part)
                else:
                    result.extend(
                        self._recursive_split(part, separators[i + 1:], chunk_size)
                    )
            return result

        # If no separator worked, just truncate
        return [_truncate_to_tokens(text, chunk_size)]

    # -- helper: merge small segments into chunks ---------------------------

    def _merge_segments(
        self,
        original_text: str,
        segments: list[str],
        chunk_size: int,
        overlap: int,
    ) -> list[Chunk]:
        """Merge small segments into chunks that respect chunk_size.

        Also handles overlap by re-adding trailing segments from the
        previous chunk.
        """
        if not segments:
            return []

        chunks: list[Chunk] = []
        current_parts: list[str] = []
        current_tokens = 0

        for seg in segments:
            seg_tokens = count_tokens(seg)
            if current_tokens + seg_tokens > chunk_size and current_parts:
                # Flush current chunk
                chunk_text = " ".join(current_parts)
                start = original_text.find(current_parts[0])
                if start == -1:
                    start = 0
                end = start + len(chunk_text)
                chunks.append(Chunk(text=chunk_text, start=start, end=min(end, len(original_text))))

                # Overlap: keep trailing segments whose total ≤ overlap
                overlap_parts: list[str] = []
                overlap_tokens = 0
                for p in reversed(current_parts):
                    pt = count_tokens(p)
                    if overlap_tokens + pt > overlap:
                        break
                    overlap_parts.insert(0, p)
                    overlap_tokens += pt

                current_parts = overlap_parts
                current_tokens = overlap_tokens

            current_parts.append(seg)
            current_tokens += seg_tokens

        # Flush remaining
        if current_parts:
            chunk_text = " ".join(current_parts)
            start = original_text.find(current_parts[0])
            if start == -1:
                start = 0
            end = start + len(chunk_text)
            chunks.append(Chunk(text=chunk_text, start=start, end=min(end, len(original_text))))

        return chunks
