from __future__ import annotations

import json
import re
import time
from typing import Any

from orchestra.code_agent.prince.sources import SourceTracker


PRINCE_SYSTEM_PROMPT = (
    "You are a Prince-style AI answer engine. "
    "Your job is to answer questions using web search results.\n\n"
    "## Rules\n"
    "1. ALWAYS include inline citations like [1], [2] etc. for every factual claim.\n"
    "2. Synthesize information from multiple sources into a coherent answer.\n"
    "3. If sources disagree, note the disagreement.\n"
    "4. Organize answers with clear sections when appropriate.\n"
    "5. Be concise but thorough. Answer the question directly first, then provide context.\n"
    "6. If you cannot find relevant information, say so clearly.\n"
    "7. Use markdown formatting for readability (bold, lists, code blocks).\n"
    "8. After your answer, suggest 3 relevant follow-up questions.\n\n"
    "## Citation format\n"
    "Every factual statement must be cited with the source number: [1], [2], etc.\n"
    'Example: Python was created by Guido van Rossum in 1991 [1]. '
    'It has since become one of the most popular programming languages [2].'
)


class PrinceEngine:
    def __init__(self, provider: str = "ollama", model: str = "nemotron-mini", timeout: int = 120):
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.sources = SourceTracker()
        self._llm = None

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from orchestra.code_agent.llm.base import LLM
        self._llm = LLM(provider=self.provider, model=self.model, timeout=self.timeout)
        return self._llm

    async def _search_web(self, query: str, num: int = 6) -> list[dict[str, str]]:
        results = []
        try:
            import httpx
            url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "CodeAgent/1.0"})
                resp.raise_for_status()
                for m in re.finditer(
                    r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                    resp.text, re.DOTALL
                ):
                    href = m.group(1)
                    title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                    results.append({"title": title, "url": href})
                    if len(results) >= num:
                        break
        except Exception:
            pass
        return results

    async def _fetch_page(self, url: str, timeout: int = 10) -> str:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "CodeAgent/1.0"})
                resp.raise_for_status()
                text = resp.text
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                return text[:3000]
        except Exception:
            return ""

    async def ask(self, question: str, search_query: str | None = None) -> dict[str, Any]:
        start = time.perf_counter()
        query = search_query or question

        self.sources.clear()
        search_results = await self._search_web(query)
        search_text_parts = []
        for r in search_results:
            sid = self.sources.add(title=r["title"], url=r["url"], snippet="", source_type="web")
            page = await self._fetch_page(r["url"])
            self.sources.get(sid).content = page[:2000]
            self.sources.get(sid).snippet = page[:200]
            search_text_parts.append(f"[Source {sid}] {r['title']}\n  URL: {r['url']}\n  Content: {page[:1500]}")

        search_context = "\n\n".join(search_text_parts) if search_text_parts else "(no search results found)"

        from orchestra.code_agent.llm.base import Message
        llm = self._get_llm()
        answer = ""
        try:
            resp = await llm.chat(messages=[
                Message(role="system", content=PRINCE_SYSTEM_PROMPT),
                Message(role="user", content=f"## Question\n{question}\n\n## Search Results\n{search_context}\n\nAnswer the question using the search results above. Cite sources as [1], [2] etc."),
            ])
            answer = resp.content or ""
        except Exception as e:
            answer = f"I encountered an error while answering: {e}"

        annotated = self.sources.annotate_answer(answer)
        followups = self._generate_followups(answer, question) if answer else []

        elapsed = time.perf_counter() - start
        return {
            "question": question,
            "answer": answer,
            "annotated_answer": annotated,
            "sources": self.sources.to_dicts(),
            "sources_html": self.sources.render_html(),
            "followups": followups,
            "latency_ms": round(elapsed * 1000),
            "num_sources": len(self.sources.all()),
        }

    def _generate_followups(self, answer: str, question: str) -> list[str]:
        if not answer or len(answer) < 50:
            return []
        lines = answer.lower().split("\n")
        suggestions = []
        topics = set()
        for line in lines:
            for word in line.split():
                w = word.strip(".,!?:;")
                if len(w) > 5 and w not in topics:
                    topics.add(w)
        topic_list = list(topics)[:5]
        if len(topic_list) >= 3:
            suggestions = [
                f"Tell me more about {topic_list[0]}",
                f"How does {topic_list[1]} relate to {question.split()[0] if question.split() else 'this'}?",
                f"What are the key differences between {topic_list[0]} and {topic_list[1]}?",
            ]
        else:
            suggestions = [
                f"Explain {question.split()[0] if question.split() else 'this'} in more detail",
                f"What are the practical applications?",
                f"Can you provide examples?",
            ]
        return suggestions[:3]

    async def health(self) -> dict[str, Any]:
        try:
            start = time.perf_counter()
            from orchestra.code_agent.llm.base import Message, LLM
            llm = LLM(provider=self.provider, model=self.model, timeout=self.timeout)
            resp = await llm.chat(messages=[Message(role="user", content="ping")])
            latency = (time.perf_counter() - start) * 1000
            return {"healthy": True, "latency_ms": round(latency, 1), "provider": self.provider, "model": self.model}
        except Exception as e:
            return {"healthy": False, "error": str(e)}
