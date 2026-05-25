"""
SEC EDGAR integration — real public filings, no API key required.

The SEC mandates a User-Agent with contact info. We use Orchestra's identity.
Rate limit: 10 req/s. We stay well under that with a small in-memory cache.
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from functools import lru_cache
from typing import Any

import httpx

_UA = {"User-Agent": "Orchestra/1.0 contact@horizon-orchestra.com"}
_BASE = "https://data.sec.gov"
_SEARCH = "https://efts.sec.gov/LATEST/search-index"

# ── Ticker → CIK lookup (cached for process lifetime) ───────────────────────

@lru_cache(maxsize=1)
def _ticker_map() -> dict[str, str]:
    """Load SEC's full ticker→CIK map once. Returns {TICKER: '0000012345'}."""
    with urllib.request.urlopen(
        urllib.request.Request(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_UA,
        ),
        timeout=15,
    ) as r:
        data = json.load(r)
    return {
        v["ticker"].upper(): str(v["cik_str"]).zfill(10)
        for v in data.values()
    }


def ticker_to_cik(ticker: str) -> str | None:
    """Return zero-padded 10-digit CIK for a ticker, or None."""
    try:
        return _ticker_map().get(ticker.upper().strip())
    except Exception:
        return None


# ── Core async fetchers ──────────────────────────────────────────────────────

async def _get(url: str, timeout: int = 15) -> dict | list:
    async with httpx.AsyncClient(headers=_UA, timeout=timeout, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.json()


async def get_submissions(cik: str) -> dict:
    """All metadata for a company — name, SIC, recent filings index."""
    return await _get(f"{_BASE}/submissions/CIK{cik}.json")


async def get_company_facts(cik: str) -> dict:
    """All XBRL-tagged financial facts (revenue, assets, EPS, etc.)."""
    return await _get(f"{_BASE}/api/xbrl/companyfacts/CIK{cik}.json", timeout=30)


async def get_concept(cik: str, concept: str, taxonomy: str = "us-gaap") -> dict:
    """Single XBRL concept history, e.g. concept='Revenues', 'NetIncomeLoss'."""
    return await _get(f"{_BASE}/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json")


async def search_full_text(query: str, form: str = "10-K", limit: int = 5) -> list[dict]:
    """Full-text search across all EDGAR filings."""
    url = f"{_SEARCH}?q={urllib.parse.quote(query)}&forms={form}&dateRange=custom&startdt=2020-01-01"
    import urllib.parse
    url = f"{_SEARCH}?q={urllib.parse.quote(query)}&forms={form}"
    try:
        data = await _get(url)
        hits = data.get("hits", {}).get("hits", [])
        return hits[:limit]
    except Exception:
        return []


# ── High-level helpers used by routes ───────────────────────────────────────

async def filings_summary(ticker: str, form_types: list[str] | None = None) -> dict:
    """
    Return a clean summary of recent filings for a ticker.
    form_types: e.g. ["10-K", "10-Q", "8-K"]. None = all.
    """
    cik = ticker_to_cik(ticker)
    if not cik:
        raise ValueError(f"Ticker '{ticker}' not found in SEC database")

    sub = await get_submissions(cik)
    recent = sub.get("filings", {}).get("recent", {})

    forms     = recent.get("form", [])
    dates     = recent.get("filingDate", [])
    accessions= recent.get("accessionNumber", [])
    docs      = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])

    filings = []
    for form, date, acc, doc, desc in zip(forms, dates, accessions, docs, descriptions):
        if form_types and form not in form_types:
            continue
        filings.append({
            "form": form,
            "date": date,
            "accession": acc,
            "primary_doc": doc,
            "description": desc or "",
            "viewer_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}/{doc}",
            "index_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}",
        })
        if len(filings) >= 20:
            break

    return {
        "ticker": ticker.upper(),
        "cik": cik,
        "company_name": sub.get("name", ""),
        "sic": sub.get("sic", ""),
        "sic_description": sub.get("sicDescription", ""),
        "state": sub.get("stateOfIncorporation", ""),
        "fiscal_year_end": sub.get("fiscalYearEnd", ""),
        "filings": filings,
    }


async def key_financials(ticker: str) -> dict:
    """
    Pull key annual financial metrics from XBRL facts.
    Returns last 5 years of: Revenue, NetIncome, EPS, Assets, Equity.
    """
    cik = ticker_to_cik(ticker)
    if not cik:
        raise ValueError(f"Ticker '{ticker}' not found")

    facts = await get_company_facts(cik)
    gaap = facts.get("facts", {}).get("us-gaap", {})

    def _annual(concept: str) -> list[dict]:
        data = gaap.get(concept, {})
        units = data.get("units", {})
        # prefer USD, fallback to shares
        values = units.get("USD", units.get("shares", []))
        # keep only annual (form 10-K) entries, last 5
        annual = [
            {"year": v.get("end", "")[:4], "value": v.get("val"), "form": v.get("form")}
            for v in values
            if v.get("form") in ("10-K", "10-K/A") and v.get("val") is not None
        ]
        # deduplicate by year, keep latest
        seen: dict[str, dict] = {}
        for a in annual:
            seen[a["year"]] = a
        return sorted(seen.values(), key=lambda x: x["year"], reverse=True)[:5]

    sub = await get_submissions(cik)

    return {
        "ticker": ticker.upper(),
        "company_name": sub.get("name", ""),
        "cik": cik,
        "revenue":        _annual("Revenues") or _annual("RevenueFromContractWithCustomerExcludingAssessedTax"),
        "net_income":     _annual("NetIncomeLoss"),
        "eps_diluted":    _annual("EarningsPerShareDiluted"),
        "total_assets":   _annual("Assets"),
        "total_equity":   _annual("StockholdersEquity"),
        "operating_cf":   _annual("NetCashProvidedByUsedInOperatingActivities"),
        "capex":          _annual("PaymentsToAcquirePropertyPlantAndEquipment"),
    }
