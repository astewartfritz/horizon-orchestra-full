"""Horizon Orchestra — Citation Grounding System.

Enforces that agent responses include verifiable citations for factual
claims. Mirrors Perplexity Computer's citation-first architecture.

Every web_search and fetch_url result is tracked as a potential source.
When the agent generates its final answer, the citation middleware:

1. Extracts factual claims (sentences with numbers, names, dates, statistics)
2. Checks each claim against the tracked sources
3. Injects [N] citation markers into the response
4. Appends a "Sources" section with full URLs

Usage::

    from orchestra.citation import CitationMiddleware, CitationTracker

    tracker = CitationTracker()
    middleware = CitationMiddleware(tracker)

    # After web_search tool:
    tracker.add_source("https://example.com/article", content, title)

    # After final answer:
    grounded = middleware.ground_response(final_answer)
    # Returns response with [1], [2] markers and Sources section
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Source",
    "Citation",
    "GroundedResponse",
    "CitationTracker",
    "CitationMiddleware",
    "CitationEnforcer",
    "parse_sonar_citations",
    "parse_search_result_citations",
    "auto_ground",
]

log = logging.getLogger("orchestra.citation")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Source:
    """A single retrieved source that may be used as a citation.

    Attributes:
        url: The canonical URL of the source.
        title: Human-readable page/document title.
        content: Raw content snippet (first 2000 characters).
        retrieved_at: Unix timestamp when the source was collected.
        tool: The tool that produced this source (``"web_search"``,
            ``"fetch_url"``, ``"file_read"``).
        citation_index: The ``[N]`` number assigned when this source is
            cited in a response.  Zero means not yet assigned.
        times_cited: How many claims in the current response cite this source.
    """

    url: str
    title: str = ""
    content: str = ""
    retrieved_at: float = field(default_factory=time.time)
    tool: str = ""
    citation_index: int = 0
    times_cited: int = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def display_title(self) -> str:
        """Return title if available, otherwise a shortened URL."""
        return self.title or self.url

    def __hash__(self) -> int:  # needed for set operations
        return hash(self.url)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Source):
            return self.url == other.url
        return NotImplemented


@dataclass
class Citation:
    """A resolved mapping between a factual claim and its supporting source.

    Attributes:
        marker: The ``[N]`` string inserted into the text.
        index: Integer index (same as the trailing number in *marker*).
        claim: The sentence that was identified as a factual claim.
        source: The :class:`Source` that supports this claim.
        confidence: Float in ``[0, 1]`` indicating how well the source
            supports the claim, based on keyword overlap.
    """

    marker: str
    index: int
    claim: str
    source: Source
    confidence: float


@dataclass
class GroundedResponse:
    """The result of running citation grounding over an agent response.

    Attributes:
        original: The agent's raw response string.
        grounded: The response with ``[N]`` markers injected after cited
            sentences.
        sources: All unique :class:`Source` objects that were cited.
        citations: Every individual :class:`Citation` match found.
        uncited_claims: Factual-looking sentences for which no source was
            found in the tracker.
        citation_rate: Fraction of factual claims that received at least
            one citation.
        sources_section: A formatted ``## Sources`` block ready to append
            to the response.
    """

    original: str
    grounded: str
    sources: list[Source]
    citations: list[Citation]
    uncited_claims: list[str]
    citation_rate: float
    sources_section: str

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def fully_grounded(self) -> bool:
        """Return ``True`` when at least 80 % of factual claims are cited."""
        return self.citation_rate > 0.8

    def to_markdown(self) -> str:
        """Return the grounded response followed by the sources section."""
        if self.sources_section:
            return f"{self.grounded}\n\n{self.sources_section}"
        return self.grounded


# ---------------------------------------------------------------------------
# CitationTracker
# ---------------------------------------------------------------------------


class CitationTracker:
    """Tracks sources as the agent calls ``web_search`` and ``fetch_url``.

    Intended to be used as a post-execution hook on tool calls so that every
    retrieved document is registered before the final answer is grounded.

    Example::

        tracker = CitationTracker()
        # ... inside agent loop after web_search ...
        tracker.add_sources_from_search(result_json)
        # ... after final answer ...
        middleware = CitationMiddleware(tracker)
        grounded = middleware.ground_response(answer)
    """

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}  # url → Source
        self._index_counter: int = 0

    # ------------------------------------------------------------------
    # Mutation methods
    # ------------------------------------------------------------------

    def add_source(
        self,
        url: str,
        content: str = "",
        title: str = "",
        tool: str = "",
    ) -> Source:
        """Register a source URL and return the :class:`Source` object.

        If the URL was already registered the existing record is returned
        (and content/title are updated only if the new values are non-empty).

        Args:
            url: Canonical URL of the source.
            content: Raw text content; stored up to 2000 characters.
            title: Human-readable title for the source.
            tool: Name of the tool that retrieved this source.

        Returns:
            The :class:`Source` instance (existing or newly created).
        """
        if not url:
            log.debug("add_source called with empty URL — skipping")
            return Source(url="", tool=tool)

        if url in self._sources:
            existing = self._sources[url]
            if content and not existing.content:
                existing.content = content[:2000]
            if title and not existing.title:
                existing.title = title
            return existing

        self._index_counter += 1
        source = Source(
            url=url,
            title=title,
            content=content[:2000],
            retrieved_at=time.time(),
            tool=tool or "unknown",
            citation_index=self._index_counter,
        )
        self._sources[url] = source
        log.debug("Registered source [%d] %s", self._index_counter, url)
        return source

    def add_sources_from_search(self, search_result: str) -> list[Source]:
        """Parse a ``web_search`` JSON result and register all sources.

        Handles both Sonar-style responses (``{"content": ..., "citations": [...]}``
        ) and generic search result lists (``{"results": [{"url": ..., "title":
        ..., "snippet": ...}]}``) .

        Args:
            search_result: Raw JSON string returned by the ``web_search`` tool.

        Returns:
            List of :class:`Source` objects that were registered (may be empty
            if the result could not be parsed or contained no URLs).
        """
        sources: list[Source] = []
        try:
            data = json.loads(search_result)
        except (json.JSONDecodeError, TypeError):
            log.debug("add_sources_from_search: could not parse JSON")
            return sources

        # Sonar format: {"content": "...", "citations": ["url1", "url2"]}
        citations = data.get("citations") or []
        content_body = data.get("content", "")

        if isinstance(citations, list):
            for item in citations:
                if isinstance(item, str) and item.startswith("http"):
                    src = self.add_source(
                        url=item,
                        content=content_body[:2000] if content_body else "",
                        tool="web_search",
                    )
                    sources.append(src)
                elif isinstance(item, dict):
                    url = item.get("url", "")
                    title = item.get("title", "")
                    snippet = item.get("snippet", "") or item.get("content", "")
                    if url:
                        src = self.add_source(
                            url=url,
                            content=snippet[:2000],
                            title=title,
                            tool="web_search",
                        )
                        sources.append(src)

        # Generic search results list: {"results": [...]}
        results = data.get("results") or []
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                url = item.get("url", "")
                title = item.get("title", "")
                snippet = item.get("snippet", "") or item.get("content", "")
                if url:
                    src = self.add_source(
                        url=url,
                        content=snippet[:2000],
                        title=title,
                        tool="web_search",
                    )
                    if src not in sources:
                        sources.append(src)

        log.debug(
            "add_sources_from_search: registered %d source(s)", len(sources)
        )
        return sources

    def add_sources_from_fetch(
        self, fetch_result: str, url: str = ""
    ) -> Source | None:
        """Parse a ``fetch_url`` JSON result and register the source.

        Args:
            fetch_result: Raw JSON string returned by the ``fetch_url`` tool.
            url: Fallback URL in case the result JSON does not include one.

        Returns:
            The registered :class:`Source`, or ``None`` if no URL could be
            determined.
        """
        try:
            data = json.loads(fetch_result)
        except (json.JSONDecodeError, TypeError):
            if url:
                return self.add_source(url=url, tool="fetch_url")
            return None

        resolved_url = data.get("url", "") or url
        content = data.get("content", "")
        title = data.get("title", "")

        if not resolved_url:
            log.debug("add_sources_from_fetch: no URL found in result")
            return None

        return self.add_source(
            url=resolved_url,
            content=content[:2000],
            title=title,
            tool="fetch_url",
        )

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_source(self, url: str) -> Source | None:
        """Look up a source by exact URL.

        Args:
            url: The URL to look up.

        Returns:
            The :class:`Source` if registered, otherwise ``None``.
        """
        return self._sources.get(url)

    def find_relevant_sources(
        self, claim: str, top_k: int = 3
    ) -> list[tuple[Source, float]]:
        """Find the sources most likely to support *claim*.

        Relevance is measured by keyword overlap between the claim text and
        the source's ``content`` and ``title`` fields.  Both strings are
        lower-cased and split on non-word characters so short tokens like
        articles are naturally de-emphasised.

        Args:
            claim: A sentence (or phrase) representing the factual claim.
            top_k: Maximum number of results to return.

        Returns:
            A list of ``(Source, score)`` tuples sorted by descending score,
            containing at most *top_k* entries.  Sources with a score of
            zero are excluded.
        """
        if not self._sources:
            return []

        claim_tokens = set(re.split(r"\W+", claim.lower())) - _STOP_WORDS
        if not claim_tokens:
            return []

        scored: list[tuple[Source, float]] = []
        for source in self._sources.values():
            haystack = f"{source.title} {source.content}".lower()
            haystack_tokens = set(re.split(r"\W+", haystack)) - _STOP_WORDS
            if not haystack_tokens:
                continue
            overlap = claim_tokens & haystack_tokens
            if not overlap:
                continue
            # Jaccard-like score weighted by claim coverage
            score = len(overlap) / max(len(claim_tokens), 1)
            scored.append((source, round(score, 4)))

        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]

    def reset(self) -> None:
        """Clear all tracked sources and reset the index counter.

        Call this between independent agent runs to avoid cross-contamination.
        """
        self._sources.clear()
        self._index_counter = 0
        log.debug("CitationTracker reset")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sources(self) -> list[Source]:
        """Return all registered sources in insertion order."""
        return list(self._sources.values())

    @property
    def source_count(self) -> int:
        """Return the number of registered sources."""
        return len(self._sources)


# ---------------------------------------------------------------------------
# CitationMiddleware
# ---------------------------------------------------------------------------

# Common English stop-words excluded from keyword overlap scoring
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "", "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "from", "is", "are", "was", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "that", "this", "it",
        "its", "as", "not", "no", "so", "if", "than", "then", "can", "also",
        "which", "who", "what", "when", "where", "how", "there", "their",
        "they", "we", "our", "i", "my", "you", "your", "he", "she", "his",
        "her", "us", "more", "most", "about", "after", "before", "between",
        "into", "through", "during", "each", "both", "few", "some", "such",
        "over", "under", "up", "down", "out", "off", "while", "because",
        "since", "until", "all", "any", "other", "same", "than", "just",
        "been", "get", "got",
    }
)


class CitationMiddleware:
    """Post-process agent responses to inject inline citations.

    Hooks into the agent loop's :class:`~orchestra.agent_loop.FinalAnswerEvent`
    to ground responses against sources tracked by a :class:`CitationTracker`.

    Typical integration pattern::

        tracker = CitationTracker()
        middleware = CitationMiddleware(tracker)

        async for event in agent_loop.run(task):
            if isinstance(event, ToolResultEvent):
                middleware.wrap_tool_result(event.tool_name, event.result, {})
            elif isinstance(event, FinalAnswerEvent):
                grounded = middleware.ground_response(event.content)
                print(grounded.to_markdown())

    Attributes:
        tracker: The :class:`CitationTracker` holding registered sources.
        enforce_citations: When ``True``, a warning is logged for every
            factual claim that could not be grounded.
        min_citation_rate: Minimum fraction ``[0, 1]`` of factual claims that
            must be cited.  Used only for logging/stats; does not block output.
    """

    # Patterns that mark a sentence as containing a factual claim
    FACTUAL_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"\b\d{4}\b"),                                   # years
        re.compile(r"\b\d+[\.,]\d+\b"),                             # decimals
        re.compile(r"\b\d+%"),                                      # percentages
        re.compile(r"\$\d+"),                                       # dollar amounts
        re.compile(                                                  # attribution verbs
            r"\b(according to|reported|study|research|found|shows|data)\b",
            re.I,
        ),
        re.compile(                                                  # large quantities
            r"\b(million|billion|trillion|thousand)\b", re.I
        ),
    ]

    def __init__(
        self,
        tracker: CitationTracker,
        enforce_citations: bool = False,
        min_citation_rate: float = 0.0,
    ) -> None:
        self.tracker = tracker
        self.enforce_citations = enforce_citations
        self.min_citation_rate = min_citation_rate

        # Internal counters for stats
        self._total_responses: int = 0
        self._total_claims: int = 0
        self._total_cited: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ground_response(self, response: str) -> GroundedResponse:
        """Main entry point: inject citations into an agent response.

        The method:

        1. Splits the response into sentences and identifies factual claims.
        2. For each claim, queries the tracker for relevant sources.
        3. Assigns ``[N]`` markers and injects them after cited sentences.
        4. Builds the ``## Sources`` section.
        5. Returns a :class:`GroundedResponse` with all metadata.

        Args:
            response: The raw final answer from the agent.

        Returns:
            A :class:`GroundedResponse` with markers injected and sources
            listed.
        """
        if not response:
            return GroundedResponse(
                original=response,
                grounded=response,
                sources=[],
                citations=[],
                uncited_claims=[],
                citation_rate=0.0,
                sources_section="",
            )

        self._total_responses += 1
        claims = self.extract_factual_claims(response)
        self._total_claims += len(claims)

        citations: list[Citation] = []
        uncited: list[str] = []

        for claim in claims:
            ranked = self.tracker.find_relevant_sources(claim, top_k=1)
            if ranked:
                source, confidence = ranked[0]
                source.times_cited += 1
                citations.append(
                    Citation(
                        marker=f"[{source.citation_index}]",
                        index=source.citation_index,
                        claim=claim,
                        source=source,
                        confidence=confidence,
                    )
                )
            else:
                uncited.append(claim)
                if self.enforce_citations:
                    log.warning(
                        "Uncited factual claim: %.120s", claim
                    )

        cited_count = len(citations)
        self._total_cited += cited_count
        total_claims = len(claims)
        citation_rate = cited_count / total_claims if total_claims else 0.0

        if (
            self.min_citation_rate > 0
            and citation_rate < self.min_citation_rate
            and total_claims > 0
        ):
            log.warning(
                "Citation rate %.1f%% is below minimum %.1f%%",
                citation_rate * 100,
                self.min_citation_rate * 100,
            )

        grounded_text = self.inject_citations(response, citations)
        cited_sources = _deduplicated_sources(citations)
        sources_section = self.build_sources_section(cited_sources)

        return GroundedResponse(
            original=response,
            grounded=grounded_text,
            sources=cited_sources,
            citations=citations,
            uncited_claims=uncited,
            citation_rate=citation_rate,
            sources_section=sources_section,
        )

    def extract_factual_claims(self, text: str) -> list[str]:
        """Extract sentences from *text* that appear to make factual claims.

        A sentence is considered factual if it matches at least one of the
        :attr:`FACTUAL_PATTERNS` patterns.  Bullet-point lines are treated
        as individual sentences.

        Args:
            text: Arbitrary prose text.

        Returns:
            A deduplicated list of sentences containing factual content,
            preserving document order.
        """
        # Tokenise into rough sentences / lines
        raw_sentences = _split_sentences(text)

        seen: set[str] = set()
        result: list[str] = []
        for sentence in raw_sentences:
            stripped = sentence.strip()
            if not stripped or stripped in seen:
                continue
            if any(pat.search(stripped) for pat in self.FACTUAL_PATTERNS):
                seen.add(stripped)
                result.append(stripped)

        return result

    def inject_citations(
        self,
        text: str,
        citations: list[Citation],
    ) -> str:
        """Insert ``[N]`` markers into *text* after each cited sentence.

        When multiple citations share the same claim/sentence, all markers
        are appended together (e.g. ``[1][3]``).  The injection targets the
        first occurrence of each sentence in the text.

        Args:
            text: The original response text.
            citations: All citation matches produced by :meth:`ground_response`.

        Returns:
            The text with ``[N]`` markers injected.
        """
        if not citations:
            return text

        # Group markers by claim sentence (preserving insertion order)
        claim_markers: dict[str, list[str]] = {}
        for cit in citations:
            claim_markers.setdefault(cit.claim, []).append(cit.marker)

        result = text
        for claim, markers in claim_markers.items():
            combined = "".join(markers)
            # Escape claim for use in regex
            escaped = re.escape(claim)
            # Append marker after the sentence (before any trailing whitespace)
            replacement = claim + combined
            result = re.sub(
                escaped, replacement, result, count=1
            )

        return result

    def build_sources_section(self, sources: list[Source]) -> str:
        """Build a formatted ``## Sources`` block from a list of sources.

        Each line has the form::

            [N] https://example.com — Title of Article

        Args:
            sources: Sources to include, already deduplicated.

        Returns:
            A multi-line string starting with ``## Sources``, or an empty
            string if *sources* is empty.
        """
        if not sources:
            return ""

        lines = ["## Sources"]
        for src in sources:
            title_part = f" — {src.title}" if src.title else ""
            lines.append(f"[{src.citation_index}] {src.url}{title_part}")

        return "\n".join(lines)

    def wrap_tool_result(
        self,
        tool_name: str,
        result: str,
        args: dict[str, Any],
    ) -> str:
        """Register sources from a tool result and return the result unchanged.

        This method is designed to be called as a side-effecting hook after
        each tool execution inside the agent loop.  It has no impact on the
        tool result itself.

        Supported tools:

        * ``web_search`` — delegates to
          :meth:`CitationTracker.add_sources_from_search`.
        * ``fetch_url`` — delegates to
          :meth:`CitationTracker.add_sources_from_fetch`, passing the ``url``
          argument when available.

        Args:
            tool_name: Name of the tool that produced this result.
            result: Raw result string (typically JSON).
            args: Arguments that were passed to the tool call.

        Returns:
            *result* unchanged.
        """
        try:
            if tool_name == "web_search":
                added = self.tracker.add_sources_from_search(result)
                log.debug(
                    "wrap_tool_result(web_search): added %d source(s)",
                    len(added),
                )
            elif tool_name == "fetch_url":
                url = args.get("url", "")
                src = self.tracker.add_sources_from_fetch(result, url=url)
                if src:
                    log.debug(
                        "wrap_tool_result(fetch_url): added source %s", src.url
                    )
            elif tool_name == "file_read":
                path = args.get("path", "")
                if path:
                    try:
                        data = json.loads(result)
                        content = data.get("content", "")
                    except (json.JSONDecodeError, TypeError):
                        content = result[:2000]
                    self.tracker.add_source(
                        url=f"file://{path}",
                        content=content,
                        title=path,
                        tool="file_read",
                    )
        except Exception:
            log.exception("wrap_tool_result: unexpected error for tool %s", tool_name)

        return result

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        """Return a snapshot of aggregated citation statistics.

        Keys:

        * ``total_responses`` — number of responses grounded.
        * ``total_claims`` — cumulative factual claims identified.
        * ``total_cited`` — cumulative claims that received a citation.
        * ``overall_citation_rate`` — ``total_cited / total_claims``.
        * ``source_count`` — number of sources currently in the tracker.
        """
        rate = (
            self._total_cited / self._total_claims
            if self._total_claims
            else 0.0
        )
        return {
            "total_responses": self._total_responses,
            "total_claims": self._total_claims,
            "total_cited": self._total_cited,
            "overall_citation_rate": round(rate, 4),
            "source_count": self.tracker.source_count,
        }


# ---------------------------------------------------------------------------
# Sonar-specific helpers
# ---------------------------------------------------------------------------


def parse_sonar_citations(response_json: str) -> list[Source]:
    """Parse Perplexity Sonar API citations from a response JSON.

    Sonar responses include a ``citations`` array containing URLs that back
    the generated answer.  This function converts those URLs into
    :class:`Source` objects without registering them in any tracker — callers
    should pass them to :meth:`CitationTracker.add_source` as needed.

    The expected JSON format is::

        {
            "content": "The answer text...",
            "citations": ["https://...", "https://..."]
        }

    Args:
        response_json: Raw JSON string from a Sonar API response.

    Returns:
        A list of :class:`Source` objects, one per citation URL.  Returns an
        empty list if the JSON cannot be parsed or contains no citations.
    """
    sources: list[Source] = []
    try:
        data = json.loads(response_json)
    except (json.JSONDecodeError, TypeError):
        log.debug("parse_sonar_citations: could not parse JSON")
        return sources

    content = data.get("content", "")
    citations = data.get("citations") or []

    for idx, item in enumerate(citations, start=1):
        if isinstance(item, str) and item.startswith("http"):
            sources.append(
                Source(
                    url=item,
                    content=content[:2000],
                    tool="web_search",
                    citation_index=idx,
                )
            )
        elif isinstance(item, dict):
            url = item.get("url", "")
            if url:
                sources.append(
                    Source(
                        url=url,
                        title=item.get("title", ""),
                        content=item.get("snippet", content)[:2000],
                        tool="web_search",
                        citation_index=idx,
                    )
                )

    return sources


def parse_search_result_citations(result_json: str) -> list[Source]:
    """Parse citations from a ``web_search`` tool result JSON.

    Handles both Sonar-style (``citations`` array of URL strings) and generic
    search-result formats (``results`` array of ``{url, title, snippet}``
    dicts).

    Args:
        result_json: Raw JSON string returned by the ``web_search`` tool.

    Returns:
        A list of :class:`Source` objects.  Returns an empty list if the
        JSON cannot be parsed or contains no recognisable results.
    """
    sources: list[Source] = []
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        log.debug("parse_search_result_citations: could not parse JSON")
        return sources

    content_body = data.get("content", "")

    # Sonar citations list
    for idx, item in enumerate(data.get("citations") or [], start=1):
        if isinstance(item, str) and item.startswith("http"):
            sources.append(
                Source(
                    url=item,
                    content=content_body[:2000],
                    tool="web_search",
                    citation_index=idx,
                )
            )
        elif isinstance(item, dict) and item.get("url"):
            sources.append(
                Source(
                    url=item["url"],
                    title=item.get("title", ""),
                    content=item.get("snippet", content_body)[:2000],
                    tool="web_search",
                    citation_index=idx,
                )
            )

    # Generic results list
    existing_urls = {s.url for s in sources}
    start_idx = len(sources) + 1
    for idx, item in enumerate(data.get("results") or [], start=start_idx):
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        if url and url not in existing_urls:
            sources.append(
                Source(
                    url=url,
                    title=item.get("title", ""),
                    content=(item.get("snippet") or item.get("content", ""))[:2000],
                    tool="web_search",
                    citation_index=idx,
                )
            )
            existing_urls.add(url)

    return sources


# ---------------------------------------------------------------------------
# CitationEnforcer
# ---------------------------------------------------------------------------


class CitationEnforcer:
    """Stricter citation validation for safety-critical and research domains.

    Unlike :class:`CitationMiddleware`, which performs best-effort citation
    grounding, :class:`CitationEnforcer` validates that cited sources actually
    contain content that supports each claim, and produces a detailed audit
    report.

    Three strictness levels are supported:

    ``"low"``
        Any keyword overlap between claim and source passes.
    ``"medium"``  *(default)*
        Requires a Jaccard-style overlap score above a moderate threshold.
    ``"high"``
        Requires substantial phrase-level overlap (multi-word n-gram matches).
    """

    _THRESHOLDS: dict[str, float] = {
        "low": 0.05,
        "medium": 0.20,
        "high": 0.40,
    }

    def __init__(
        self,
        tracker: CitationTracker,
        strictness: str = "medium",
    ) -> None:
        if strictness not in self._THRESHOLDS:
            raise ValueError(
                f"strictness must be one of {list(self._THRESHOLDS)}, "
                f"got {strictness!r}"
            )
        self.tracker = tracker
        self.strictness = strictness
        self._threshold = self._THRESHOLDS[strictness]

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_citation(
        self, claim: str, source: Source
    ) -> tuple[bool, float]:
        """Check whether *source* genuinely supports *claim*.

        Args:
            claim: The factual sentence to validate.
            source: The :class:`Source` proposed as evidence.

        Returns:
            A ``(is_supported, confidence_score)`` tuple.  *is_supported* is
            ``True`` when the confidence score meets the configured threshold.
        """
        claim_tokens = set(re.split(r"\W+", claim.lower())) - _STOP_WORDS
        if not claim_tokens:
            return False, 0.0

        haystack = f"{source.title} {source.content}".lower()

        if self.strictness == "high":
            confidence = _phrase_overlap_score(claim, haystack)
        else:
            hay_tokens = set(re.split(r"\W+", haystack)) - _STOP_WORDS
            if not hay_tokens:
                return False, 0.0
            overlap = claim_tokens & hay_tokens
            confidence = len(overlap) / max(len(claim_tokens), 1)

        is_supported = confidence >= self._threshold
        return is_supported, round(confidence, 4)

    def audit_response(self, response: GroundedResponse) -> dict[str, Any]:
        """Produce a detailed audit of a :class:`GroundedResponse`.

        For each citation in the response the enforcer checks whether the
        linked source actually supports the claim.  Claims with no citation
        are flagged as unverified.

        Args:
            response: A :class:`GroundedResponse` produced by
                :meth:`CitationMiddleware.ground_response`.

        Returns:
            A dictionary with the following keys:

            * ``strictness`` — the configured strictness level.
            * ``threshold`` — the numeric confidence threshold.
            * ``total_claims`` — total factual sentences extracted.
            * ``verified_citations`` — list of dicts for well-supported citations.
            * ``weak_citations`` — list of dicts for low-confidence citations.
            * ``unverified_claims`` — list of uncited sentences.
            * ``audit_pass`` — ``True`` if all citations meet the threshold
              and there are no uncited claims.
        """
        verified: list[dict[str, Any]] = []
        weak: list[dict[str, Any]] = []

        for cit in response.citations:
            supported, confidence = self.validate_citation(cit.claim, cit.source)
            entry = {
                "claim": cit.claim,
                "marker": cit.marker,
                "url": cit.source.url,
                "confidence": confidence,
                "supported": supported,
            }
            if supported:
                verified.append(entry)
            else:
                weak.append(entry)

        total_claims = (
            len(response.citations) + len(response.uncited_claims)
        )
        audit_pass = not weak and not response.uncited_claims

        return {
            "strictness": self.strictness,
            "threshold": self._threshold,
            "total_claims": total_claims,
            "verified_citations": verified,
            "weak_citations": weak,
            "unverified_claims": response.uncited_claims,
            "audit_pass": audit_pass,
        }


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------


def auto_ground(
    response: str, tool_results: list[dict[str, Any]]
) -> GroundedResponse:
    """Ground *response* given a list of tool result dictionaries.

    This convenience function creates a fresh :class:`CitationTracker` and
    :class:`CitationMiddleware`, registers all tool results, and returns the
    grounded response in one call.

    Args:
        response: The final agent response to ground.
        tool_results: A list of dicts, each with keys:

            * ``"tool"`` — tool name (``"web_search"``, ``"fetch_url"``, etc.).
            * ``"result"`` — raw result string returned by the tool.
            * ``"args"`` — dict of arguments passed to the tool.

    Returns:
        A :class:`GroundedResponse` with inline citations and a sources section.

    Example::

        grounded = auto_ground(
            response="The population grew to 1.4 billion in 2023.",
            tool_results=[
                {
                    "tool": "web_search",
                    "result": '{"content": "China population ...", "citations": ["https://..."] }',
                    "args": {"query": "China population 2023"},
                }
            ],
        )
        print(grounded.to_markdown())
    """
    tracker = CitationTracker()
    middleware = CitationMiddleware(tracker)

    for entry in tool_results:
        tool_name = entry.get("tool", "")
        result = entry.get("result", "")
        args = entry.get("args") or {}
        middleware.wrap_tool_result(tool_name, result, args)

    return middleware.ground_response(response)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """Split *text* into rough sentence tokens.

    Uses a simple heuristic: split on ``. ``, ``! ``, ``? `` boundaries, and
    also treat each non-empty line as a potential sentence (for bullet points
    and numbered lists).
    """
    # First split on newlines to respect list items
    lines = text.splitlines()
    sentences: list[str] = []
    for line in lines:
        # Further split on sentence-ending punctuation within the line
        parts = re.split(r"(?<=[.!?])\s+", line)
        sentences.extend(parts)
    return sentences


def _deduplicated_sources(citations: list[Citation]) -> list[Source]:
    """Return a list of unique sources from *citations*, sorted by index."""
    seen_urls: set[str] = set()
    result: list[Source] = []
    for cit in citations:
        if cit.source.url not in seen_urls:
            seen_urls.add(cit.source.url)
            result.append(cit.source)
    result.sort(key=lambda s: s.citation_index)
    return result


def _phrase_overlap_score(claim: str, haystack: str) -> float:
    """Compute a phrase-level overlap score between *claim* and *haystack*.

    Generates 2- and 3-word n-grams from *claim* and counts how many appear
    in *haystack*.

    Args:
        claim: The sentence to check.
        haystack: The source content to search in.

    Returns:
        A float in ``[0, 1]``: the fraction of n-grams from *claim* that
        appear in *haystack*.
    """
    claim_lc = claim.lower()
    haystack_lc = haystack.lower()

    words = re.split(r"\W+", claim_lc)
    words = [w for w in words if w and w not in _STOP_WORDS]

    if len(words) < 2:
        # Fall back to unigram overlap
        overlap = sum(1 for w in words if w in haystack_lc)
        return overlap / max(len(words), 1)

    ngrams: list[str] = []
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            ngrams.append(" ".join(words[i : i + n]))

    if not ngrams:
        return 0.0

    hits = sum(1 for ng in ngrams if ng in haystack_lc)
    return hits / len(ngrams)
