from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class InjectionRisk(Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    LIKELY = "likely"
    CONFIRMED = "confirmed"


@dataclass
class ShieldResult:
    risk: InjectionRisk
    score: float
    flags: list[str] = field(default_factory=list)
    sanitized: str = ""


_JAILBREAK_PATTERNS = [
    (r"(?i)\b(system\s*prompt|ignore\s*(all\s*)?(previous|prior)\s*instructions)\b",
     "Instruction override attempt"),
    (r"(?i)\bDAN\b",
     "DAN jailbreak reference"),
    (r"(?i)\byou\s+(are|must|will|need\s*to)\s+(now|ignore|forget|disregard|bypass)\b",
     "Role coercion"),
    (r"(?i)\b(act\s*as\s*if|pretend|imagine\s+you(\'re| are))\s+.{0,50}(unrestricted|unfiltered|without\s*rules|no\s*limits)\b",
     "Fictional scenario jailbreak"),
    (r"(?i)\b(tell\s+me\s+how\s+to|instructions?\s+for|steps?\s+to)\s+(hack|crack|exploit|bypass|cheat|scam)\b",
     "Malicious instruction request"),
    (r"(?i)\b(output|respond|reply|answer)\s*(without|with\s*no|bypassing|ignoring)\s*(filter|limit|restriction|rule|guardrail|safety)\b",
     "Filter bypass request"),
    (r"(?i)\b(do\s+not\s+refuse|do\s+not\s+say\s+(sorry|i\s+can\'?t)|never\s+refuse)\b",
     "Refusal suppression"),
    (r"(?i)\b(generate|create|write|produce)\s*(malware|virus|ransomware|keylogger|exploit|shellcode)\b",
     "Malicious code generation"),
    (r"(?i)\b(leak|reveal|expose|dump|show)\s*(prompt|system\s*message|initial\s*instruction|secret)\b",
     "Prompt extraction"),
    (r"(?i)^\s*(repeat|say|echo|mirror|reflect)\s+(the\s+)?(above|previous|everything|all)\b",
     "Prompt reflection"),
    (r"(?i)\bsudo\s+(make\s+me\s+a\s+)?(sandwich|admin)\b",
     "Joke jailbreak reference"),
]

_PII_PATTERNS = [
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "Email address"),
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "Phone number"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),
    (r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b", "Credit card"),
]

_REDACTION_MAP = {
    "Email address": "[EMAIL REDACTED]",
    "Phone number": "[PHONE REDACTED]",
    "SSN": "[SSN REDACTED]",
    "Credit card": "[CC REDACTED]",
}

_SEPARATOR_PATTERNS = [
    (r"(?i)(---+\s*(begin|end).*?|---+)", "Potential separator injection"),
    (r"(?i)(```\s*\w*\s*\n)", "Code block injection"),
    (r"(?i)(\{[^}]*\{[^}]*\})", "Nested template injection"),
    (r"(?i)(\$\{[^}]+\})", "Variable injection"),
]


class InjectionShield:
    def __init__(self, sensitivity: float = 0.5):
        self.sensitivity = sensitivity

    def analyze(self, text: str) -> ShieldResult:
        flags = []
        score = 0.0

        for pattern, description in _JAILBREAK_PATTERNS:
            if re.search(pattern, text):
                flags.append(description)
                score += 0.35

        for pattern, description in _SEPARATOR_PATTERNS:
            if re.search(pattern, text):
                flags.append(description)
                score += 0.15

        pii_found = []
        for pattern, description in _PII_PATTERNS:
            if re.search(pattern, text):
                pii_found.append(description)
                score += 0.1

        if len(text) > 2000:
            score += 0.05

        repetition = len(re.findall(r"\b(\w+)\s+\1\s+\1\b", text))
        if repetition > 3:
            flags.append(f"Word repetition ({repetition}x)")
            score += 0.1

        if score >= 0.7:
            risk = InjectionRisk.CONFIRMED
        elif score >= 0.4:
            risk = InjectionRisk.LIKELY
        elif score >= 0.2:
            risk = InjectionRisk.SUSPICIOUS
        else:
            risk = InjectionRisk.SAFE

        sanitized = text
        for pattern, desc in _PII_PATTERNS:
            replacement = _REDACTION_MAP.get(desc, "[REDACTED]")
            sanitized = re.sub(pattern, replacement, sanitized)

        return ShieldResult(risk=risk, score=min(score, 1.0), flags=flags, sanitized=sanitized)

    def is_safe(self, text: str) -> bool:
        result = self.analyze(text)
        return result.risk in (InjectionRisk.SAFE, InjectionRisk.SUSPICIOUS)

    def summary_text(self, result: ShieldResult) -> str:
        risk_colors = {
            InjectionRisk.SAFE: "GREEN",
            InjectionRisk.SUSPICIOUS: "YELLOW",
            InjectionRisk.LIKELY: "ORANGE",
            InjectionRisk.CONFIRMED: "RED",
        }
        lines = [
            f"Injection Shield Analysis:",
            f"  Risk:     {result.risk.value.upper()} ({risk_colors[result.risk]})",
            f"  Score:    {result.score:.2f}",
        ]
        if result.flags:
            lines.append(f"  Flags ({len(result.flags)}):")
            for f in result.flags:
                lines.append(f"    ⚠ {f}")
        if result.sanitized != "" and result.risk != InjectionRisk.SAFE:
            lines.append(f"  PII redacted: {'Yes' if result.sanitized else 'None detected'}")
        return "\n".join(lines)
