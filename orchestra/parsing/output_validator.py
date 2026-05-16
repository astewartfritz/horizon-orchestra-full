"""Output validation engine for Horizon Orchestra.

Validates all LLM outputs against expected schemas, checks completeness,
format, safety, length, coherence, and actionability.  Returns quality
scores and can enforce rules by removing violations.

Pure Python, no external dependencies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

__all__ = [
    "OutputValidator",
    "ValidationReport",
    "ValidationRule",
    "RuleType",
    "Violation",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class RuleType(Enum):
    """Categories of validation rules."""
    SCHEMA = auto()
    COMPLETENESS = auto()
    FORMAT = auto()
    SAFETY = auto()
    LENGTH = auto()
    COHERENCE = auto()
    ACTIONABILITY = auto()


@dataclass
class Violation:
    """A single validation violation."""
    rule_type: RuleType
    severity: float  # 0.0 – 1.0
    description: str
    span: tuple[int, int] = (0, 0)
    suggestion: str = ""


@dataclass
class ValidationRule:
    """A rule to enforce on LLM output."""
    rule_type: RuleType
    description: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Full validation report for an LLM output."""
    valid: bool = True
    score: float = 1.0
    violations: list[Violation] = field(default_factory=list)
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OutputValidator
# ---------------------------------------------------------------------------

class OutputValidator:
    """Comprehensive LLM output validator.

    Checks:
      1. Schema compliance — output matches expected JSON structure
      2. Completeness — response addresses all parts of the request
      3. Format — code/JSON/markdown validity
      4. Safety — no PII, credentials, or malicious content
      5. Length — not truncated, not padded
      6. Coherence — first/last sentences make sense together
      7. Actionability — if task requested, concrete steps present
    """

    # PII patterns.
    _SSN_RE = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
    _CC_RE = re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b')
    _EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    _PHONE_RE = re.compile(r'(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')

    # Credential patterns.
    _API_KEY_RE = re.compile(r'(?:api[_-]?key|secret|token|password|auth)\s*[:=]\s*["\']?([A-Za-z0-9_\-]{16,})["\']?', re.IGNORECASE)
    _AWS_KEY_RE = re.compile(r'(?:AKIA|ASIA)[A-Z0-9]{16}')
    _PRIVATE_KEY_RE = re.compile(r'-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----')

    # Malicious patterns.
    _INJECTION_RE = re.compile(
        r'(?:ignore\s+(?:all\s+)?(?:previous|above)\s+instructions|'
        r'system\s+prompt|'
        r'you\s+are\s+now\s+(?:DAN|jailbroken|unrestricted))',
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        output: str,
        request: str,
        schema: dict[str, Any] | None = None,
    ) -> ValidationReport:
        """Run all validation checks on an LLM output.

        Args:
            output: The LLM's response text.
            request: The original user request (for completeness checks).
            schema: Optional JSON Schema the output should conform to.

        Returns:
            A :class:`ValidationReport` with violations and score.
        """
        violations: list[Violation] = []
        passed: list[str] = []
        failed: list[str] = []

        # 1. Schema compliance.
        if schema:
            schema_v = self._check_schema(output, schema)
            if schema_v:
                violations.extend(schema_v)
                failed.append("schema_compliance")
            else:
                passed.append("schema_compliance")

        # 2. Completeness.
        comp_v = self._check_completeness(output, request)
        if comp_v:
            violations.extend(comp_v)
            failed.append("completeness")
        else:
            passed.append("completeness")

        # 3. Format.
        fmt_v = self._check_format(output)
        if fmt_v:
            violations.extend(fmt_v)
            failed.append("format")
        else:
            passed.append("format")

        # 4. Safety.
        safety_v = self._check_safety(output)
        if safety_v:
            violations.extend(safety_v)
            failed.append("safety")
        else:
            passed.append("safety")

        # 5. Length.
        length_v = self._check_length(output, request)
        if length_v:
            violations.extend(length_v)
            failed.append("length")
        else:
            passed.append("length")

        # 6. Coherence.
        coh_v = self._check_coherence(output)
        if coh_v:
            violations.extend(coh_v)
            failed.append("coherence")
        else:
            passed.append("coherence")

        # 7. Actionability.
        act_v = self._check_actionability(output, request)
        if act_v:
            violations.extend(act_v)
            failed.append("actionability")
        else:
            passed.append("actionability")

        # Compute overall score.
        score = self._compute_score(violations)

        return ValidationReport(
            valid=len(violations) == 0,
            score=score,
            violations=violations,
            checks_passed=passed,
            checks_failed=failed,
            suggestions=[v.suggestion for v in violations if v.suggestion],
        )

    def enforce(
        self,
        output: str,
        rules: list[ValidationRule],
    ) -> str:
        """Remove content that violates the given rules.

        Returns the cleaned output.
        """
        result = output

        for rule in rules:
            if rule.rule_type == RuleType.SAFETY:
                result = self._enforce_safety(result)
            elif rule.rule_type == RuleType.LENGTH:
                max_len = rule.params.get("max_length", 0)
                min_len = rule.params.get("min_length", 0)
                if max_len and len(result) > max_len:
                    # Truncate at the last sentence boundary.
                    truncated = result[:max_len]
                    last_period = truncated.rfind(".")
                    if last_period > max_len * 0.5:
                        result = truncated[:last_period + 1]
                    else:
                        result = truncated.rstrip() + "..."
                if min_len and len(result) < min_len:
                    pass  # Can't add content, just flag it.
            elif rule.rule_type == RuleType.FORMAT:
                result = self._enforce_format(result, rule.params)
            elif rule.rule_type == RuleType.SCHEMA:
                schema = rule.params.get("schema")
                if schema:
                    result = self._enforce_schema(result, schema)

        return result

    def grade(self, output: str, request: str) -> float:
        """Return a 0–1 quality score for the output given the request.

        Higher is better.
        """
        report = self.validate(output, request)
        return report.score

    # ------------------------------------------------------------------
    # Check implementations
    # ------------------------------------------------------------------

    def _check_schema(
        self,
        output: str,
        schema: dict[str, Any],
    ) -> list[Violation]:
        """Check if the output conforms to a JSON Schema."""
        violations: list[Violation] = []

        # Try to parse as JSON.
        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            # Try to extract JSON from the output.
            from .json_healer import JSONHealer
            healer = JSONHealer()
            try:
                data, _ = healer.heal(output)
            except Exception:
                violations.append(Violation(
                    rule_type=RuleType.SCHEMA,
                    severity=0.8,
                    description="Output is not valid JSON and could not be healed",
                    suggestion="Ensure the output is valid JSON",
                ))
                return violations

        # Validate against schema.
        from .json_healer import JSONHealer
        healer = JSONHealer()
        result = healer.validate(data, schema)
        for error in result.errors:
            violations.append(Violation(
                rule_type=RuleType.SCHEMA,
                severity=0.6,
                description=error,
            ))

        return violations

    def _check_completeness(
        self,
        output: str,
        request: str,
    ) -> list[Violation]:
        """Check if the output addresses all parts of the request."""
        violations: list[Violation] = []

        if not request.strip():
            return violations

        # Extract question marks — each likely represents a question to answer.
        questions = re.findall(r'[^.!?]*\?', request)
        output_lower = output.lower()

        for q in questions:
            # Check if key words from the question appear in the answer.
            key_words = set(re.findall(r'\b\w{4,}\b', q.lower()))
            key_words -= {"what", "where", "when", "which", "would", "could", "should", "does", "that", "this", "have", "with", "from", "about"}
            if key_words:
                matches = sum(1 for w in key_words if w in output_lower)
                if matches < len(key_words) * 0.3:
                    violations.append(Violation(
                        rule_type=RuleType.COMPLETENESS,
                        severity=0.4,
                        description=f"Question may not be addressed: '{q.strip()[:80]}'",
                        suggestion="Ensure all questions in the request are answered",
                    ))

        # Check for numbered items in request.
        numbered = re.findall(r'(?:^|\n)\s*(\d+)[.)]\s+(.+)', request)
        if len(numbered) >= 3:
            addressed = 0
            for num, item in numbered:
                item_words = set(re.findall(r'\b\w{4,}\b', item.lower()))
                if any(w in output_lower for w in item_words):
                    addressed += 1
            if addressed < len(numbered) * 0.5:
                violations.append(Violation(
                    rule_type=RuleType.COMPLETENESS,
                    severity=0.5,
                    description=f"Only {addressed}/{len(numbered)} numbered items appear addressed",
                    suggestion="Address all numbered items from the request",
                ))

        return violations

    def _check_format(self, output: str) -> list[Violation]:
        """Check format validity: balanced brackets, valid code blocks, etc."""
        violations: list[Violation] = []

        # Check balanced markdown code fences.
        fence_count = output.count("```")
        if fence_count % 2 != 0:
            violations.append(Violation(
                rule_type=RuleType.FORMAT,
                severity=0.3,
                description=f"Unbalanced code fences: {fence_count} triple-backtick markers",
                suggestion="Ensure all code blocks are properly closed",
            ))

        # Check balanced brackets in any JSON-like sections.
        open_braces = output.count("{") - output.count("}")
        open_brackets = output.count("[") - output.count("]")
        if abs(open_braces) > 2:
            violations.append(Violation(
                rule_type=RuleType.FORMAT,
                severity=0.3,
                description=f"Unbalanced braces: {abs(open_braces)} unclosed",
            ))
        if abs(open_brackets) > 2:
            violations.append(Violation(
                rule_type=RuleType.FORMAT,
                severity=0.3,
                description=f"Unbalanced brackets: {abs(open_brackets)} unclosed",
            ))

        # Check for incomplete sentences at the end.
        stripped = output.rstrip()
        if stripped and stripped[-1] not in '.!?:"\')]}>`~|*_':
            # Check if it looks like a truncated sentence.
            last_line = stripped.split("\n")[-1].strip()
            if len(last_line) > 20 and not last_line.startswith(("```", "|", "-", "*", "#")):
                violations.append(Violation(
                    rule_type=RuleType.FORMAT,
                    severity=0.2,
                    description="Output may be truncated (doesn't end with punctuation)",
                    suggestion="Ensure the response is complete",
                ))

        return violations

    def _check_safety(self, output: str) -> list[Violation]:
        """Check for PII, credentials, and malicious content."""
        violations: list[Violation] = []

        # SSN.
        for m in self._SSN_RE.finditer(output):
            violations.append(Violation(
                rule_type=RuleType.SAFETY,
                severity=0.9,
                description="Possible SSN detected",
                span=(m.start(), m.end()),
                suggestion="Remove Social Security numbers",
            ))

        # Credit card.
        for m in self._CC_RE.finditer(output):
            # Quick Luhn-like check: just flag the pattern.
            violations.append(Violation(
                rule_type=RuleType.SAFETY,
                severity=0.9,
                description="Possible credit card number detected",
                span=(m.start(), m.end()),
                suggestion="Remove credit card numbers",
            ))

        # API keys.
        for m in self._API_KEY_RE.finditer(output):
            violations.append(Violation(
                rule_type=RuleType.SAFETY,
                severity=0.8,
                description="Possible API key or credential detected",
                span=(m.start(), m.end()),
                suggestion="Remove API keys and credentials",
            ))

        # AWS keys.
        for m in self._AWS_KEY_RE.finditer(output):
            violations.append(Violation(
                rule_type=RuleType.SAFETY,
                severity=0.9,
                description="Possible AWS access key detected",
                span=(m.start(), m.end()),
                suggestion="Remove AWS credentials",
            ))

        # Private keys.
        for m in self._PRIVATE_KEY_RE.finditer(output):
            violations.append(Violation(
                rule_type=RuleType.SAFETY,
                severity=0.9,
                description="Private key material detected",
                span=(m.start(), m.end()),
                suggestion="Remove private key content",
            ))

        # Injection attempts.
        for m in self._INJECTION_RE.finditer(output):
            violations.append(Violation(
                rule_type=RuleType.SAFETY,
                severity=0.7,
                description="Possible prompt injection detected in output",
                span=(m.start(), m.end()),
            ))

        return violations

    def _check_length(
        self,
        output: str,
        request: str,
    ) -> list[Violation]:
        """Check if the output length is appropriate."""
        violations: list[Violation] = []
        output_len = len(output)
        request_len = len(request)

        # Too short (potential truncation).
        if output_len < 10 and request_len > 50:
            violations.append(Violation(
                rule_type=RuleType.LENGTH,
                severity=0.5,
                description=f"Response suspiciously short ({output_len} chars) for request ({request_len} chars)",
                suggestion="Response may be truncated",
            ))

        # Very long with lots of repetition (padding).
        if output_len > 5000:
            words = output.split()
            unique_words = set(w.lower() for w in words)
            ratio = len(unique_words) / max(len(words), 1)
            if ratio < 0.15:
                violations.append(Violation(
                    rule_type=RuleType.LENGTH,
                    severity=0.5,
                    description=f"Low vocabulary diversity ({ratio:.1%}) suggests padding or repetition",
                    suggestion="Reduce repetitive content",
                ))

        return violations

    def _check_coherence(self, output: str) -> list[Violation]:
        """Check that the output is coherent (first/last sentences make sense)."""
        violations: list[Violation] = []
        sentences = re.split(r'(?<=[.!?])\s+', output.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        if len(sentences) < 2:
            return violations

        first = sentences[0]
        last = sentences[-1]

        # Check if first sentence starts with a lowercase word that isn't "the", "a", etc.
        # — might indicate truncated beginning.
        if first and first[0].islower() and not first.startswith(("the ", "a ", "an ", "i ", "e.g.")):
            violations.append(Violation(
                rule_type=RuleType.COHERENCE,
                severity=0.2,
                description="First sentence starts with lowercase — possible truncation",
            ))

        # Check if the response appears to be cut off mid-word.
        if last and not last[-1] in '.!?:"\')]}' and len(last) > 5:
            words = last.split()
            if words and len(words[-1]) < 3:
                violations.append(Violation(
                    rule_type=RuleType.COHERENCE,
                    severity=0.3,
                    description="Last sentence may be truncated mid-word",
                ))

        # Check for topic drift: first and last sentences share few words.
        if len(sentences) > 10:
            first_words = set(first.lower().split()) - {"the", "a", "an", "is", "are", "was", "in", "of", "to", "and"}
            last_words = set(last.lower().split()) - {"the", "a", "an", "is", "are", "was", "in", "of", "to", "and"}
            if first_words and last_words:
                overlap = len(first_words & last_words) / max(len(first_words | last_words), 1)
                # Very low overlap across a long text is fine.  Only flag if
                # the text is short AND disjoint.
                if overlap == 0 and len(sentences) < 15 and len(output) < 2000:
                    violations.append(Violation(
                        rule_type=RuleType.COHERENCE,
                        severity=0.2,
                        description="First and last sentences share no content words — possible topic drift",
                    ))

        return violations

    def _check_actionability(
        self,
        output: str,
        request: str,
    ) -> list[Violation]:
        """Check if the output is actionable when the request asks for action."""
        violations: list[Violation] = []

        # Detect if the request asks for concrete steps.
        action_patterns = [
            r'\b(?:how\s+(?:do|can|to|should))\b',
            r'\b(?:steps?\s+(?:to|for))\b',
            r'\b(?:create|build|implement|write|make|set\s+up|configure|install)\b',
            r'\b(?:give\s+me|provide|list)\s+(?:steps|instructions)\b',
        ]
        is_action_request = any(re.search(p, request, re.IGNORECASE) for p in action_patterns)

        if not is_action_request:
            return violations

        # Check if the response contains concrete steps.
        has_numbered_steps = bool(re.search(r'(?:^|\n)\s*\d+[.)]\s+', output))
        has_bullet_steps = bool(re.search(r'(?:^|\n)\s*[-*]\s+', output))
        has_code = "```" in output or bool(re.search(r'(?:^|\n)\s{4,}\S', output))
        has_imperative = bool(re.search(
            r'\b(?:run|execute|install|open|click|type|enter|navigate|create|add|set|configure)\b',
            output, re.IGNORECASE,
        ))

        if not (has_numbered_steps or has_bullet_steps or has_code or has_imperative):
            violations.append(Violation(
                rule_type=RuleType.ACTIONABILITY,
                severity=0.3,
                description="Request asks for actionable steps but response lacks concrete instructions",
                suggestion="Include numbered steps, code examples, or specific commands",
            ))

        return violations

    # ------------------------------------------------------------------
    # Score computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_score(violations: list[Violation]) -> float:
        """Compute a 0–1 quality score from violations."""
        if not violations:
            return 1.0
        total_penalty = sum(v.severity * 0.15 for v in violations)
        return max(0.0, min(1.0, 1.0 - total_penalty))

    # ------------------------------------------------------------------
    # Enforcement helpers
    # ------------------------------------------------------------------

    def _enforce_safety(self, text: str) -> str:
        """Remove PII and credentials from text."""
        result = text
        result = self._SSN_RE.sub("[REDACTED-SSN]", result)
        result = self._CC_RE.sub("[REDACTED-CC]", result)
        result = self._AWS_KEY_RE.sub("[REDACTED-AWS-KEY]", result)
        result = self._PRIVATE_KEY_RE.sub("[REDACTED-PRIVATE-KEY]", result)
        result = self._API_KEY_RE.sub(lambda m: m.group(0).split("=")[0] + "=[REDACTED]" if "=" in m.group(0) else m.group(0).split(":")[0] + ": [REDACTED]", result)
        return result

    @staticmethod
    def _enforce_format(text: str, params: dict[str, Any]) -> str:
        """Fix format issues."""
        result = text

        # Balance code fences.
        if result.count("```") % 2 != 0:
            result += "\n```"

        return result

    @staticmethod
    def _enforce_schema(text: str, schema: dict[str, Any]) -> str:
        """Try to coerce text to match schema."""
        from .json_healer import JSONHealer
        healer = JSONHealer()
        try:
            obj, _ = healer.heal(text)
            normalized = healer.normalize(obj, schema)
            return json.dumps(normalized, indent=2)
        except Exception:
            return text
