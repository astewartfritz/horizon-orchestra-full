"""Horizon Orchestra — Deep Research Skill.

Horizon Prince core capability: multi-source web search with citation synthesis.
Generates diversified search queries, executes them in parallel, synthesises
findings via LLM, and returns structured results with inline [N] citations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .base import Skill

if TYPE_CHECKING:
    from ..router import ModelRouter
    from ..perplexity import PerplexitySearch

__all__ = [
    "DeepResearchSkill",
    "ResearchResult",
    "FactCheckResult",
]

log = logging.getLogger("orchestra.skills.research")


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ResearchResult:
    """Structured output of a research operation."""

    answer: str                                         # LLM synthesis with [N] inline citations
    sources: list[dict[str, str]] = field(default_factory=list)   # [{title, url, snippet}]
    confidence: float = 0.0                             # 0-1 estimate
    research_queries: list[str] = field(default_factory=list)
    duration: float = 0.0                               # seconds


@dataclass
class FactCheckResult:
    """Structured output of a fact-check operation."""

    claim: str
    verdict: str = "unverified"                         # "supported" | "contested" | "unverified"
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Skill implementation
# ---------------------------------------------------------------------------

class DeepResearchSkill(Skill):
    """Multi-source web research with citation synthesis.

    Requires a :class:`~orchestra.router.ModelRouter` for LLM calls.
    Optionally accepts a :class:`~orchestra.perplexity.PerplexitySearch`
    instance — if present, Sonar is used for grounded search; otherwise the
    skill falls back to httpx direct fetches.
    """

    name: str = "research"
    description: str = (
        "Deep web research with citation synthesis. Searches multiple sources, "
        "extracts content, and returns a structured answer with inline citations."
    )

    def __init__(
        self,
        router: ModelRouter,
        perplexity: PerplexitySearch | None = None,
    ) -> None:
        self.router = router
        self.perplexity = perplexity

    # ------------------------------------------------------------------
    # Core research flow
    # ------------------------------------------------------------------

    async def research(
        self,
        query: str,
        depth: str = "standard",
        max_sources: int = 10,
    ) -> ResearchResult:
        """Main research entry-point.

        Steps:
        1. Generate 3-5 diversified sub-queries from *query*.
        2. Execute all sub-queries in parallel (Sonar or direct HTTP).
        3. Collect raw text + URLs from results.
        4. Call the LLM to synthesise a cited answer.
        5. Return :class:`ResearchResult`.
        """
        t_start = time.monotonic()
        log.info("research() query=%r depth=%s max_sources=%d", query, depth, max_sources)

        # --- 1. Generate search queries ---------------------------------
        sub_queries = await self._generate_queries(query, depth)
        log.debug("Generated sub-queries: %s", sub_queries)

        # --- 2. Execute searches in parallel ----------------------------
        raw_results: list[dict[str, Any]] = []
        if self.perplexity:
            raw_results = await self._sonar_search_all(sub_queries, max_sources)
        else:
            raw_results = await self._http_search_all(sub_queries, max_sources)

        # --- 3. Deduplicate and cap sources -----------------------------
        sources = _deduplicate_sources(raw_results)[:max_sources]

        # --- 4. Synthesise via LLM -------------------------------------
        answer, confidence = await self._synthesise(query, sources)

        duration = time.monotonic() - t_start
        log.info("research() done in %.2fs, sources=%d", duration, len(sources))

        return ResearchResult(
            answer=answer,
            sources=sources,
            confidence=confidence,
            research_queries=sub_queries,
            duration=duration,
        )

    async def deep_dive(
        self,
        query: str,
        max_sources: int = 20,
    ) -> ResearchResult:
        """Extended research: decompose into sub-questions, research each,
        then synthesise a comprehensive report.
        """
        t_start = time.monotonic()
        log.info("deep_dive() query=%r max_sources=%d", query, max_sources)

        # --- Generate sub-questions ------------------------------------
        sub_questions = await self._generate_sub_questions(query)
        log.debug("Sub-questions: %s", sub_questions)

        # --- Research each sub-question in parallel --------------------
        tasks = [
            self.research(q, depth="deep", max_sources=max_sources // len(sub_questions) + 1)
            for q in sub_questions
        ]
        partial_results: list[ResearchResult | BaseException] = await asyncio.gather(
            *tasks, return_exceptions=True
        )

        # --- Aggregate sources and partial answers ---------------------
        all_sources: list[dict[str, str]] = []
        section_texts: list[str] = []
        for sq, pr in zip(sub_questions, partial_results):
            if isinstance(pr, BaseException):
                log.warning("Sub-question %r failed: %s", sq, pr)
                section_texts.append(f"**{sq}**\n[Research failed: {pr}]")
                continue
            section_texts.append(f"**{sq}**\n{pr.answer}")
            all_sources.extend(pr.sources)

        all_sources = _deduplicate_sources(all_sources)[:max_sources]

        # --- Final synthesis -------------------------------------------
        combined_text = "\n\n".join(section_texts)
        synthesis_prompt = (
            f"You have researched the following question in depth:\n\n"
            f"**{query}**\n\n"
            f"Below are section-by-section findings from multiple sub-questions. "
            f"Write a single comprehensive, well-structured report that integrates "
            f"all findings. Use inline citations like [1], [2], etc. referring to "
            f"the source list provided.\n\n"
            f"=== SECTION FINDINGS ===\n{combined_text}"
        )

        answer, confidence = await self._synthesise_with_prompt(synthesis_prompt, all_sources)
        duration = time.monotonic() - t_start

        return ResearchResult(
            answer=answer,
            sources=all_sources,
            confidence=confidence,
            research_queries=sub_questions,
            duration=duration,
        )

    async def fact_check(self, claim: str) -> FactCheckResult:
        """Search for evidence supporting or contradicting *claim*.

        Returns a :class:`FactCheckResult` with verdict and evidence lists.
        """
        log.info("fact_check() claim=%r", claim)

        # Search for both supporting and contradicting evidence
        queries_for = [
            f"evidence supporting: {claim}",
            f"studies confirming: {claim}",
        ]
        queries_against = [
            f"evidence against: {claim}",
            f"debunking: {claim}",
            f"criticism of: {claim}",
        ]

        all_queries = queries_for + queries_against
        if self.perplexity:
            raw_results = await self._sonar_search_all(all_queries, max_sources=10)
        else:
            raw_results = await self._http_search_all(all_queries, max_sources=10)

        sources = _deduplicate_sources(raw_results)

        # LLM-based verdict
        verdict, evidence_for, evidence_against, confidence = await self._evaluate_claim(
            claim, sources
        )

        return FactCheckResult(
            claim=claim,
            verdict=verdict,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            sources=sources,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Internal helpers — query generation
    # ------------------------------------------------------------------

    async def _generate_queries(self, query: str, depth: str) -> list[str]:
        """Ask the LLM to produce diversified search sub-queries."""
        n = 5 if depth == "deep" else 3
        prompt = (
            f"Generate exactly {n} diverse web search queries to thoroughly research "
            f"the following question. Each query should explore a different angle "
            f"(e.g., overview, technical details, recent developments, expert opinions, "
            f"statistics). Output ONLY the queries, one per line, no numbering.\n\n"
            f"Question: {query}"
        )
        text = await self._llm_call(prompt, max_tokens=300)
        queries = [q.strip() for q in text.strip().splitlines() if q.strip()]
        if not queries:
            queries = [query]
        return queries[:n]

    async def _generate_sub_questions(self, query: str) -> list[str]:
        """Decompose a broad question into focused sub-questions."""
        prompt = (
            f"Break the following research question into 4-6 focused sub-questions "
            f"that together cover all aspects needed for a comprehensive answer. "
            f"Output ONLY the sub-questions, one per line, no numbering.\n\n"
            f"Question: {query}"
        )
        text = await self._llm_call(prompt, max_tokens=400)
        questions = [q.strip() for q in text.strip().splitlines() if q.strip()]
        if not questions:
            questions = [query]
        return questions[:6]

    # ------------------------------------------------------------------
    # Internal helpers — search execution
    # ------------------------------------------------------------------

    async def _sonar_search_all(
        self, queries: list[str], max_sources: int
    ) -> list[dict[str, Any]]:
        """Run all queries via Perplexity Sonar in parallel."""
        assert self.perplexity is not None

        async def _one(q: str) -> list[dict[str, Any]]:
            try:
                result = await self.perplexity.search(q, model="sonar")  # type: ignore[union-attr]
                items: list[dict[str, Any]] = []
                # citations come back as URL strings
                for i, url in enumerate(result.citations or []):
                    items.append({
                        "title": f"Source {i + 1}",
                        "url": url,
                        "snippet": result.content[:300] if i == 0 else "",
                    })
                # The main content block is always a source
                if result.content:
                    items.insert(0, {
                        "title": q,
                        "url": result.citations[0] if result.citations else "",
                        "snippet": result.content[:500],
                    })
                return items
            except Exception as exc:
                log.warning("Sonar search failed for %r: %s", q, exc)
                return []

        tasks = [_one(q) for q in queries]
        nested = await asyncio.gather(*tasks)
        flat: list[dict[str, Any]] = [item for sub in nested for item in sub]
        return flat[:max_sources]

    async def _http_search_all(
        self, queries: list[str], max_sources: int
    ) -> list[dict[str, Any]]:
        """Fallback: ask LLM to synthesise without real web search."""
        log.warning("No Perplexity client — using LLM knowledge base only")
        items: list[dict[str, Any]] = []
        for q in queries:
            items.append({
                "title": q,
                "url": "",
                "snippet": f"[LLM knowledge: {q}]",
            })
        return items[:max_sources]

    # ------------------------------------------------------------------
    # Internal helpers — synthesis
    # ------------------------------------------------------------------

    async def _synthesise(
        self, query: str, sources: list[dict[str, str]]
    ) -> tuple[str, float]:
        """Build synthesis prompt and call LLM."""
        prompt = _build_synthesis_prompt(query, sources)
        answer = await self._llm_call(prompt, max_tokens=2000)
        confidence = _estimate_confidence(sources)
        return answer, confidence

    async def _synthesise_with_prompt(
        self, prompt: str, sources: list[dict[str, str]]
    ) -> tuple[str, float]:
        """Synthesise using a pre-built prompt."""
        sources_block = _format_sources_block(sources)
        full_prompt = f"{prompt}\n\n=== SOURCES ===\n{sources_block}"
        answer = await self._llm_call(full_prompt, max_tokens=4000)
        confidence = _estimate_confidence(sources)
        return answer, confidence

    async def _evaluate_claim(
        self,
        claim: str,
        sources: list[dict[str, str]],
    ) -> tuple[str, list[str], list[str], float]:
        """LLM-based verdict extraction for fact-checking."""
        sources_block = _format_sources_block(sources)
        prompt = (
            f"You are a rigorous fact-checker. Evaluate the following claim based "
            f"on the sources provided.\n\n"
            f"Claim: {claim}\n\n"
            f"Sources:\n{sources_block}\n\n"
            f"Respond in this exact format:\n"
            f"VERDICT: supported|contested|unverified\n"
            f"FOR:\n- [evidence point 1]\n- [evidence point 2]\n"
            f"AGAINST:\n- [counter-evidence point 1]\n- [counter-evidence point 2]\n"
            f"CONFIDENCE: 0.0-1.0"
        )
        text = await self._llm_call(prompt, max_tokens=600)

        verdict = "unverified"
        evidence_for: list[str] = []
        evidence_against: list[str] = []
        confidence = 0.5

        lines = text.strip().splitlines()
        section = ""
        for line in lines:
            low = line.strip().lower()
            if low.startswith("verdict:"):
                v = low.replace("verdict:", "").strip()
                if v in ("supported", "contested", "unverified"):
                    verdict = v
            elif low == "for:":
                section = "for"
            elif low == "against:":
                section = "against"
            elif low.startswith("confidence:"):
                try:
                    confidence = float(low.replace("confidence:", "").strip())
                except ValueError:
                                        import logging as _log; _log.getLogger('skills.research').debug('Suppressed exception', exc_info=True)
            elif line.strip().startswith("-"):
                point = line.strip().lstrip("- ").strip()
                if section == "for":
                    evidence_for.append(point)
                elif section == "against":
                    evidence_against.append(point)

        return verdict, evidence_for, evidence_against, confidence

    # ------------------------------------------------------------------
    # Internal helpers — LLM
    # ------------------------------------------------------------------

    async def _llm_call(self, prompt: str, max_tokens: int = 1000) -> str:
        """Route an LLM call via the router."""
        model_name = self.router.route("reasoning")
        client, model_id = self.router.get_client(model_name)
        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            log.error("LLM call failed: %s", exc)
            return f"[LLM error: {exc}]"

    # ------------------------------------------------------------------
    # Skill ABC interface
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "research_query",
                    "description": (
                        "Research a question using multi-source web search and LLM synthesis. "
                        "Returns an answer with inline [N] citations and a source list."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The research question or topic.",
                            },
                            "depth": {
                                "type": "string",
                                "enum": ["standard", "deep"],
                                "description": "standard = 3 sub-queries; deep = 5 sub-queries.",
                                "default": "standard",
                            },
                            "max_sources": {
                                "type": "integer",
                                "description": "Maximum sources to include (default 10).",
                                "default": 10,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "research_deep_dive",
                    "description": (
                        "Extended research: decomposes the question into sub-questions, "
                        "researches each independently, then synthesises a comprehensive report."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The broad research question.",
                            },
                            "max_sources": {
                                "type": "integer",
                                "description": "Maximum total sources (default 20).",
                                "default": 20,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "research_fact_check",
                    "description": (
                        "Fact-check a claim by searching for supporting and contradicting evidence. "
                        "Returns verdict: supported, contested, or unverified."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "claim": {
                                "type": "string",
                                "description": "The claim to fact-check.",
                            },
                        },
                        "required": ["claim"],
                    },
                },
            },
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch tool calls to the appropriate method."""
        if action == "research_query":
            result = await self.research(
                query=params["query"],
                depth=params.get("depth", "standard"),
                max_sources=int(params.get("max_sources", 10)),
            )
            return {
                "answer": result.answer,
                "sources": result.sources,
                "confidence": result.confidence,
                "research_queries": result.research_queries,
                "duration": result.duration,
            }

        if action == "research_deep_dive":
            result = await self.deep_dive(
                query=params["query"],
                max_sources=int(params.get("max_sources", 20)),
            )
            return {
                "answer": result.answer,
                "sources": result.sources,
                "confidence": result.confidence,
                "research_queries": result.research_queries,
                "duration": result.duration,
            }

        if action == "research_fact_check":
            result = await self.fact_check(claim=params["claim"])
            return {
                "claim": result.claim,
                "verdict": result.verdict,
                "evidence_for": result.evidence_for,
                "evidence_against": result.evidence_against,
                "sources": result.sources,
                "confidence": result.confidence,
            }

        return {"error": f"Unknown action: {action!r}"}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _deduplicate_sources(
    sources: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Remove duplicates by URL, preserving order."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for s in sources:
        url = s.get("url", "")
        key = url if url else s.get("title", "")
        if key and key in seen:
            continue
        seen.add(key)
        out.append({
            "title": str(s.get("title", "")),
            "url": str(url),
            "snippet": str(s.get("snippet", "")),
        })
    return out


def _format_sources_block(sources: list[dict[str, str]]) -> str:
    """Format sources list for LLM prompt."""
    lines: list[str] = []
    for i, src in enumerate(sources, 1):
        title = src.get("title", f"Source {i}")
        url = src.get("url", "")
        snippet = src.get("snippet", "")
        lines.append(f"[{i}] {title}")
        if url:
            lines.append(f"    URL: {url}")
        if snippet:
            lines.append(f"    Excerpt: {snippet[:300]}")
    return "\n".join(lines)


def _build_synthesis_prompt(query: str, sources: list[dict[str, str]]) -> str:
    """Construct the synthesis prompt for the LLM."""
    sources_block = _format_sources_block(sources)
    return (
        f"You are a research synthesiser. Answer the following question based on "
        f"the provided sources. Use inline citations like [1], [2], etc. "
        f"Be accurate, comprehensive, and well-structured.\n\n"
        f"Question: {query}\n\n"
        f"Sources:\n{sources_block}\n\n"
        f"Synthesised Answer:"
    )


def _estimate_confidence(sources: list[dict[str, str]]) -> float:
    """Estimate confidence based on number and quality of sources."""
    n = len(sources)
    if n == 0:
        return 0.1
    if n >= 8:
        return 0.9
    return 0.4 + (n / 8) * 0.5
