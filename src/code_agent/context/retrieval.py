from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievedPassage:
    content: str
    score: float = 0.0
    source: str = "unknown"
    title: str = ""


class RetrievalPipeline:
    """Query → retrieve → filter → rank → summarize → admit into context."""

    def __init__(self):
        self._web_cache: dict[str, list[RetrievedPassage]] = {}

    async def search_web(self, query: str, top_k: int = 5) -> list[RetrievedPassage]:
        """Search web indexes via available web search tools."""
        if query in self._web_cache:
            return self._web_cache[query][:top_k]
        try:
            from code_agent.tools.web import WebSearchTool
            tool = WebSearchTool()
            result = await tool.run(query=query, top_k=top_k)
            passages = []
            if result.output:
                try:
                    data = json.loads(result.output)
                    for item in data if isinstance(data, list) else data.get("results", []):
                        passages.append(RetrievedPassage(
                            content=item.get("snippet", item.get("content", "")),
                            score=item.get("score", 0.5),
                            source="web",
                            title=item.get("title", ""),
                        ))
                except json.JSONDecodeError:
                    passages.append(RetrievedPassage(content=result.output[:500], source="web"))
            self._web_cache[query] = passages
            return passages[:top_k]
        except Exception:
            return []

    async def search_vector(self, query: str, top_k: int = 5) -> list[RetrievedPassage]:
        """Search the skill library via vector similarity."""
        passages = []
        try:
            from code_agent.skills.base import SkillLibrary
            from code_agent.skills.manager import Embedder
            lib = SkillLibrary()
            embedder = Embedder()
            q_emb = embedder.embed(query)
            all_skills = lib.list_all(limit=100)
            scored = []
            for s in all_skills:
                if s.embedding:
                    sim = embedder.cosine_similarity(q_emb, s.embedding)
                    scored.append((sim, s))
            scored.sort(key=lambda x: x[0], reverse=True)
            for sim, s in scored[:top_k]:
                passages.append(RetrievedPassage(
                    content=s.body,
                    score=sim,
                    source="skill_library",
                    title=f"Skill #{s.id}",
                ))
        except Exception:
            pass
        return passages

    async def search_knowledge_base(self, query: str, top_k: int = 3) -> list[RetrievedPassage]:
        """Search user knowledge bases and curated corpora."""
        passages = []
        try:
            from code_agent.knowledge.tool import KnowledgeTool
            tool = KnowledgeTool()
            result = await tool.run(query=query, top_k=top_k)
            if result.output:
                passages.append(RetrievedPassage(content=result.output[:500], source="knowledge_base"))
        except Exception:
            pass
        return passages

    async def retrieve(self, query: str, sources: list[str] | None = None) -> list[RetrievedPassage]:
        """Multi-source retrieval: web + vector + knowledge base."""
        all_passages: list[RetrievedPassage] = []
        tasks = []
        if sources is None or "web" in sources:
            tasks.append(self.search_web(query))
        if sources is None or "skills" in sources:
            tasks.append(self.search_vector(query))
        if sources is None or "knowledge" in sources:
            tasks.append(self.search_knowledge_base(query))

        import asyncio
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                all_passages.extend(r)

        return self.rerank(all_passages)

    def filter(self, passages: list[RetrievedPassage], min_score: float = 0.3,
               max_length: int = 1000) -> list[RetrievedPassage]:
        """Filter passages by relevance score and length."""
        filtered = [p for p in passages if p.score >= min_score and len(p.content) <= max_length]
        return filtered[:20]

    def rerank(self, passages: list[RetrievedPassage]) -> list[RetrievedPassage]:
        """Deduplicate and re-rank by score."""
        seen = set()
        unique = []
        for p in sorted(passages, key=lambda x: x.score, reverse=True):
            key = p.content[:80]
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    def summarize_passages(self, passages: list[RetrievedPassage], max_tokens: int = 2000) -> str:
        """Concatenate and truncate passages to fit token budget."""
        parts = []
        budget = max_tokens * 4  # approximate char budget
        used = 0
        for p in passages:
            text = f"[{p.source}] {p.content}"
            if used + len(text) > budget:
                remaining = budget - used
                if remaining > 80:
                    parts.append(text[:remaining])
                break
            parts.append(text)
            used += len(text)
        return "\n\n".join(parts)

    async def retrieve_and_format(self, query: str, max_tokens: int = 2000) -> str:
        """Full pipeline: retrieve → filter → rerank → summarize → return string."""
        passages = await self.retrieve(query)
        passages = self.filter(passages)
        passages = self.rerank(passages)
        return self.summarize_passages(passages, max_tokens)
