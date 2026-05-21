"""AI-powered legal document drafter and matter analysis."""
from __future__ import annotations

import json
import os
import re
from typing import Any

DOCUMENT_SYSTEM_PROMPT = """\
You are an expert legal document drafting assistant. You help attorneys at small law firms \
draft professional legal documents quickly and accurately.

When asked to draft a document, you produce a complete, professional draft based on the \
facts and parameters provided. Always include:
- Proper legal headings and structure
- Standard boilerplate clauses appropriate to the document type
- Clear placeholder markers like [PARTY NAME], [DATE], [JURISDICTION] for facts not provided
- Professional legal language appropriate to the jurisdiction

You return a JSON object with:
{
  "document_type": "string — the type of document drafted",
  "title": "string — the document title",
  "content": "string — the full document text with proper formatting",
  "key_terms": ["list of important defined terms or key provisions"],
  "review_checklist": ["list of items attorney should verify before signing"],
  "warnings": ["any legal warnings or jurisdiction-specific notes"]
}

Return ONLY the JSON object. No markdown fences, no explanation outside the JSON.
"""

ACTIVITY_CODES: dict[str, str] = {
    "GEN": "General",
    "RES": "Legal Research",
    "DRA": "Drafting",
    "REV": "Document Review",
    "CONF": "Conference / Meeting",
    "COURT": "Court Appearance",
    "DEP": "Deposition",
    "NEG": "Negotiation",
    "CORR": "Correspondence",
    "TRAVEL": "Travel",
    "ADMIN": "Administrative",
    "DISC": "Discovery",
    "MOT": "Motion Practice",
    "TRIAL": "Trial",
    "APPEAL": "Appeal",
    "SETTLE": "Settlement",
    "TRANS": "Transactional",
    "CLOSE": "Closing",
    "DILIG": "Due Diligence",
    "COMP": "Compliance",
}

DOCUMENT_TEMPLATES: dict[str, str] = {
    "nda_mutual": "Mutual Non-Disclosure Agreement",
    "nda_one_way": "One-Way Non-Disclosure Agreement",
    "engagement_letter": "Attorney Engagement Letter / Retainer Agreement",
    "demand_letter": "Demand Letter",
    "settlement_agreement": "Settlement Agreement and Release",
    "independent_contractor": "Independent Contractor Agreement",
    "employment_offer": "Employment Offer Letter",
    "cease_desist": "Cease and Desist Letter",
    "promissory_note": "Promissory Note",
    "bill_of_sale": "Bill of Sale",
    "lease_commercial": "Commercial Lease Agreement",
    "operating_agreement": "LLC Operating Agreement",
    "shareholder_agreement": "Shareholder Agreement",
    "ip_assignment": "IP Assignment Agreement",
    "services_agreement": "Professional Services Agreement",
    "complaint": "Civil Complaint",
    "answer": "Answer to Complaint",
    "motion_summary_judgment": "Motion for Summary Judgment",
    "interrogatories": "Interrogatories",
    "deposition_notice": "Notice of Deposition",
    "will_simple": "Simple Last Will and Testament",
    "power_of_attorney": "Durable Power of Attorney",
    "healthcare_directive": "Healthcare Directive / Living Will",
    "case_summary": "Case Summary Memorandum",
}


def _resolve_api_key(provider: str) -> str:
    mapping = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "gemini": "GOOGLE_API_KEY",
    }
    return os.environ.get(mapping.get(provider.lower(), ""), "") or ""


def _parse_llm_response(content: str) -> dict[str, Any]:
    text = content.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    else:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            text = text[s:e + 1]
    return json.loads(text)


async def _claude_code_call(full_prompt: str) -> str:
    """Call Claude Code CLI via stdin — works without an API key."""
    import asyncio
    import shutil

    cli = shutil.which("claude") or "claude"
    cmd = [cli, "--print", "--output-format", "text",
           "--permission-mode", "bypassPermissions", "--max-turns", "3"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=full_prompt.encode("utf-8")), timeout=120
    )
    output = stdout.decode("utf-8", errors="replace").strip()
    if not output:
        err = stderr.decode("utf-8", errors="replace").strip()[:300]
        raise RuntimeError(f"Claude Code returned no output. stderr: {err}")
    return output


async def draft_document(
    doc_type: str,
    facts: str,
    party_a: str = "",
    party_b: str = "",
    jurisdiction: str = "",
    additional_terms: str = "",
    provider: str = "anthropic",
    model: str = "claude-opus-4-7",
    api_key: str = "",
) -> dict[str, Any]:
    doc_label = DOCUMENT_TEMPLATES.get(doc_type, doc_type.replace("_", " ").title())
    user_prompt = f"""Draft a {doc_label}.

FACTS AND CONTEXT:
{facts}

PARTIES:
- Party A / Client: {party_a or "[TO BE PROVIDED]"}
- Party B / Counterparty: {party_b or "[TO BE PROVIDED]"}

JURISDICTION: {jurisdiction or "[TO BE PROVIDED]"}

ADDITIONAL TERMS OR SPECIAL PROVISIONS:
{additional_terms or "None"}

Produce a complete, professional draft ready for attorney review."""

    resolved_key = api_key or _resolve_api_key(provider)

    if resolved_key:
        from orchestra.code_agent.llm.base import LLM, Message
        llm = LLM(provider=provider, model=model, api_key=resolved_key, temperature=0.1)
        messages = [
            Message(role="system", content=DOCUMENT_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ]
        response = await llm.chat(messages)
        return _parse_llm_response(response.content)

    # No API key — use Claude Code CLI
    full_prompt = DOCUMENT_SYSTEM_PROMPT + "\n\n" + user_prompt
    output = await _claude_code_call(full_prompt)
    return _parse_llm_response(output)


async def analyze_matter(
    matter_title: str,
    matter_type: str,
    facts: str,
    provider: str = "anthropic",
    model: str = "claude-opus-4-7",
    api_key: str = "",
) -> dict[str, Any]:
    """Generate a strategic matter analysis with recommended next steps."""
    from orchestra.code_agent.llm.base import LLM, Message

    system = """\
You are an expert litigation and transactional attorney providing strategic counsel. \
Analyze the matter and provide actionable guidance.

Return a JSON object with:
{
  "summary": "2-3 sentence matter summary",
  "strengths": ["list of legal/factual strengths"],
  "weaknesses": ["list of legal/factual weaknesses or risks"],
  "recommended_actions": [{"action": "string", "priority": "high|medium|low", "timeline": "string"}],
  "key_issues": ["list of key legal issues to research or address"],
  "estimated_timeline": "string",
  "settlement_considerations": "string (if applicable)",
  "research_topics": ["list of areas requiring legal research"]
}

Return ONLY the JSON object."""

    user_prompt = f"""Matter: {matter_title}
Type: {matter_type}

Facts and Background:
{facts}

Provide strategic analysis and recommended next steps."""

    resolved_key = api_key or _resolve_api_key(provider)

    if resolved_key:
        llm = LLM(provider=provider, model=model, api_key=resolved_key, temperature=0.2)
        messages = [
            Message(role="system", content=system),
            Message(role="user", content=user_prompt),
        ]
        response = await llm.chat(messages)
        return _parse_llm_response(response.content)

    output = await _claude_code_call(system + "\n\n" + user_prompt)
    return _parse_llm_response(output)
