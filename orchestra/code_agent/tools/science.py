from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

_SS_BASE = "https://api.semanticscholar.org/graph/v1"
_PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_HEADERS = {"User-Agent": "OrchestraBot/1.0 (research-pipeline)"}
_SS_FIELDS = "paperId,title,abstract,year,authors,citationCount"


@dataclass
class Paper:
    title: str
    authors: list[str]
    year: int | None
    abstract: str
    source: str
    paper_id: str
    citation_count: int = 0
    url: str = ""


async def fetch_semantic_scholar(query: str, limit: int = 10) -> list[Paper]:
    """Search Semantic Scholar; returns [] on any failure. Retries once on 429."""
    if not HAS_HTTPX:
        return []
    try:
        async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as c:
            r = await c.get(
                f"{_SS_BASE}/paper/search",
                params={"query": query, "fields": _SS_FIELDS, "limit": limit},
            )
            if r.status_code == 429:
                await asyncio.sleep(5)
                r = await c.get(
                    f"{_SS_BASE}/paper/search",
                    params={"query": query, "fields": _SS_FIELDS, "limit": limit},
                )
            r.raise_for_status()
            data = r.json()
        papers = []
        for p in data.get("data", []):
            if not p.get("abstract"):
                continue
            pid = p.get("paperId", "")
            papers.append(Paper(
                title=p.get("title", "Untitled"),
                authors=[a.get("name", "") for a in p.get("authors", [])][:5],
                year=p.get("year"),
                abstract=p.get("abstract", ""),
                source="semantic_scholar",
                paper_id=pid,
                citation_count=p.get("citationCount", 0),
                url=f"https://www.semanticscholar.org/paper/{pid}" if pid else "",
            ))
        return papers
    except Exception:
        return []


async def fetch_pubmed(query: str, limit: int = 10) -> list[Paper]:
    """Search PubMed via NCBI E-utilities; returns [] on any failure."""
    if not HAS_HTTPX:
        return []
    try:
        async with httpx.AsyncClient(timeout=25, headers=_HEADERS) as c:
            r = await c.get(
                f"{_PUBMED_BASE}/esearch.fcgi",
                params={"db": "pubmed", "term": query, "retmax": limit, "retmode": "json"},
            )
            r.raise_for_status()
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []

            r2 = await c.get(
                f"{_PUBMED_BASE}/efetch.fcgi",
                params={"db": "pubmed", "id": ",".join(ids), "rettype": "abstract", "retmode": "text"},
            )
            r2.raise_for_status()

            r3 = await c.get(
                f"{_PUBMED_BASE}/esummary.fcgi",
                params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            )
            r3.raise_for_status()
            summaries = r3.json().get("result", {})

        abstract_blocks = r2.text.strip().split("\n\n\n")
        papers = []
        for i, pmid in enumerate(ids):
            meta = summaries.get(pmid, {})
            title = meta.get("title", "").rstrip(".")
            year_raw = meta.get("pubdate", "")[:4]
            year = int(year_raw) if year_raw.isdigit() else None
            authors = [a.get("name", "") for a in meta.get("authors", [])][:5]

            abstract = ""
            if i < len(abstract_blocks):
                ab_lines = []
                in_ab = False
                for line in abstract_blocks[i].split("\n"):
                    if line.startswith("AB  -"):
                        in_ab = True
                        ab_lines.append(line[6:].strip())
                    elif in_ab:
                        if line.startswith("      "):
                            ab_lines.append(line.strip())
                        else:
                            break
                abstract = " ".join(ab_lines).strip()

            if not abstract:
                continue
            papers.append(Paper(
                title=title or "Untitled",
                authors=authors,
                year=year,
                abstract=abstract,
                source="pubmed",
                paper_id=pmid,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            ))
        return papers
    except Exception:
        return []


def _format_papers(papers: list[Paper], header: str) -> str:
    lines = [header, ""]
    for i, p in enumerate(papers, 1):
        authors_str = ", ".join(p.authors) if p.authors else "Unknown"
        year_str = str(p.year) if p.year else "n.d."
        lines.append(f"{i}. {p.title} ({year_str})")
        lines.append(f"   Authors: {authors_str}")
        if p.citation_count:
            lines.append(f"   Citations: {p.citation_count}")
        snippet = p.abstract[:300] + ("..." if len(p.abstract) > 300 else "")
        lines.append(f"   Abstract: {snippet}")
        if p.url:
            lines.append(f"   URL: {p.url}")
        lines.append("")
    return "\n".join(lines).strip()


class SemanticScholarTool(Tool):
    spec = ToolSpec(
        name="semantic_scholar",
        description=(
            "Search academic papers on Semantic Scholar. Returns titles, authors, "
            "abstracts, and citation counts. No API key required."
        ),
        parameters={
            "query": {
                "type": "string",
                "description": "Search query (e.g. 'CRISPR cancer therapy off-target effects')",
            },
            "limit": {
                "type": "integer",
                "description": "Number of papers to return (1–20)",
                "default": 10,
            },
        },
    )

    async def __call__(self, query: str, limit: int = 10) -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx not installed: pip install httpx")
        if not query.strip():
            return ToolResult(error="query is required")
        limit = max(1, min(20, int(limit)))
        papers = await fetch_semantic_scholar(query.strip(), limit)
        if not papers:
            return ToolResult(output=f"No papers with abstracts found for: {query!r}")
        return ToolResult(output=_format_papers(papers, f'Semantic Scholar — "{query}"'))


class PubMedTool(Tool):
    spec = ToolSpec(
        name="pubmed",
        description=(
            "Search biomedical literature on PubMed (NCBI). Best for clinical and "
            "biomedical research. No API key required."
        ),
        parameters={
            "query": {
                "type": "string",
                "description": "Search query (e.g. 'mTOR inhibitor insulin resistance')",
            },
            "limit": {
                "type": "integer",
                "description": "Number of papers to return (1–20)",
                "default": 10,
            },
        },
    )

    async def __call__(self, query: str, limit: int = 10) -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx not installed: pip install httpx")
        if not query.strip():
            return ToolResult(error="query is required")
        limit = max(1, min(20, int(limit)))
        papers = await fetch_pubmed(query.strip(), limit)
        if not papers:
            return ToolResult(output=f"No papers found on PubMed for: {query!r}")
        return ToolResult(output=_format_papers(papers, f'PubMed — "{query}"'))
