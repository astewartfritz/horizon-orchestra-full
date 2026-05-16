"""Horizon Orchestra — Test-Driven Development (TDD) Loop.

Autonomous red-green-refactor cycle: the agent writes or modifies code,
runs the test suite, parses failures, asks the LLM for fixes, and repeats
until all tests pass or the iteration budget is exhausted.

Mirrors the TDD workflow described in Claude's engineering practices and
Codex's autonomous coding loop.

Usage::

    from orchestra.codebase.tdd_loop import TDDConfig, TDDLoop
    from orchestra.router import ModelRouter

    router = ModelRouter()
    loop = TDDLoop(router=router)
    result = await loop.run(
        task="Implement a binary search function that passes pytest tests",
        test_file="tests/test_binary_search.py",
    )
    print(result.success, result.iterations)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "TDDConfig",
    "TDDResult",
    "TestRunResult",
    "TestFailure",
    "TDDLoop",
]

log = logging.getLogger("orchestra.codebase.tdd_loop")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TDDConfig:
    """Configuration for the TDD loop.

    Attributes:
        max_iterations: Maximum red-green-refactor cycles before giving up.
        test_command: Shell command used to run the test suite.
        auto_fix: If False, generate fix proposals without applying them.
        model: LLM model name (must be registered in the router) for code
            generation and fix reasoning.
        work_dir: Directory in which tests and source files reside.
        timeout_seconds: Per-test-run timeout in seconds.
    """

    max_iterations: int = 10
    test_command: str = "python -m pytest"
    auto_fix: bool = True
    model: str = "kimi-k2.5"
    work_dir: str = "."
    timeout_seconds: int = 120


@dataclass
class TestFailure:
    """A single test failure extracted from pytest/unittest output.

    Attributes:
        test_name: Fully qualified test name (e.g. ``tests/test_foo.py::test_bar``).
        file: Source file where the failure occurred.
        line: Line number of the assertion error.
        error_message: Short error description.
        traceback: Full traceback text.
    """

    test_name: str
    file: str = ""
    line: int = 0
    error_message: str = ""
    traceback: str = ""


@dataclass
class TestRunResult:
    """Outcome of a single test command execution.

    Attributes:
        passed: Number of tests that passed.
        failed: Number of tests that failed.
        errors: Number of tests with errors (distinct from failures).
        output: Full captured stdout+stderr.
        duration: Wall-clock time in seconds.
        exit_code: Process exit code.
    """

    passed: int = 0
    failed: int = 0
    errors: int = 0
    output: str = ""
    duration: float = 0.0
    exit_code: int = 0


@dataclass
class TDDResult:
    """Final outcome of the complete TDD loop run.

    Attributes:
        success: True if all tests passed by the final iteration.
        iterations: Number of red-green-refactor cycles that ran.
        tests_passed: Final passing test count.
        tests_failed: Final failing test count.
        code_changes: List of file paths that were modified.
        duration: Total wall-clock time in seconds.
        final_output: Test runner output from the last run.
        error: Reason for failure if ``success`` is False.
    """

    success: bool = False
    iterations: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    code_changes: list[str] = field(default_factory=list)
    duration: float = 0.0
    final_output: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_INITIAL_CODE_PROMPT = """\
You are an expert software engineer implementing code to make the following tests pass.

Task: {task}

Test file content:
```
{test_content}
```

Write the implementation code that will make all these tests pass. Return a JSON object:
{{
  "files": [
    {{
      "path": "relative/path/to/file.py",
      "content": "...full file content..."
    }}
  ],
  "reasoning": "Brief explanation of your approach"
}}

Only return valid JSON. No markdown fences around the outer JSON.
"""

_FIX_CODE_PROMPT = """\
You are an expert software engineer. The following tests are failing.
Analyse the failures and provide fixes.

Task: {task}

Test failures:
{failures}

Current file contents:
{file_contents}

Iteration: {iteration}/{max_iterations}

Return a JSON object:
{{
  "files": [
    {{
      "path": "relative/path/to/file.py",
      "content": "...full corrected file content..."
    }}
  ],
  "reasoning": "Why these changes fix the failures"
}}

Only return valid JSON. No markdown fences around the outer JSON.
"""


# ---------------------------------------------------------------------------
# TDDLoop
# ---------------------------------------------------------------------------

class TDDLoop:
    """Autonomous TDD loop that writes code, runs tests, and fixes failures.

    The loop follows this cycle for each iteration:
    1. Generate/fix code via LLM.
    2. Write generated files to disk.
    3. Run the test command.
    4. If all pass → done.
    5. Parse failures → go to step 1.

    Args:
        router: :class:`~orchestra.router.ModelRouter` for LLM calls.
        config: TDD loop configuration. Uses defaults if not provided.
    """

    def __init__(
        self,
        router: Any | None = None,  # ModelRouter
        config: TDDConfig | None = None,
    ) -> None:
        self.router = router
        self.config = config or TDDConfig()
        self._work_dir = Path(self.config.work_dir).resolve()

    # ------------------------------------------------------------------
    # Public: run the full loop
    # ------------------------------------------------------------------

    async def run(
        self,
        task: str,
        test_file: str = "",
    ) -> TDDResult:
        """Execute the TDD loop for *task*.

        Args:
            task: Natural language description of what to implement.
            test_file: Path to an existing test file (relative to work_dir).
                If empty, the loop will try to find test files automatically.

        Returns:
            :class:`TDDResult` summarising the outcome.
        """
        t0 = time.monotonic()
        code_changes: list[str] = []
        last_run: TestRunResult | None = None

        # Load test file content for the initial prompt
        test_content = ""
        if test_file:
            test_path = self._work_dir / test_file
            if test_path.exists():
                test_content = test_path.read_text(encoding="utf-8", errors="replace")
            else:
                return TDDResult(
                    success=False,
                    error=f"Test file not found: {test_file}",
                    duration=time.monotonic() - t0,
                )

        # Generate initial implementation
        if self.config.auto_fix:
            changes = await self._generate_initial_code(task, test_content)
            if changes:
                written = self._write_files(changes, self._work_dir)
                code_changes.extend(written)

        for iteration in range(1, self.config.max_iterations + 1):
            log.info("TDD iteration %d/%d", iteration, self.config.max_iterations)

            # Run the test suite
            last_run = await self._run_tests(self.config.test_command)
            log.info(
                "  Tests: %d passed, %d failed, %d errors (exit %d)",
                last_run.passed, last_run.failed, last_run.errors, last_run.exit_code,
            )

            # All green?
            if last_run.exit_code == 0 and last_run.failed == 0 and last_run.errors == 0:
                log.info("All tests pass after %d iteration(s)!", iteration)
                return TDDResult(
                    success=True,
                    iterations=iteration,
                    tests_passed=last_run.passed,
                    tests_failed=0,
                    code_changes=code_changes,
                    duration=time.monotonic() - t0,
                    final_output=last_run.output,
                )

            # Parse failures and attempt fixes
            failures = self._parse_failures(last_run.output)
            if not failures and last_run.exit_code != 0:
                # Execution error, not a test failure — still try to fix
                failures = [TestFailure(
                    test_name="execution_error",
                    error_message=last_run.output[-2000:],
                    traceback=last_run.output[-2000:],
                )]

            if self.config.auto_fix and self.router is not None:
                fixes = await self._fix_code(failures, task, iteration)
                if fixes:
                    written = self._write_files(fixes, self._work_dir)
                    code_changes.extend(w for w in written if w not in code_changes)
                else:
                    log.warning("LLM returned no fixes for iteration %d", iteration)

        # Exhausted budget
        final_run = last_run or TestRunResult()
        return TDDResult(
            success=False,
            iterations=self.config.max_iterations,
            tests_passed=final_run.passed,
            tests_failed=final_run.failed + final_run.errors,
            code_changes=code_changes,
            duration=time.monotonic() - t0,
            final_output=final_run.output,
            error=f"Max iterations ({self.config.max_iterations}) reached without all tests passing",
        )

    # ------------------------------------------------------------------
    # Internal: run tests
    # ------------------------------------------------------------------

    async def _run_tests(self, command: str) -> TestRunResult:
        """Execute the test command and capture output.

        Args:
            command: Shell command string (e.g. ``"python -m pytest -v"``).

        Returns:
            :class:`TestRunResult` with parsed pass/fail counts.
        """
        t0 = time.monotonic()
        parts = command.split()

        try:
            proc = await asyncio.create_subprocess_exec(
                *parts,
                cwd=str(self._work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONPATH": str(self._work_dir)},
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=self.config.timeout_seconds
                )
            except asyncio.TimeoutError:
                proc.kill()
                return TestRunResult(
                    output=f"Test run timed out after {self.config.timeout_seconds}s",
                    exit_code=124,
                    duration=time.monotonic() - t0,
                )
        except FileNotFoundError as exc:
            return TestRunResult(
                output=f"Test command not found: {exc}",
                exit_code=127,
                duration=time.monotonic() - t0,
            )

        output = (
            stdout_b.decode(errors="replace") + "\n" + stderr_b.decode(errors="replace")
        ).strip()
        exit_code = proc.returncode or 0
        duration = time.monotonic() - t0

        passed, failed, errors = self._parse_counts(output)
        return TestRunResult(
            passed=passed,
            failed=failed,
            errors=errors,
            output=output,
            duration=duration,
            exit_code=exit_code,
        )

    # ------------------------------------------------------------------
    # Internal: parse failures
    # ------------------------------------------------------------------

    def _parse_failures(self, output: str) -> list[TestFailure]:
        """Extract individual test failure details from test runner output.

        Supports pytest-style output. Falls back to generic parsing for
        other frameworks.

        Args:
            output: Combined stdout+stderr from the test runner.

        Returns:
            List of :class:`TestFailure` objects.
        """
        failures: list[TestFailure] = []

        # Try pytest-style: FAILED tests/test_foo.py::test_bar - AssertionError
        failed_pattern = re.compile(
            r"^FAILED\s+(.+?)\s*(?:-\s*(.+))?$", re.MULTILINE
        )
        for m in failed_pattern.finditer(output):
            test_name = m.group(1).strip()
            error_msg = (m.group(2) or "").strip()

            # Extract file and line from the test name
            file_part = test_name.split("::")[0] if "::" in test_name else test_name

            failures.append(TestFailure(
                test_name=test_name,
                file=file_part,
                error_message=error_msg,
            ))

        # Try to enrich with traceback blocks
        # Pytest formats: "_____ test_name _____\n...<traceback>..."
        section_pattern = re.compile(
            r"_{5,}\s+(.+?)\s+_{5,}\n(.*?)(?=_{5,}|\Z)", re.DOTALL
        )
        failure_sections: dict[str, str] = {}
        for m in section_pattern.finditer(output):
            section_name = m.group(1).strip()
            section_body = m.group(2).strip()
            failure_sections[section_name] = section_body

        for f in failures:
            # Match by test function name
            short_name = f.test_name.split("::")[-1]
            if short_name in failure_sections:
                tb = failure_sections[short_name]
                f.traceback = tb
                # Try to extract line number
                line_m = re.search(r":(\d+):", tb)
                if line_m:
                    f.line = int(line_m.group(1))

        # If pytest parsing found nothing, try ERROR lines
        if not failures:
            error_pattern = re.compile(r"^ERROR\s+(.+)$", re.MULTILINE)
            for m in error_pattern.finditer(output):
                failures.append(TestFailure(
                    test_name=m.group(1).strip(),
                    error_message="Error during collection or setup",
                    traceback=output[-3000:],
                ))

        return failures

    def _parse_counts(self, output: str) -> tuple[int, int, int]:
        """Parse pass/fail/error counts from pytest summary line.

        Handles lines like:
        ``3 passed, 2 failed, 1 error in 0.5s``

        Args:
            output: Raw test runner output.

        Returns:
            Tuple of ``(passed, failed, errors)``.
        """
        passed = failed = errors = 0

        # Pytest summary: "=== 3 passed, 2 failed in 0.5s ==="
        summary_m = re.search(
            r"(\d+)\s+passed.*?(\d+)\s+failed.*?(\d+)\s+error|"
            r"(\d+)\s+passed.*?(\d+)\s+failed|"
            r"(\d+)\s+passed.*?(\d+)\s+error|"
            r"(\d+)\s+failed.*?(\d+)\s+error|"
            r"(\d+)\s+passed|"
            r"(\d+)\s+failed|"
            r"(\d+)\s+error",
            output,
        )

        if summary_m:
            groups = summary_m.groups()
            # This is complex; just search individually
            pass

        # Simpler individual searches
        p = re.search(r"(\d+)\s+passed", output)
        f = re.search(r"(\d+)\s+failed", output)
        e = re.search(r"(\d+)\s+error", output)

        if p:
            passed = int(p.group(1))
        if f:
            failed = int(f.group(1))
        if e:
            errors = int(e.group(1))

        return passed, failed, errors

    # ------------------------------------------------------------------
    # Internal: LLM-based code generation & fixing
    # ------------------------------------------------------------------

    async def _generate_initial_code(
        self, task: str, test_content: str
    ) -> list[dict[str, str]]:
        """Use the LLM to generate initial implementation files.

        Args:
            task: Natural language task description.
            test_content: Content of the test file.

        Returns:
            List of ``{"path": "...", "content": "..."}`` dicts.
        """
        if self.router is None:
            return []

        prompt = _INITIAL_CODE_PROMPT.format(
            task=task,
            test_content=test_content[:8000],
        )

        try:
            client, model_id = self.router.get_client(self.config.model)
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "You are an expert Python developer."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=8192,
            )
            raw = response.choices[0].message.content or "{}"
            data = self._parse_json_response(raw)
            return data.get("files", [])
        except Exception as exc:
            log.warning("Initial code generation failed: %s", exc)
            return []

    async def _fix_code(
        self,
        failures: list[TestFailure],
        task: str,
        iteration: int,
    ) -> list[dict[str, str]]:
        """Ask the LLM to fix code based on observed test failures.

        Args:
            failures: List of parsed test failures.
            task: Original task description.
            iteration: Current iteration number for prompt context.

        Returns:
            List of ``{"path": "...", "content": "..."}`` dicts to write.
        """
        if self.router is None:
            return []

        # Collect current file contents for context
        file_contents = self._collect_source_files()

        failures_text = "\n\n".join(
            f"Test: {f.test_name}\n"
            f"File: {f.file}:{f.line}\n"
            f"Error: {f.error_message}\n"
            f"Traceback:\n{f.traceback[:1500]}"
            for f in failures[:10]
        )

        prompt = _FIX_CODE_PROMPT.format(
            task=task,
            failures=failures_text,
            file_contents=file_contents[:6000],
            iteration=iteration,
            max_iterations=self.config.max_iterations,
        )

        try:
            client, model_id = self.router.get_client(self.config.model)
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "You are an expert Python debugger."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=8192,
            )
            raw = response.choices[0].message.content or "{}"
            data = self._parse_json_response(raw)
            return data.get("files", [])
        except Exception as exc:
            log.warning("Fix code generation failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write_files(
        self,
        files: list[dict[str, str]],
        base_dir: Path,
    ) -> list[str]:
        """Write generated files to disk.

        Args:
            files: List of ``{"path": str, "content": str}`` dicts.
            base_dir: Root directory for relative paths.

        Returns:
            List of relative paths that were successfully written.
        """
        written: list[str] = []
        for entry in files:
            rel_path = entry.get("path", "")
            content = entry.get("content", "")
            if not rel_path or not content:
                continue

            dest = base_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            log.debug("Wrote %s (%d bytes)", rel_path, len(content))
            written.append(rel_path)

        return written

    def _collect_source_files(self) -> str:
        """Collect contents of Python source files in the work directory.

        Skips test files and hidden directories. Truncates large files.

        Returns:
            Concatenated file contents with path headers.
        """
        parts: list[str] = []
        for py_file in sorted(self._work_dir.rglob("*.py")):
            # Skip test files and virtualenvs
            if any(part.startswith((".", "_")) or part in ("venv", "env", "__pycache__")
                   for part in py_file.parts):
                continue
            if "test" in py_file.name.lower():
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")[:3000]
                rel = py_file.relative_to(self._work_dir)
                parts.append(f"### {rel} ###\n{content}")
            except Exception:
                                import logging as _log; _log.getLogger('codebase.tdd_loop').debug('Suppressed exception', exc_info=True)

        return "\n\n".join(parts)

    @staticmethod
    def _parse_json_response(raw: str) -> dict[str, Any]:
        """Parse a JSON response from the LLM, stripping markdown fences.

        Args:
            raw: Raw LLM output string.

        Returns:
            Parsed dict, or empty dict on failure.
        """
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            # Remove opening fence line
            raw = re.sub(r"^```[a-z]*\s*\n", "", raw)
            # Remove closing fence
            raw = re.sub(r"\n```\s*$", "", raw)
        raw = raw.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON object from a larger response
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            log.warning("Could not parse JSON from LLM response: %s", raw[:200])
            return {}
