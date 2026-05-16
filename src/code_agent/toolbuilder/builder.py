from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class GeneratedTool:
    name: str
    description: str
    code: str
    path: str = ""
    parameters: list[dict] = field(default_factory=list)
    valid: bool = True
    error: str = ""


_TOOL_TEMPLATE = '''from __future__ import annotations

from code_agent.tools.base import Tool, ToolResult, ToolSpec


class {name}(Tool):
    name = "{name}"
    description = "{description}"

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters={parameters},
        )

    def run(self, {params_sig}) -> ToolResult:
        try:
{body}
            return ToolResult(output=result)
        except Exception as e:
            return ToolResult(error=str(e))
'''


class ToolBuilder:
    def __init__(self, output_dir: str = "src/code_agent/custom_tools"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def from_description(self, name: str, description: str, behavior: str) -> GeneratedTool:
        param_patterns = {
            "path": {"type": "string", "description": "File path"},
            "pattern": {"type": "string", "description": "Search pattern"},
            "query": {"type": "string", "description": "Search query"},
            "url": {"type": "string", "description": "URL"},
            "command": {"type": "string", "description": "Command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds"},
            "count": {"type": "integer", "description": "Number of results"},
            "data": {"type": "string", "description": "Input data"},
            "message": {"type": "string", "description": "Message content"},
            "key": {"type": "string", "description": "Key name"},
            "value": {"type": "string", "description": "Value"},
            "name_param": {"type": "string", "description": "Name"},
        }

        params = []
        body_lines = []
        used_params = set()

        for word in re.findall(r'\b(path|file|pattern|query|url|command|timeout|count|data|message|key|value|name)\b', behavior.lower()):
            if word not in used_params:
                if word in param_patterns:
                    params.append({"name": word, **param_patterns[word]})
                    used_params.add(word)

        if not params:
            params.append({"name": "input", "type": "string", "description": "Input"})

        for p in params:
            body_lines.append(f"            {p['name']} = {p['name']}")
        body_lines.append(f'            result = f"{{self.name}}: executed with {{", ".join([{", ".join(p["name"] for p in params)}])}}"')

        pnames = [p["name"] for p in params]
        params_sig = ", ".join(f"{p}: {p['type']} = ''" for p in params)

        import json
        parameters_schema = {p["name"]: {"type": p["type"], "description": p["description"]} for p in params}

        sanitized_name = re.sub(r'[^a-zA-Z0-9_]', '', name.title().replace(" ", ""))
        if not sanitized_name:
            sanitized_name = "CustomTool"
        if not sanitized_name.endswith("Tool"):
            sanitized_name += "Tool"

        code = _TOOL_TEMPLATE.format(
            name=sanitized_name,
            description=description,
            parameters=json.dumps(parameters_schema, indent=8),
            params_sig=params_sig,
            body="\n".join(body_lines) if body_lines else '            result = "ok"',
        )

        file_path = str(self.output_dir / f"{sanitized_name.lower()}.py")

        tool = GeneratedTool(
            name=sanitized_name,
            description=description,
            code=code,
            path=file_path,
            parameters=params,
        )
        return tool

    def save(self, tool: GeneratedTool) -> str:
        Path(tool.path).write_text(tool.code, encoding="utf-8")
        init_file = self.output_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text(
                f"from code_agent.custom_tools.{Path(tool.path).stem} import {tool.name}\n",
                encoding="utf-8",
            )
        else:
            content = init_file.read_text(encoding="utf-8")
            if tool.name not in content:
                init_file.write_text(
                    content + f"from code_agent.custom_tools.{Path(tool.path).stem} import {tool.name}\n",
                    encoding="utf-8",
                )
        return tool.path

    def list_tools(self) -> list[str]:
        tools = []
        for f in self.output_dir.glob("*.py"):
            if f.name != "__init__.py":
                tools.append(f.stem)
        return tools

    def summary_text(self, tool: GeneratedTool) -> str:
        lines = [
            f"Generated Tool: {tool.name}",
            f"  Description: {tool.description}",
            f"  Parameters:  {len(tool.parameters)}",
        ]
        for p in tool.parameters:
            lines.append(f"    - {p['name']}: {p['type']} ({p.get('description', '')})")
        lines.append(f"  Path:        {tool.path}")
        return "\n".join(lines)
