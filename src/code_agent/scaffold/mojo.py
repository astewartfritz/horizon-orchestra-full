from __future__ import annotations

from pathlib import Path

from code_agent.tools.base import Tool, ToolResult, ToolSpec

MOJO_PROJECT = """[project]
name = "{name}"
version = "0.1.0"
description = "{description}"

[build]
type = "module"
entry = "src/main.mojo"
"""

MAIN_MOJO = """from .lib import greet


def main():
    print(greet("World"))


if __name__ == "__main__":
    main()
"""

LIB_MOJO = '''fn greet(name: String) -> String:
    return "Hello, " + name + "!"


fn add(a: Int, b: Int) -> Int:
    return a + b


fn fibonacci(n: Int) -> Int:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
'''

TEST_MOJO = """from .lib import greet, add, fibonacci
from testing import assert_equal


def test_greet():
    assert_equal(greet("Mojo"), "Hello, Mojo!")


def test_add():
    assert_equal(add(2, 3), 5)


def test_fibonacci():
    assert_equal(fibonacci(0), 0)
    assert_equal(fibonacci(1), 1)
    assert_equal(fibonacci(10), 55)


def main():
    test_greet()
    test_add()
    test_fibonacci()
    print("All tests passed!")
"""

MAKEFILE = """.PHONY: build test run clean

build:
\tmojo build src/main.mojo -o {name}

test:
\tmojo test tests/

run:
\tmojo run src/main.mojo

clean:
\trm -f {name}
\trm -rf __pycache__ .mojocache

notebook:
\tmojo run notebooks/example.ipynb
"""

GITIGNORE_MOJO = """__pycache__/
.mojocache/
*.pyc
.ipynb_checkpoints/
.idea/
"""

README_MOJO = '''# {name}

{description}

## Prerequisites

- [Mojo SDK](https://docs.modular.com/mojo/)

## Quick Start

```bash
make build
make test
make run
```

## Development

```bash
# Run tests
mojo test tests/

# Build binary
mojo build src/main.mojo -o {name}
```

## License

MIT
'''

NOTEBOOK_JSON = """{{
 "cells": [
  {{
   "cell_type": "markdown",
   "metadata": {{}},
   "source": ["# {name}\\n\\n{description}"]
  }},
  {{
   "cell_type": "code",
   "execution_count": null,
   "metadata": {{}},
   "source": [
    "from lib import greet\\n\\nprint(greet(\\"Mojo\\"))"
   ],
   "outputs": []
  }}
 ],
 "metadata": {{
  "kernelspec": {{
   "display_name": "Mojo",
   "language": "mojo",
   "name": "mojo"
  }}
 }},
 "nbformat": 4,
 "nbformat_minor": 5
}}
"""

MOJO_TEMPLATES: dict[str, dict[str, str]] = {
    "mojo-package": {
        "mojoproject.toml": MOJO_PROJECT,
        "src/main.mojo": MAIN_MOJO,
        "src/lib.mojo": LIB_MOJO,
        "tests/test_main.mojo": TEST_MOJO,
        "Makefile": MAKEFILE,
        "notebooks/example.ipynb": NOTEBOOK_JSON,
        ".gitignore": GITIGNORE_MOJO,
        "README.md": README_MOJO,
    },
}


class MojoScaffold(Tool):
    spec = ToolSpec(
        name="scaffold_mojo",
        description="Generate a Mojo project with module structure, tests, Makefile, and Jupyter notebook.",
        parameters={
            "name": {"type": "string", "description": "Project name"},
            "description": {"type": "string", "description": "Short description", "default": ""},
            "output_dir": {"type": "string", "description": "Output directory"},
        },
    )

    async def __call__(self, name: str, description: str = "", output_dir: str | None = None) -> ToolResult:
        out = Path(output_dir or name).resolve()
        out.mkdir(parents=True, exist_ok=True)
        created = []
        for relpath, content in MOJO_TEMPLATES["mojo-package"].items():
            fpath = out / relpath
            fpath.parent.mkdir(parents=True, exist_ok=True)
            formatted = content.format(name=name, description=description or f"A Mojo project")
            fpath.write_text(formatted, "utf-8")
            created.append(str(fpath.relative_to(out.parent)))
        summary = "\n".join(f"  + {p}" for p in created)
        return ToolResult(output=f"Scaffolded Mojo project '{name}' at {out}\n{summary}")
