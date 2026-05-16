"""Test runner with failure detection for the GRC loop. Runs tests, captures output, detects failures."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestResult:
    name: str
    passed: bool
    output: str = ""
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "error": self.error[:200], "duration_ms": self.duration_ms}


class TestRunner:
    """Runs test commands and parses results. Supports pytest, cargo test, npm test."""

    def __init__(self, command: str = "python -m pytest -x -q"):
        self.command = command

    async def run(self, timeout: int = 120) -> list[TestResult]:
        """Run the test command and parse results."""
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_shell(
                self.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return [TestResult(name="timeout", passed=False, error=f"Timed out after {timeout}s")]

            out = stdout.decode("utf-8", errors="replace") if stdout else ""
            err = stderr.decode("utf-8", errors="replace") if stderr else ""
            combined = out + "\n" + err

            return self._parse_results(combined, int((time.time() - start) * 1000))

        except FileNotFoundError:
            return [TestResult(name="command_not_found", passed=False, error=f"Command not found: {self.command.split()[0]}")]
        except Exception as e:
            return [TestResult(name="runner_error", passed=False, error=str(e))]

    def _parse_results(self, output: str, duration_ms: int) -> list[TestResult]:
        results: list[TestResult] = []

        # pytest format: "PASSED", "FAILED", "ERROR"
        if "pytest" in self.command:
            # Check for overall pass/fail
            passed_match = re.search(r"(\d+) passed", output)
            failed_match = re.search(r"(\d+) failed", output)

            if failed_match and int(failed_match.group(1)) > 0:
                # Extract individual test failures
                for m in re.finditer(r"FAILED (.+?) - (.+?: .+)", output):
                    results.append(TestResult(name=m.group(1), passed=False, error=m.group(2), duration_ms=duration_ms))
                if not results:
                    results.append(TestResult(name="tests", passed=False, error=output[:500], duration_ms=duration_ms))
                return results

            total = int(passed_match.group(1)) if passed_match else 0
            results.append(TestResult(name="all_tests", passed=failed_match is None or int(failed_match.group(1)) == 0,
                                      output=output[:500], duration_ms=duration_ms))

        elif "cargo test" in self.command:
            # Rust test output
            failed_match = re.search(r"(\d+) failed", output)
            passed_match = re.search(r"(\d+) passed", output)
            if failed_match and int(failed_match.group(1)) > 0:
                for m in re.finditer(r"test (.+?) \.\.\. FAILED", output):
                    results.append(TestResult(name=m.group(1), passed=False, duration_ms=duration_ms))
                return results
            results.append(TestResult(name="cargo_test", passed=failed_match is None or int(failed_match.group(1)) == 0,
                                      output=output[:500], duration_ms=duration_ms))

        elif "npm test" in self.command or "npm run" in self.command:
            errors = re.findall(r"ERROR|FAIL", output)
            results.append(TestResult(name="npm_test", passed=len(errors) == 0, output=output[:500], duration_ms=duration_ms))

        else:
            # Generic: check exit code via output heuristic
            has_error = bool(re.search(r"(error|failure|FAILED|failed)", output, re.IGNORECASE)) if output else True
            results.append(TestResult(name="test", passed=not has_error, output=output[:500], duration_ms=duration_ms))

        return results if results else [TestResult(name="no_tests", passed=True, output="(no tests matched)", duration_ms=duration_ms)]
