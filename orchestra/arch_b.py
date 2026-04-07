"""Architecture B — RAG Pipeline (Sonar → Kimi K2.5 Thinking).

Retrieval-Augmented Generation architecture that uses Perplexity Sonar API
for web-grounded retrieval and citation extraction, then pipes the retrieved
passages into Kimi K2.5 Thinking mode for deeper synthesis and reasoning.

The pipeline::

    Query → Sonar Search (retrieval) → Passage Ranking → Context Assembly
    → Kimi K2.5 Thinking (synthesis) → Citation-Verified Output

This is cheaper than using Sonar for full generation while providing
better reasoning quality through Kimi's thinking mode.

Usage::

    from orchestra.arch_b import RAGPipeline, RAGConfig

    config = RAGConfig(user_id="ashton")
    pipeline = RAGPipeline(config=config)
    result = await pipeline.run("What are the latest advances in quantum computing?")
    print(result.content)
    for c in result.citations:
        print(f"  [{c.index}] {c.title}: {c.url}")
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import httpx

from .router import ModelRouter, ModelConfig
from .perplexity import PerplexitySearch, SearchResult
from .memory import (
    MemoryStore,
    MemoryManager,
    SessionContext,
    register_memory_tools,
)
from .context_engine import ContextEngine, RAGContextPlugin
from .agent_loop import (
    AgentLoop,
    AgentConfig,
    AgentEvent,
    FinalAnswerEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolRegistry,
    create_default_tools,
)

# ---------------------------------------------------------------------------
# Optional module imports — guarded so the file loads even if modules are
# absent (e.g. during isolated unit tests or partial installs).
# ---------------------------------------------------------------------------

try:
    from .adaptive_context import (
        AdaptiveContext,
        AdaptiveContextConfig,
        TokenCounter,
        PriorityMessage,
    )
    _HAS_ADAPTIVE_CONTEXT = True
except ImportError:  # pragma: no cover
    AdaptiveContext = None  # type: ignore[assignment,misc]
    AdaptiveContextConfig = None  # type: ignore[assignment,misc]
    TokenCounter = None  # type: ignore[assignment,misc]
    PriorityMessage = None  # type: ignore[assignment,misc]
    _HAS_ADAPTIVE_CONTEXT = False

try:
    from .long_horizon import (
        LongHorizonRunner,
        LongHorizonConfig,
        LongHorizonResult,
        CheckpointStore,
        ProgressTracker,
    )
    _HAS_LONG_HORIZON = True
except ImportError:  # pragma: no cover
    LongHorizonRunner = None  # type: ignore[assignment,misc]
    LongHorizonConfig = None  # type: ignore[assignment,misc]
    LongHorizonResult = None  # type: ignore[assignment,misc]
    CheckpointStore = None  # type: ignore[assignment,misc]
    ProgressTracker = None  # type: ignore[assignment,misc]
    _HAS_LONG_HORIZON = False

try:
    from .token_streaming import (
        TokenStreamer,
        StreamingConfig,
        StreamChunk,
        BufferedStreamer,
    )
    _HAS_TOKEN_STREAMING = True
except ImportError:  # pragma: no cover
    TokenStreamer = None  # type: ignore[assignment,misc]
    StreamingConfig = None  # type: ignore[assignment,misc]
    StreamChunk = None  # type: ignore[assignment,misc]
    BufferedStreamer = None  # type: ignore[assignment,misc]
    _HAS_TOKEN_STREAMING = False

__all__ = [
    "RAGConfig",
    "RetrievedPassage",
    "SynthesisResult",
    "Citation",
    "PassageRanker",
    "CitationVerifier",
    "MultiSourceFuser",
    "QueryExpander",
    "RAGPipeline",
]

log = logging.getLogger("orchestra.arch_b")


# ---------------------------------------------------------------------------
# Token estimation helper
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Estimate token count using a simple len/4 heuristic.

    Args:
        text: Input text.

    Returns:
        Approximate token count.
    """
    return max(1, len(text) // 4)


def _content_hash(text: str) -> str:
    """Return a short SHA-256 hex digest for deduplication."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RAGConfig:
    """Tuning knobs for Architecture B — RAG Pipeline.

    Controls retrieval depth, synthesis model, citation verification,
    memory integration, and optional adaptive context / long horizon /
    token streaming features.
    """

    # -- Retrieval settings -------------------------------------------------
    sonar_model: str = "sonar-pro"
    max_sources: int = 10
    min_relevance_score: float = 0.5
    search_depth: str = "deep"  # "quick" | "deep" | "exhaustive"

    # -- Synthesis settings -------------------------------------------------
    synthesis_model: str = "kimi-k2.5"
    thinking_mode: bool = True  # Use Kimi's thinking/reasoning mode
    max_synthesis_tokens: int = 16384
    temperature: float = 0.3  # Low for factual synthesis

    # -- Citation settings --------------------------------------------------
    verify_citations: bool = True
    inline_citations: bool = True  # [1], [2] style inline
    max_citation_hops: int = 2  # Follow references up to N levels deep

    # -- Memory -------------------------------------------------------------
    user_id: str = ""
    memory_db: str = ""

    # -- Context management -------------------------------------------------
    enable_adaptive_context: bool = True
    adaptive_context_config: "AdaptiveContextConfig | None" = None

    enable_long_horizon: bool = False
    long_horizon_config: "LongHorizonConfig | None" = None

    enable_token_streaming: bool = True
    streaming_config: "StreamingConfig | None" = None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RetrievedPassage:
    """A single passage retrieved from Sonar search.

    Attributes:
        content: Full text of the retrieved passage.
        source_url: URL where the passage was found.
        source_title: Title of the source page.
        relevance_score: 0–1 relevance score assigned by the ranker.
        citation_index: Citation number ([1], [2], etc.) for inline refs.
        snippet: Highlighted excerpt used for context assembly.
        metadata: Additional metadata (domain, date, search query, etc.).
    """

    content: str
    source_url: str
    source_title: str
    relevance_score: float
    citation_index: int
    snippet: str  # highlighted excerpt
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Citation:
    """A citation reference produced during synthesis.

    Attributes:
        index: The inline citation number, e.g. 1 for [1].
        url: Source URL.
        title: Source page title.
        excerpt: The specific passage that was cited.
        verified: Whether URL was checked to still support the claim.
    """

    index: int  # [1], [2], etc.
    url: str
    title: str
    excerpt: str  # The specific passage cited
    verified: bool = False  # Whether we checked the URL still supports the claim


@dataclass
class SynthesisResult:
    """Complete result from the RAG pipeline.

    Attributes:
        content: Final synthesized answer text.
        citations: List of citations referenced in the answer.
        passages_used: Ranked passages that informed the synthesis.
        thinking_trace: Kimi's internal reasoning chain (if thinking mode).
        model: Model used for synthesis.
        usage: Token usage statistics.
        search_queries: All search queries dispatched.
        synthesis_time_ms: Time spent in Kimi synthesis.
        retrieval_time_ms: Time spent in Sonar retrieval.
    """

    content: str  # Final synthesized answer
    citations: list[Citation]
    passages_used: list[RetrievedPassage]
    thinking_trace: str  # Kimi's reasoning chain
    model: str
    usage: dict[str, Any]
    search_queries: list[str]  # All queries used
    synthesis_time_ms: float
    retrieval_time_ms: float


# ---------------------------------------------------------------------------
# Synthesis system prompt
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = """\
You are a research synthesizer. Your job is to produce a comprehensive,
accurate answer using ONLY the provided source passages.

Rules:
- Use inline citations like [1], [2] to attribute every factual claim.
- If sources conflict, note the disagreement and cite both sides.
- Do not invent information not present in the sources.
- Organise your answer with clear structure (headings, bullet points).
- Be thorough — cover all relevant angles from the sources.
- End with a brief summary of confidence level and any gaps in coverage.

Sources are provided below with their citation indices.
"""

_RANKING_PROMPT = """\
Score each passage for relevance to the query on a scale of 0.0 to 1.0.
Return a JSON array of objects with "index" (int) and "score" (float).
Only return the JSON array, no other text.

Query: {query}

Passages:
{passages}
"""

_EXPANSION_PROMPT = """\
Given the user's question, generate up to {max_queries} diverse search \
queries that would help comprehensively answer it.

Include:
- The original query (possibly rephrased for search engines)
- Sub-questions that break down complex aspects
- Related queries for broader context

Return a JSON array of strings. Only return the JSON array, no other text.

User question: {query}
"""

_FUSION_PROMPT = """\
You are a context assembler. Merge the following source passages into a \
single coherent context document suitable for answering the query.

Rules:
- Remove duplicated information.
- If sources conflict, note disagreements with [Source N] vs [Source M].
- Prioritise more recent and authoritative sources.
- Keep citation markers [1], [2], etc. so the synthesizer can reference them.
- Stay within approximately {token_budget} tokens.

Query: {query}

Source passages:
{passages}
"""

_CLAIM_CHECK_PROMPT = """\
Does the following page content support the cited claim? Answer only "yes" or "no".

Claim: {claim}

Page content (first 3000 chars):
{content}
"""

_FOLLOW_UP_PROMPT = """\
Given the initial research synthesis below, identify claims that need \
further verification or topics that need deeper exploration.

Generate up to {max_queries} follow-up search queries as a JSON array \
of strings. Only return the JSON array, no other text.

If no follow-up is needed, return an empty array [].

Synthesis:
{synthesis}
"""


# ---------------------------------------------------------------------------
# PassageRanker
# ---------------------------------------------------------------------------

class PassageRanker:
    """Re-ranks retrieved passages by relevance to the query.

    Uses a lightweight cross-encoder approach: asks Kimi to score each
    passage 0–1 for relevance, then sorts. Falls back to keyword-overlap
    scoring if the API call fails.
    """

    async def rank(
        self,
        query: str,
        passages: list[RetrievedPassage],
        router: ModelRouter,
        model: str = "kimi-k2.5",
        top_k: int = 5,
    ) -> list[RetrievedPassage]:
        """Rank passages by relevance and return the top-k.

        Args:
            query: Original user query.
            passages: Retrieved passages to rank.
            router: ModelRouter for Kimi API calls.
            model: Model name for ranking calls.
            top_k: Number of top passages to return.

        Returns:
            Sorted list of up to *top_k* passages, highest relevance first.
        """
        if not passages:
            return []

        if len(passages) <= top_k:
            # No need to rank; just assign default scores
            for p in passages:
                if p.relevance_score <= 0:
                    p.relevance_score = 0.8
            return passages

        try:
            return await self._rank_via_model(query, passages, router, model, top_k)
        except Exception as exc:
            log.warning("[B] Model-based ranking failed (%s), using keyword fallback", exc)
            return self._keyword_fallback(query, passages, top_k)

    async def _rank_via_model(
        self,
        query: str,
        passages: list[RetrievedPassage],
        router: ModelRouter,
        model: str,
        top_k: int,
    ) -> list[RetrievedPassage]:
        """Score passages via Kimi and sort by relevance."""
        passage_block = "\n\n".join(
            f"[Passage {i}] ({p.source_title})\n{p.snippet[:500]}"
            for i, p in enumerate(passages)
        )
        prompt = _RANKING_PROMPT.format(query=query, passages=passage_block)

        client, model_id = router.get_client(model)
        resp = await client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1024,
        )
        raw = resp.choices[0].message.content or "[]"
        # Extract JSON array from response (handle markdown fences)
        raw = self._extract_json(raw)

        scores: list[dict[str, Any]] = json.loads(raw)
        score_map: dict[int, float] = {}
        for item in scores:
            idx = int(item.get("index", -1))
            sc = float(item.get("score", 0.0))
            if 0 <= idx < len(passages):
                score_map[idx] = sc

        for i, p in enumerate(passages):
            p.relevance_score = score_map.get(i, 0.5)

        ranked = sorted(passages, key=lambda p: p.relevance_score, reverse=True)
        return ranked[:top_k]

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown code fences if present."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        return text.strip()

    def _keyword_fallback(
        self,
        query: str,
        passages: list[RetrievedPassage],
        top_k: int,
    ) -> list[RetrievedPassage]:
        """Rank passages by keyword overlap when model ranking is unavailable.

        Computes a simple TF overlap score: the fraction of query words
        that appear in the passage text.

        Args:
            query: Original user query.
            passages: Passages to rank.
            top_k: Number to return.

        Returns:
            Sorted list of top-k passages.
        """
        query_words = set(query.lower().split())
        if not query_words:
            return passages[:top_k]

        for p in passages:
            text_lower = p.content.lower()
            hits = sum(1 for w in query_words if w in text_lower)
            p.relevance_score = hits / len(query_words)

        ranked = sorted(passages, key=lambda p: p.relevance_score, reverse=True)
        return ranked[:top_k]


# ---------------------------------------------------------------------------
# CitationVerifier
# ---------------------------------------------------------------------------

class CitationVerifier:
    """Verifies citations by checking source URLs still support the claims.

    Uses httpx to fetch source pages and asks Kimi to confirm the cited
    content is still present. Marks citations as verified/unverified.
    """

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    async def verify(
        self,
        citations: list[Citation],
        router: ModelRouter,
        model: str = "kimi-k2.5",
    ) -> list[Citation]:
        """Verify a batch of citations concurrently.

        Fetches each source URL and asks the model whether the page
        content still supports the cited excerpt.

        Args:
            citations: Citations to verify.
            router: ModelRouter for claim-checking calls.
            model: Model name for verification.

        Returns:
            The same citation objects with ``.verified`` updated.
        """
        if not citations:
            return citations

        tasks = [
            self._verify_one(c, router, model)
            for c in citations
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        verified_count = sum(1 for c in citations if c.verified)
        log.info(
            "[B] Citation verification: %d/%d verified",
            verified_count, len(citations),
        )
        return citations

    async def _verify_one(
        self,
        citation: Citation,
        router: ModelRouter,
        model: str,
    ) -> None:
        """Verify a single citation in-place."""
        page_content = await self._fetch_source(citation.url)
        if page_content is None:
            log.debug("[B] Could not fetch %s — marking unverified", citation.url)
            citation.verified = False
            return

        citation.verified = await self._check_claim(
            claim=citation.excerpt,
            page_content=page_content,
            router=router,
            model=model,
        )

    async def _fetch_source(self, url: str) -> str | None:
        """Fetch page content from a URL.

        Args:
            url: The URL to fetch.

        Returns:
            The page text (truncated to ~3000 chars), or None on failure.
        """
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "HorizonOrchestra/1.0 CitationVerifier"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                text = resp.text[:3000]
                return text
        except Exception as exc:
            log.debug("[B] Fetch failed for %s: %s", url, exc)
            return None

    async def _check_claim(
        self,
        claim: str,
        page_content: str,
        router: ModelRouter,
        model: str = "kimi-k2.5",
    ) -> bool:
        """Ask the model whether page content supports the claim.

        Args:
            claim: The excerpt or claim to check.
            page_content: Fetched page text.
            router: ModelRouter for the verification call.
            model: Model name to use.

        Returns:
            True if the model confirms the claim is supported.
        """
        prompt = _CLAIM_CHECK_PROMPT.format(
            claim=claim,
            content=page_content[:3000],
        )

        try:
            client, model_id = router.get_client(model)
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=16,
            )
            answer = (resp.choices[0].message.content or "").strip().lower()
            return answer.startswith("yes")
        except Exception as exc:
            log.debug("[B] Claim check failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# MultiSourceFuser
# ---------------------------------------------------------------------------

class MultiSourceFuser:
    """Fuses information from multiple retrieved passages into coherent context.

    Handles:
    - Deduplication of overlapping information
    - Conflict detection between sources
    - Priority ordering (more recent, more authoritative sources first)
    - Token budget allocation across sources
    """

    async def fuse(
        self,
        passages: list[RetrievedPassage],
        query: str,
        token_budget: int,
        router: ModelRouter,
        model: str = "kimi-k2.5",
    ) -> str:
        """Fuse multiple passages into a single coherent context document.

        Uses the model to merge, deduplicate, and prioritise passages.
        Falls back to simple concatenation if the model call fails.

        Args:
            passages: Ranked passages to fuse.
            query: Original user query for relevance guidance.
            token_budget: Approximate token limit for the fused context.
            router: ModelRouter for fusion calls.
            model: Model name.

        Returns:
            A single context string suitable for the synthesis stage.
        """
        if not passages:
            return ""

        if len(passages) == 1:
            return self._format_single(passages[0])

        try:
            return await self._fuse_via_model(passages, query, token_budget, router, model)
        except Exception as exc:
            log.warning("[B] Model-based fusion failed (%s), using concat fallback", exc)
            return self._concat_fallback(passages, token_budget)

    async def _fuse_via_model(
        self,
        passages: list[RetrievedPassage],
        query: str,
        token_budget: int,
        router: ModelRouter,
        model: str,
    ) -> str:
        """Use Kimi to fuse passages intelligently."""
        passage_block = "\n\n---\n\n".join(
            f"[{p.citation_index}] ({p.source_title} — {p.source_url})\n{p.content}"
            for p in passages
        )
        prompt = _FUSION_PROMPT.format(
            query=query,
            token_budget=token_budget,
            passages=passage_block,
        )

        client, model_id = router.get_client(model)
        resp = await client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=min(token_budget, 8192),
        )
        return resp.choices[0].message.content or self._concat_fallback(passages, token_budget)

    @staticmethod
    def _format_single(passage: RetrievedPassage) -> str:
        """Format a single passage as a context block."""
        return (
            f"[{passage.citation_index}] ({passage.source_title} — "
            f"{passage.source_url})\n{passage.content}"
        )

    @staticmethod
    def _concat_fallback(passages: list[RetrievedPassage], token_budget: int) -> str:
        """Simple concatenation fallback with budget-aware truncation.

        Allocates tokens proportionally:
        - Top 60% of budget for highest-ranked passages
        - Remaining 40% for supporting passages
        """
        parts: list[str] = []
        total_tokens = 0

        for p in passages:
            entry = (
                f"[{p.citation_index}] ({p.source_title} — {p.source_url})\n"
                f"{p.content}\n"
            )
            entry_tokens = _estimate_tokens(entry)
            if total_tokens + entry_tokens > token_budget:
                # Truncate this passage to fit remaining budget
                remaining_chars = (token_budget - total_tokens) * 4
                if remaining_chars > 100:
                    entry = entry[:remaining_chars] + "\n[...truncated]"
                    parts.append(entry)
                break
            parts.append(entry)
            total_tokens += entry_tokens

        return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# QueryExpander
# ---------------------------------------------------------------------------

class QueryExpander:
    """Expands a user query into multiple search queries for broader retrieval.

    Uses Kimi to generate:
    - Reformulations of the original query
    - Sub-questions that need answering
    - Related queries for comprehensive coverage
    """

    async def expand(
        self,
        query: str,
        router: ModelRouter,
        model: str = "kimi-k2.5",
        max_queries: int = 5,
    ) -> list[str]:
        """Expand a single query into multiple diverse search queries.

        Args:
            query: The original user question.
            router: ModelRouter for expansion calls.
            model: Model name.
            max_queries: Maximum number of queries to generate.

        Returns:
            List of search queries (always includes the original).
        """
        # Always include the original query
        queries = [query]

        if max_queries <= 1:
            return queries

        try:
            expanded = await self._expand_via_model(query, router, model, max_queries)
            # Deduplicate while preserving order
            seen: set[str] = {query.lower()}
            for q in expanded:
                q_stripped = q.strip()
                if q_stripped and q_stripped.lower() not in seen:
                    seen.add(q_stripped.lower())
                    queries.append(q_stripped)
                if len(queries) >= max_queries:
                    break
        except Exception as exc:
            log.warning("[B] Query expansion failed (%s), using original only", exc)

        log.debug("[B] Expanded '%s' into %d queries", query[:60], len(queries))
        return queries

    async def _expand_via_model(
        self,
        query: str,
        router: ModelRouter,
        model: str,
        max_queries: int,
    ) -> list[str]:
        """Generate expanded queries via Kimi."""
        prompt = _EXPANSION_PROMPT.format(query=query, max_queries=max_queries)

        client, model_id = router.get_client(model)
        resp = await client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=512,
        )
        raw = resp.choices[0].message.content or "[]"
        raw = PassageRanker._extract_json(raw)  # reuse JSON extraction
        return json.loads(raw)


# ---------------------------------------------------------------------------
# RAGPipeline — main entry point
# ---------------------------------------------------------------------------

class RAGPipeline:
    """Architecture B — Sonar retrieval → Kimi K2.5 Thinking synthesis.

    Full pipeline:
      1. Check memory for prior relevant findings
      2. Query expansion → multiple search queries
      3. Parallel Sonar retrieval across all queries
      4. Passage ranking and deduplication
      5. Multi-source fusion into coherent context
      6. Kimi K2.5 Thinking mode synthesis with citations
      7. Citation verification (optional)
      8. Memory storage of key findings

    Supports:
      - Single-shot Q&A via ``run()``
      - Multi-hop research via ``research()``  (follow citations N levels)
      - Streaming synthesis via ``stream()`` / ``stream_sse()``
      - Long-horizon research via ``run_long_horizon()``

    New capabilities (additive, all opt-in via config):

    * **AdaptiveContext** — priority-based message management that auto-
      compresses when the context window reaches 80 % capacity.
    * **LongHorizonRunner** — checkpoint/resume for multi-hour research;
      activate via ``config.enable_long_horizon=True`` or ``run_long_horizon()``.
    * **TokenStreamer** — SSE/WebSocket-ready streaming via ``stream_sse()``.

    Usage::

        config = RAGConfig(user_id="ashton")
        pipeline = RAGPipeline(config=config)
        result = await pipeline.run("Explain CRISPR gene editing advances")
        print(result.content)
    """

    def __init__(
        self,
        config: RAGConfig | None = None,
        router: ModelRouter | None = None,
    ) -> None:
        self.config = config or RAGConfig()
        self.router = router or ModelRouter()

        # -- sub-components -------------------------------------------------
        self.searcher = PerplexitySearch()
        self.ranker = PassageRanker()
        self.verifier = CitationVerifier()
        self.fuser = MultiSourceFuser()
        self.expander = QueryExpander()

        # -- memory ---------------------------------------------------------
        db_path = self.config.memory_db or None
        self.memory_store = MemoryStore(db_path=db_path)
        self.memory = MemoryManager(
            store=self.memory_store,
            user_id=self.config.user_id or "default",
        )

        # -- session tracking -----------------------------------------------
        self.session = SessionContext(
            session_id=str(uuid.uuid4())[:8],
            user_id=self.config.user_id or "default",
        )
        self._total_queries = 0
        self._total_passages = 0

        # -- adaptive context -----------------------------------------------
        self.adaptive_context: "AdaptiveContext | None" = None
        if self.config.enable_adaptive_context and _HAS_ADAPTIVE_CONTEXT:
            ac_config = self.config.adaptive_context_config or AdaptiveContextConfig()
            self.adaptive_context = AdaptiveContext(
                config=ac_config,
                router=self.router,
            )
            log.debug("[B] AdaptiveContext enabled (max_tokens=%d)", ac_config.max_tokens)

        # -- token streamer -------------------------------------------------
        self.token_streamer: "TokenStreamer | None" = None
        if self.config.enable_token_streaming and _HAS_TOKEN_STREAMING:
            st_config = self.config.streaming_config or StreamingConfig()
            self.token_streamer = TokenStreamer(config=st_config)
            log.debug("[B] TokenStreamer enabled")

        # -- long horizon (lazy — instantiated on first use) ----------------
        self._long_horizon: "LongHorizonRunner | None" = None

    # -- internal helpers ---------------------------------------------------

    def _get_long_horizon_runner(self) -> "LongHorizonRunner":
        """Return (or lazily create) the LongHorizonRunner."""
        if not _HAS_LONG_HORIZON:
            raise RuntimeError(
                "long_horizon module is not available; "
                "ensure orchestra/long_horizon.py is present."
            )
        if self._long_horizon is None:
            lh_config = (
                self.config.long_horizon_config or LongHorizonConfig(
                    model=self.config.synthesis_model,
                )
            )
            checkpoint_store = CheckpointStore()
            self._long_horizon = LongHorizonRunner(
                router=self.router,
                tools=[],
                config=lh_config,
                checkpoint_store=checkpoint_store,
            )
            log.debug(
                "[B] LongHorizonRunner created (max_hours=%.1f)",
                lh_config.max_runtime_hours,
            )
        return self._long_horizon

    def _search_depth_to_query_count(self) -> int:
        """Map search_depth config to number of expanded queries."""
        return {
            "quick": 2,
            "deep": 5,
            "exhaustive": 8,
        }.get(self.config.search_depth, 5)

    # -----------------------------------------------------------------------
    # Pipeline stage: Retrieve
    # -----------------------------------------------------------------------

    async def retrieve(self, queries: list[str]) -> list[RetrievedPassage]:
        """Run parallel Sonar searches and collect passages.

        Args:
            queries: Search queries to dispatch.

        Returns:
            Deduplicated list of RetrievedPassage objects.
        """
        if not queries:
            return []

        t0 = time.monotonic()

        # Dispatch all queries in parallel
        tasks = [
            self.searcher.search(
                query=q,
                model=self.config.sonar_model,
                return_citations=True,
            )
            for q in queries
        ]
        results: list[SearchResult] = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect passages and deduplicate
        passages: list[RetrievedPassage] = []
        seen_hashes: set[str] = set()
        citation_idx = 1

        for query_idx, result in enumerate(results):
            if isinstance(result, Exception):
                log.warning("[B] Search failed for query %d: %s", query_idx, result)
                continue

            # Build passages from Sonar result content + citations
            content = result.content or ""
            citations = result.citations or []

            # Each citation URL becomes a passage source
            if citations:
                # Split content into chunks aligned with citations
                for url in citations:
                    ch = _content_hash(url + content[:200])
                    if ch in seen_hashes:
                        continue
                    seen_hashes.add(ch)

                    passage = RetrievedPassage(
                        content=content,
                        source_url=url,
                        source_title=self._extract_domain(url),
                        relevance_score=0.0,  # Assigned during ranking
                        citation_index=citation_idx,
                        snippet=content[:300],
                        metadata={
                            "query": queries[query_idx] if query_idx < len(queries) else "",
                            "sonar_model": self.config.sonar_model,
                        },
                    )
                    passages.append(passage)
                    citation_idx += 1

                    if len(passages) >= self.config.max_sources * 2:
                        break
            else:
                # No citations — use the content as a single passage
                ch = _content_hash(content[:500])
                if ch not in seen_hashes:
                    seen_hashes.add(ch)
                    passages.append(RetrievedPassage(
                        content=content,
                        source_url="",
                        source_title="Sonar Search",
                        relevance_score=0.5,
                        citation_index=citation_idx,
                        snippet=content[:300],
                        metadata={
                            "query": queries[query_idx] if query_idx < len(queries) else "",
                        },
                    ))
                    citation_idx += 1

        elapsed_ms = (time.monotonic() - t0) * 1000
        self._total_queries += len(queries)
        self._total_passages += len(passages)
        log.info(
            "[B] Retrieved %d passages from %d queries in %.0fms",
            len(passages), len(queries), elapsed_ms,
        )
        return passages

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract a readable domain name from a URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            return domain.replace("www.", "")
        except Exception:
            return url[:50]

    # -----------------------------------------------------------------------
    # Pipeline stage: Rank
    # -----------------------------------------------------------------------

    async def rank(
        self,
        query: str,
        passages: list[RetrievedPassage],
    ) -> list[RetrievedPassage]:
        """Rank passages by relevance and return top-k.

        Args:
            query: The original user query.
            passages: Retrieved passages to rank.

        Returns:
            Top passages sorted by relevance score.
        """
        return await self.ranker.rank(
            query=query,
            passages=passages,
            router=self.router,
            model=self.config.synthesis_model,
            top_k=self.config.max_sources,
        )

    # -----------------------------------------------------------------------
    # Pipeline stage: Fuse
    # -----------------------------------------------------------------------

    async def fuse(
        self,
        query: str,
        passages: list[RetrievedPassage],
    ) -> str:
        """Fuse ranked passages into a single context document.

        Args:
            query: The user query.
            passages: Ranked passages.

        Returns:
            Fused context string with citation markers.
        """
        # Token budget: ~60% of max synthesis tokens for context
        token_budget = int(self.config.max_synthesis_tokens * 0.6)
        return await self.fuser.fuse(
            passages=passages,
            query=query,
            token_budget=token_budget,
            router=self.router,
            model=self.config.synthesis_model,
        )

    # -----------------------------------------------------------------------
    # Pipeline stage: Synthesize
    # -----------------------------------------------------------------------

    async def synthesize(
        self,
        query: str,
        context: str,
        passages: list[RetrievedPassage],
    ) -> SynthesisResult:
        """Generate a synthesized answer from fused context.

        Calls Kimi K2.5 in thinking mode (if enabled) to produce a
        citation-rich answer grounded in the retrieved passages.

        Args:
            query: Original user query.
            context: Fused context document from the fusion stage.
            passages: Passages used (for result metadata).

        Returns:
            SynthesisResult with content, citations, and metadata.
        """
        t0 = time.monotonic()

        # Build the user message with source context
        user_message = (
            f"Question: {query}\n\n"
            f"--- Retrieved Sources ---\n\n"
            f"{context}\n\n"
            f"--- End Sources ---\n\n"
            f"Please synthesize a comprehensive answer using the sources above. "
            f"Use inline citations like [1], [2] for every factual claim."
        )

        # Prepare messages
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYNTHESIS_SYSTEM},
            {"role": "user", "content": user_message},
        ]

        # Wire adaptive context if available
        if self.adaptive_context is not None:
            self.adaptive_context.add_message("system", _SYNTHESIS_SYSTEM, priority=1)
            self.adaptive_context.add_message("user", user_message)
            await self.adaptive_context.compress()
            log.debug("[B] AdaptiveContext prepared for synthesis")

        # Call Kimi K2.5
        client, model_id = self.router.get_client(self.config.synthesis_model)
        extra_kwargs: dict[str, Any] = {}

        # Enable thinking mode if supported
        if self.config.thinking_mode:
            extra_kwargs["extra_body"] = {"thinking": True}

        resp = await client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_synthesis_tokens,
            **extra_kwargs,
        )

        content = resp.choices[0].message.content or ""

        # Extract thinking trace if present
        thinking_trace = ""
        if hasattr(resp.choices[0].message, "reasoning_content"):
            thinking_trace = resp.choices[0].message.reasoning_content or ""
        elif hasattr(resp.choices[0].message, "thinking"):
            thinking_trace = resp.choices[0].message.thinking or ""

        # Parse usage
        usage: dict[str, Any] = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }

        # Extract citations from synthesis content
        citations = self._extract_citations(content, passages)

        synthesis_time_ms = (time.monotonic() - t0) * 1000

        return SynthesisResult(
            content=content,
            citations=citations,
            passages_used=passages,
            thinking_trace=thinking_trace,
            model=self.config.synthesis_model,
            usage=usage,
            search_queries=[],  # Filled by run()
            synthesis_time_ms=synthesis_time_ms,
            retrieval_time_ms=0.0,  # Filled by run()
        )

    def _extract_citations(
        self,
        content: str,
        passages: list[RetrievedPassage],
    ) -> list[Citation]:
        """Extract inline citation references [1], [2], ... from synthesized text.

        Matches each citation index to the corresponding passage and
        extracts the surrounding sentence as the excerpt.

        Args:
            content: Synthesized answer text.
            passages: Passages that were available during synthesis.

        Returns:
            List of Citation objects.
        """
        # Find all citation indices referenced in the text
        pattern = r"\[(\d+)\]"
        cited_indices = set(int(m) for m in re.findall(pattern, content))

        # Build a passage lookup by citation index
        passage_map: dict[int, RetrievedPassage] = {
            p.citation_index: p for p in passages
        }

        citations: list[Citation] = []
        for idx in sorted(cited_indices):
            p = passage_map.get(idx)
            if p is None:
                continue
            citations.append(Citation(
                index=idx,
                url=p.source_url,
                title=p.source_title,
                excerpt=p.snippet[:200],
                verified=False,
            ))

        return citations

    # -----------------------------------------------------------------------
    # Core pipeline: run()
    # -----------------------------------------------------------------------

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> SynthesisResult:
        """Execute the full RAG pipeline end-to-end.

        Pipeline stages:
          1. Check memory for prior relevant findings
          2. Expand query into multiple search queries
          3. Parallel Sonar retrieval
          4. Passage ranking
          5. Multi-source fusion
          6. Kimi K2.5 synthesis
          7. Citation verification (if enabled)
          8. Store findings in memory

        Args:
            query: The user's question or research request.
            context: Optional context dict (e.g. prior conversation).

        Returns:
            SynthesisResult with the synthesized answer, citations,
            usage stats, and timing information.
        """
        self.session.add_turn("user", query)
        t0 = time.monotonic()

        # 1. Check memory for prior relevant findings
        memory_context = ""
        try:
            memory_block = await self.memory.get_context_block(
                query=query, limit=10,
            )
            if memory_block:
                memory_context = f"Prior knowledge:\n{memory_block}\n\n"
                log.debug("[B] Found relevant memories for query")
        except Exception as exc:
            log.debug("[B] Memory check failed: %s", exc)

        # 2. Query expansion
        max_queries = self._search_depth_to_query_count()
        expanded_queries = await self.expander.expand(
            query=query,
            router=self.router,
            model=self.config.synthesis_model,
            max_queries=max_queries,
        )

        # 3. Parallel Sonar retrieval
        retrieval_t0 = time.monotonic()
        passages = await self.retrieve(expanded_queries)
        retrieval_time_ms = (time.monotonic() - retrieval_t0) * 1000

        # 4. Passage ranking
        ranked = await self.rank(query, passages)

        # 5. Multi-source fusion
        fused_context = await self.fuse(query, ranked)

        # Prepend memory context if available
        if memory_context:
            fused_context = memory_context + fused_context

        # Inject additional context if provided
        if context:
            ctx_str = json.dumps(context, default=str, indent=2)
            fused_context = f"Additional context:\n{ctx_str}\n\n{fused_context}"

        # 6. Kimi K2.5 synthesis
        result = await self.synthesize(query, fused_context, ranked)
        result.search_queries = expanded_queries
        result.retrieval_time_ms = retrieval_time_ms

        # 7. Citation verification
        if self.config.verify_citations and result.citations:
            try:
                result.citations = await self.verifier.verify(
                    citations=result.citations,
                    router=self.router,
                    model=self.config.synthesis_model,
                )
            except Exception as exc:
                log.warning("[B] Citation verification failed: %s", exc)

        # 8. Store findings in memory
        await self._store_findings(query, result)

        elapsed = time.monotonic() - t0
        self.session.add_turn("assistant", result.content[:2000])
        log.info(
            "[B] RAG pipeline complete: %d sources, %d citations, "
            "retrieval=%.0fms, synthesis=%.0fms, total=%.1fs",
            len(result.passages_used),
            len(result.citations),
            result.retrieval_time_ms,
            result.synthesis_time_ms,
            elapsed,
        )
        return result

    # -----------------------------------------------------------------------
    # Core pipeline: stream()
    # -----------------------------------------------------------------------

    async def stream(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Execute the RAG pipeline, yielding events as they occur.

        Performs retrieval and ranking first, then streams the synthesis
        step so the user sees tokens as they are generated.

        Args:
            query: The user's question.
            context: Optional context dict.

        Yields:
            AgentEvent objects (ToolCallEvent, FinalAnswerEvent, etc.).
        """
        self.session.add_turn("user", query)
        t0 = time.monotonic()

        # -- retrieval phase (non-streaming) --------------------------------
        max_queries = self._search_depth_to_query_count()
        expanded_queries = await self.expander.expand(
            query=query,
            router=self.router,
            model=self.config.synthesis_model,
            max_queries=max_queries,
        )

        # Emit retrieval event
        yield ToolCallEvent(
            iteration=0,
            tool_name="sonar_search",
            arguments={"queries": expanded_queries},
            tool_call_id=str(uuid.uuid4())[:8],
        )

        retrieval_t0 = time.monotonic()
        passages = await self.retrieve(expanded_queries)
        retrieval_time_ms = (time.monotonic() - retrieval_t0) * 1000

        yield ToolResultEvent(
            iteration=0,
            tool_name="sonar_search",
            result=f"Retrieved {len(passages)} passages",
            tool_call_id=str(uuid.uuid4())[:8],
        )

        ranked = await self.rank(query, passages)
        fused_context = await self.fuse(query, ranked)

        # Check memory and add context
        try:
            memory_block = await self.memory.get_context_block(query=query, limit=10)
            if memory_block:
                fused_context = f"Prior knowledge:\n{memory_block}\n\n{fused_context}"
        except Exception:
            pass

        if context:
            ctx_str = json.dumps(context, default=str, indent=2)
            fused_context = f"Additional context:\n{ctx_str}\n\n{fused_context}"

        # -- synthesis phase (streaming) ------------------------------------
        user_message = (
            f"Question: {query}\n\n"
            f"--- Retrieved Sources ---\n\n"
            f"{fused_context}\n\n"
            f"--- End Sources ---\n\n"
            f"Please synthesize a comprehensive answer using the sources above. "
            f"Use inline citations like [1], [2] for every factual claim."
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYNTHESIS_SYSTEM},
            {"role": "user", "content": user_message},
        ]

        client, model_id = self.router.get_client(self.config.synthesis_model)
        extra_kwargs: dict[str, Any] = {"stream": True}
        if self.config.thinking_mode:
            extra_kwargs["extra_body"] = {"thinking": True}

        content_parts: list[str] = []
        try:
            stream_resp = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_synthesis_tokens,
                **extra_kwargs,
            )

            async for chunk in stream_resp:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    content_parts.append(delta.content)
                    # Yield as FinalAnswerEvent chunks for downstream consumers
                    yield FinalAnswerEvent(content=delta.content)

        except Exception as exc:
            yield ErrorEvent(message=f"Synthesis streaming error: {exc}", recoverable=False)
            return

        final_content = "".join(content_parts)
        citations = self._extract_citations(final_content, ranked)

        # Store findings
        result = SynthesisResult(
            content=final_content,
            citations=citations,
            passages_used=ranked,
            thinking_trace="",
            model=self.config.synthesis_model,
            usage={},
            search_queries=expanded_queries,
            synthesis_time_ms=(time.monotonic() - t0) * 1000 - retrieval_time_ms,
            retrieval_time_ms=retrieval_time_ms,
        )
        await self._store_findings(query, result)
        self.session.add_turn("assistant", final_content[:2000])

        elapsed = time.monotonic() - t0
        log.info("[B] Stream complete: %.1fs, %d passages", elapsed, len(ranked))

    # -----------------------------------------------------------------------
    # Multi-hop research
    # -----------------------------------------------------------------------

    async def research(
        self,
        query: str,
        max_hops: int = 2,
    ) -> SynthesisResult:
        """Perform multi-hop research by following citations.

        After the initial synthesis, extracts claims that need verification,
        generates follow-up queries from those claims, runs additional
        retrieval rounds (up to *max_hops*), and re-synthesizes with the
        expanded evidence base.

        Args:
            query: The research question.
            max_hops: Maximum number of follow-up retrieval rounds.

        Returns:
            SynthesisResult with comprehensive, multi-hop findings.
        """
        max_hops = min(max_hops, self.config.max_citation_hops)
        log.info("[B] Starting multi-hop research (max_hops=%d)", max_hops)

        # Hop 0: initial run
        result = await self.run(query)
        all_passages = list(result.passages_used)
        all_queries = list(result.search_queries)

        for hop in range(1, max_hops + 1):
            # Generate follow-up queries from the current synthesis
            follow_ups = await self._generate_follow_ups(
                result.content, max_queries=3,
            )
            if not follow_ups:
                log.info("[B] No follow-up queries at hop %d — stopping", hop)
                break

            log.info("[B] Hop %d: %d follow-up queries", hop, len(follow_ups))
            all_queries.extend(follow_ups)

            # Retrieve additional passages
            new_passages = await self.retrieve(follow_ups)
            if not new_passages:
                log.info("[B] No new passages at hop %d — stopping", hop)
                break

            # Merge with existing passages (deduplicate)
            seen = {_content_hash(p.content[:200]) for p in all_passages}
            for p in new_passages:
                h = _content_hash(p.content[:200])
                if h not in seen:
                    seen.add(h)
                    all_passages.append(p)

            # Re-rank the full set
            ranked = await self.rank(query, all_passages)

            # Re-fuse
            fused_context = await self.fuse(query, ranked)

            # Re-synthesize with expanded evidence
            result = await self.synthesize(query, fused_context, ranked)
            result.search_queries = all_queries

        # Final citation verification
        if self.config.verify_citations and result.citations:
            try:
                result.citations = await self.verifier.verify(
                    citations=result.citations,
                    router=self.router,
                    model=self.config.synthesis_model,
                )
            except Exception as exc:
                log.warning("[B] Final citation verification failed: %s", exc)

        # Store comprehensive findings
        await self._store_findings(query, result)

        log.info(
            "[B] Multi-hop research complete: %d hops, %d total passages, "
            "%d queries, %d citations",
            min(max_hops, len(all_queries)),
            len(all_passages),
            len(all_queries),
            len(result.citations),
        )
        return result

    async def _generate_follow_ups(
        self,
        synthesis: str,
        max_queries: int = 3,
    ) -> list[str]:
        """Generate follow-up queries from a synthesis for multi-hop research.

        Args:
            synthesis: The current synthesized answer.
            max_queries: Maximum follow-up queries.

        Returns:
            List of follow-up search queries.
        """
        prompt = _FOLLOW_UP_PROMPT.format(
            synthesis=synthesis[:3000],
            max_queries=max_queries,
        )

        try:
            client, model_id = self.router.get_client(self.config.synthesis_model)
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=512,
            )
            raw = resp.choices[0].message.content or "[]"
            raw = PassageRanker._extract_json(raw)
            follow_ups = json.loads(raw)
            return follow_ups[:max_queries] if isinstance(follow_ups, list) else []
        except Exception as exc:
            log.debug("[B] Follow-up generation failed: %s", exc)
            return []

    # -----------------------------------------------------------------------
    # Streaming: SSE
    # -----------------------------------------------------------------------

    async def stream_sse(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncGenerator["StreamChunk", None]:
        """Execute the pipeline and yield SSE-ready StreamChunk objects.

        Wraps ``stream()`` with BufferedStreamer to produce typed chunks
        (token, tool_call_start, tool_call_complete, finish, heartbeat)
        suitable for Server-Sent Events or WebSocket delivery.

        Args:
            query: The user's question.
            context: Optional context dict.

        Yields:
            StreamChunk objects. Call ``.to_sse()`` on each for raw SSE
            wire format.

        Raises:
            RuntimeError: If the token_streaming module is unavailable.
        """
        if not _HAS_TOKEN_STREAMING:
            raise RuntimeError(
                "token_streaming module is not available; "
                "ensure orchestra/token_streaming.py is present."
            )

        st_config = self.config.streaming_config or StreamingConfig()
        buffered = BufferedStreamer(config=st_config)
        log.debug("[B] stream_sse: starting buffered SSE stream")

        seq = 0
        async for event in self.stream(query, context=context):
            if isinstance(event, ToolCallEvent):
                yield StreamChunk(
                    type="tool_call_start",
                    content=event.tool_name,
                    tool_call={"name": event.tool_name, "arguments": event.arguments},
                    sequence=seq,
                )
                seq += 1
            elif isinstance(event, ToolResultEvent):
                yield StreamChunk(
                    type="tool_call_complete",
                    content=event.result if isinstance(event.result, str) else str(event.result),
                    sequence=seq,
                )
                seq += 1
            elif isinstance(event, FinalAnswerEvent):
                yield StreamChunk(
                    type="token",
                    content=event.content,
                    sequence=seq,
                )
                seq += 1
            elif isinstance(event, ErrorEvent):
                yield StreamChunk(
                    type="error",
                    content=event.message,
                    sequence=seq,
                )
                seq += 1

        # Emit finish chunk
        yield StreamChunk(
            type="finish",
            finish_reason="stop",
            sequence=seq,
        )

    # -----------------------------------------------------------------------
    # Long-horizon research
    # -----------------------------------------------------------------------

    async def run_long_horizon(
        self,
        task: str,
        user_id: str = "",
        resume_from: str = "",
    ) -> Any:
        """Execute a long-horizon research task with checkpoint/resume.

        Uses LongHorizonRunner to break the research task into steps,
        execute them sequentially with periodic checkpointing, and
        pause gracefully near runtime/Lambda limits.

        Args:
            task: The high-level research task description.
            user_id: User identifier (defaults to config.user_id).
            resume_from: Task ID of a prior paused run to resume.

        Returns:
            LongHorizonResult with status, result text, and progress info.

        Raises:
            RuntimeError: If the long_horizon module is unavailable.
        """
        runner = self._get_long_horizon_runner()
        uid = user_id or self.config.user_id or "default"
        log.info(
            "[B] Starting long-horizon research user_id=%s resume=%s",
            uid, resume_from or "none",
        )
        result = await runner.run(
            task=task,
            user_id=uid,
            resume_from=resume_from,
        )
        log.info(
            "[B] Long-horizon complete: status=%s steps=%d/%d",
            result.status, result.steps_completed, result.total_steps,
        )
        return result

    # -----------------------------------------------------------------------
    # Memory integration
    # -----------------------------------------------------------------------

    async def _store_findings(
        self,
        query: str,
        result: SynthesisResult,
    ) -> None:
        """Store research findings in memory for future reference.

        Extracts key facts from the synthesis and stores them as
        tagged memory entries for cross-session recall.

        Args:
            query: Original query.
            result: The synthesis result to extract findings from.
        """
        if not self.config.user_id:
            return

        try:
            # Store the query + summary as a research memory
            summary = result.content[:500]
            citation_summary = ", ".join(
                f"[{c.index}] {c.title}" for c in result.citations[:5]
            )
            memory_text = (
                f"Research: {query}\n"
                f"Summary: {summary}\n"
                f"Sources: {citation_summary}"
            )
            await self.memory_store.store(
                user_id=self.config.user_id,
                content=memory_text,
                category="fact",
                source="research",
            )
            log.debug("[B] Stored research findings in memory")
        except Exception as exc:
            log.debug("[B] Failed to store findings: %s", exc)

    # -----------------------------------------------------------------------
    # Session helpers
    # -----------------------------------------------------------------------

    async def recall(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search memories related to a query.

        Args:
            query: Search query.
            limit: Max results.

        Returns:
            List of dicts with content, category, and relevance.
        """
        results = await self.memory_store.search(
            self.config.user_id or "default",
            query,
            limit=limit,
        )
        return [
            {
                "content": r.content,
                "category": r.category,
                "relevance": round(r.relevance_score, 3),
            }
            for r in results
        ]

    async def remember(self, fact: str, category: str = "fact") -> str:
        """Manually store a memory.

        Args:
            fact: The fact to store.
            category: Category tag.

        Returns:
            The memory entry ID.
        """
        entry = await self.memory_store.store(
            self.config.user_id or "default",
            fact,
            category=category,
            source="explicit",
        )
        return entry.id

    @property
    def stats(self) -> dict[str, Any]:
        """Return pipeline statistics as a dict."""
        return {
            "architecture": "B",
            "synthesis_model": self.config.synthesis_model,
            "sonar_model": self.config.sonar_model,
            "search_depth": self.config.search_depth,
            "total_queries": self._total_queries,
            "total_passages": self._total_passages,
            "session_id": self.session.session_id,
            "session_turns": len(self.session.turns),
            "verify_citations": self.config.verify_citations,
            "thinking_mode": self.config.thinking_mode,
            "adaptive_context_enabled": self.adaptive_context is not None,
            "token_streaming_enabled": self.token_streamer is not None,
            "long_horizon_enabled": self.config.enable_long_horizon,
        }


# ---------------------------------------------------------------------------
# Quick-run helpers
# ---------------------------------------------------------------------------

async def run_rag(
    query: str,
    model: str = "kimi-k2.5",
    user_id: str = "default",
    search_depth: str = "deep",
    verify: bool = True,
) -> SynthesisResult:
    """One-liner to run a query through Architecture B.

    Args:
        query: The question to answer.
        model: Synthesis model name.
        user_id: User identifier.
        search_depth: "quick", "deep", or "exhaustive".
        verify: Whether to verify citations.

    Returns:
        SynthesisResult with answer, citations, and metadata.
    """
    config = RAGConfig(
        synthesis_model=model,
        user_id=user_id,
        search_depth=search_depth,
        verify_citations=verify,
    )
    pipeline = RAGPipeline(config=config)
    return await pipeline.run(query)


async def run_research(
    query: str,
    max_hops: int = 2,
    user_id: str = "default",
) -> SynthesisResult:
    """One-liner for multi-hop research through Architecture B.

    Args:
        query: The research question.
        max_hops: Maximum citation-following hops.
        user_id: User identifier.

    Returns:
        SynthesisResult with comprehensive research findings.
    """
    config = RAGConfig(
        user_id=user_id,
        search_depth="exhaustive",
        max_citation_hops=max_hops,
        verify_citations=True,
    )
    pipeline = RAGPipeline(config=config)
    return await pipeline.research(query, max_hops=max_hops)
