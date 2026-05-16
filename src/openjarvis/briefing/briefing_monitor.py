"""
openjarvis/briefing/briefing_monitor.py
────────────────────────────────────────
News fetcher and briefing composer for OpenJarvis Enterprise daily briefings.

Pipeline:
  1. fetch_topic_news()   — parallel web search per topic query
  2. deduplicate()        — remove overlapping results across queries
  3. compose_briefing()   — Kimi K2.5 synthesizes into structured email text
  4. detect_breaking()    — check against breaking_keywords for notifications
  5. BriefingResult       — structured output ready for delivery
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from openai import AsyncOpenAI

from openjarvis.briefing.briefing_config import BriefingConfig, BriefingTopic


@dataclass
class NewsItem:
    title: str
    snippet: str
    url: str
    source: str
    topic_name: str
    published_at: Optional[str] = None

    @property
    def fingerprint(self) -> str:
        return hashlib.md5(self.url.encode()).hexdigest()


@dataclass
class TopicResult:
    topic: BriefingTopic
    items: list[NewsItem] = field(default_factory=list)
    is_breaking: bool = False
    breaking_headline: Optional[str] = None


@dataclass
class BriefingResult:
    config_id: str
    customer_id: str
    briefing_name: str
    date_label: str
    subject: str
    body: str
    topic_results: list[TopicResult] = field(default_factory=list)
    has_breaking_news: bool = False
    breaking_summary: Optional[str] = None
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class SonarSearchProvider:
    def __init__(self, sonar_key: str):
        self.client = AsyncOpenAI(
            api_key=sonar_key,
            base_url="https://api.perplexity.ai",
        )

    async def search(self, query: str, max_results: int = 5) -> list[NewsItem]:
        try:
            response = await self.client.chat.completions.create(
                model="sonar-pro",
                messages=[{
                    "role": "system",
                    "content": (
                        "You are a news research assistant. "
                        "Find the most recent and significant developments "
                        "from the past 24 hours for the given topic. "
                        "Return up to 5 bullet points, each starting with "
                        "the source name in brackets, e.g.: "
                        "[Reuters] Headline — brief context. URL: https://..."
                    ),
                }, {
                    "role": "user",
                    "content": query,
                }],
                max_tokens=1024,
            )
            raw = response.choices[0].message.content
            citations = getattr(response, "citations", []) or []
            return self._parse_bullets(raw, citations, query)
        except Exception:
            return []

    def _parse_bullets(self, raw: str, citations: list[str],
                       query: str) -> list[NewsItem]:
        items: list[NewsItem] = []
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        url_pool = list(citations)
        url_idx = 0

        for line in lines:
            if not line.startswith(("-", "•", "*", "[")):
                continue
            source_match = re.match(r"[-•*]?\s*\[([^\]]+)\]", line)
            source = source_match.group(1) if source_match else "Unknown"
            text = re.sub(r"^[-•*\s]*\[[^\]]+\]\s*", "", line)
            url_match = re.search(r"https?://\S+", text)
            url = url_match.group(0) if url_match else (
                url_pool[url_idx] if url_idx < len(url_pool) else ""
            )
            if url_match:
                text = text.replace(url_match.group(0), "").strip()
            else:
                url_idx += 1

            items.append(NewsItem(
                title=text[:120],
                snippet=text,
                url=url.rstrip(".,)"),
                source=source,
                topic_name=query,
            ))

        return items


class BriefingMonitor:
    def __init__(
        self,
        moonshot_key: str,
        sonar_key: str,
        max_parallel_queries: int = 10,
    ):
        self.kimi = AsyncOpenAI(
            api_key=moonshot_key,
            base_url="https://api.moonshot.ai/v1",
        )
        self.search = SonarSearchProvider(sonar_key)
        self.semaphore = asyncio.Semaphore(max_parallel_queries)

    async def run(self, config: BriefingConfig) -> BriefingResult:
        date_label = datetime.now(timezone.utc).strftime("%B %d, %Y")

        topic_results = await self._fetch_all_topics(config.topics)

        for tr in topic_results:
            tr.is_breaking, tr.breaking_headline = self._detect_breaking(tr)

        body = await self._compose_email(
            config=config,
            topic_results=topic_results,
            date_label=date_label,
        )

        subject = config.delivery.subject_template.format(
            briefing_name=config.briefing_name,
            date=date_label,
        )

        breaking_items = [tr for tr in topic_results if tr.is_breaking]
        breaking_summary = None
        if breaking_items:
            breaking_summary = " | ".join(
                f"{tr.topic.name}: {tr.breaking_headline}"
                for tr in breaking_items
                if tr.breaking_headline
            )

        return BriefingResult(
            config_id=config.id,
            customer_id=config.customer_id,
            briefing_name=config.briefing_name,
            date_label=date_label,
            subject=subject,
            body=body,
            topic_results=topic_results,
            has_breaking_news=bool(breaking_items),
            breaking_summary=breaking_summary,
        )

    async def _fetch_all_topics(
        self, topics: list[BriefingTopic]
    ) -> list[TopicResult]:
        tasks = [self._fetch_topic(t) for t in topics]
        return await asyncio.gather(*tasks)

    async def _fetch_topic(self, topic: BriefingTopic) -> TopicResult:
        async with self.semaphore:
            query_tasks = [self.search.search(q, max_results=5) for q in topic.queries]
            results_per_query = await asyncio.gather(*query_tasks)

        seen: set[str] = set()
        items: list[NewsItem] = []
        for batch in results_per_query:
            for item in batch:
                item.topic_name = topic.name
                if item.fingerprint not in seen:
                    seen.add(item.fingerprint)
                    items.append(item)

        return TopicResult(topic=topic, items=items)

    def _detect_breaking(
        self, tr: TopicResult
    ) -> tuple[bool, Optional[str]]:
        if not tr.topic.breaking_keywords:
            return False, None

        keywords = [kw.lower() for kw in tr.topic.breaking_keywords]
        for item in tr.items:
            text = (item.title + " " + item.snippet).lower()
            for kw in keywords:
                if kw in text:
                    return True, item.title[:120]

        return False, None

    async def _compose_email(
        self,
        config: BriefingConfig,
        topic_results: list[TopicResult],
        date_label: str,
    ) -> str:
        research_blocks: list[str] = []
        for tr in topic_results:
            if not tr.items:
                research_blocks.append(
                    f"[{tr.topic.name}]\nNo significant developments found in the past 24 hours."
                )
                continue
            bullets = "\n".join(
                f"- {item.snippet} ({item.source}) {item.url}"
                for item in tr.items[:8]
            )
            research_blocks.append(f"[{tr.topic.name}]\n{bullets}")

        research_context = "\n\n".join(research_blocks)

        section_guide = ""
        if config.sections:
            section_guide = "Structure your email using these exact section headers:\n"
            for sec in config.sections:
                topic_names = [
                    tr.topic.name
                    for tr in topic_results
                    if tr.topic.id in sec.topic_ids
                ]
                section_guide += (
                    f"  {sec.header} — covering: {', '.join(topic_names)}\n"
                )
        else:
            section_guide = "Create one section per topic using the topic name as header (ALL CAPS)."

        system_prompt = f"""You are OpenJarvis's Intelligence Briefing Engine.
Your task: compose a clean, actionable daily briefing email in PLAIN TEXT.

RULES:
- Use plain text only. No markdown, no HTML, no asterisks, no bold.
- Use ALL CAPS for section headers.
- Each bullet point starts with a dash (-)
- Every factual claim must include the source name and URL inline: (Source Name: URL)
- Be concise. Max 5 bullets per section.
- End with a KEY TAKEAWAYS section: 2-3 sentences on overall trajectory.
- If a topic had no news, write "No significant developments in the past 24 hours."

EMAIL STRUCTURE:
{config.briefing_name.upper()} -- {date_label}
{'-' * 60}

{section_guide}

KEY TAKEAWAYS
[2-3 sentence synthesis]

{'-' * 60}
Delivered by OpenJarvis Enterprise | openjarvis.com
"""

        response = await self.kimi.chat.completions.create(
            model="kimi-k2.5",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    f"Here is the raw research gathered in the past 24 hours:\n\n"
                    f"{research_context}\n\n"
                    f"Compose the briefing email now."
                )},
            ],
            max_tokens=4096,
        )

        return response.choices[0].message.content
