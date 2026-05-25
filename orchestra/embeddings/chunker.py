"""Horizon Orchestra — Text Chunking for Embeddings.

Splits text into overlapping chunks using configurable strategies:
fixed-token, sentence, paragraph, semantic, and recursive.

Improvements over v1:
- _chunk_fixed: operates on actual token IDs via tiktoken (exact boundaries)
- _merge_segments: forward-scanning position tracker (no more wrong find() on repeated text)
- Separator presets for code and markdown; auto-detection from content
- min_chunk_size to suppress micro-fragments at chunk boundaries
- Semantic fallback to RECURSIVE (not SENTENCE — keeps structure)
- Tunable semantic sensitivity threshold
- chunk_code() / chunk_markdown() convenience wrappers
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
    "count_tokens",
]

log = logging.getLogger("orchestra.embeddings.chunker")


# ---------------------------------------------------------------------------
# Token counting  (tiktoken with heuristic fallback)
# ---------------------------------------------------------------------------

_tiktoken_encoder: Any = None


def _get_tiktoken_encoder() -> Any:
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
    """Count tokens. Uses tiktoken when available; falls back to len//4."""
    enc = _get_tiktoken_encoder()
    if enc is not None:
        return len(enc.encode(text))
    return max(1, len(text) // 4)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    enc = _get_tiktoken_encoder()
    if enc is not None:
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return enc.decode(tokens[:max_tokens])
    return text[: max_tokens * 4]


# ---------------------------------------------------------------------------
# Chunk dataclass
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """A single text chunk produced by the chunker."""

    text: str
    start: int   # character offset in original text
    end: int     # character offset (exclusive)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        return count_tokens(self.text)

    def __repr__(self) -> str:
        preview = self.text[:60].replace("\n", " ")
        return f"Chunk(start={self.start}, end={self.end}, tokens≈{self.token_count}, text={preview!r}…)"


# ---------------------------------------------------------------------------
# Strategy enum
# ---------------------------------------------------------------------------

class ChunkStrategy(str, Enum):
    FIXED     = "fixed"
    SENTENCE  = "sentence"
    PARAGRAPH = "paragraph"
    SEMANTIC  = "semantic"
    RECURSIVE = "recursive"


# ---------------------------------------------------------------------------
# Separator presets
# ---------------------------------------------------------------------------

# Generic prose
_DEFAULT_SEPARATORS: list[str] = ["\n\n", "\n", ". ", ", ", " ", ""]

# Markdown: split at headings first, then paragraphs, then lines
_MARKDOWN_SEPARATORS: list[str] = [
    "\n# ", "\n## ", "\n### ", "\n#### ",
    "\n\n", "\n", ". ", " ", "",
]

# Source code: class/function boundaries first
_CODE_SEPARATORS: list[str] = [
    "\nclass ", "\ndef ", "\n\tasync def ", "\n    async def ",
    "\n\n", "\n", " ", "",
]


def _detect_separators(text: str) -> list[str]:
    """Heuristically pick separator preset from content signals."""
    sample = text[:2000]
    code_signals = sum([
        sample.count("\ndef ") > 1,
        sample.count("\nclass ") > 0,
        sample.count("    return ") > 1,
        sample.count("import ") > 2,
    ])
    md_signals = sum([
        sample.count("\n## ") > 0,
        sample.count("\n# ") > 0,
        sample.count("```") > 0,
        sample.count("**") > 2,
    ])
    if code_signals >= 2:
        return _CODE_SEPARATORS
    if md_signals >= 2:
        return _MARKDOWN_SEPARATORS
    return _DEFAULT_SEPARATORS


# ---------------------------------------------------------------------------
# Sentence / paragraph splitting helpers
# ---------------------------------------------------------------------------

# Handles Mr./Dr./etc. by NOT splitting when abbreviation precedes uppercase
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "cf",
    "e.g", "i.e", "dept", "approx", "est", "govt", "inc", "ltd", "co",
})

_SENTENCE_RE = re.compile(
    r"(?<=[.!?])\s+"
    r"|(?<=\.\")\s+|(?<=\.')\s+"
    r"|\n{2,}"
)

_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_RE.split(text)
    result = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        # Skip split if previous part ends with a known abbreviation
        if i > 0 and result:
            prev = result[-1].strip().lower().rstrip(".")
            if any(prev.endswith(abbr.rstrip(".")) for abbr in _ABBREVIATIONS):
                result[-1] = result[-1] + " " + part
                continue
        result.append(part)
    return result


def _split_paragraphs(text: str) -> list[str]:
    parts = _PARAGRAPH_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# TextChunker
# ---------------------------------------------------------------------------

class TextChunker:
    """Configurable text chunker for embedding pipelines.

    Usage::

        chunker = TextChunker()
        chunks = chunker.chunk("Long document text…")

        # Domain-specific:
        chunks = chunker.chunk_code(source_code)
        chunks = chunker.chunk_markdown(readme)
    """

    def __init__(
        self,
        *,
        default_chunk_size: int = 512,
        default_overlap: int = 50,
        default_strategy: ChunkStrategy | str = ChunkStrategy.RECURSIVE,
        min_chunk_size: int = 20,
        semantic_sensitivity: float = 1.0,
        embed_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        default_chunk_size:
            Maximum tokens per chunk.
        default_overlap:
            Overlap in tokens between adjacent chunks.
        default_strategy:
            Default chunking strategy.
        min_chunk_size:
            Minimum tokens for a chunk to be kept. Micro-fragments below
            this threshold are merged into the preceding chunk.
        semantic_sensitivity:
            Std-dev multiplier for the semantic split threshold.
            Higher = fewer, larger chunks; lower = finer splits.
            Default 1.0 (split where similarity drops > 1σ below mean).
        embed_fn:
            Optional synchronous embedding function for semantic chunking.
        """
        if isinstance(default_strategy, str):
            default_strategy = ChunkStrategy(default_strategy)
        self.default_chunk_size   = default_chunk_size
        self.default_overlap      = default_overlap
        self.default_strategy     = default_strategy
        self.min_chunk_size       = min_chunk_size
        self.semantic_sensitivity = semantic_sensitivity
        self._embed_fn            = embed_fn

    # -- public API ---------------------------------------------------------

    def chunk(
        self,
        text: str,
        strategy: ChunkStrategy | str | None = None,
        chunk_size: int | None = None,
        overlap: int | None = None,
        separators: list[str] | None = None,
    ) -> list[Chunk]:
        """Split *text* into chunks.

        Parameters
        ----------
        text:
            Input text.
        strategy:
            Chunking strategy (defaults to instance default).
        chunk_size:
            Max tokens per chunk (defaults to instance default).
        overlap:
            Token overlap between consecutive chunks.
        separators:
            Custom separator hierarchy for the recursive strategy.
            When None, auto-detected from content signals.
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

        dispatch = {
            ChunkStrategy.FIXED:     lambda: self._chunk_fixed(text, chunk_size, overlap),
            ChunkStrategy.SENTENCE:  lambda: self._chunk_sentence(text, chunk_size, overlap),
            ChunkStrategy.PARAGRAPH: lambda: self._chunk_paragraph(text, chunk_size, overlap),
            ChunkStrategy.SEMANTIC:  lambda: self._chunk_semantic(text, chunk_size, overlap),
            ChunkStrategy.RECURSIVE: lambda: self._chunk_recursive(
                text, chunk_size, overlap, separators or _detect_separators(text)
            ),
        }
        chunks = dispatch[strategy]()

        for i, c in enumerate(chunks):
            c.metadata["chunk_index"]  = i
            c.metadata["total_chunks"] = len(chunks)
            c.metadata["strategy"]     = strategy.value

        return chunks

    def chunk_code(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[Chunk]:
        """Chunk source code using code-aware separators."""
        return self.chunk(
            text,
            strategy=ChunkStrategy.RECURSIVE,
            chunk_size=chunk_size,
            overlap=overlap,
            separators=_CODE_SEPARATORS,
        )

    def chunk_markdown(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[Chunk]:
        """Chunk Markdown using heading-aware separators."""
        return self.chunk(
            text,
            strategy=ChunkStrategy.RECURSIVE,
            chunk_size=chunk_size,
            overlap=overlap,
            separators=_MARKDOWN_SEPARATORS,
        )

    # -- fixed strategy (token-accurate) ------------------------------------

    def _chunk_fixed(self, text: str, chunk_size: int, overlap: int) -> list[Chunk]:
        """Split into exactly chunk_size-token chunks using tiktoken token IDs."""
        enc = _get_tiktoken_encoder()
        if enc is not None:
            return self._chunk_fixed_tiktoken(text, chunk_size, overlap, enc)
        return self._chunk_fixed_charfallback(text, chunk_size, overlap)

    def _chunk_fixed_tiktoken(self, text: str, chunk_size: int, overlap: int, enc: Any) -> list[Chunk]:
        token_ids = enc.encode(text)
        step      = max(1, chunk_size - overlap)
        chunks: list[Chunk] = []

        pos = 0
        while pos < len(token_ids):
            end_tok = min(pos + chunk_size, len(token_ids))
            chunk_ids  = token_ids[pos:end_tok]
            chunk_text = enc.decode(chunk_ids)

            # Character offsets: decode prefix up to pos
            char_start = len(enc.decode(token_ids[:pos]))
            char_end   = char_start + len(chunk_text)

            if chunk_text.strip():
                chunks.append(Chunk(text=chunk_text.strip(), start=char_start, end=char_end))
            pos += step

        return self._filter_min_size(chunks)

    def _chunk_fixed_charfallback(self, text: str, chunk_size: int, overlap: int) -> list[Chunk]:
        chars_per_tok = max(1, len(text) / max(1, count_tokens(text)))
        char_chunk    = int(chunk_size * chars_per_tok)
        char_overlap  = int(overlap * chars_per_tok)
        step          = max(1, char_chunk - char_overlap)

        chunks: list[Chunk] = []
        pos = 0
        while pos < len(text):
            end = min(pos + char_chunk, len(text))
            if end < len(text):
                ws = text.rfind(" ", pos, end)
                if ws > pos:
                    end = ws + 1
            chunk_text = text[pos:end].strip()
            if chunk_text:
                chunks.append(Chunk(text=chunk_text, start=pos, end=end))
            pos += step

        return self._filter_min_size(chunks)

    # -- sentence strategy --------------------------------------------------

    def _chunk_sentence(self, text: str, chunk_size: int, overlap: int) -> list[Chunk]:
        return self._merge_segments(text, _split_sentences(text), chunk_size, overlap)

    # -- paragraph strategy -------------------------------------------------

    def _chunk_paragraph(self, text: str, chunk_size: int, overlap: int) -> list[Chunk]:
        return self._merge_segments(text, _split_paragraphs(text), chunk_size, overlap)

    # -- semantic strategy --------------------------------------------------

    def _chunk_semantic(self, text: str, chunk_size: int, overlap: int) -> list[Chunk]:
        """Split on topic changes detected via embedding cosine similarity.

        Falls back to RECURSIVE (not sentence) when no embed_fn is configured,
        preserving structural boundaries better than sentence-only.
        """
        if self._embed_fn is None:
            log.debug("No embed_fn — semantic chunking falls back to recursive")
            return self._chunk_recursive(text, chunk_size, overlap, _detect_separators(text))

        sentences = _split_sentences(text)
        if len(sentences) <= 2:
            return self._chunk_recursive(text, chunk_size, overlap, _detect_separators(text))

        embeddings = [self._embed_fn(s) for s in sentences]

        similarities: list[float] = []
        for i in range(len(embeddings) - 1):
            a, b = embeddings[i], embeddings[i + 1]
            dot  = sum(x * y for x, y in zip(a, b))
            na   = sum(x * x for x in a) ** 0.5
            nb   = sum(x * x for x in b) ** 0.5
            similarities.append(dot / (na * nb) if (na and nb) else 0.0)

        if not similarities:
            return self._chunk_sentence(text, chunk_size, overlap)

        mean_s = sum(similarities) / len(similarities)
        std_s  = (sum((s - mean_s) ** 2 for s in similarities) / len(similarities)) ** 0.5
        threshold = mean_s - self.semantic_sensitivity * std_s

        segments: list[list[str]] = [[sentences[0]]]
        for i, sim in enumerate(similarities):
            if sim < threshold:
                segments.append([sentences[i + 1]])
            else:
                segments[-1].append(sentences[i + 1])

        merged_segs = [" ".join(seg) for seg in segments]
        return self._merge_segments(text, merged_segs, chunk_size, overlap)

    # -- recursive strategy -------------------------------------------------

    def _chunk_recursive(
        self,
        text: str,
        chunk_size: int,
        overlap: int,
        separators: list[str] | None = None,
    ) -> list[Chunk]:
        if separators is None:
            separators = _detect_separators(text)
        segments = self._recursive_split(text, separators, chunk_size)
        return self._merge_segments(text, segments, chunk_size, overlap)

    def _recursive_split(
        self,
        text: str,
        separators: list[str],
        chunk_size: int,
    ) -> list[str]:
        if not separators or count_tokens(text) <= 1:
            return [text]

        for i, sep in enumerate(separators):
            if sep == "":
                parts = list(text)
            else:
                parts = [p for p in text.split(sep) if p]
            if len(parts) <= 1:
                continue
            result: list[str] = []
            for part in parts:
                result.extend(self._recursive_split(part, separators[i + 1:], chunk_size))
            return result

        return [_truncate_to_tokens(text, chunk_size)]

    # -- helper: merge segments → Chunk list --------------------------------

    def _merge_segments(
        self,
        original_text: str,
        segments: list[str],
        chunk_size: int,
        overlap: int,
    ) -> list[Chunk]:
        """Merge small segments into chunks that respect chunk_size.

        Position tracking uses a forward-scanning cursor so repeated or
        overlapping text never lands on the wrong offset.
        """
        if not segments:
            return []

        # Break any segment that already exceeds chunk_size
        normalized: list[str] = []
        for seg in segments:
            if count_tokens(seg) > chunk_size:
                normalized.extend(self._recursive_split(seg, _DEFAULT_SEPARATORS, chunk_size))
            else:
                normalized.append(seg)
        segments = normalized

        chunks: list[Chunk] = []
        current_parts: list[str] = []
        current_tokens = 0
        # Forward-scanning cursor: next search must begin at or after this offset
        search_from = 0

        def _flush_chunk(parts: list[str]) -> Chunk:
            nonlocal search_from
            text_out = " ".join(parts)

            # Locate start of first part, scanning forward from cursor
            fp = parts[0]
            start = original_text.find(fp, search_from)
            if start == -1:
                start = max(0, search_from)

            # Locate end of last part, scanning forward from start
            lp = parts[-1]
            lp_pos = original_text.find(lp, start)
            if lp_pos != -1:
                end = min(lp_pos + len(lp), len(original_text))
            else:
                end = min(start + len(text_out), len(original_text))

            # Advance cursor past the start of this chunk (not past end,
            # because the next chunk's overlap begins inside this chunk)
            search_from = start + 1

            return Chunk(text=text_out, start=start, end=end)

        for seg in segments:
            seg_tokens = count_tokens(seg)

            if current_tokens + seg_tokens > chunk_size and current_parts:
                chunks.append(_flush_chunk(current_parts))

                # Overlap: carry trailing parts whose token sum ≤ overlap
                overlap_parts: list[str] = []
                overlap_tokens = 0
                for p in reversed(current_parts):
                    pt = count_tokens(p)
                    if overlap_tokens + pt > overlap:
                        break
                    overlap_parts.insert(0, p)
                    overlap_tokens += pt

                current_parts  = overlap_parts
                current_tokens = overlap_tokens

            current_parts.append(seg)
            current_tokens += seg_tokens

        if current_parts:
            chunks.append(_flush_chunk(current_parts))

        return self._filter_min_size(chunks)

    # -- micro-fragment filter ----------------------------------------------

    def _filter_min_size(self, chunks: list[Chunk]) -> list[Chunk]:
        """Merge chunks smaller than min_chunk_size into their predecessor."""
        if not chunks or self.min_chunk_size <= 0:
            return chunks

        result: list[Chunk] = []
        for c in chunks:
            if result and c.token_count < self.min_chunk_size:
                prev = result[-1]
                merged_text = prev.text + " " + c.text
                merged = Chunk(
                    text=merged_text,
                    start=prev.start,
                    end=c.end,
                    metadata=prev.metadata.copy(),
                )
                # Only merge if the result still stays below min_chunk_size,
                # otherwise keep the current chunk as a new boundary
                if merged.token_count < self.min_chunk_size:
                    result[-1] = merged
                else:
                    result.append(c)
            else:
                result.append(c)
        return result
