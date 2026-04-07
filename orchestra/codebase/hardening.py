"""Horizon Orchestra — Code Hardening.

Makes generated code bulletproof before execution or delivery.

Components:
  :class:`CodeValidator`      — full static analysis (syntax, imports,
                                 undefined names, security, type hints)
  :class:`TestCoverageAnalyzer` — pytest + coverage integration
  :class:`CodeQualityGate`    — pass/fail threshold checks + reporting
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import logging
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..router import ModelRouter

__all__ = [
    "CodeValidator",
    "TestCoverageAnalyzer",
    "CodeQualityGate",
    "ValidationReport",
    "CoverageReport",
]

log = logging.getLogger("orchestra.codebase.hardening")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    """Full static-analysis report for a code snippet or file."""

    valid: bool
    language: str
    syntax_errors: list[str] = field(default_factory=list)
    import_issues: list[str] = field(default_factory=list)
    undefined_names: list[str] = field(default_factory=list)
    security_issues: list[dict[str, str]] = field(default_factory=list)   # [{pattern, line, severity}]
    type_hint_coverage: float = 0.0     # 0.0 – 1.0
    docstring_coverage: float = 0.0     # 0.0 – 1.0
    complexity: dict[str, Any] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class CoverageReport:
    """pytest-cov output summary."""

    total_statements: int
    covered: int
    missed: int
    coverage_pct: float
    uncovered_lines: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Security scan patterns
# ---------------------------------------------------------------------------

_SECURITY_PATTERNS: list[dict[str, Any]] = [
    {
        "pattern": r"\beval\s*\(",
        "message": "Use of eval() — arbitrary code execution risk",
        "severity": "high",
    },
    {
        "pattern": r"\bexec\s*\(",
        "message": "Use of exec() — arbitrary code execution risk",
        "severity": "high",
    },
    {
        "pattern": r"subprocess\.[a-zA-Z_]+\(.*shell\s*=\s*True",
        "message": "subprocess with shell=True — command injection risk",
        "severity": "high",
    },
    {
        "pattern": r"\bpickle\.loads?\s*\(",
        "message": "pickle.load/loads — deserialisation of untrusted data risk",
        "severity": "high",
    },
    {
        "pattern": r"\b__import__\s*\(",
        "message": "Dynamic __import__() — potential code injection",
        "severity": "medium",
    },
    {
        "pattern": r"\bos\.system\s*\(",
        "message": "os.system() — prefer subprocess with shell=False",
        "severity": "medium",
    },
    {
        "pattern": r"\binput\s*\(",
        "message": "input() in non-interactive code — potential injection vector",
        "severity": "low",
    },
    {
        "pattern": r"hashlib\.(md5|sha1)\s*\(",
        "message": "Use of weak hash (MD5/SHA-1) — prefer SHA-256+",
        "severity": "low",
    },
    {
        "pattern": r"open\(.*[\"']w[\"'].*\)",
        "message": "File write — ensure path is validated/sanitised",
        "severity": "info",
    },
    {
        "pattern": r"\bsqlite3\b.*execute\s*\(.*%",
        "message": "Possible SQL injection via string formatting",
        "severity": "high",
    },
    {
        "pattern": r"yaml\.load\s*\([^)]*\)",
        "message": "yaml.load() without Loader — use yaml.safe_load()",
        "severity": "high",
    },
    {
        "pattern": r"\bctypes\b",
        "message": "ctypes usage — low-level memory access, review carefully",
        "severity": "medium",
    },
]


# ---------------------------------------------------------------------------
# AST Scope Analyser
# ---------------------------------------------------------------------------

class _ScopeAnalyser(ast.NodeVisitor):
    """Basic undefined-name detector via scope tracking."""

    # Names that are always available (builtins)
    _BUILTINS: frozenset[str] = frozenset(dir(__builtins__) if isinstance(__builtins__, dict) else dir(__builtins__))  # type: ignore[arg-type]

    def __init__(self) -> None:
        # Global scope bindings (names that are defined)
        self._scopes: list[set[str]] = [set()]
        self._undefined: list[str] = []
        # Module-level names that come from imports (collect first pass)
        self._imports: set[str] = set()

    # Scope helpers
    def _push_scope(self) -> None:
        self._scopes.append(set())

    def _pop_scope(self) -> None:
        if len(self._scopes) > 1:
            self._scopes.pop()

    def _define(self, name: str) -> None:
        if self._scopes:
            self._scopes[-1].add(name)

    def _is_defined(self, name: str) -> bool:
        if name in self._BUILTINS:
            return True
        if name in self._imports:
            return True
        # Walk scopes from innermost to outermost
        for scope in reversed(self._scopes):
            if name in scope:
                return True
        # Common type annotation names
        if name in ("Optional", "Union", "List", "Dict", "Tuple", "Set",
                    "Any", "Callable", "Type", "ClassVar", "Final",
                    "Literal", "TypeVar", "Generic", "Protocol",
                    "overload", "dataclass", "field"):
            return True
        return False

    # Visitor methods
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name.split(".")[0]
            self._define(name)
            self._imports.add(name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            if name != "*":
                self._define(name)
                self._imports.add(name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._define_from_target(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._define_from_target(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._define_from_target(node.target)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._define(node.target.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._define(node.name)
        self._push_scope()
        # Define arguments
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            self._define(arg.arg)
        if node.args.vararg:
            self._define(node.args.vararg.arg)
        if node.args.kwarg:
            self._define(node.args.kwarg.arg)
        self.generic_visit(node)
        self._pop_scope()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._define(node.name)
        self._push_scope()
        self.generic_visit(node)
        self._pop_scope()

    def visit_For(self, node: ast.For) -> None:
        self._define_from_target(node.target)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._define_from_target(node.target)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars:
                self._define_from_target(item.optional_vars)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars:
                self._define_from_target(item.optional_vars)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self._define(node.name)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._define_from_target(node.target)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and not self._is_defined(node.id):
            # Avoid duplicates
            if node.id not in self._undefined:
                self._undefined.append(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self._define(node.id)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        for name in node.names:
            self._define(name)
            if self._scopes:
                self._scopes[0].add(name)   # register in global scope too
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        for name in node.names:
            self._define(name)
        self.generic_visit(node)

    def _define_from_target(self, target: ast.expr) -> None:
        """Recursively extract names from assignment targets."""
        if isinstance(target, ast.Name):
            self._define(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._define_from_target(elt)
        elif isinstance(target, ast.Starred):
            self._define_from_target(target.value)

    @property
    def undefined(self) -> list[str]:
        return self._undefined


# ---------------------------------------------------------------------------
# CodeValidator
# ---------------------------------------------------------------------------

class CodeValidator:
    """Full static analysis for Python (and basic JS) code.

    Checks:
    - Syntax validity (AST parse)
    - Import resolution (stdlib + installed packages)
    - Undefined name detection
    - Type hint coverage
    - Docstring coverage
    - Security scan
    - Complexity metrics
    """

    def validate_python(self, code: str) -> ValidationReport:
        """Full Python validation.

        Args:
            code: Python source code string.

        Returns:
            :class:`ValidationReport` with all analysis results.
        """
        report = ValidationReport(valid=True, language="python")

        # ------------------------------------------------------------------
        # 1. Syntax check
        # ------------------------------------------------------------------
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            report.valid = False
            report.syntax_errors.append(
                f"SyntaxError at line {exc.lineno}: {exc.msg} — {exc.text!r}"
            )
            # Can't do further analysis without a valid AST
            report.suggestions.append("Fix syntax errors before running further checks.")
            return report

        # ------------------------------------------------------------------
        # 2. Import resolution
        # ------------------------------------------------------------------
        report.import_issues = self._check_imports(tree)

        # ------------------------------------------------------------------
        # 3. Undefined name detection
        # ------------------------------------------------------------------
        analyser = _ScopeAnalyser()
        try:
            analyser.visit(tree)
            # Filter out names that appear in type annotations only (strings)
            # and common false positives
            _FALSE_POSITIVES = {
                "__name__", "__file__", "__doc__", "__spec__", "__loader__",
                "__builtins__", "__package__", "__annotations__",
                "self", "cls", "_", "__",
            }
            report.undefined_names = [
                n for n in analyser.undefined
                if n not in _FALSE_POSITIVES
            ]
        except Exception as exc:
            log.debug("Scope analysis failed: %s", exc)

        # ------------------------------------------------------------------
        # 4. Security scan
        # ------------------------------------------------------------------
        lines = code.splitlines()
        for lineno, line in enumerate(lines, 1):
            for pattern_info in _SECURITY_PATTERNS:
                if re.search(pattern_info["pattern"], line):
                    report.security_issues.append({
                        "line": str(lineno),
                        "pattern": pattern_info["message"],
                        "severity": pattern_info["severity"],
                        "code": line.strip()[:120],
                    })

        # ------------------------------------------------------------------
        # 5. Type hint coverage
        # ------------------------------------------------------------------
        report.type_hint_coverage = self._calc_type_hint_coverage(tree)

        # ------------------------------------------------------------------
        # 6. Docstring coverage
        # ------------------------------------------------------------------
        report.docstring_coverage = self._calc_docstring_coverage(tree)

        # ------------------------------------------------------------------
        # 7. Complexity metrics
        # ------------------------------------------------------------------
        report.complexity = self._calc_complexity(code, tree)

        # ------------------------------------------------------------------
        # 8. Generate suggestions
        # ------------------------------------------------------------------
        report.suggestions = self._generate_suggestions(report)

        # Mark invalid if there are serious issues
        high_security = [s for s in report.security_issues if s.get("severity") == "high"]
        if high_security or report.syntax_errors or report.undefined_names:
            report.valid = False

        return report

    def validate_javascript(self, code: str) -> ValidationReport:
        """Basic JavaScript validation.

        Uses Node.js for syntax checking if available; otherwise applies
        regex-based heuristic checks.

        Args:
            code: JavaScript source code string.

        Returns:
            :class:`ValidationReport`.
        """
        report = ValidationReport(valid=True, language="javascript")

        # --- Try Node.js syntax check ---
        node_available = _command_available("node")
        if node_available:
            try:
                result = subprocess.run(
                    ["node", "--check", "/dev/stdin"],
                    input=code.encode(),
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    stderr = result.stderr.decode(errors="replace")
                    for line in stderr.splitlines():
                        if line.strip():
                            report.syntax_errors.append(line.strip())
                    report.valid = False
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                log.debug("Node.js check failed: %s", exc)

        # --- Regex heuristics ---
        lines = code.splitlines()
        brace_depth = 0
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            # Basic brace balance heuristic
            brace_depth += stripped.count("{") - stripped.count("}")
            # Detect eval usage
            if re.search(r"\beval\s*\(", stripped):
                report.security_issues.append({
                    "line": str(lineno),
                    "pattern": "Use of eval() — code injection risk",
                    "severity": "high",
                    "code": stripped[:120],
                })
            # Detect dangerouslySetInnerHTML
            if "dangerouslySetInnerHTML" in stripped:
                report.security_issues.append({
                    "line": str(lineno),
                    "pattern": "dangerouslySetInnerHTML — XSS risk",
                    "severity": "high",
                    "code": stripped[:120],
                })
            # Detect document.write
            if re.search(r"document\.write\s*\(", stripped):
                report.security_issues.append({
                    "line": str(lineno),
                    "pattern": "document.write() — XSS risk",
                    "severity": "medium",
                    "code": stripped[:120],
                })

        if brace_depth != 0:
            report.syntax_errors.append(
                f"Unbalanced braces: depth at EOF = {brace_depth}"
            )
            if not node_available:  # Only mark invalid if Node didn't already check
                report.valid = False

        high_issues = [s for s in report.security_issues if s.get("severity") == "high"]
        if high_issues:
            report.valid = False

        report.complexity = {
            "lines": len(lines),
            "functions": len(re.findall(r"\bfunction\b|\barrow\b|=>", code)),
        }
        report.suggestions = self._generate_suggestions(report)
        return report

    def validate_any(self, code: str, language: str) -> ValidationReport:
        """Route to the appropriate validator based on *language*.

        Supports: "python", "javascript", "js", "typescript", "ts".
        Falls back to a minimal report for unknown languages.
        """
        lang = language.lower().strip()
        if lang == "python":
            return self.validate_python(code)
        if lang in ("javascript", "js", "typescript", "ts"):
            return self.validate_javascript(code)

        # Unknown language: minimal report
        report = ValidationReport(valid=True, language=lang)
        report.suggestions.append(
            f"Language {lang!r} is not supported for deep analysis. "
            "Consider using 'python' or 'javascript'."
        )
        return report

    # ------------------------------------------------------------------
    # Analysis helpers
    # ------------------------------------------------------------------

    def _check_imports(self, tree: ast.Module) -> list[str]:
        """Check that imported modules exist (stdlib or installed)."""
        issues: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if not _module_exists(module_name):
                        issues.append(f"Unresolved import: '{alias.name}'")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.split(".")[0]
                    if node.level == 0 and not _module_exists(module_name):
                        issues.append(f"Unresolved import: 'from {node.module} import ...'")
        return issues

    def _calc_type_hint_coverage(self, tree: ast.Module) -> float:
        """Return fraction of functions that have return + argument annotations."""
        total = 0
        annotated = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                # Count as annotated if return annotation OR ≥50% of args annotated
                has_return = node.returns is not None
                all_args = node.args.args + node.args.posonlyargs + node.args.kwonlyargs
                # Exclude 'self' / 'cls'
                all_args = [a for a in all_args if a.arg not in ("self", "cls")]
                n_args = len(all_args)
                n_annotated_args = sum(1 for a in all_args if a.annotation is not None)
                if has_return or (n_args > 0 and n_annotated_args / n_args >= 0.5):
                    annotated += 1
        return annotated / total if total else 1.0

    def _calc_docstring_coverage(self, tree: ast.Module) -> float:
        """Return fraction of public functions/classes with docstrings."""
        total = 0
        with_doc = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Skip private names
                if node.name.startswith("_"):
                    continue
                total += 1
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    with_doc += 1
        return with_doc / total if total else 1.0

    def _calc_complexity(self, code: str, tree: ast.Module) -> dict[str, Any]:
        """Estimate code complexity metrics."""
        lines = code.splitlines()
        non_blank_lines = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))

        functions = sum(
            1 for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))

        # Cyclomatic complexity approximation: count branches
        branches = sum(
            1 for n in ast.walk(tree)
            if isinstance(n, (
                ast.If, ast.For, ast.While, ast.ExceptHandler,
                ast.With, ast.Assert, ast.comprehension,
            ))
        )

        # Max nesting depth
        max_depth = _calc_max_nesting(tree)

        return {
            "lines_total": len(lines),
            "lines_code": non_blank_lines,
            "functions": functions,
            "classes": classes,
            "branches": branches,
            "max_nesting_depth": max_depth,
            "cyclomatic_complexity_approx": branches + 1,
        }

    def _generate_suggestions(self, report: ValidationReport) -> list[str]:
        """Generate human-readable improvement suggestions from the report."""
        suggestions: list[str] = []

        if report.syntax_errors:
            suggestions.append(f"Fix {len(report.syntax_errors)} syntax error(s) first.")

        if report.import_issues:
            suggestions.append(
                f"{len(report.import_issues)} unresolved import(s). "
                "Add missing packages to requirements.txt or check spelling."
            )

        if report.undefined_names:
            names = ", ".join(report.undefined_names[:5])
            suggestions.append(
                f"Potentially undefined names: {names}. "
                "Check for typos or missing imports."
            )

        high_sec = [s for s in report.security_issues if s.get("severity") == "high"]
        if high_sec:
            suggestions.append(
                f"{len(high_sec)} HIGH-severity security issue(s) detected. "
                "Review and remediate before deploying."
            )

        if report.type_hint_coverage < 0.5:
            suggestions.append(
                f"Type hint coverage is {report.type_hint_coverage:.0%}. "
                "Add type annotations to improve IDE support and catch bugs early."
            )

        if report.docstring_coverage < 0.5:
            suggestions.append(
                f"Docstring coverage is {report.docstring_coverage:.0%}. "
                "Add docstrings to public functions and classes."
            )

        depth = report.complexity.get("max_nesting_depth", 0)
        if isinstance(depth, int) and depth > 5:
            suggestions.append(
                f"Max nesting depth is {depth}. "
                "Consider refactoring deeply nested logic into helper functions."
            )

        return suggestions


# ---------------------------------------------------------------------------
# TestCoverageAnalyzer
# ---------------------------------------------------------------------------

class TestCoverageAnalyzer:
    """Run pytest with coverage and analyse the results.

    Requires pytest and pytest-cov to be installed.
    """

    def __init__(self, router: ModelRouter | None = None) -> None:
        self.router = router

    async def analyze(
        self,
        source_file: str,
        test_file: str,
    ) -> CoverageReport:
        """Run pytest --cov on *source_file* with *test_file* and return a report.

        Args:
            source_file: Path to the module under test.
            test_file: Path to the pytest test file.

        Returns:
            :class:`CoverageReport` parsed from pytest-cov output.
        """
        source_path = Path(source_file)
        test_path = Path(test_file)

        if not source_path.exists():
            log.error("Source file not found: %s", source_file)
            return CoverageReport(total_statements=0, covered=0, missed=0, coverage_pct=0.0)

        if not test_path.exists():
            log.error("Test file not found: %s", test_file)
            return CoverageReport(total_statements=0, covered=0, missed=0, coverage_pct=0.0)

        module_name = source_path.stem
        cmd = [
            sys.executable, "-m", "pytest",
            str(test_path),
            f"--cov={module_name}",
            "--cov-report=term-missing",
            "--tb=short",
            "-q",
        ]

        log.info("analyze() running pytest coverage: %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(source_path.parent),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            log.error("pytest timed out after 120 seconds")
            return CoverageReport(total_statements=0, covered=0, missed=0, coverage_pct=0.0)
        except Exception as exc:
            log.error("pytest failed: %s", exc)
            return CoverageReport(total_statements=0, covered=0, missed=0, coverage_pct=0.0)

        output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        return _parse_coverage_output(output, module_name)

    async def suggest_missing_tests(
        self,
        source_file: str,
        test_file: str,
    ) -> list[str]:
        """Use LLM to suggest uncovered test cases.

        Reads the source and existing test files, asks the LLM to identify
        untested paths, edge cases, and missing scenarios.

        Args:
            source_file: Path to the module under test.
            test_file: Path to the existing test file (may not exist yet).

        Returns:
            List of suggested test case descriptions.
        """
        if not self.router:
            return ["[No router configured — cannot generate test suggestions]"]

        source_path = Path(source_file)
        test_path = Path(test_file)

        source_code = source_path.read_text(encoding="utf-8") if source_path.exists() else "[File not found]"
        test_code = test_path.read_text(encoding="utf-8") if test_path.exists() else "[No tests yet]"

        # Truncate for context window
        source_code = source_code[:6000]
        test_code = test_code[:4000]

        prompt = (
            f"You are a senior Python test engineer. Analyse the source code and "
            f"existing tests below. Identify missing test cases covering:\n"
            f"1. Uncovered code paths (branches, edge cases)\n"
            f"2. Error/exception handling paths\n"
            f"3. Boundary conditions\n"
            f"4. Async behaviour (if applicable)\n"
            f"5. Integration points\n\n"
            f"Output a numbered list of specific test case descriptions. "
            f"Be concrete: describe exactly what to test and what the expected behaviour is.\n\n"
            f"=== SOURCE: {source_file} ===\n{source_code}\n\n"
            f"=== EXISTING TESTS: {test_file} ===\n{test_code}\n\n"
            f"Missing test cases:"
        )

        model_name = self.router.route("coding")
        client, model_id = self.router.get_client(model_name)

        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )
            text = resp.choices[0].message.content or ""
            # Parse numbered list
            suggestions: list[str] = []
            for line in text.strip().splitlines():
                line = line.strip()
                if line and re.match(r"^\d+\.", line):
                    suggestions.append(re.sub(r"^\d+\.\s*", "", line))
                elif line and suggestions:
                    # Continuation of previous item
                    suggestions[-1] += " " + line
            return suggestions if suggestions else [text.strip()]

        except Exception as exc:
            log.error("LLM test suggestion failed: %s", exc)
            return [f"[LLM error: {exc}]"]


# ---------------------------------------------------------------------------
# CodeQualityGate
# ---------------------------------------------------------------------------

class CodeQualityGate:
    """Pass/fail quality thresholds for code validation reports.

    Thresholds (configurable):
    - No syntax errors
    - No HIGH-severity security issues
    - Type hint coverage >= 50%
    - No undefined names
    """

    def __init__(
        self,
        min_type_hint_coverage: float = 0.5,
        allow_undefined_names: bool = False,
        allow_security_medium: bool = True,
        allow_security_low: bool = True,
    ) -> None:
        self.min_type_hint_coverage = min_type_hint_coverage
        self.allow_undefined_names = allow_undefined_names
        self.allow_security_medium = allow_security_medium
        self.allow_security_low = allow_security_low

    def check(self, report: ValidationReport) -> bool:
        """Return True if *report* passes all quality thresholds.

        Failing conditions:
        - Any syntax errors
        - Any HIGH-severity security issues
        - Type hint coverage < ``self.min_type_hint_coverage``
        - Undefined names (unless ``allow_undefined_names=True``)
        """
        if report.syntax_errors:
            return False

        high_issues = [s for s in report.security_issues if s.get("severity") == "high"]
        if high_issues:
            return False

        if not self.allow_security_medium:
            medium_issues = [s for s in report.security_issues if s.get("severity") == "medium"]
            if medium_issues:
                return False

        if report.type_hint_coverage < self.min_type_hint_coverage:
            return False

        if not self.allow_undefined_names and report.undefined_names:
            return False

        return True

    def format_report(self, report: ValidationReport) -> str:
        """Return a human-readable summary of the validation report."""
        passed = self.check(report)
        status = "✓ PASSED" if passed else "✗ FAILED"
        lines: list[str] = [
            f"Code Quality Report [{report.language.upper()}] — {status}",
            "=" * 60,
        ]

        # Syntax
        if report.syntax_errors:
            lines.append(f"\nSYNTAX ERRORS ({len(report.syntax_errors)}):")
            for e in report.syntax_errors:
                lines.append(f"  • {e}")
        else:
            lines.append("\nSyntax: OK")

        # Imports
        if report.import_issues:
            lines.append(f"\nIMPORT ISSUES ({len(report.import_issues)}):")
            for i in report.import_issues:
                lines.append(f"  • {i}")

        # Undefined names
        if report.undefined_names:
            lines.append(f"\nUNDEFINED NAMES ({len(report.undefined_names)}):")
            lines.append("  " + ", ".join(report.undefined_names[:10]))

        # Security
        if report.security_issues:
            by_severity: dict[str, list[dict[str, str]]] = {}
            for issue in report.security_issues:
                sev = issue.get("severity", "unknown")
                by_severity.setdefault(sev, []).append(issue)
            lines.append(f"\nSECURITY ISSUES ({len(report.security_issues)}):")
            for sev in ("high", "medium", "low", "info", "unknown"):
                if sev not in by_severity:
                    continue
                for issue in by_severity[sev]:
                    lines.append(
                        f"  [{sev.upper():6s}] Line {issue.get('line', '?')}: "
                        f"{issue.get('pattern', '')} — {issue.get('code', '')[:60]}"
                    )
        else:
            lines.append("\nSecurity: No issues detected")

        # Coverage metrics
        lines.append(f"\nType hint coverage:  {report.type_hint_coverage:.0%}")
        lines.append(f"Docstring coverage:  {report.docstring_coverage:.0%}")

        # Complexity
        if report.complexity:
            c = report.complexity
            lines.append(
                f"\nComplexity:  {c.get('lines_code', '?')} code lines | "
                f"{c.get('functions', 0)} functions | "
                f"{c.get('classes', 0)} classes | "
                f"max nesting {c.get('max_nesting_depth', '?')} | "
                f"cyclomatic ~{c.get('cyclomatic_complexity_approx', '?')}"
            )

        # Suggestions
        if report.suggestions:
            lines.append(f"\nSUGGESTIONS ({len(report.suggestions)}):")
            for s in report.suggestions:
                lines.append(f"  → {s}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool definitions (standalone for agent registration)
# ---------------------------------------------------------------------------

CODE_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "code_validate",
            "description": (
                "Validate code for syntax errors, import issues, undefined names, "
                "security vulnerabilities, and type hint coverage. "
                "Returns a detailed validation report."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Source code to validate."},
                    "language": {
                        "type": "string",
                        "description": "Programming language: 'python', 'javascript', or 'typescript'.",
                        "default": "python",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_coverage",
            "description": (
                "Run pytest with coverage on a source file and test file. "
                "Returns statement counts and coverage percentage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_file": {"type": "string", "description": "Path to the module under test."},
                    "test_file": {"type": "string", "description": "Path to the pytest test file."},
                },
                "required": ["source_file", "test_file"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_suggest_tests",
            "description": (
                "Use an LLM to analyse source and existing tests, then suggest "
                "missing test cases covering uncovered paths, edge cases, and error handling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_file": {"type": "string", "description": "Path to the module under test."},
                    "test_file": {"type": "string", "description": "Path to the existing test file."},
                },
                "required": ["source_file"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _module_exists(name: str) -> bool:
    """Return True if *name* is importable (stdlib or installed)."""
    if name in sys.stdlib_module_names:  # type: ignore[attr-defined]
        return True
    spec = importlib.util.find_spec(name)
    return spec is not None


def _command_available(cmd: str) -> bool:
    """Return True if *cmd* is on PATH."""
    import shutil
    return shutil.which(cmd) is not None


def _calc_max_nesting(tree: ast.AST) -> int:
    """Calculate the maximum nesting depth of the AST."""
    _NESTING_NODES = (
        ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
        ast.If, ast.For, ast.AsyncFor, ast.While,
        ast.With, ast.AsyncWith, ast.Try,
    )

    def _depth(node: ast.AST, current: int) -> int:
        max_d = current
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _NESTING_NODES):
                max_d = max(max_d, _depth(child, current + 1))
            else:
                max_d = max(max_d, _depth(child, current))
        return max_d

    return _depth(tree, 0)


def _parse_coverage_output(output: str, module_name: str) -> CoverageReport:
    """Parse pytest-cov terminal output into a :class:`CoverageReport`."""
    # Look for line like:
    #   module.py      45      3    93%   10-12
    pattern = re.compile(
        rf"{re.escape(module_name)}(?:\.py)?\s+"
        r"(\d+)\s+"                 # Total statements
        r"(\d+)\s+"                 # Missed
        r"(\d+)%"                   # Coverage %
        r"(?:\s+(.+))?",            # Missed lines (optional)
    )
    m = pattern.search(output)
    if m:
        total = int(m.group(1))
        missed = int(m.group(2))
        pct = float(m.group(3))
        covered = total - missed
        # Parse missed lines
        uncovered_lines: list[int] = []
        if m.group(4):
            for part in re.split(r"[,\s]+", m.group(4)):
                part = part.strip()
                if "-" in part:
                    start_str, end_str = part.split("-", 1)
                    try:
                        uncovered_lines.extend(range(int(start_str), int(end_str) + 1))
                    except ValueError:
                                                import logging as _log; _log.getLogger('codebase.hardening').debug('Suppressed exception', exc_info=True)
                elif part.isdigit():
                    uncovered_lines.append(int(part))
        return CoverageReport(
            total_statements=total,
            covered=covered,
            missed=missed,
            coverage_pct=pct,
            uncovered_lines=uncovered_lines,
        )

    # Try the TOTAL line as fallback
    total_pattern = re.compile(r"TOTAL\s+(\d+)\s+(\d+)\s+(\d+)%")
    m2 = total_pattern.search(output)
    if m2:
        total = int(m2.group(1))
        missed = int(m2.group(2))
        pct = float(m2.group(3))
        return CoverageReport(
            total_statements=total,
            covered=total - missed,
            missed=missed,
            coverage_pct=pct,
        )

    log.warning("Could not parse coverage output:\n%s", output[:500])
    return CoverageReport(total_statements=0, covered=0, missed=0, coverage_pct=0.0)
