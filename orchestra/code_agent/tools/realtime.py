"""Real-time data tools: Crypto, Currency, Wikipedia, GitHub, NASA APOD."""
from __future__ import annotations

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

_HEADERS = {"User-Agent": "Orchestra/1.0"}


# ── Crypto ────────────────────────────────────────────────────────────────────

class CryptoTool(Tool):
    spec = ToolSpec(
        name="crypto",
        description="Get live cryptocurrency prices. Uses CoinGecko — no API key required.",
        parameters={
            "coins": {"type": "string", "description": "Comma-separated coin ids, e.g. 'bitcoin,ethereum,solana'. Leave empty for top 10.", "default": ""},
            "currency": {"type": "string", "description": "Quote currency (usd, eur, gbp…)", "default": "usd"},
        },
    )

    async def __call__(self, coins: str = "", currency: str = "usd") -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx not installed")
        try:
            params: dict = {"vs_currency": currency.lower(), "order": "market_cap_desc",
                            "sparkline": "false", "price_change_percentage": "24h"}
            if coins.strip():
                params["ids"] = coins.strip()
            else:
                params["per_page"] = 10
                params["page"] = 1
            async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as c:
                r = await c.get("https://api.coingecko.com/api/v3/coins/markets", params=params)
                r.raise_for_status()
                data = r.json()
            cur = currency.upper()
            lines = [f"Crypto prices ({cur})", ""]
            for coin in data:
                chg = coin.get("price_change_percentage_24h") or 0
                arrow = "▲" if chg >= 0 else "▼"
                lines.append(
                    f"  {coin['symbol'].upper():6}  {coin['current_price']:>14,.4f} {cur}  "
                    f"{arrow} {abs(chg):.1f}%  (mcap #{coin.get('market_cap_rank','?')})"
                )
            return ToolResult(output="\n".join(lines))
        except Exception as e:
            return ToolResult(error=f"Crypto fetch failed: {e}")


# ── Currency ──────────────────────────────────────────────────────────────────

_COMMON_PAIRS = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "MXN",
                 "BRL", "KRW", "SGD", "HKD", "NOK", "SEK", "DKK", "NZD", "ZAR", "RUB"]


class CurrencyTool(Tool):
    spec = ToolSpec(
        name="currency",
        description="Get live foreign exchange rates. Uses open.er-api.com — no API key required.",
        parameters={
            "base": {"type": "string", "description": "Base currency (e.g. USD, EUR, GBP)", "default": "USD"},
            "targets": {"type": "string", "description": "Comma-separated target currencies. Leave empty for 20 major currencies.", "default": ""},
        },
    )

    async def __call__(self, base: str = "USD", targets: str = "") -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx not installed")
        try:
            async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as c:
                r = await c.get(f"https://open.er-api.com/v6/latest/{base.upper()}")
                r.raise_for_status()
                d = r.json()
            rates = d.get("rates", {})
            want = [t.strip().upper() for t in targets.split(",") if t.strip()] or _COMMON_PAIRS
            lines = [f"Exchange rates — 1 {base.upper()} =", ""]
            for sym in want:
                if sym in rates and sym != base.upper():
                    lines.append(f"  {sym:5}  {rates[sym]:>12.4f}")
            lines.append(f"\n  Updated: {d.get('time_last_update_utc', 'unknown')}")
            return ToolResult(output="\n".join(lines))
        except Exception as e:
            return ToolResult(error=f"Currency fetch failed: {e}")


# ── Wikipedia ─────────────────────────────────────────────────────────────────

class WikipediaTool(Tool):
    spec = ToolSpec(
        name="wikipedia",
        description="Look up any topic on Wikipedia and get a concise summary. No API key required.",
        parameters={
            "topic": {"type": "string", "description": "Topic or article title to look up"},
            "sentences": {"type": "integer", "description": "Number of sentences to return (1–10)", "default": 5},
        },
    )

    async def __call__(self, topic: str, sentences: int = 5) -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx not installed")
        try:
            async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as c:
                # Search first to get canonical title
                sr = await c.get("https://en.wikipedia.org/w/api.php", params={
                    "action": "query", "list": "search", "srsearch": topic,
                    "srlimit": 1, "format": "json",
                })
                hits = sr.json().get("query", {}).get("search", [])
                if not hits:
                    return ToolResult(error=f"No Wikipedia article found for: {topic!r}")
                title = hits[0]["title"]
                # Fetch summary
                sr2 = await c.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}")
                data = sr2.json()
            extract = data.get("extract", "")
            # Truncate to N sentences
            import re
            sents = re.split(r'(?<=[.!?])\s+', extract)
            summary = " ".join(sents[:max(1, sentences)])
            url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
            lines = [f"Wikipedia: {data.get('title', title)}", ""]
            if data.get("description"):
                lines.append(f"  {data['description']}")
                lines.append("")
            lines.append(summary)
            if url:
                lines.append(f"\n  → {url}")
            return ToolResult(output="\n".join(lines))
        except Exception as e:
            return ToolResult(error=f"Wikipedia fetch failed: {e}")


# ── GitHub Search ─────────────────────────────────────────────────────────────

class GitHubSearchTool(Tool):
    spec = ToolSpec(
        name="github_search",
        description="Search GitHub repositories. Uses the public GitHub API — no key required (60 req/hr).",
        parameters={
            "query": {"type": "string", "description": "Search query (e.g. 'fastapi stars:>1000 language:python')"},
            "count": {"type": "integer", "description": "Number of results (1–10)", "default": 5},
            "sort": {"type": "string", "description": "Sort by: stars, forks, updated (default: stars)", "default": "stars"},
        },
    )

    async def __call__(self, query: str, count: int = 5, sort: str = "stars") -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx not installed")
        try:
            async with httpx.AsyncClient(timeout=15, headers={**_HEADERS, "Accept": "application/vnd.github+json"}) as c:
                r = await c.get("https://api.github.com/search/repositories", params={
                    "q": query, "sort": sort, "order": "desc", "per_page": min(10, max(1, count)),
                })
                r.raise_for_status()
                data = r.json()
            items = data.get("items", [])
            total = data.get("total_count", 0)
            lines = [f"GitHub search: \"{query}\" ({total:,} results)", ""]
            for repo in items:
                lang = f" [{repo['language']}]" if repo.get("language") else ""
                lines.append(f"  ★ {repo['stargazers_count']:>6,}  {repo['full_name']}{lang}")
                if repo.get("description"):
                    lines.append(f"            {repo['description'][:100]}")
                lines.append(f"            {repo['html_url']}")
                lines.append("")
            return ToolResult(output="\n".join(lines).strip())
        except Exception as e:
            return ToolResult(error=f"GitHub search failed: {e}")


# ── NASA APOD ─────────────────────────────────────────────────────────────────

class NASATool(Tool):
    spec = ToolSpec(
        name="nasa_apod",
        description="Get NASA's Astronomy Picture of the Day — title, explanation, and image URL. Uses DEMO key.",
        parameters={
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format (leave empty for today)", "default": ""},
        },
    )

    async def __call__(self, date: str = "") -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx not installed")
        try:
            params: dict = {"api_key": "DEMO_KEY"}
            if date.strip():
                params["date"] = date.strip()
            async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as c:
                r = await c.get("https://api.nasa.gov/planetary/apod", params=params)
                r.raise_for_status()
                d = r.json()
            lines = [
                f"NASA Astronomy Picture of the Day — {d.get('date', '')}",
                "",
                f"  {d.get('title', '')}",
                "",
                d.get("explanation", "")[:600],
                "",
                f"  Image: {d.get('hdurl') or d.get('url', '')}",
            ]
            if d.get("copyright"):
                lines.append(f"  © {d['copyright'].strip()}")
            return ToolResult(output="\n".join(lines))
        except Exception as e:
            return ToolResult(error=f"NASA APOD fetch failed: {e}")
