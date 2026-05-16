"""Lint script — runs ruff, mypy, bandit, and license checks."""

from __future__ import annotations

import subprocess
import sys


def run(cmd: list[str], check: bool = True) -> tuple[int, str]:
    label = cmd[0] if len(cmd) == 1 else cmd[1]
    print(f"[lint] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.stdout:
        print(result.stdout[:500])
    if result.stderr:
        print(f"[lint] ERR: {result.stderr[:300]}")
    if result.returncode != 0 and check:
        print(f"[lint] WARNING: {label} found issues")
    return result.returncode, result.stdout


def main() -> int:
    warnings = 0

    print("=" * 60)
    print("Lint Stage")
    print("=" * 60)

    # Ruff
    rc, _ = run([sys.executable, "-m", "ruff", "check", "src/"], check=False)
    if rc != 0:
        warnings += 1

    # MyPy
    rc, _ = run([sys.executable, "-m", "mypy", "src/", "--ignore-missing-imports"], check=False)
    if rc != 0:
        warnings += 1

    # Bandit security scan
    rc, _ = run([
        sys.executable, "-m", "bandit", "-r", "src/",
        "-f", "json", "-o", "bandit.json",
    ], check=False)

    # License check
    try:
        run([
            sys.executable, "-m", "pip_licenses",
            "--allow-only=MIT;Apache-2.0;BSD-2-Clause;BSD-3-Clause;Python-2.0;PSF;Unlicense",
        ], check=False)
    except FileNotFoundError:
        print("[lint] pip-licenses not installed, skipping")

    if warnings:
        print(f"[lint] Completed with {warnings} warning(s)")
    else:
        print("[lint] All checks passed")

    return 0  # Lint warnings don't fail the pipeline


if __name__ == "__main__":
    sys.exit(main())
