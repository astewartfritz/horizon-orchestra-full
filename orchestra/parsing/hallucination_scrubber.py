"""Hallucination detection and scrubbing engine for Horizon Orchestra.

Detects and removes hallucinated content from LLM outputs using 10
heuristic detection methods.  Pure Python, no ML models.

Target: >95% recall, <5ms overhead per call.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "HallucinationScrubber",
    "HallucinationReport",
    "HallucinationFinding",
    "CitationIssue",
    "InconsistencyFound",
    "FabricationFound",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class HallucinationFinding:
    """A single detected hallucination."""
    method: str
    severity: float  # 0.0 – 1.0
    description: str
    span: tuple[int, int] = (0, 0)
    suggestion: str = ""


@dataclass
class HallucinationReport:
    """Full hallucination scan report."""
    findings: list[HallucinationFinding] = field(default_factory=list)
    severity: float = 0.0
    scrubbed_count: int = 0
    verification_notes: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


@dataclass
class CitationIssue:
    """A problem found during citation verification."""
    citation_text: str
    issue: str
    severity: float = 0.5


@dataclass
class InconsistencyFound:
    """A numeric inconsistency found in the text."""
    description: str
    values: list[str] = field(default_factory=list)
    severity: float = 0.5


@dataclass
class FabricationFound:
    """Likely fabricated code detected."""
    description: str
    span: tuple[int, int] = (0, 0)
    severity: float = 0.5


# ---------------------------------------------------------------------------
# HallucinationScrubber
# ---------------------------------------------------------------------------

class HallucinationScrubber:
    """High-speed hallucination detector for LLM outputs.

    Implements 10 detection methods, all pure-Python and designed
    for <5ms per call on typical responses.

    Detection methods:
      1. Citation verification
      2. Numeric consistency
      3. Entity verification (known-entity lookup)
      4. Temporal consistency
      5. Logical consistency (contradiction detection)
      6. Confidence calibration
      7. Unknown-fact detection
      8. Code hallucination (fabricated APIs)
      9. URL hallucination (fabricated URLs)
     10. Repetition detection
    """

    # Known top-level domains for URL plausibility.
    _VALID_TLDS = frozenset({
        "com", "org", "net", "edu", "gov", "io", "ai", "co", "dev", "app",
        "info", "biz", "us", "uk", "de", "fr", "jp", "cn", "ru", "br",
        "in", "au", "ca", "nl", "se", "no", "fi", "dk", "ch", "at",
    })

    # Confidence boosters — words that signal high (possibly over-) confidence.
    _CERTAINTY_WORDS = frozenset({
        "certainly", "definitely", "absolutely", "undoubtedly", "without a doubt",
        "always", "never", "guaranteed", "100%", "proven",
    })

    # Hedge words — words that signal uncertainty.
    _HEDGE_WORDS = frozenset({
        "might", "maybe", "perhaps", "possibly", "could", "likely",
        "I think", "I believe", "it seems", "not sure", "unclear",
        "approximately", "roughly", "about",
    })

    # Common hallucinated Python stdlib modules/APIs.
    _FAKE_PYTHON_APIS = frozenset({
        "os.execute", "str.toInt", "list.push", "dict.add",
        "json.parse", "json.stringify", "print.ln", "string.format",
        "array.length", "math.sum", "sys.run", "file.open",
    })

    _FAKE_JS_APIS = frozenset({
        "Array.remove", "String.contains", "Math.sum",
        "console.write", "window.sleep", "document.fetch",
    })

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> HallucinationReport:
        """Scan text for hallucinations without modifying it.

        Args:
            text: The LLM output to scan.
            context: Optional context dict with keys like ``sources``,
                ``known_entities``, ``expected_dates``, ``code_language``.

        Returns:
            A :class:`HallucinationReport` with all findings.
        """
        t0 = time.monotonic()
        context = context or {}
        findings: list[HallucinationFinding] = []

        # Run all 10 detectors.
        findings.extend(self._check_citations(text, context))
        findings.extend(self._check_numeric_consistency_internal(text))
        findings.extend(self._check_entities(text, context))
        findings.extend(self._check_temporal(text))
        findings.extend(self._check_logical(text))
        findings.extend(self._check_confidence(text))
        findings.extend(self._check_unknown_facts(text))
        findings.extend(self._check_code(text, context))
        findings.extend(self._check_urls(text))
        findings.extend(self._check_repetition(text))

        severity = max((f.severity for f in findings), default=0.0)
        elapsed = (time.monotonic() - t0) * 1000

        return HallucinationReport(
            findings=findings,
            severity=severity,
            scrubbed_count=0,
            verification_notes=[f"Scanned with 10 methods in {elapsed:.2f}ms"],
            elapsed_ms=elapsed,
        )

    def scrub(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, HallucinationReport]:
        """Scan and remove hallucinated content.

        Returns the cleaned text and the report.
        """
        report = self.scan(text, context)

        scrubbed = text
        removed = 0

        # Remove findings with severity >= 0.7 (high confidence hallucinations).
        # Sort by span start descending to preserve positions.
        removable = sorted(
            [f for f in report.findings if f.severity >= 0.7 and f.span != (0, 0)],
            key=lambda f: f.span[0],
            reverse=True,
        )
        for finding in removable:
            start, end = finding.span
            if 0 <= start < end <= len(scrubbed):
                scrubbed = scrubbed[:start] + scrubbed[end:]
                removed += 1

        report.scrubbed_count = removed
        return scrubbed, report

    def verify_citations(
        self,
        text: str,
        sources: list[str],
    ) -> list[CitationIssue]:
        """Verify that citations in the text reference provided sources."""
        issues: list[CitationIssue] = []

        # Extract bracketed citations [1], [2], etc.
        for m in re.finditer(r'\[(\d+)\]', text):
            idx = int(m.group(1))
            if idx < 1 or idx > len(sources):
                issues.append(CitationIssue(
                    citation_text=m.group(0),
                    issue=f"Citation [{idx}] references non-existent source (have {len(sources)} sources)",
                    severity=0.8,
                ))

        # Extract named citations (Author, Year) or (Author Year).
        for m in re.finditer(r'\(([A-Z][a-z]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][a-z]+))?),?\s*(\d{4})\)', text):
            author = m.group(1)
            year = m.group(2)
            # Check if any source mentions this author/year.
            found = any(author.split()[0].lower() in s.lower() and year in s for s in sources)
            if not found and sources:
                issues.append(CitationIssue(
                    citation_text=m.group(0),
                    issue=f"Citation ({author}, {year}) not found in provided sources",
                    severity=0.6,
                ))

        # Check for URL citations.
        for m in re.finditer(r'(?:according to|source:|ref:)\s*(https?://\S+)', text, re.IGNORECASE):
            url = m.group(1)
            if sources and not any(url in s for s in sources):
                issues.append(CitationIssue(
                    citation_text=url,
                    issue="Cited URL not found in provided sources",
                    severity=0.5,
                ))

        return issues

    def check_numeric_consistency(self, text: str) -> list[InconsistencyFound]:
        """Check that numbers in the text are internally consistent."""
        findings: list[InconsistencyFound] = []

        # Extract all percentages.
        pct_pattern = re.compile(r'(\d+(?:\.\d+)?)\s*%')
        percentages = [(float(m.group(1)), m.start()) for m in pct_pattern.finditer(text)]

        # Check if percentages that should sum to 100 actually do.
        if len(percentages) >= 3:
            values = [p[0] for p in percentages]
            total = sum(values)
            if 95 < total < 105 and abs(total - 100) > 2:
                findings.append(InconsistencyFound(
                    description=f"Percentages sum to {total}% (expected ~100%)",
                    values=[f"{v}%" for v in values],
                    severity=0.5,
                ))

        # Check for contradictory numbers with same unit.
        number_re = re.compile(r'(\d[\d,]*\.?\d*)\s*(million|billion|trillion|thousand|hundred|%|dollars?|USD|EUR)', re.IGNORECASE)
        number_contexts: dict[str, list[tuple[float, str]]] = {}
        for m in number_re.finditer(text):
            value = float(m.group(1).replace(",", ""))
            unit = m.group(2).lower()
            # Get surrounding context.
            start = max(0, m.start() - 50)
            end = min(len(text), m.end() + 50)
            ctx = text[start:end]
            key = unit
            if key not in number_contexts:
                number_contexts[key] = []
            number_contexts[key].append((value, ctx))

        # Look for same-unit values that differ by >10x near similar context words.
        for unit, pairs in number_contexts.items():
            if len(pairs) >= 2:
                for i in range(len(pairs)):
                    for j in range(i + 1, len(pairs)):
                        v1, c1 = pairs[i]
                        v2, c2 = pairs[j]
                        if v1 > 0 and v2 > 0:
                            ratio = max(v1, v2) / min(v1, v2)
                            if ratio > 10:
                                # Check if contexts are similar.
                                words1 = set(c1.lower().split())
                                words2 = set(c2.lower().split())
                                overlap = len(words1 & words2) / max(len(words1 | words2), 1)
                                if overlap > 0.3:
                                    findings.append(InconsistencyFound(
                                        description=f"Large discrepancy: {v1} vs {v2} {unit} in similar context",
                                        values=[f"{v1} {unit}", f"{v2} {unit}"],
                                        severity=0.6,
                                    ))

        return findings

    def detect_fabricated_code(
        self,
        code: str,
        language: str,
    ) -> list[FabricationFound]:
        """Detect fabricated API calls in code."""
        findings: list[FabricationFound] = []
        lang = language.lower()

        fake_apis = set()
        if lang in ("python", "py"):
            fake_apis = self._FAKE_PYTHON_APIS
        elif lang in ("javascript", "js", "typescript", "ts"):
            fake_apis = self._FAKE_JS_APIS

        for api in fake_apis:
            idx = code.find(api)
            if idx >= 0:
                findings.append(FabricationFound(
                    description=f"Likely fabricated API: '{api}' does not exist in {language}",
                    span=(idx, idx + len(api)),
                    severity=0.8,
                ))

        # Detect suspicious import patterns.
        if lang in ("python", "py"):
            for m in re.finditer(r'^from\s+(\w+)\s+import\s+(\w+)', code, re.MULTILINE):
                module = m.group(1)
                name = m.group(2)
                # Known-bad patterns.
                if module in ("utils", "helpers", "common") and name[0].isupper():
                    findings.append(FabricationFound(
                        description=f"Suspicious import: 'from {module} import {name}' — generic module name",
                        span=(m.start(), m.end()),
                        severity=0.3,
                    ))

        # Detect non-existent methods on built-in types.
        if lang in ("python", "py"):
            fake_methods = {
                r'\.length\b': "Use len() instead of .length in Python",
                r'\.push\(': "Use .append() instead of .push() in Python",
                r'\.forEach\(': "Use for loop instead of .forEach() in Python",
                r'\.toUpperCase\(': "Use .upper() instead of .toUpperCase() in Python",
                r'\.toLowerCase\(': "Use .lower() instead of .toLowerCase() in Python",
            }
            for pattern, desc in fake_methods.items():
                for m in re.finditer(pattern, code):
                    findings.append(FabricationFound(
                        description=desc,
                        span=(m.start(), m.end()),
                        severity=0.7,
                    ))

        return findings

    def score_confidence(self, text: str) -> float:
        """Return a 0–1 confidence score for how trustworthy the text is.

        Lower scores indicate more likely hallucination.
        """
        report = self.scan(text)
        if not report.findings:
            return 0.95
        # Penalize based on severity and count.
        penalty = sum(f.severity * 0.15 for f in report.findings)
        return max(0.0, min(1.0, 0.95 - penalty))

    # ------------------------------------------------------------------
    # Internal detection methods
    # ------------------------------------------------------------------

    def _check_citations(
        self,
        text: str,
        context: dict[str, Any],
    ) -> list[HallucinationFinding]:
        """Method 1: Citation verification."""
        findings: list[HallucinationFinding] = []
        sources = context.get("sources", [])

        if not sources:
            # Look for citations without any provided sources.
            cit_count = len(re.findall(r'\[\d+\]', text))
            if cit_count > 3:
                findings.append(HallucinationFinding(
                    method="citation_verification",
                    severity=0.4,
                    description=f"Found {cit_count} numeric citations but no sources provided for verification",
                ))
            return findings

        issues = self.verify_citations(text, sources)
        for issue in issues:
            findings.append(HallucinationFinding(
                method="citation_verification",
                severity=issue.severity,
                description=issue.issue,
            ))

        return findings

    def _check_numeric_consistency_internal(
        self,
        text: str,
    ) -> list[HallucinationFinding]:
        """Method 2: Numeric consistency."""
        findings: list[HallucinationFinding] = []
        issues = self.check_numeric_consistency(text)
        for issue in issues:
            findings.append(HallucinationFinding(
                method="numeric_consistency",
                severity=issue.severity,
                description=issue.description,
            ))
        return findings

    def _check_entities(
        self,
        text: str,
        context: dict[str, Any],
    ) -> list[HallucinationFinding]:
        """Method 3: Entity verification against known entities."""
        findings: list[HallucinationFinding] = []
        known = set(context.get("known_entities", []))
        if not known:
            return findings

        # Extract capitalized multi-word names (potential entities).
        entity_re = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
        for m in entity_re.finditer(text):
            entity = m.group(1)
            # Skip common phrases.
            if entity.lower() in ("the united", "new york", "los angeles"):
                continue
            if entity not in known and len(known) > 5:
                findings.append(HallucinationFinding(
                    method="entity_verification",
                    severity=0.3,
                    description=f"Entity '{entity}' not in known entity set",
                    span=(m.start(), m.end()),
                ))

        return findings

    _DATE_RE = re.compile(
        r'\b(?:in\s+)?(\d{4})\b'
    )
    _FULL_DATE_RE = re.compile(
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+(\d{4})\b'
    )

    def _check_temporal(self, text: str) -> list[HallucinationFinding]:
        """Method 4: Temporal consistency."""
        findings: list[HallucinationFinding] = []

        years: list[int] = []
        for m in self._FULL_DATE_RE.finditer(text):
            years.append(int(m.group(1)))
        for m in self._DATE_RE.finditer(text):
            y = int(m.group(1))
            if 1800 <= y <= 2100:
                years.append(y)

        # Check for implausible years.
        for y in years:
            if y > 2026:
                findings.append(HallucinationFinding(
                    method="temporal_consistency",
                    severity=0.7,
                    description=f"Future date reference: year {y}",
                ))
            elif y < 1000:
                findings.append(HallucinationFinding(
                    method="temporal_consistency",
                    severity=0.3,
                    description=f"Suspiciously old date: year {y}",
                ))

        # Check for contradictory timelines.
        if years and len(set(years)) > 1:
            sorted_years = sorted(set(years))
            if sorted_years[-1] - sorted_years[0] > 500:
                findings.append(HallucinationFinding(
                    method="temporal_consistency",
                    severity=0.4,
                    description=f"Wide date range in text: {sorted_years[0]}–{sorted_years[-1]}",
                ))

        return findings

    _CONTRADICTION_PAIRS = [
        (r'\bis\s+(?:the\s+)?largest\b', r'\bis\s+(?:the\s+)?smallest\b'),
        (r'\bincreased\b', r'\bdecreased\b'),
        (r'\bmore\s+than\b', r'\bless\s+than\b'),
        (r'\balways\b', r'\bnever\b'),
        (r'\bbefore\b', r'\bafter\b'),
        (r'\bfirst\b', r'\blast\b'),
    ]

    def _check_logical(self, text: str) -> list[HallucinationFinding]:
        """Method 5: Logical consistency (contradiction detection)."""
        findings: list[HallucinationFinding] = []
        sentences = re.split(r'(?<=[.!?])\s+', text)

        for pat_a, pat_b in self._CONTRADICTION_PAIRS:
            sents_a = [s for s in sentences if re.search(pat_a, s, re.IGNORECASE)]
            sents_b = [s for s in sentences if re.search(pat_b, s, re.IGNORECASE)]

            for sa in sents_a:
                for sb in sents_b:
                    # Check if they share a subject (first 3 words overlap).
                    words_a = set(sa.lower().split()[:5])
                    words_b = set(sb.lower().split()[:5])
                    if len(words_a & words_b) >= 2:
                        findings.append(HallucinationFinding(
                            method="logical_consistency",
                            severity=0.6,
                            description=f"Potential contradiction: '{sa[:60]}...' vs '{sb[:60]}...'",
                        ))

        return findings

    def _check_confidence(self, text: str) -> list[HallucinationFinding]:
        """Method 6: Confidence calibration."""
        findings: list[HallucinationFinding] = []
        text_lower = text.lower()

        certainty_count = sum(1 for w in self._CERTAINTY_WORDS if w in text_lower)
        hedge_count = sum(1 for w in self._HEDGE_WORDS if w in text_lower)

        # Flag when text uses both strong certainty and hedging.
        if certainty_count >= 2 and hedge_count >= 2:
            findings.append(HallucinationFinding(
                method="confidence_calibration",
                severity=0.4,
                description=f"Mixed confidence signals: {certainty_count} certainty + {hedge_count} hedge words",
            ))

        # Flag excessive certainty.
        if certainty_count >= 4:
            findings.append(HallucinationFinding(
                method="confidence_calibration",
                severity=0.3,
                description=f"Excessive certainty language ({certainty_count} strong assertions)",
            ))

        return findings

    _SPECIFICITY_RE = re.compile(
        r'(?:exactly|precisely)\s+(\d[\d,.]+)\s+(?:people|users|customers|items|records|entries)',
        re.IGNORECASE,
    )

    def _check_unknown_facts(self, text: str) -> list[HallucinationFinding]:
        """Method 7: Detect claims about specific facts the model couldn't know."""
        findings: list[HallucinationFinding] = []

        # Suspiciously precise numbers.
        for m in self._SPECIFICITY_RE.finditer(text):
            findings.append(HallucinationFinding(
                method="unknown_fact",
                severity=0.5,
                description=f"Suspiciously precise claim: '{m.group()}'",
                span=(m.start(), m.end()),
            ))

        # Claim patterns that are hard to verify.
        patterns = [
            (r'(?:studies show|research shows|scientists found|experts agree)\s+that', 0.3,
             "Unattributed claim to authority"),
            (r'(?:according to internal|internal data shows|private sources)', 0.5,
             "Claim based on inaccessible sources"),
        ]
        for pat, sev, desc in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                findings.append(HallucinationFinding(
                    method="unknown_fact",
                    severity=sev,
                    description=desc,
                    span=(m.start(), m.end()),
                ))

        return findings

    def _check_code(
        self,
        text: str,
        context: dict[str, Any],
    ) -> list[HallucinationFinding]:
        """Method 8: Code hallucination detection."""
        findings: list[HallucinationFinding] = []

        # Extract code blocks.
        code_blocks = re.findall(r'```(\w*)\n(.*?)```', text, re.DOTALL)
        if not code_blocks:
            # Check inline code-like patterns.
            lang = context.get("code_language", "")
            if lang:
                fabs = self.detect_fabricated_code(text, lang)
                for fab in fabs:
                    findings.append(HallucinationFinding(
                        method="code_hallucination",
                        severity=fab.severity,
                        description=fab.description,
                        span=fab.span,
                    ))
            return findings

        for lang, code in code_blocks:
            if not lang:
                lang = context.get("code_language", "python")
            fabs = self.detect_fabricated_code(code, lang)
            for fab in fabs:
                findings.append(HallucinationFinding(
                    method="code_hallucination",
                    severity=fab.severity,
                    description=fab.description,
                    span=fab.span,
                ))

        return findings

    _URL_RE = re.compile(r'https?://([^\s<>"\']+)')

    def _check_urls(self, text: str) -> list[HallucinationFinding]:
        """Method 9: URL hallucination detection."""
        findings: list[HallucinationFinding] = []

        for m in self._URL_RE.finditer(text):
            url = m.group(0)
            domain = m.group(1).split("/")[0].split(":")[0]
            parts = domain.split(".")

            if len(parts) < 2:
                findings.append(HallucinationFinding(
                    method="url_hallucination",
                    severity=0.7,
                    description=f"Malformed URL domain: {domain}",
                    span=(m.start(), m.end()),
                ))
                continue

            tld = parts[-1].lower()
            if tld not in self._VALID_TLDS and len(tld) > 3:
                findings.append(HallucinationFinding(
                    method="url_hallucination",
                    severity=0.5,
                    description=f"Unusual TLD in URL: .{tld}",
                    span=(m.start(), m.end()),
                ))

            # Check for suspiciously long random-looking paths.
            path = "/".join(m.group(1).split("/")[1:])
            if len(path) > 100 and re.search(r'[a-f0-9]{20,}', path):
                findings.append(HallucinationFinding(
                    method="url_hallucination",
                    severity=0.4,
                    description=f"Possibly fabricated URL with random path: {url[:80]}...",
                    span=(m.start(), m.end()),
                ))

        return findings

    def _check_repetition(self, text: str) -> list[HallucinationFinding]:
        """Method 10: Repetition detection."""
        findings: list[HallucinationFinding] = []
        sentences = re.split(r'(?<=[.!?])\s+', text)

        if len(sentences) < 3:
            return findings

        # Check for near-duplicate sentences.
        seen: dict[str, int] = {}
        for i, sent in enumerate(sentences):
            # Normalize: lowercase, strip punctuation, collapse whitespace.
            normalized = re.sub(r'[^\w\s]', '', sent.lower()).strip()
            normalized = re.sub(r'\s+', ' ', normalized)
            if len(normalized) < 10:
                continue

            # Use first N words as a fingerprint.
            words = normalized.split()
            if len(words) >= 5:
                fingerprint = " ".join(words[:8])
                if fingerprint in seen:
                    findings.append(HallucinationFinding(
                        method="repetition",
                        severity=0.6,
                        description=f"Near-duplicate sentence at positions {seen[fingerprint]} and {i}: '{sent[:60]}...'",
                    ))
                else:
                    seen[fingerprint] = i

        # Check for repeated phrases (3+ word n-grams appearing 3+ times).
        words = text.lower().split()
        if len(words) > 20:
            trigrams: dict[str, int] = {}
            for i in range(len(words) - 2):
                tri = " ".join(words[i:i + 3])
                trigrams[tri] = trigrams.get(tri, 0) + 1
            for tri, count in trigrams.items():
                if count >= 4 and len(tri) > 10:
                    findings.append(HallucinationFinding(
                        method="repetition",
                        severity=0.4,
                        description=f"Phrase repeated {count} times: '{tri}'",
                    ))
                    break  # Report only the worst case.

        return findings
