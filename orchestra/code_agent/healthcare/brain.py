"""AI documentation assistant — raw notes → SOAP note + billing codes."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .billing import ICD10_CODES, CPT_CODES


SOAP_SYSTEM_PROMPT = """You are a medical documentation AI assistant for a private practice clinic.

Your job is to convert raw clinical notes from a physician into a structured SOAP note and suggest appropriate billing codes.

Return a JSON object with exactly this structure:
{
  "subjective": "Patient's chief complaint and history of present illness in clinical language",
  "objective": "Vital signs, physical exam findings, and relevant test results",
  "assessment": "Clinical assessment and diagnosis in professional medical language",
  "plan": "Treatment plan, medications, follow-up instructions",
  "icd10_codes": [
    {"code": "E11.9", "description": "Type 2 diabetes mellitus without complications", "category": "Endocrine"}
  ],
  "cpt_codes": [
    {"code": "99213", "description": "Office visit, established patient, 20 min", "fee": 115.00, "rvu": 1.88}
  ],
  "confidence": "high|medium|low",
  "notes": "Any clarifications or flags for physician review"
}

Rules:
- Use real ICD-10 codes (format: letter + 2 digits + optional decimal + 1-2 chars)
- Use real CPT codes (5 digits)
- Choose the most specific and accurate codes
- For E&M visits, choose the correct level based on complexity described
- If the visit appears to be a new patient, use 9920x codes; established patient use 9921x
- Always include at least one E&M CPT code unless it is clearly a procedure-only visit
- Include additional CPT codes for any procedures, labs, or imaging described
- Write the SOAP note in professional medical language — concise, clinical, precise
- Do NOT invent symptoms or diagnoses not mentioned in the raw notes
- If notes are unclear, flag in "notes" field and use lower confidence
"""


async def _claude_code_call(full_prompt: str) -> str:
    import asyncio, shutil
    cli = shutil.which("claude") or "claude"
    cmd = [cli, "--print", "--output-format", "text",
           "--permission-mode", "bypassPermissions", "--max-turns", "3"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(input=full_prompt.encode("utf-8")), timeout=120)
    output = stdout.decode("utf-8", errors="replace").strip()
    if not output:
        raise RuntimeError("Claude Code returned no output")
    return output


async def generate_soap_note(
    raw_notes: str,
    patient_context: dict[str, Any] | None = None,
    provider: str = "anthropic",
    model: str = "claude-opus-4-7",
    api_key: str = "",
) -> dict[str, Any]:
    """Generate a structured SOAP note. Uses API key if provided, Claude Code CLI otherwise."""
    context_lines = []
    if patient_context:
        for label, key in [("Patient age", "age"), ("Gender", "gender"),
                           ("Known allergies", "allergies"), ("Current medications", "medications")]:
            val = patient_context.get(key, "")
            if val:
                context_lines.append(f"{label}: {val}")

    user_prompt = ""
    if context_lines:
        user_prompt += "PATIENT CONTEXT:\n" + "\n".join(context_lines) + "\n\n"
    user_prompt += f"RAW CLINICAL NOTES:\n{raw_notes}\n\nGenerate the SOAP note and billing codes."

    resolved_key = api_key or _resolve_api_key(provider)

    try:
        if resolved_key:
            from orchestra.code_agent.llm.base import LLM, Message
            llm = LLM(provider=provider, model=model, api_key=resolved_key, temperature=0.1)
            messages = [
                Message(role="system", content=SOAP_SYSTEM_PROMPT),
                Message(role="user", content=user_prompt),
            ]
            response = await llm.chat(messages)
            return _parse_llm_response(response.content)

        # No API key — use Claude Code CLI
        output = await _claude_code_call(SOAP_SYSTEM_PROMPT + "\n\n" + user_prompt)
        return _parse_llm_response(output)
    except Exception as e:
        result = _fallback_parse(raw_notes)
        result["error"] = str(e)
        return result


def _resolve_api_key(provider: str) -> str:
    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    return os.environ.get(env_map.get(provider, ""), "")


def _parse_llm_response(content: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code blocks."""
    cleaned = content.strip()
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if json_match:
        cleaned = json_match.group(1).strip()
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]

    try:
        data = json.loads(cleaned)
        return _validate_and_enrich_soap(data)
    except json.JSONDecodeError:
        return _fallback_parse(content)


def _validate_and_enrich_soap(data: dict[str, Any]) -> dict[str, Any]:
    """Validate codes against reference data and fill in missing info."""
    icd10_out = []
    for code_obj in data.get("icd10_codes", []):
        code = code_obj.get("code", "").upper()
        ref = ICD10_CODES.get(code)
        if ref:
            icd10_out.append({"code": code, "description": ref["description"], "category": ref["category"]})
        elif code_obj.get("description"):
            icd10_out.append(code_obj)

    cpt_out = []
    for code_obj in data.get("cpt_codes", []):
        code = code_obj.get("code", "")
        ref = CPT_CODES.get(code)
        if ref:
            cpt_out.append({"code": code, "description": ref["description"], "fee": ref["fee"], "rvu": ref["rvu"]})
        elif code_obj.get("description"):
            cpt_out.append(code_obj)

    return {
        "subjective": data.get("subjective", ""),
        "objective": data.get("objective", ""),
        "assessment": data.get("assessment", ""),
        "plan": data.get("plan", ""),
        "icd10_codes": icd10_out,
        "cpt_codes": cpt_out,
        "confidence": data.get("confidence", "medium"),
        "notes": data.get("notes", ""),
        "raw_notes": "",
    }


def _fallback_parse(raw_notes: str) -> dict[str, Any]:
    """Return minimal structure when LLM is unavailable."""
    return {
        "subjective": raw_notes,
        "objective": "",
        "assessment": "",
        "plan": "",
        "icd10_codes": [],
        "cpt_codes": [],
        "confidence": "low",
        "notes": "AI generation unavailable — manual entry required.",
        "raw_notes": raw_notes,
    }


def suggest_codes_from_keywords(text: str) -> dict[str, Any]:
    """Rule-based code suggestion as a fallback/supplement to LLM."""
    text_lower = text.lower()
    suggested_icd10 = []
    suggested_cpt = []

    keyword_icd10_map = {
        "diabetes": ["E11.9", "E10.9"],
        "hypertension": ["I10"],
        "high blood pressure": ["I10"],
        "back pain": ["M54.50"],
        "low back": ["M54.50"],
        "depression": ["F32.9"],
        "anxiety": ["F41.1"],
        "asthma": ["J45.20"],
        "copd": ["J44.1"],
        "hypothyroid": ["E03.9"],
        "hyperlipidemia": ["E78.5"],
        "cholesterol": ["E78.5"],
        "uti": ["N39.0"],
        "urinary tract": ["N39.0"],
        "strep": ["J02.9"],
        "pharyngitis": ["J02.9"],
        "upper respiratory": ["J06.9"],
        "uri": ["J06.9"],
        "cold": ["J00"],
        "pneumonia": ["J18.9"],
        "knee pain": ["M25.561"],
        "shoulder pain": ["M25.511"],
        "migraine": ["G43.909"],
        "headache": ["G43.909"],
        "gerd": ["K21.9"],
        "reflux": ["K21.9"],
        "adhd": ["F90.2"],
        "obesity": ["E66.9"],
        "sleep apnea": ["G47.33"],
        "atrial fibrillation": ["I48.91"],
        "afib": ["I48.91"],
    }

    keyword_cpt_map = {
        "new patient": ["99203"],
        "established patient": ["99213"],
        "annual exam": ["99395", "G0439"],
        "annual wellness": ["G0439"],
        "preventive": ["99395"],
        "physical": ["99395"],
        "lab": ["36415"],
        "blood draw": ["36415"],
        "ecg": ["93000"],
        "ekg": ["93000"],
        "strep test": ["86592"],
        "flu test": ["87430"],
        "urinalysis": ["81001"],
        "a1c": ["83036"],
        "cbc": ["85025"],
        "hba1c": ["83036"],
        "cholesterol panel": ["83721"],
        "tsh": ["84443"],
        "x-ray": ["71046"],
        "chest x-ray": ["71046"],
        "vaccine": ["90471"],
        "flu shot": ["90686", "90471"],
        "injection": ["20610"],
    }

    seen_icd = set()
    for kw, codes in keyword_icd10_map.items():
        if kw in text_lower:
            for c in codes:
                if c not in seen_icd and c in ICD10_CODES:
                    suggested_icd10.append({"code": c, **ICD10_CODES[c]})
                    seen_icd.add(c)

    seen_cpt = set()
    for kw, codes in keyword_cpt_map.items():
        if kw in text_lower:
            for c in codes:
                if c not in seen_cpt and c in CPT_CODES:
                    suggested_cpt.append({"code": c, **CPT_CODES[c]})
                    seen_cpt.add(c)

    return {"suggested_icd10": suggested_icd10, "suggested_cpt": suggested_cpt}
