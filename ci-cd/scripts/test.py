"""Test runner script — runs all project tests with coverage."""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET


def run(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> tuple[int, str, str]:
    print(f"[test] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        print(result.stdout[-500:])
    if result.stderr:
        print(f"[test] STDERR: {result.stderr[-300:]}")
    return result.returncode, result.stdout, result.stderr


def get_coverage_pct(coverage_xml: str = "coverage.xml") -> float:
    try:
        root = ET.parse(coverage_xml).getroot()
        return float(root.attrib.get("line-rate", 0)) * 100
    except Exception:
        return 0.0


def main() -> int:
    errors = 0
    threshold = int(sys.argv[1]) if len(sys.argv) > 1 else 80

    print("=" * 60)
    print(f"Test Stage — Coverage Threshold: {threshold}%")
    print("=" * 60)

    # Python tests
    rc, out, _ = run([
        sys.executable, "-m", "pytest", "src/", "-v",
        "--junitxml=junit-python.xml",
        "--cov=src/", "--cov-report=xml", "--cov-report=term",
    ])
    if rc != 0:
        errors += 1

    # Coverage gate
    cov = get_coverage_pct()
    print(f"[test] Coverage: {cov:.1f}%")
    if cov < threshold:
        print(f"[test] FAIL: Coverage {cov:.1f}% < {threshold}%")
        errors += 1

    # TypeScript tests
    try:
        rc2, _, _ = run(["npm", "test"], cwd="channels/ts", timeout=120)
        if rc2 != 0:
            errors += 1
    except FileNotFoundError:
        print("[test] Skipping TS tests (channels/ts not found)")

    if errors:
        print(f"[test] FAILED: {errors} test step(s) failed")
    else:
        print("[test] All tests passed")

    return errors


if __name__ == "__main__":
    sys.exit(main())
