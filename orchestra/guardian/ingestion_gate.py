"""IngestionGate — Security gate for ALL code entering the Orchestra codebase.

When Orchestra generates new code (via CodingTeam, codebase agent, or
direct AI generation), it **must** pass through IngestionGate before being
written to disk.  When a human writes code and stages it for commit,
IngestionGate can be invoked to validate.

This ensures:
- No hardcoded secrets ever enter the codebase.
- All AI-generated code meets quality + security standards.
- Every approved file is signed with an audit trail.
- Security-critical files get extra scrutiny.

Violation categories
--------------------
**Blocking violations** (reject the file):
    ``SECRET_HARDCODED``, ``SQL_FSTRING``, ``SHELL_INJECTION_RISK``

**Warning violations** (allow but log):
    Everything else (missing type hints, bare excepts, mutable defaults,
    hardcoded IPs, etc.)

Integration points
------------------
- ``orchestra/codebase/editor.py`` calls this before ``write_file()``.
- ``orchestra/teams/pre_built_teams.py`` coding_team wraps all writes.
- Pre-commit hook (``scripts/pre-commit-check.sh``) can call this.
- API endpoint ``POST /v1/code/validate``.

Dependencies: **stdlib only** (``ast``, ``re``, ``hashlib``, ``hmac``,
``time``, ``logging``, ``asyncio``, ``os``, ``pathlib``).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from orchestra.guardian.security_config import SECURITY_CONFIG, SecurityConfig

__all__ = [
    "IngestionViolation",
    "IngestionReport",
    "IngestionGate",
]

log = logging.getLogger("orchestra.guardian.ingestion_gate")


# ---------------------------------------------------------------------------
# IngestionViolation enum
# ---------------------------------------------------------------------------

class IngestionViolation(str, Enum):
    """Violation types detected during code ingestion.

    Each variant represents a specific quality or security issue found
    in code entering the Orchestra codebase.
    """

    SECRET_HARDCODED = "secret_hardcoded"
    """API key, password, or token found in source code."""

    HARDCODED_IP = "hardcoded_ip"
    """Literal IP address (e.g. ``192.168.x.x`` or public IPs)."""

    MISSING_TYPE_HINTS = "missing_type_hints"
    """Public API function/method missing type annotations."""

    MISSING_DOCSTRING = "missing_docstring"
    """Public class or function missing a docstring."""

    PRINT_IN_PROD = "print_in_prod"
    """``print()`` used instead of ``logging``."""

    BARE_EXCEPT = "bare_except"
    """``except:`` or ``except Exception:`` with ``pass``."""

    MUTABLE_DEFAULT = "mutable_default"
    """Mutable default argument: ``def f(x=[]):``."""

    SQL_FSTRING = "sql_fstring"
    """f-string or %-format used in SQL query context."""

    SHELL_INJECTION_RISK = "shell_injection_risk"
    """``subprocess`` with user input or ``shell=True``."""

    DEPENDENCY_PINNED = "dependency_pinned"
    """Dependency pinned with ``==`` instead of ``>=`` (inflexible)."""

    GPL_LICENSE_RISK = "gpl_license_risk"
    """Import of a known GPL-licensed package in non-GPL project."""

    BROAD_PERMISSIONS = "broad_permissions"
    """``chmod 777``, ``rwxrwxrwx``, or world-writable permissions."""

    TODO_IN_SECURITY = "todo_in_security"
    """``TODO`` or ``FIXME`` in security-critical code path."""

    MISSING_AUTH_CHECK = "missing_auth_check"
    """Route handler without authentication/authorisation check."""

    UNVALIDATED_INPUT = "unvalidated_input"
    """Route handler uses raw request body without validation."""


# ---------------------------------------------------------------------------
# Violation severity / blocking status
# ---------------------------------------------------------------------------

_BLOCKING_VIOLATIONS: frozenset[IngestionViolation] = frozenset({
    IngestionViolation.SECRET_HARDCODED,
    IngestionViolation.SQL_FSTRING,
    IngestionViolation.SHELL_INJECTION_RISK,
})

_VIOLATION_SECURITY_WEIGHT: dict[IngestionViolation, float] = {
    IngestionViolation.SECRET_HARDCODED: 1.0,
    IngestionViolation.SQL_FSTRING: 0.95,
    IngestionViolation.SHELL_INJECTION_RISK: 0.95,
    IngestionViolation.BARE_EXCEPT: 0.3,
    IngestionViolation.HARDCODED_IP: 0.4,
    IngestionViolation.BROAD_PERMISSIONS: 0.6,
    IngestionViolation.TODO_IN_SECURITY: 0.5,
    IngestionViolation.MISSING_AUTH_CHECK: 0.7,
    IngestionViolation.UNVALIDATED_INPUT: 0.65,
    IngestionViolation.GPL_LICENSE_RISK: 0.3,
    IngestionViolation.MUTABLE_DEFAULT: 0.2,
    IngestionViolation.PRINT_IN_PROD: 0.1,
    IngestionViolation.MISSING_TYPE_HINTS: 0.05,
    IngestionViolation.MISSING_DOCSTRING: 0.05,
    IngestionViolation.DEPENDENCY_PINNED: 0.1,
}

_VIOLATION_QUALITY_WEIGHT: dict[IngestionViolation, float] = {
    IngestionViolation.MISSING_TYPE_HINTS: 0.3,
    IngestionViolation.MISSING_DOCSTRING: 0.3,
    IngestionViolation.PRINT_IN_PROD: 0.2,
    IngestionViolation.BARE_EXCEPT: 0.25,
    IngestionViolation.MUTABLE_DEFAULT: 0.3,
    IngestionViolation.DEPENDENCY_PINNED: 0.15,
    IngestionViolation.HARDCODED_IP: 0.15,
    IngestionViolation.TODO_IN_SECURITY: 0.2,
    IngestionViolation.GPL_LICENSE_RISK: 0.1,
    IngestionViolation.SECRET_HARDCODED: 0.5,
    IngestionViolation.SQL_FSTRING: 0.4,
    IngestionViolation.SHELL_INJECTION_RISK: 0.4,
    IngestionViolation.BROAD_PERMISSIONS: 0.2,
    IngestionViolation.MISSING_AUTH_CHECK: 0.3,
    IngestionViolation.UNVALIDATED_INPUT: 0.3,
}


# ---------------------------------------------------------------------------
# Secret detection patterns
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, str]] = [
    # Generic API key patterns
    (r'(?:api[_-]?key|apikey)\s*[=:]\s*["\'][a-zA-Z0-9_\-]{8,}["\']', "API key literal"),
    (r'(?:secret|SECRET)\s*[=:]\s*["\'][a-zA-Z0-9_\-]{8,}["\']', "Secret literal"),
    (r'(?:token|TOKEN)\s*[=:]\s*["\'][a-zA-Z0-9_\-]{8,}["\']', "Token literal"),
    (r'(?:password|PASSWORD|passwd)\s*[=:]\s*["\'][^"\']{4,}["\']', "Password literal"),
    # Variable assignment patterns (KEY = "value" or KEY="value")
    (r'[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTH)[A-Z_]*\s*=\s*["\'][a-zA-Z0-9_\-]{8,}["\']', "Credential assignment"),
    # Specific provider patterns
    (r'sk-[a-zA-Z0-9]{10,}', "OpenAI API key"),
    (r'sk-proj-[a-zA-Z0-9_\-]{10,}', "OpenAI project key"),
    (r'ghp_[a-zA-Z0-9]{36,}', "GitHub personal access token"),
    (r'gho_[a-zA-Z0-9]{36,}', "GitHub OAuth token"),
    (r'github_pat_[a-zA-Z0-9_]{36,}', "GitHub PAT"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key ID"),
    (r'xoxb-[0-9]+-[0-9a-zA-Z]+', "Slack bot token"),
    (r'xoxp-[0-9]+-[0-9a-zA-Z]+', "Slack user token"),
    (r'xoxs-[0-9]+-[0-9a-zA-Z]+', "Slack session token"),
    (r'AIza[0-9A-Za-z\-_]{35}', "Google API key"),
    (r'ya29\.[0-9A-Za-z\-_]+', "Google OAuth token"),
    (r'eyJ[a-zA-Z0-9_\-]+\.eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+', "JWT token"),
    (r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----', "Private key"),
    (r'-----BEGIN CERTIFICATE-----', "Certificate"),
    (r'SG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43}', "SendGrid API key"),
    (r'sk_live_[a-zA-Z0-9]{24,}', "Stripe live key"),
    (r'pk_live_[a-zA-Z0-9]{24,}', "Stripe publishable key"),
    (r'sq0csp-[a-zA-Z0-9_\-]{43}', "Square OAuth secret"),
    (r'AC[a-f0-9]{32}', "Twilio account SID"),
    (r'npm_[a-zA-Z0-9]{36}', "NPM token"),
    (r'pypi-[a-zA-Z0-9]{64,}', "PyPI token"),
]

_COMPILED_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), desc) for p, desc in _SECRET_PATTERNS
]


# ---------------------------------------------------------------------------
# IP address patterns
# ---------------------------------------------------------------------------

_IP_PATTERN = re.compile(
    r'\b(?:'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
)

_SAFE_IPS: frozenset[str] = frozenset({
    "127.0.0.1",
    "0.0.0.0",
    "255.255.255.255",
    "255.255.255.0",
    "224.0.0.1",      # multicast
})

# ---------------------------------------------------------------------------
# SQL injection patterns
# ---------------------------------------------------------------------------

_SQL_FSTRING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'f["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\s', re.IGNORECASE),
    re.compile(r'["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\s.*%\s*\(', re.IGNORECASE),
    re.compile(r'["\'](?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\s.*\.format\s*\(', re.IGNORECASE),
    re.compile(r'execute\s*\(\s*f["\']', re.IGNORECASE),
    re.compile(r'execute\s*\(\s*["\'].*%\s', re.IGNORECASE),
    re.compile(r'executemany\s*\(\s*f["\']', re.IGNORECASE),
    re.compile(r'cursor\.execute\s*\(\s*f["\']', re.IGNORECASE),
    re.compile(r'\.raw\s*\(\s*f["\']', re.IGNORECASE),  # Django ORM raw SQL
]

# ---------------------------------------------------------------------------
# Shell injection patterns
# ---------------------------------------------------------------------------

_SHELL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'subprocess\.\w+\(.*shell\s*=\s*True', re.IGNORECASE | re.DOTALL),
    re.compile(r'os\.system\s*\(', re.IGNORECASE),
    re.compile(r'os\.popen\s*\(', re.IGNORECASE),
    re.compile(r'subprocess\.\w+\(\s*f["\']', re.IGNORECASE),
    re.compile(r'subprocess\.\w+\(\s*["\'].*\.format\s*\(', re.IGNORECASE | re.DOTALL),
    re.compile(r'subprocess\.\w+\(\s*["\'].*%\s', re.IGNORECASE | re.DOTALL),
    re.compile(r'subprocess\.\w+\(\s*\w+\s*\+', re.IGNORECASE),  # string concat
    re.compile(r'commands\.get\w+\s*\(', re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# GPL-licensed packages
# ---------------------------------------------------------------------------

_GPL_PACKAGES: frozenset[str] = frozenset({
    "readline",
    "mysql-connector-python",
    "PyQt5",
    "PyQt6",
    "sip",
    "linux",
    "ghostscript",
    "pycairo",
    "pygobject",
    "ffmpeg",       # LGPL/GPL
    "linux",
    "bash",
    "glib",
    "gtk",
    "gobject",
})

# ---------------------------------------------------------------------------
# Route handler patterns (for auth and input validation checks)
# ---------------------------------------------------------------------------

_ROUTE_DECORATORS: list[re.Pattern[str]] = [
    re.compile(r'@\w+\.(?:route|get|post|put|delete|patch|api_view)\s*\('),
    re.compile(r'@(?:app|router|blueprint|api)\.(?:route|get|post|put|delete|patch)\s*\('),
    re.compile(r'@require_http_methods\s*\('),
]

_AUTH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'@(?:login_required|auth_required|requires_auth|permission_required)'),
    re.compile(r'@(?:jwt_required|token_required|api_key_required)'),
    re.compile(r'(?:authenticate|verify_token|check_auth|verify_api_key)\s*\('),
    re.compile(r'request\.(?:user|auth|credentials)'),
    re.compile(r'current_user'),
    re.compile(r'Authorization.*header', re.IGNORECASE),
    re.compile(r'Bearer\s+token', re.IGNORECASE),
    re.compile(r'Depends\s*\(\s*\w*(?:auth|token|user|credential)', re.IGNORECASE),
]

_INPUT_VALIDATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'(?:pydantic|marshmallow|cerberus|voluptuous|wtforms)'),
    re.compile(r'\.validate\s*\('),
    re.compile(r'(?:Schema|Serializer|Form)\s*\('),
    re.compile(r'@validate\b'),
    re.compile(r'request\.(?:get_json|json)\s*\(\s*force\s*=\s*True\s*\)'),  # unsafe
    re.compile(r'json\.loads\s*\(\s*request'),  # manual parse
    re.compile(r'\.is_valid\s*\('),
    re.compile(r'TypeAdapter|BaseModel'),
]

# ---------------------------------------------------------------------------
# Broad permissions patterns
# ---------------------------------------------------------------------------

_BROAD_PERM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'chmod\s+777\b'),
    re.compile(r'chmod\s+666\b'),
    re.compile(r'0o777\b'),
    re.compile(r'0o666\b'),
    re.compile(r'rwxrwxrwx'),
    re.compile(r'rw-rw-rw-'),
    re.compile(r'os\.chmod\s*\(.*0o?777'),
    re.compile(r'os\.chmod\s*\(.*0o?666'),
    re.compile(r'stat\.S_IRWXU\s*\|\s*stat\.S_IRWXG\s*\|\s*stat\.S_IRWXO'),
]


# ---------------------------------------------------------------------------
# IngestionReport
# ---------------------------------------------------------------------------

@dataclass
class IngestionReport:
    """Result of an IngestionGate check on a code file.

    Consumers should check ``approved`` to decide whether the file may
    be written / committed.

    Attributes
    ----------
    file_path : str
        Path (or logical name) of the file checked.
    violations : list[tuple[IngestionViolation, int, str]]
        All detected violations: ``(violation, line_number, description)``.
    blocking_violations : list[IngestionViolation]
        Subset of violations that cause rejection.
    warnings : list[tuple[IngestionViolation, int, str]]
        Non-blocking violations.
    approved : bool
        ``True`` if the file passed the gate.
    quality_score : float
        Quality score in ``[0, 1]`` (higher is better).
    security_score : float
        Security score in ``[0, 1]`` (higher is better).
    signed_hash : str
        If approved, HMAC-SHA256 signature of the file hash.
        Empty string if not approved.
    timestamp : float
        Unix epoch timestamp of the check.
    """

    file_path: str
    violations: list[tuple[IngestionViolation, int, str]]
    blocking_violations: list[IngestionViolation]
    warnings: list[tuple[IngestionViolation, int, str]]
    approved: bool
    quality_score: float
    security_score: float
    signed_hash: str
    timestamp: float


# ---------------------------------------------------------------------------
# IngestionGate
# ---------------------------------------------------------------------------

class IngestionGate:
    """Security gate for ALL code entering the Orchestra codebase.

    When Orchestra generates new code (via CodingTeam, codebase agent,
    or direct AI generation), it MUST pass through IngestionGate before
    being written to disk.  When a human writes code and stages it for
    commit, IngestionGate can be invoked to validate.

    Parameters
    ----------
    audit : AuditLedger | None
        Optional audit ledger for recording gate decisions.
    strict : bool
        When ``True``, blocking violations always reject.
        When ``False``, only ``SECRET_HARDCODED`` blocks.
    security_critical_paths : list[str] | None
        Path prefixes for security-critical files (extra scrutiny).
    config : SecurityConfig | None
        Security configuration.  Falls back to global ``SECURITY_CONFIG``.
    """

    def __init__(
        self,
        audit: Any | None = None,
        strict: bool = True,
        security_critical_paths: list[str] | None = None,
        config: SecurityConfig | None = None,
    ) -> None:
        self._audit = audit
        self._strict = strict
        self._config = config or SECURITY_CONFIG
        self._security_critical_paths = (
            security_critical_paths
            or list(self._config.security_critical_paths)
        )

        # Statistics
        self._check_count = 0
        self._reject_count = 0
        self._rejection_log: list[IngestionReport] = []
        self._stats_lock = asyncio.Lock()

        log.info(
            "IngestionGate initialised (strict=%s, critical_paths=%d)",
            self._strict, len(self._security_critical_paths),
        )

    # ===================================================================
    # Core gate
    # ===================================================================

    async def check(
        self,
        code: str,
        file_path: str,
        agent_id: str = "human",
    ) -> IngestionReport:
        """Check code against all ingestion rules.

        Parameters
        ----------
        code : str
            Source code to check.
        file_path : str
            Logical file path (used for security-critical detection).
        agent_id : str
            Identifier of the agent/human submitting the code.

        Returns
        -------
        IngestionReport
            Full report with violations, scores, and approval status.
        """
        if not self._config.ingestion_gate_enabled:
            return self._make_pass_report(code, file_path)

        violations: list[tuple[IngestionViolation, int, str]] = []
        is_security_critical = self._is_security_critical(file_path)
        is_python = file_path.endswith(".py") or self._looks_like_python(code)

        # --- Secret scan ---
        violations.extend(self._scan_secrets(code))

        # --- IP scan ---
        violations.extend(self._scan_hardcoded_ips(code))

        # --- SQL injection scan ---
        violations.extend(self._scan_sql_injection(code))

        # --- Shell injection scan ---
        violations.extend(self._scan_shell_injection(code))

        # --- Broad permissions scan ---
        violations.extend(self._scan_broad_permissions(code))

        # --- Python-specific checks ---
        if is_python:
            violations.extend(self._scan_print_usage(code))
            violations.extend(self._scan_bare_except(code))
            violations.extend(self._scan_mutable_defaults(code))
            violations.extend(self._scan_type_hints(code))
            violations.extend(self._scan_docstrings(code))
            violations.extend(self._scan_route_handlers(code))
            violations.extend(self._scan_gpl_imports(code))

        # --- Security-critical specific checks ---
        if is_security_critical:
            violations.extend(self._scan_todos_in_security(code))

        # --- Separate blocking vs warnings ---
        blocking: list[IngestionViolation] = []
        warnings: list[tuple[IngestionViolation, int, str]] = []

        for v, line, desc in violations:
            if v in _BLOCKING_VIOLATIONS:
                blocking.append(v)
            else:
                warnings.append((v, line, desc))

        # Deduplicate blocking
        blocking = list(dict.fromkeys(blocking))

        # Calculate scores
        quality_score = self._calculate_quality_score(violations)
        security_score = self._calculate_security_score(violations)

        # Determine approval
        approved = len(blocking) == 0
        if approved and security_score < self._config.min_security_score:
            approved = False

        # Sign if approved
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        signed_hash = self._sign(code_hash, file_path) if approved else ""

        ts = time.time()

        report = IngestionReport(
            file_path=file_path,
            violations=violations,
            blocking_violations=blocking,
            warnings=warnings,
            approved=approved,
            quality_score=quality_score,
            security_score=security_score,
            signed_hash=signed_hash,
            timestamp=ts,
        )

        # Update stats
        async with self._stats_lock:
            self._check_count += 1
            if not approved:
                self._reject_count += 1
                self._rejection_log.append(report)

        # Audit logging
        if self._audit and self._config.audit_ingestion_checks:
            try:
                await self._audit.record(
                    agent_id=agent_id,
                    event_type="ingestion_check",
                    resource=file_path,
                    action="check",
                    result="approved" if approved else "rejected",
                    metadata={
                        "violations": [(v.value, ln, d) for v, ln, d in violations],
                        "blocking": [v.value for v in blocking],
                        "quality_score": quality_score,
                        "security_score": security_score,
                        "security_critical": is_security_critical,
                    },
                )
            except Exception:
                log.exception("Failed to write audit record for ingestion check")

        return report

    async def check_file(
        self,
        path: str,
        agent_id: str = "human",
    ) -> IngestionReport:
        """Check a file on disk.

        Parameters
        ----------
        path : str
            File system path to read and check.
        agent_id : str
            Agent/human identifier.

        Returns
        -------
        IngestionReport
            Full report.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        code = p.read_text(encoding="utf-8", errors="replace")
        return await self.check(code, str(p), agent_id)

    async def check_diff(
        self,
        diff: str,
        agent_id: str = "human",
    ) -> list[IngestionReport]:
        """Check a unified diff for violations.

        Extracts added lines from the diff and checks each modified file.

        Parameters
        ----------
        diff : str
            Unified diff text.
        agent_id : str
            Agent/human identifier.

        Returns
        -------
        list[IngestionReport]
            One report per file in the diff.
        """
        reports: list[IngestionReport] = []
        current_file: str | None = None
        added_lines: list[str] = []

        for line in diff.split("\n"):
            if line.startswith("+++ b/"):
                # Flush previous file
                if current_file and added_lines:
                    code = "\n".join(added_lines)
                    report = await self.check(code, current_file, agent_id)
                    reports.append(report)
                current_file = line[6:]  # strip "+++ b/"
                added_lines = []
            elif line.startswith("+") and not line.startswith("+++"):
                added_lines.append(line[1:])  # strip leading +

        # Flush last file
        if current_file and added_lines:
            code = "\n".join(added_lines)
            report = await self.check(code, current_file, agent_id)
            reports.append(report)

        return reports

    # ===================================================================
    # Batch
    # ===================================================================

    async def check_directory(
        self,
        path: str,
    ) -> list[IngestionReport]:
        """Recursively check all Python files in a directory.

        Parameters
        ----------
        path : str
            Directory path to scan.

        Returns
        -------
        list[IngestionReport]
            One report per ``.py`` file.
        """
        reports: list[IngestionReport] = []
        root = Path(path)

        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        py_files = sorted(root.rglob("*.py"))
        for py_file in py_files:
            try:
                report = await self.check_file(str(py_file))
                reports.append(report)
            except Exception as exc:
                log.warning("Failed to check %s: %s", py_file, exc)

        return reports

    # ===================================================================
    # Integration helper
    # ===================================================================

    async def approve_and_sign(
        self,
        code: str,
        file_path: str,
        agent_id: str,
    ) -> tuple[bool, IngestionReport]:
        """Check code and return approval status + report.

        This is the primary integration point for code editors and
        writing pipelines.

        Parameters
        ----------
        code : str
            Source code.
        file_path : str
            Target file path.
        agent_id : str
            Agent identifier.

        Returns
        -------
        tuple[bool, IngestionReport]
            ``(True, report)`` if approved; ``(False, report)`` if rejected.
        """
        report = await self.check(code, file_path, agent_id)
        return report.approved, report

    # ===================================================================
    # Quick checks (fast path for CI)
    # ===================================================================

    def quick_secret_check(self, code: str) -> bool:
        """Fast check: does the code contain hardcoded secrets?

        Cost: <1 ms.  Suitable for CI pipelines.

        Parameters
        ----------
        code : str
            Source code.

        Returns
        -------
        bool
            ``True`` if secrets are detected (i.e. the code is *unsafe*).
        """
        for pattern, _ in _COMPILED_SECRET_PATTERNS:
            if pattern.search(code):
                return True
        return False

    def quick_sql_check(self, code: str) -> bool:
        """Fast check: does the code contain SQL injection risks?

        Cost: <1 ms.  Suitable for CI pipelines.

        Parameters
        ----------
        code : str
            Source code.

        Returns
        -------
        bool
            ``True`` if SQL injection risk is detected.
        """
        for pattern in _SQL_FSTRING_PATTERNS:
            if pattern.search(code):
                return True
        return False

    # ===================================================================
    # Individual scan methods
    # ===================================================================

    def _scan_secrets(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for hardcoded secrets in source code.

        Checks each line individually to report accurate line numbers.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
            Violations with line numbers and descriptions.
        """
        violations: list[tuple[IngestionViolation, int, str]] = []
        lines = code.split("\n")

        for line_num, line in enumerate(lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            for pattern, description in _COMPILED_SECRET_PATTERNS:
                if pattern.search(line):
                    violations.append((
                        IngestionViolation.SECRET_HARDCODED,
                        line_num,
                        f"{description} detected on line {line_num}",
                    ))
                    break  # One match per line is enough

        return violations

    def _scan_hardcoded_ips(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for hardcoded IP addresses.

        Allows safe IPs (localhost, broadcast, etc.).

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []
        lines = code.split("\n")

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            for match in _IP_PATTERN.finditer(line):
                ip = match.group()
                if ip not in _SAFE_IPS:
                    violations.append((
                        IngestionViolation.HARDCODED_IP,
                        line_num,
                        f"Hardcoded IP address {ip} on line {line_num}",
                    ))
                    break  # One per line

        return violations

    def _scan_sql_injection(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for SQL injection vulnerabilities (f-strings in SQL).

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []
        lines = code.split("\n")

        for line_num, line in enumerate(lines, 1):
            for pattern in _SQL_FSTRING_PATTERNS:
                if pattern.search(line):
                    violations.append((
                        IngestionViolation.SQL_FSTRING,
                        line_num,
                        f"SQL injection risk (dynamic SQL) on line {line_num}",
                    ))
                    break

        return violations

    def _scan_shell_injection(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for shell injection risks.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []
        lines = code.split("\n")

        for line_num, line in enumerate(lines, 1):
            for pattern in _SHELL_PATTERNS:
                if pattern.search(line):
                    violations.append((
                        IngestionViolation.SHELL_INJECTION_RISK,
                        line_num,
                        f"Shell injection risk on line {line_num}",
                    ))
                    break

        return violations

    def _scan_broad_permissions(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for overly broad file permissions.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []
        lines = code.split("\n")

        for line_num, line in enumerate(lines, 1):
            for pattern in _BROAD_PERM_PATTERNS:
                if pattern.search(line):
                    violations.append((
                        IngestionViolation.BROAD_PERMISSIONS,
                        line_num,
                        f"Overly broad file permissions on line {line_num}",
                    ))
                    break

        return violations

    def _scan_print_usage(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for ``print()`` usage (should use logging).

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []
        lines = code.split("\n")
        print_re = re.compile(r'^\s*print\s*\(')

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if print_re.match(line):
                violations.append((
                    IngestionViolation.PRINT_IN_PROD,
                    line_num,
                    f"print() on line {line_num} — use logging instead",
                ))

        return violations

    def _scan_bare_except(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for bare ``except:`` or ``except Exception: pass``.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []
        lines = code.split("\n")

        bare_except_re = re.compile(r'^\s*except\s*:\s*$')
        except_pass_re = re.compile(r'^\s*except\s+\w*\s*:\s*$')

        for line_num, line in enumerate(lines, 1):
            if bare_except_re.match(line):
                violations.append((
                    IngestionViolation.BARE_EXCEPT,
                    line_num,
                    f"Bare except on line {line_num}",
                ))
            elif except_pass_re.match(line):
                # Check if next non-empty line is just "pass"
                for next_line in lines[line_num:]:
                    stripped_next = next_line.strip()
                    if stripped_next == "":
                        continue
                    if stripped_next == "pass":
                        violations.append((
                            IngestionViolation.BARE_EXCEPT,
                            line_num,
                            f"except with bare pass on line {line_num}",
                        ))
                    break

        return violations

    def _scan_mutable_defaults(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for mutable default arguments.

        Detects ``def f(x=[]):`` and ``def f(x={}):`` anti-patterns.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return violations

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults + node.args.kw_defaults:
                    if default is None:
                        continue
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        violations.append((
                            IngestionViolation.MUTABLE_DEFAULT,
                            getattr(node, "lineno", 0),
                            f"Mutable default argument in {node.name}() "
                            f"on line {getattr(node, 'lineno', '?')}",
                        ))

        return violations

    def _scan_type_hints(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for missing type hints on public functions.

        Only reports if ``require_type_hints`` is enabled in config.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        if not self._config.require_type_hints:
            return []

        violations: list[tuple[IngestionViolation, int, str]] = []

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return violations

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip private functions
                if node.name.startswith("_"):
                    continue
                # Check return annotation
                if node.returns is None:
                    violations.append((
                        IngestionViolation.MISSING_TYPE_HINTS,
                        node.lineno,
                        f"Missing return type hint for {node.name}() "
                        f"on line {node.lineno}",
                    ))
                # Check argument annotations
                for arg in node.args.args:
                    if arg.arg == "self" or arg.arg == "cls":
                        continue
                    if arg.annotation is None:
                        violations.append((
                            IngestionViolation.MISSING_TYPE_HINTS,
                            node.lineno,
                            f"Missing type hint for parameter '{arg.arg}' "
                            f"in {node.name}() on line {node.lineno}",
                        ))

        return violations

    def _scan_docstrings(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for missing docstrings on public classes and functions.

        Only reports if ``require_docstrings`` is enabled in config.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        if not self._config.require_docstrings:
            return []

        violations: list[tuple[IngestionViolation, int, str]] = []

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return violations

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Skip private
                if node.name.startswith("_"):
                    continue
                if not (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    violations.append((
                        IngestionViolation.MISSING_DOCSTRING,
                        node.lineno,
                        f"Missing docstring for {node.name} on line {node.lineno}",
                    ))

        return violations

    def _scan_route_handlers(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan route handlers for missing auth and unvalidated input.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []
        lines = code.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i]
            is_route = any(p.search(line) for p in _ROUTE_DECORATORS)

            if is_route:
                # Collect the function block (decorator + function + body)
                block_start = i
                block_end = i + 1
                # Find the function def
                while block_end < len(lines) and not lines[block_end].strip().startswith("def ") and not lines[block_end].strip().startswith("async def "):
                    block_end += 1
                # Include some body lines
                if block_end < len(lines):
                    indent_level = len(lines[block_end]) - len(lines[block_end].lstrip())
                    block_end += 1
                    while block_end < len(lines):
                        stripped = lines[block_end].strip()
                        if stripped and not stripped.startswith("#"):
                            curr_indent = len(lines[block_end]) - len(lines[block_end].lstrip())
                            if curr_indent <= indent_level:
                                break
                        block_end += 1

                block = "\n".join(lines[block_start:min(block_end, len(lines))])

                # Check for auth
                has_auth = any(p.search(block) for p in _AUTH_PATTERNS)
                if not has_auth:
                    func_line = block_start + 1
                    for j in range(block_start, min(block_end, len(lines))):
                        if "def " in lines[j]:
                            func_line = j + 1
                            break
                    violations.append((
                        IngestionViolation.MISSING_AUTH_CHECK,
                        func_line,
                        f"Route handler without auth check near line {func_line}",
                    ))

                # Check for input validation
                has_validation = any(p.search(block) for p in _INPUT_VALIDATION_PATTERNS)
                uses_request_body = bool(re.search(
                    r'request\.(json|data|body|form|get_json|content)',
                    block, re.IGNORECASE,
                ))
                if uses_request_body and not has_validation:
                    func_line = block_start + 1
                    for j in range(block_start, min(block_end, len(lines))):
                        if "def " in lines[j]:
                            func_line = j + 1
                            break
                    violations.append((
                        IngestionViolation.UNVALIDATED_INPUT,
                        func_line,
                        f"Route handler uses raw request body without validation near line {func_line}",
                    ))

                i = block_end
            else:
                i += 1

        return violations

    def _scan_gpl_imports(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for imports of GPL-licensed packages.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return violations

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod in _GPL_PACKAGES:
                        violations.append((
                            IngestionViolation.GPL_LICENSE_RISK,
                            node.lineno,
                            f"GPL-licensed package '{mod}' imported on line {node.lineno}",
                        ))
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split(".")[0]
                if mod in _GPL_PACKAGES:
                    violations.append((
                        IngestionViolation.GPL_LICENSE_RISK,
                        node.lineno,
                        f"GPL-licensed package '{mod}' imported on line {node.lineno}",
                    ))

        return violations

    def _scan_todos_in_security(
        self, code: str,
    ) -> list[tuple[IngestionViolation, int, str]]:
        """Scan for TODO/FIXME/HACK in security-critical code.

        Returns
        -------
        list[tuple[IngestionViolation, int, str]]
        """
        violations: list[tuple[IngestionViolation, int, str]] = []
        todo_re = re.compile(r'\b(TODO|FIXME|HACK|XXX|TEMP)\b', re.IGNORECASE)
        lines = code.split("\n")

        for line_num, line in enumerate(lines, 1):
            if todo_re.search(line):
                violations.append((
                    IngestionViolation.TODO_IN_SECURITY,
                    line_num,
                    f"TODO/FIXME in security-critical code on line {line_num}",
                ))

        return violations

    # ===================================================================
    # Score calculations
    # ===================================================================

    def _calculate_quality_score(
        self,
        violations: list[tuple[IngestionViolation, int, str]],
    ) -> float:
        """Calculate quality score from violations.

        Starts at 1.0 and decreases based on violation weights.

        Parameters
        ----------
        violations : list
            Detected violations.

        Returns
        -------
        float
            Quality score in ``[0.0, 1.0]``.
        """
        if not violations:
            return 1.0

        total_penalty = sum(
            _VIOLATION_QUALITY_WEIGHT.get(v, 0.1)
            for v, _, _ in violations
        )
        return max(0.0, 1.0 - total_penalty)

    def _calculate_security_score(
        self,
        violations: list[tuple[IngestionViolation, int, str]],
    ) -> float:
        """Calculate security score from violations.

        Starts at 1.0 and decreases based on security weights.

        Parameters
        ----------
        violations : list
            Detected violations.

        Returns
        -------
        float
            Security score in ``[0.0, 1.0]``.
        """
        if not violations:
            return 1.0

        total_penalty = sum(
            _VIOLATION_SECURITY_WEIGHT.get(v, 0.05)
            for v, _, _ in violations
        )
        return max(0.0, 1.0 - total_penalty)

    # ===================================================================
    # Helpers
    # ===================================================================

    def _is_security_critical(self, file_path: str) -> bool:
        """Check if a file path is in a security-critical directory.

        Parameters
        ----------
        file_path : str
            File path to check.

        Returns
        -------
        bool
        """
        normalised = file_path.replace("\\", "/")
        return any(
            normalised.startswith(p) or f"/{p}" in normalised
            for p in self._security_critical_paths
        )

    def _looks_like_python(self, code: str) -> bool:
        """Heuristic: does this code look like Python?

        Parameters
        ----------
        code : str
            Source code.

        Returns
        -------
        bool
        """
        python_indicators = [
            r'^\s*def\s+\w+\s*\(',
            r'^\s*class\s+\w+',
            r'^\s*import\s+\w+',
            r'^\s*from\s+\w+\s+import',
            r'^\s*if\s+__name__\s*==',
            r'^\s*async\s+def\s+',
        ]
        for pattern in python_indicators:
            if re.search(pattern, code, re.MULTILINE):
                return True
        return False

    def _sign(self, code_hash: str, file_path: str) -> str:
        """Generate HMAC-SHA256 signature for an approved file.

        Parameters
        ----------
        code_hash : str
            SHA-256 of the code.
        file_path : str
            File path.

        Returns
        -------
        str
            Hex-encoded HMAC-SHA256 signature.
        """
        msg = f"{code_hash}:{file_path}:{time.time()}".encode("utf-8")
        secret = self._config.get_hmac_secret()
        return hmac.new(secret, msg, hashlib.sha256).hexdigest()

    def _make_pass_report(self, code: str, file_path: str) -> IngestionReport:
        """Create a pass-through report when the gate is disabled.

        Parameters
        ----------
        code : str
            Source code.
        file_path : str
            File path.

        Returns
        -------
        IngestionReport
            Always-approved report.
        """
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        return IngestionReport(
            file_path=file_path,
            violations=[],
            blocking_violations=[],
            warnings=[],
            approved=True,
            quality_score=1.0,
            security_score=1.0,
            signed_hash=self._sign(code_hash, file_path),
            timestamp=time.time(),
        )

    # ===================================================================
    # Statistics
    # ===================================================================

    def get_gate_stats(self) -> dict[str, Any]:
        """Return gate statistics.

        Returns
        -------
        dict
            Keys: ``check_count``, ``reject_count``, ``reject_rate``.
        """
        return {
            "check_count": self._check_count,
            "reject_count": self._reject_count,
            "reject_rate": (
                self._reject_count / self._check_count
                if self._check_count > 0
                else 0.0
            ),
        }

    def get_rejection_log(self) -> list[IngestionReport]:
        """Return all rejected reports.

        Returns
        -------
        list[IngestionReport]
            Rejected reports, most recent first.
        """
        return list(reversed(self._rejection_log))

    # ===================================================================
    # Repr
    # ===================================================================

    def __repr__(self) -> str:
        return (
            f"IngestionGate(strict={self._strict}, "
            f"checks={self._check_count}, "
            f"rejects={self._reject_count})"
        )
