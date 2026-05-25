"""Literature-to-Experiment Pipeline.

Given a research question, this pipeline:
  1. Generates targeted search queries via LLM
  2. Fetches papers from Semantic Scholar (PubMed fallback)
  3. Synthesizes the literature
  4. Produces a testable hypothesis
  5. Designs a concrete experiment

Usage::

    from orchestra.code_agent.science import LiteratureToExperimentPipeline

    pipeline = LiteratureToExperimentPipeline(model="kimi-k2.5")
    report = await pipeline.run("Does intermittent fasting improve insulin sensitivity?")
    print(report.to_markdown())
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from orchestra.code_agent.tools.science import Paper, fetch_semantic_scholar, fetch_pubmed

log = logging.getLogger("orchestra.science")

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

@dataclass
class ScienceReport:
    question: str
    queries_used: list[str]
    papers: list[Paper]
    synthesis: str
    hypothesis: str
    experimental_design: str

    def to_markdown(self) -> str:
        lines = [
            "# Science Report",
            "",
            "## Research Question",
            self.question,
            "",
            "## Literature Synthesis",
            self.synthesis,
            "",
            "## Testable Hypothesis",
            self.hypothesis,
            "",
            "## Experimental Design",
            self.experimental_design,
            "",
            f"## Papers Reviewed ({len(self.papers)})",
        ]
        for i, p in enumerate(self.papers, 1):
            et_al = " et al." if len(p.authors) > 3 else ""
            authors = ", ".join(p.authors[:3]) + et_al
            year = str(p.year) if p.year else "n.d."
            entry = f"{i}. **{p.title}** — {authors} ({year})"
            if p.citation_count:
                entry += f" · {p.citation_count} citations"
            lines.append(entry)
            if p.url:
                lines.append(f"   {p.url}")
        lines.append("")
        lines.append(f"*Queries: {', '.join(repr(q) for q in self.queries_used)}*")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a rigorous scientific assistant. You reason step-by-step, cite evidence, "
    "and are precise about what is known versus uncertain."
)

_QUERY_PROMPT = """\
Research question: {question}

Generate exactly 3 search queries to find relevant academic papers on this topic.
Return a JSON array of 3 strings — nothing else.
Example: ["query one", "query two", "query three"]

Make the queries specific, varied (cover different angles), and suitable for Semantic Scholar or PubMed."""

_SYNTHESIS_PROMPT = """\
Research question: {question}

Papers retrieved ({n} papers):
{paper_text}

Write a 300–500 word synthesis of what these papers collectively reveal about the research question.
Focus on: key findings, areas of consensus, contradictions, and gaps in the literature.
Be specific — name mechanisms, cite results, and note effect sizes where available."""

_HYPOTHESIS_PROMPT = """\
Research question: {question}

Literature synthesis:
{synthesis}

Based on this synthesis, state ONE specific, testable scientific hypothesis. Format your answer as:

**Hypothesis:** [single declarative sentence in If X → then Y format]

**Mechanistic rationale:** [2–3 sentences explaining the biological/physical mechanism]

**Novel prediction:** [what this predicts that isn't already established]

**Falsification criterion:** [what result would conclusively disprove the hypothesis]"""

_DESIGN_PROMPT = """\
Research question: {question}

Hypothesis to test: {hypothesis}

Design a practical experiment to test this hypothesis. Structure your answer as:

1. **Study design** — type (RCT, cohort, in vitro, animal model, etc.) and justification
2. **Model system or population** — specific cell line, organism, or patient group
3. **Primary outcome measure** — the key variable to measure and how
4. **Controls** — positive, negative, and confound controls
5. **Sample size** — order-of-magnitude estimate with brief rationale
6. **Timeline** — realistic duration for a well-funded academic lab
7. **Threats to validity** — top 2–3 risks and mitigation strategies

Be concrete. Assume standard academic lab resources."""


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class LiteratureToExperimentPipeline:
    """
    Full pipeline: research question → papers → synthesis → hypothesis → experimental design.

    Uses Semantic Scholar (primary) and PubMed (fallback) for paper retrieval,
    then Orchestra's model router for all LLM synthesis steps.
    """

    def __init__(self, model: str = "kimi-k2.5", max_papers: int = 15) -> None:
        self.model = model
        self.max_papers = max_papers

    def _get_client(self):
        from orchestra.router import ModelRouter
        router = ModelRouter()
        return router.get_client(self.model)

    async def _llm(self, prompt: str, temperature: float = 0.3, max_tokens: int = 1500) -> str:
        client, model_id = self._get_client()
        response = await client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (response.choices[0].message.content or "").strip()

    async def _generate_queries(self, question: str) -> list[str]:
        raw = await self._llm(_QUERY_PROMPT.format(question=question), temperature=0.2, max_tokens=200)
        try:
            start, end = raw.find("["), raw.rfind("]") + 1
            queries = json.loads(raw[start:end])
            if isinstance(queries, list) and queries:
                return [str(q) for q in queries[:3]]
        except Exception:
            pass
        return [question]

    async def _fetch_papers(self, queries: list[str]) -> list[Paper]:
        per_query = max(3, self.max_papers // len(queries))
        results = await asyncio.gather(
            *[fetch_semantic_scholar(q, per_query) for q in queries],
            return_exceptions=True,
        )
        seen: set[str] = set()
        papers: list[Paper] = []
        for batch in results:
            if isinstance(batch, Exception):
                continue
            for p in batch:
                if p.paper_id not in seen and p.abstract:
                    seen.add(p.paper_id)
                    papers.append(p)
        papers.sort(key=lambda p: p.citation_count, reverse=True)
        return papers[:self.max_papers]

    async def _fetch_pubmed_fallback(self, queries: list[str]) -> list[Paper]:
        per_query = max(3, self.max_papers // len(queries))
        results = await asyncio.gather(
            *[fetch_pubmed(q, per_query) for q in queries],
            return_exceptions=True,
        )
        seen: set[str] = set()
        papers: list[Paper] = []
        for batch in results:
            if isinstance(batch, Exception):
                continue
            for p in batch:
                if p.paper_id not in seen and p.abstract:
                    seen.add(p.paper_id)
                    papers.append(p)
        return papers[:self.max_papers]

    async def _synthesize_literature(self, question: str, papers: list[Paper]) -> str:
        paper_text = "\n\n".join(
            f"[{i+1}] {p.title} ({p.year or 'n.d.'}) — {', '.join(p.authors[:3])}\n{p.abstract}"
            for i, p in enumerate(papers)
        )
        return await self._llm(
            _SYNTHESIS_PROMPT.format(question=question, n=len(papers), paper_text=paper_text),
            temperature=0.3,
            max_tokens=1000,
        )

    async def _generate_hypothesis(self, question: str, synthesis: str) -> str:
        return await self._llm(
            _HYPOTHESIS_PROMPT.format(question=question, synthesis=synthesis),
            temperature=0.4,
            max_tokens=600,
        )

    async def _design_experiment(self, question: str, hypothesis: str) -> str:
        return await self._llm(
            _DESIGN_PROMPT.format(question=question, hypothesis=hypothesis),
            temperature=0.3,
            max_tokens=1200,
        )

    async def run(self, question: str, verbose: bool = False) -> ScienceReport:
        """Run the full pipeline. Pass verbose=True for progress output."""

        def _log(msg: str) -> None:
            if verbose:
                print(msg)

        _log("[1/5] Generating search queries...")
        queries = await self._generate_queries(question)
        _log(f"      {queries}")

        _log("[2/5] Fetching papers from Semantic Scholar...")
        papers = await self._fetch_papers(queries)

        if not papers:
            _log("      Semantic Scholar returned nothing — trying PubMed...")
            papers = await self._fetch_pubmed_fallback(queries)

        if not papers:
            return ScienceReport(
                question=question,
                queries_used=queries,
                papers=[],
                synthesis="No relevant papers found. Try a different research question or check your connection.",
                hypothesis="Cannot generate a hypothesis without literature.",
                experimental_design="Cannot design an experiment without a hypothesis.",
            )

        _log(f"      Retrieved {len(papers)} papers.")

        _log("[3/5] Synthesizing literature...")
        synthesis = await self._synthesize_literature(question, papers)

        _log("[4/5] Generating hypothesis...")
        hypothesis = await self._generate_hypothesis(question, synthesis)

        _log("[5/5] Designing experiment...")
        design = await self._design_experiment(question, hypothesis)

        return ScienceReport(
            question=question,
            queries_used=queries,
            papers=papers,
            synthesis=synthesis,
            hypothesis=hypothesis,
            experimental_design=design,
        )
