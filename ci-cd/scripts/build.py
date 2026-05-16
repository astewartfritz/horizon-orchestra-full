"""Build script — installs all project dependencies."""

from __future__ import annotations

import subprocess
import sys


def run(cmd: list[str], cwd: str | None = None) -> bool:
    print(f"[build] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[build] ERROR: {result.stderr.strip()}")
    else:
        print(f"[build] OK: {result.stdout.strip()[-200:]}")
    return result.returncode == 0


def main() -> int:
    errors = 0

    print("=" * 60)
    print("Build Stage — Installing Dependencies")
    print("=" * 60)

    # Python
    if not run([sys.executable, "-m", "pip", "install", "-e", ".[dev]"]):
        errors += 1

    # TypeScript channels
    ts_ok = run(["npm", "ci"], cwd="channels/ts")
    if not ts_ok:
        errors += 1

    # Express API
    express_ok = run(["npm", "ci"], cwd="api/express")
    if not express_ok:
        errors += 1

    if errors:
        print(f"[build] FAILED: {errors} build step(s) failed")
    else:
        print("[build] All dependencies installed successfully")

    return errors


if __name__ == "__main__":
    sys.exit(main())
