"""Backward-compatible CLI shim. Commands are now in the `cli/` package."""
from orchestra.code_agent.cli import main  # noqa: F401

if __name__ == "__main__":
    main()
