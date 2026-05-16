"""Hardening advisor — auto-generates security rules from red-team bypasses.

Analyses ``RedTeamReport`` output, identifies patterns in successful
bypasses, and produces hardening patches that can be applied to
``AdversarialFilter`` (from ``orchestra.security.hardening``).

Usage::

    advisor = HardeningAdvisor()
    patches = await advisor.analyze_bypasses(report)
    rules = await advisor.generate_new_rules(report.critical_bypasses)
    applied = await advisor.auto_patch(report, dry_run=True)
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .red_team_runner import RedTeamReport, BypassFinding

__all__ = [
    "HardeningAdvisor",
    "HardeningPatch",
    "SecurityRule",
    "AppliedPatch",
    "RegressionReport",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SecurityRule:
    """A new detection rule derived from bypass analysis."""
    id: str
    name: str
    pattern: str                # Regex pattern
    severity: str               # low | medium | high | critical
    category: str               # Which attack class it covers
    description: str
    confidence: float           # 0.0–1.0 confidence this rule is correct
    false_positive_risk: str    # low | medium | high
    source_bypass_ids: list[str] = field(default_factory=list)


@dataclass
class HardeningPatch:
    """A recommended patch for the security stack."""
    id: str
    priority: str               # critical | high | medium | low
    title: str
    description: str
    rules: list[SecurityRule]
    estimated_block_rate_improvement: float
    estimated_fp_risk: float
    attack_classes_covered: list[str]
    code_snippet: str = ""      # Suggested code change


@dataclass
class AppliedPatch:
    """Record of a patch that was applied (or would be in dry-run)."""
    patch_id: str
    applied: bool
    dry_run: bool
    rules_added: int
    timestamp: datetime
    details: str


@dataclass
class RegressionReport:
    """Comparison of two red-team reports to detect regressions."""
    timestamp: datetime
    report_before_id: str
    report_after_id: str
    block_rate_delta: float
    fp_rate_delta: float
    new_bypasses: list[BypassFinding]
    fixed_bypasses: list[str]
    regressions: list[str]
    improvements: list[str]
    overall_trend: str          # improved | regressed | stable


# ---------------------------------------------------------------------------
# Pattern extraction heuristics
# ---------------------------------------------------------------------------

_KEYWORD_GROUPS: dict[str, list[str]] = {
    "ignore_override": [
        "ignore", "disregard", "forget", "bypass", "override", "cancel",
        "skip", "drop", "remove", "delete", "disable", "turn off",
    ],
    "instruction_targets": [
        "instructions", "rules", "guidelines", "constraints", "policies",
        "restrictions", "filters", "safety", "system prompt", "configuration",
    ],
    "authority_claims": [
        "admin", "administrator", "root", "sudo", "superuser", "developer",
        "researcher", "auditor", "authorized", "operator", "engineer",
    ],
    "persona_attacks": [
        "DAN", "STAN", "DUDE", "jailbreak", "unrestricted", "unfiltered",
        "uncensored", "evil", "no rules", "no restrictions", "developer mode",
    ],
    "encoding_markers": [
        "base64", "hex", "decode", "encoded", "ROT13", "cipher",
        "binary", "morse", "reverse", "atbash",
    ],
    "exfiltration_verbs": [
        "reveal", "show", "print", "output", "display", "dump", "export",
        "extract", "leak", "send", "post", "email", "upload",
    ],
}


def _extract_keywords(text: str) -> set[str]:
    """Extract known adversarial keywords from bypass payload."""
    found: set[str] = set()
    text_lower = text.lower()
    for group, keywords in _KEYWORD_GROUPS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                found.add(f"{group}:{kw}")
    return found


def _generate_regex_from_bypass(bypass: BypassFinding) -> str | None:
    """Attempt to generate a detection regex from a bypass payload.

    Uses keyword extraction and common attack pattern templates.
    Returns None if no reliable pattern can be inferred.
    """
    text = bypass.payload_text
    keywords = _extract_keywords(text)

    if not keywords:
        return None

    # Build a pattern from the most prominent keyword groups found.
    groups_found = {kw.split(":")[0] for kw in keywords}

    patterns: list[str] = []

    if "ignore_override" in groups_found and "instruction_targets" in groups_found:
        # Extract the specific override verb and target.
        override_words = [
            kw.split(":")[1] for kw in keywords if kw.startswith("ignore_override:")
        ]
        target_words = [
            kw.split(":")[1] for kw in keywords if kw.startswith("instruction_targets:")
        ]
        if override_words and target_words:
            verb_group = "|".join(re.escape(w) for w in override_words)
            target_group = "|".join(re.escape(w) for w in target_words)
            patterns.append(
                rf"(?i)({verb_group})\s+.{{0,30}}({target_group})"
            )

    if "authority_claims" in groups_found:
        auth_words = [
            kw.split(":")[1] for kw in keywords if kw.startswith("authority_claims:")
        ]
        if auth_words:
            auth_group = "|".join(re.escape(w) for w in auth_words)
            patterns.append(rf"(?i)\b({auth_group})\b.{{0,20}}(mode|override|access|privilege)")

    if "persona_attacks" in groups_found:
        persona_words = [
            kw.split(":")[1] for kw in keywords if kw.startswith("persona_attacks:")
        ]
        if persona_words:
            persona_group = "|".join(re.escape(w) for w in persona_words)
            patterns.append(rf"(?i)\b({persona_group})\b")

    if "encoding_markers" in groups_found:
        enc_words = [
            kw.split(":")[1] for kw in keywords if kw.startswith("encoding_markers:")
        ]
        if enc_words:
            enc_group = "|".join(re.escape(w) for w in enc_words)
            patterns.append(rf"(?i)({enc_group})\s*(decode|encoded?|and follow|and comply)")

    if "exfiltration_verbs" in groups_found:
        exfil_words = [
            kw.split(":")[1] for kw in keywords if kw.startswith("exfiltration_verbs:")
        ]
        if exfil_words:
            exfil_group = "|".join(re.escape(w) for w in exfil_words)
            patterns.append(
                rf"(?i)({exfil_group})\s+.{{0,20}}(system\s*prompt|api\s*key|credentials?|secrets?)"
            )

    if not patterns:
        return None

    # Combine with OR.
    if len(patterns) == 1:
        return patterns[0]
    return "|".join(f"({p})" for p in patterns)


# ---------------------------------------------------------------------------
# Hardening Advisor
# ---------------------------------------------------------------------------

class HardeningAdvisor:
    """Analyses red-team results and auto-generates hardening patches.

    Works with the ``AdversarialFilter`` from ``orchestra.security.hardening``
    to propose and optionally apply new detection rules.
    """

    def __init__(self, *, adversarial_filter: Any | None = None) -> None:
        self._filter = adversarial_filter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze_bypasses(
        self, report: RedTeamReport
    ) -> list[HardeningPatch]:
        """Analyse a red-team report and produce hardening patches.

        Groups bypasses by attack class, generates detection rules for each
        group, and packages them into prioritised patches.

        Args:
            report: The red-team report to analyse.

        Returns:
            List of ``HardeningPatch`` instances, sorted by priority.
        """
        # Group bypasses by attack class.
        by_class: dict[str, list[BypassFinding]] = {}
        all_bypasses = list(report.critical_bypasses)
        for cr in report.attack_results.values():
            for b in cr.bypasses:
                by_class.setdefault(b.attack_class, []).append(b)

        patches: list[HardeningPatch] = []

        for cls_name, bypasses in by_class.items():
            rules = await self.generate_new_rules(bypasses)
            if not rules:
                continue

            max_severity = max(b.severity for b in bypasses)
            priority = "critical" if max_severity >= 9 else (
                "high" if max_severity >= 7 else (
                    "medium" if max_severity >= 5 else "low"
                )
            )

            # Estimate improvement: each rule covers some fraction of bypasses.
            estimated_improvement = min(0.95, len(rules) * 0.1)

            # Code snippet.
            snippet_lines = [
                f"# Auto-generated rules for {cls_name}",
                f"# Generated from {len(bypasses)} bypass(es)",
            ]
            for rule in rules:
                snippet_lines.append(
                    f'("{rule.name}", r"{rule.pattern}", "{rule.severity}"),'
                )
            code_snippet = "\n".join(snippet_lines)

            patch_id = f"PATCH-{hashlib.sha256(cls_name.encode()).hexdigest()[:8]}"
            patches.append(HardeningPatch(
                id=patch_id,
                priority=priority,
                title=f"Harden against {cls_name} bypasses",
                description=(
                    f"Add {len(rules)} new detection rule(s) to cover "
                    f"{len(bypasses)} bypass(es) found in {cls_name}."
                ),
                rules=rules,
                estimated_block_rate_improvement=estimated_improvement,
                estimated_fp_risk=0.02 * len(rules),
                attack_classes_covered=[cls_name],
                code_snippet=code_snippet,
            ))

        # Sort by priority.
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        patches.sort(key=lambda p: priority_order.get(p.priority, 99))

        return patches

    async def generate_new_rules(
        self, bypasses: list[BypassFinding]
    ) -> list[SecurityRule]:
        """Generate new security rules from a list of bypass findings.

        Uses keyword extraction and pattern inference to produce regex
        rules that would have caught the bypasses.

        Args:
            bypasses: Bypass findings to analyse.

        Returns:
            List of ``SecurityRule`` instances.
        """
        rules: list[SecurityRule] = []
        seen_patterns: set[str] = set()

        for bypass in bypasses:
            pattern = _generate_regex_from_bypass(bypass)
            if pattern and pattern not in seen_patterns:
                seen_patterns.add(pattern)

                severity = "critical" if bypass.severity >= 9 else (
                    "high" if bypass.severity >= 7 else (
                        "medium" if bypass.severity >= 5 else "low"
                    )
                )

                # Estimate confidence based on keyword richness.
                keywords = _extract_keywords(bypass.payload_text)
                confidence = min(1.0, len(keywords) * 0.15)

                rule_id = f"RULE-{hashlib.sha256(pattern.encode()).hexdigest()[:8]}"
                rules.append(SecurityRule(
                    id=rule_id,
                    name=f"auto_{bypass.attack_class.lower()}_{rule_id[-4:]}",
                    pattern=pattern,
                    severity=severity,
                    category=bypass.attack_class,
                    description=(
                        f"Auto-generated rule from bypass {bypass.payload_id} "
                        f"in {bypass.attack_class}/{bypass.subclass}."
                    ),
                    confidence=confidence,
                    false_positive_risk="low" if confidence > 0.6 else "medium",
                    source_bypass_ids=[bypass.payload_id],
                ))

        return rules

    async def auto_patch(
        self,
        report: RedTeamReport,
        dry_run: bool = True,
    ) -> list[AppliedPatch]:
        """Automatically apply hardening patches from a red-team report.

        In dry-run mode (default), reports what would be applied without
        making changes.

        Args:
            report: The red-team report to patch from.
            dry_run: If ``True``, only simulate patching.

        Returns:
            List of ``AppliedPatch`` records.
        """
        patches = await self.analyze_bypasses(report)
        applied: list[AppliedPatch] = []

        for patch in patches:
            if not dry_run and self._filter is not None:
                # Apply rules to the live filter.
                for rule in patch.rules:
                    try:
                        compiled = re.compile(rule.pattern)
                        # Inject into the filter's compiled pattern list.
                        if hasattr(self._filter, "_COMPILED_INJECTION"):
                            self._filter._COMPILED_INJECTION.append(
                                (rule.name, compiled, rule.severity)
                            )
                    except re.error as e:
                        logger.warning(
                            "Invalid regex in rule %s: %s", rule.id, e
                        )

            applied.append(AppliedPatch(
                patch_id=patch.id,
                applied=not dry_run,
                dry_run=dry_run,
                rules_added=len(patch.rules),
                timestamp=datetime.now(timezone.utc),
                details=(
                    f"{'[DRY RUN] ' if dry_run else ''}"
                    f"Patch {patch.id}: {patch.title} — "
                    f"{len(patch.rules)} rule(s) for {', '.join(patch.attack_classes_covered)}"
                ),
            ))

        return applied

    async def track_regression(
        self,
        report_before: RedTeamReport,
        report_after: RedTeamReport,
    ) -> RegressionReport:
        """Compare two red-team reports to detect regressions or improvements.

        Args:
            report_before: Earlier report (baseline).
            report_after: Later report (current).

        Returns:
            A ``RegressionReport`` summarising changes.
        """
        before_bypass_ids = {
            b.payload_id for b in report_before.critical_bypasses
        }
        after_bypass_ids = {
            b.payload_id for b in report_after.critical_bypasses
        }

        new_bypasses = [
            b for b in report_after.critical_bypasses
            if b.payload_id not in before_bypass_ids
        ]
        fixed_bypasses = list(before_bypass_ids - after_bypass_ids)

        br_delta = report_after.overall_block_rate - report_before.overall_block_rate
        fp_delta = report_after.overall_false_positive_rate - report_before.overall_false_positive_rate

        regressions: list[str] = []
        improvements: list[str] = []

        for cls_name in set(report_before.attack_results) | set(report_after.attack_results):
            before_cr = report_before.attack_results.get(cls_name)
            after_cr = report_after.attack_results.get(cls_name)
            if before_cr and after_cr:
                delta = after_cr.block_rate - before_cr.block_rate
                if delta < -0.05:
                    regressions.append(
                        f"{cls_name}: block rate dropped {abs(delta)*100:.1f}pp "
                        f"({before_cr.block_rate*100:.1f}% → {after_cr.block_rate*100:.1f}%)"
                    )
                elif delta > 0.05:
                    improvements.append(
                        f"{cls_name}: block rate improved {delta*100:.1f}pp "
                        f"({before_cr.block_rate*100:.1f}% → {after_cr.block_rate*100:.1f}%)"
                    )

        # Overall trend.
        if br_delta > 0.02 and not regressions:
            trend = "improved"
        elif br_delta < -0.02 or len(regressions) > len(improvements):
            trend = "regressed"
        else:
            trend = "stable"

        return RegressionReport(
            timestamp=datetime.now(timezone.utc),
            report_before_id=report_before.report_id,
            report_after_id=report_after.report_id,
            block_rate_delta=br_delta,
            fp_rate_delta=fp_delta,
            new_bypasses=new_bypasses,
            fixed_bypasses=fixed_bypasses,
            regressions=regressions,
            improvements=improvements,
            overall_trend=trend,
        )
