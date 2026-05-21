from __future__ import annotations

from pathlib import Path

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec
from orchestra.code_agent.scaffold.rust import RUST_TEMPLATES
from orchestra.code_agent.scaffold.typescript import TYPESCRIPT_TEMPLATES
from orchestra.code_agent.scaffold.mojo import MOJO_TEMPLATES

TEMPLATES: dict[str, dict[str, str]] = {
    **RUST_TEMPLATES,
    **TYPESCRIPT_TEMPLATES,
    **MOJO_TEMPLATES,

    "python-package": {
        "pyproject.toml": "[build-system]\nrequires = [\"hatchling\"]\nbuild-backend = \"hatchling.build\"\n\n[project]\nname = \"{name}\"\nversion = \"0.1.0\"\ndescription = \"{description}\"\nreadme = \"README.md\"\nrequires-python = \">=3.11\"\nlicense = {text = \"MIT\"}\n\n[project.scripts]\n{name} = \"{name}.cli:main\"\n",
        "README.md": "# {name}\n\n{description}\n",
        "src/{name}/__init__.py": "",
        "src/{name}/cli.py": "def main():\n    print('Hello from {name}')\n\nif __name__ == '__main__':\n    main()\n",
        "tests/__init__.py": "",
        "tests/test_{name}.py": "def test_placeholder():\n    assert True\n",
        ".gitignore": "__pycache__/\n*.pyc\n*.egg-info/\ndist/\nbuild/\n.venv/\n",
    },
    "python-script": {
        "{name}.py": "#!/usr/bin/env python3\n\"\"\"{description}\"\"\"\n\n\ndef main():\n    print('Hello from {name}')\n\n\nif __name__ == '__main__':\n    main()\n",
        "README.md": "# {name}\n\n{description}\n",
    },
    "typescript-package": {
        "package.json": "{{\n  \"name\": \"{name}\",\n  \"version\": \"0.1.0\",\n  \"description\": \"{description}\",\n  \"main\": \"dist/index.js\",\n  \"scripts\": {{\n    \"build\": \"tsc\",\n    \"test\": \"jest\"\n  }},\n  \"devDependencies\": {{\n    \"typescript\": \"^5.0\",\n    \"jest\": \"^29.0\"\n  }}\n}}\n",
        "tsconfig.json": "{{\n  \"compilerOptions\": {{\n    \"target\": \"ES2022\",\n    \"module\": \"commonjs\",\n    \"outDir\": \"dist\",\n    \"strict\": true\n  }},\n  \"include\": [\"src\"]\n}}\n",
        "src/index.ts": "export const greeting = 'Hello from {name}';\n",
        "tests/test.ts": "import {{ greeting }} from '../src';\n\ntest('greeting', () => {{\n  expect(greeting).toBeDefined();\n}});\n",
        ".gitignore": "node_modules/\ndist/\n",
    },
    "web-app": {
        "index.html": "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n<title>{name}</title>\n<link rel=\"stylesheet\" href=\"style.css\">\n</head>\n<body>\n  <h1>{name}</h1>\n  <script src=\"app.js\"></script>\n</body>\n</html>\n",
        "style.css": "body {{\n  font-family: system-ui, sans-serif;\n  margin: 0;\n  padding: 2rem;\n  background: #f5f5f5;\n}}\n",
        "app.js": "console.log('{name} loaded');\n",
        "README.md": "# {name}\n\n{description}\n",
    },
    "fastapi-app": {
        "pyproject.toml": "[build-system]\nrequires = [\"hatchling\"]\nbuild-backend = \"hatchling.build\"\n\n[project]\nname = \"{name}\"\nversion = \"0.1.0\"\ndescription = \"{description}\"\nrequires-python = \">=3.11\"\ndependencies = [\"fastapi>=0.100\", \"uvicorn>=0.20\"]\n",
        "src/{name}/__init__.py": "from fastapi import FastAPI\n\napp = FastAPI(title='{name}')\n\n@app.get('/')\nasync def root():\n    return {{\"message\": \"Hello from {name}\"}}\n",
        "src/{name}/cli.py": "import uvicorn\nfrom . import app\n\ndef main():\n    uvicorn.run(app, host='0.0.0.0', port=8000)\n",
        "README.md": "# {name}\n\n{description}\n",
    },
}


class ScaffoldGenerator(Tool):
    spec = ToolSpec(
        name="scaffold",
        description="Generate a project scaffold from a template (python-package, python-script, typescript-package, web-app, fastapi-app).",
        parameters={
            "template": {
                "type": "string",
                "description": "Template name: python-package, python-script, typescript-package, web-app, fastapi-app",
            },
            "name": {"type": "string", "description": "Project name"},
            "description": {"type": "string", "description": "Short description", "default": ""},
            "output_dir": {"type": "string", "description": "Output directory (default: current dir / name)"},
        },
    )

    async def __call__(
        self,
        template: str,
        name: str,
        description: str = "",
        output_dir: str | None = None,
    ) -> ToolResult:
        if template not in TEMPLATES:
            return ToolResult(
                error=f"Unknown template: {template}. Available: {', '.join(TEMPLATES)}"
            )

        out = Path(output_dir or name).resolve()
        out.mkdir(parents=True, exist_ok=True)

        created = []
        for relpath, content in TEMPLATES[template].items():
            fpath = out / relpath.replace("{name}", name)
            fpath.parent.mkdir(parents=True, exist_ok=True)
            formatted = content.format(name=name, description=description or f"A {template} project")
            fpath.write_text(formatted, "utf-8")
            created.append(str(fpath.relative_to(out.parent)))

        summary = "\n".join(f"  + {p}" for p in created)
        return ToolResult(
            output=f"Scaffolded '{template}' project '{name}' at {out}\n{summary}"
        )

    @classmethod
    def add_template(cls, name: str, files: dict[str, str]) -> None:
        TEMPLATES[name] = files
