from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


@dataclass
class Endpoint:
    method: str
    path: str
    summary: str = ""
    params: list[dict] = field(default_factory=list)
    responses: dict[str, dict] = field(default_factory=lambda: {"200": {"description": "Success"}})
    request_body: Optional[dict] = None
    tags: list[str] = field(default_factory=list)
    source_file: str = ""
    source_line: int = 0


@dataclass
class ApiSpec:
    title: str
    version: str
    description: str = ""
    endpoints: list[Endpoint] = field(default_factory=list)
    servers: list[dict] = field(default_factory=list)

    def to_openapi(self) -> dict:
        paths: dict = {}
        for ep in self.endpoints:
            ep_path = ep.path
            paths.setdefault(ep_path, {})
            method_item = {
                "summary": ep.summary,
                "tags": ep.tags or ["default"],
                "parameters": [
                    {
                        "name": p.get("name"),
                        "in": p.get("in", "query"),
                        "required": p.get("required", False),
                        "schema": {"type": p.get("type", "string")},
                    }
                    for p in ep.params
                ],
                "responses": {
                    code: {"description": desc.get("description", "")} for code, desc in ep.responses.items()
                },
            }
            if ep.request_body:
                method_item["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": ep.request_body}},
                }
            paths[ep_path][ep.method.lower()] = method_item

        return {
            "openapi": "3.0.3",
            "info": {"title": self.title, "version": self.version, "description": self.description},
            "servers": self.servers or [{"url": "http://localhost:8000"}],
            "paths": paths,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_openapi(), indent=indent)

    def to_postman(self) -> dict:
        items = []
        for ep in self.endpoints:
            req = {
                "method": ep.method.upper(),
                "header": [{"key": "Content-Type", "value": "application/json"}],
                "url": {
                    "raw": f"{{base_url}}{ep.path}",
                    "path": [p for p in ep.path.split("/") if p],
                },
            }
            if ep.params:
                req["url"]["query"] = [{"key": p["name"], "value": ""} for p in ep.params if p.get("in") == "query"]
            if ep.request_body:
                req["body"] = {"mode": "raw", "raw": json.dumps(ep.request_body, indent=2)}
            items.append({"name": f"{ep.method} {ep.path}", "request": req})
        return {
            "info": {"name": self.title, "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": items,
        }


_FASTAPI_DECORATORS = {
    "app.get", "app.post", "app.put", "app.delete", "app.patch",
    "router.get", "router.post", "router.put", "router.delete", "router.patch",
}


class ApiDocGenerator:
    def __init__(self, source_path: str = "."):
        self.source = Path(source_path).resolve()

    def generate(self, title: str = "API", version: str = "1.0.0") -> ApiSpec:
        spec = ApiSpec(title=title, version=version, servers=[{"url": "http://localhost:8000"}])
        sources = list(self.source.rglob("*.py")) if self.source.is_dir() else [self.source]
        for fp in sources:
            if "__pycache__" in str(fp):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            endpoints = self._parse_fastapi(text, str(fp))
            spec.endpoints.extend(endpoints)

            if not endpoints:
                endpoints = self._parse_flask(text, str(fp))
                spec.endpoints.extend(endpoints)

            if not endpoints:
                endpoints = self._parse_django(text, str(fp))
                spec.endpoints.extend(endpoints)

        return spec

    def _parse_fastapi(self, text: str, file_path: str) -> list[Endpoint]:
        endpoints: list[Endpoint] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return endpoints

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for deco in node.decorator_list:
                method = self._extract_fastapi_method(deco)
                if not method:
                    continue
                path = self._extract_fastapi_path(deco)
                ep = Endpoint(
                    method=method.upper(),
                    path=path or "/",
                    summary=ast.get_docstring(node) or "",
                    source_file=file_path,
                    source_line=node.lineno,
                )

                for arg_node in ast.walk(node):
                    if isinstance(arg_node, ast.AnnAssign) and isinstance(arg_node.target, ast.Name):
                        ep.params.append({
                            "name": arg_node.target.id,
                            "in": "query",
                            "type": self._type_name(arg_node.annotation),
                            "required": True,
                        })

                endpoints.append(ep)
        return endpoints

    def _parse_flask(self, text: str, file_path: str) -> list[Endpoint]:
        endpoints: list[Endpoint] = []
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"@(\w+)\.(route)\s*\(\s*['\"]([^'\"]+)['\"]", line)
            if not m:
                continue
            path = m.group(3)
            methods = ["GET"]
            methods_m = re.search(r"methods\s*=\s*\[([^\]]+)\]", line)
            if methods_m:
                methods = [m.strip().strip("'\"").upper() for m in methods_m.group(1).split(",")]
            doc = ""
            if i + 1 < len(lines):
                doc_match = re.search(r'"""(.*?)"""', lines[i + 1], re.DOTALL)
                if doc_match:
                    doc = doc_match.group(1).strip()
            for meth in methods:
                endpoints.append(Endpoint(method=meth, path=path, summary=doc, source_file=file_path, source_line=i + 1))
        return endpoints

    def _parse_django(self, text: str, file_path: str) -> list[Endpoint]:
        endpoints: list[Endpoint] = []
        patterns = [
            (r"path\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\w+)", "GET"),
            (r"re_path\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\w+)", "GET"),
            (r"url\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\w+)", "GET"),
        ]
        for pat, method in patterns:
            for m in re.finditer(pat, text):
                endpoints.append(Endpoint(method=method, path=m.group(1), source_file=file_path, source_line=text[:m.start()].count("\n") + 1))
        return endpoints

    def _extract_fastapi_method(self, deco_node: ast.expr) -> Optional[str]:
        if isinstance(deco_node, ast.Call) and isinstance(deco_node.func, ast.Attribute):
            full = f"{self._get_attr_name(deco_node.func.value)}.{deco_node.func.attr}" if hasattr(deco_node.func, 'value') else ""
        elif isinstance(deco_node, ast.Attribute):
            full = f"{self._get_attr_name(deco_node.value)}.{deco_node.attr}" if hasattr(deco_node, 'value') else ""
        else:
            return None

        attr_to_method = {
            "get": "GET", "post": "POST", "put": "PUT",
            "delete": "DELETE", "patch": "PATCH",
        }
        for attr, method in attr_to_method.items():
            if full.endswith(f".{attr}"):
                return method
        return None

    def _extract_fastapi_path(self, deco_node: ast.expr) -> Optional[str]:
        if isinstance(deco_node, ast.Call) and deco_node.args:
            if isinstance(deco_node.args[0], ast.Constant):
                return deco_node.args[0].value
        return None

    def _get_attr_name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._get_attr_name(node.value)}.{node.attr}"
        return ""

    def _type_name(self, node: Optional[ast.expr]) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Subscript):
            return "array"
        return "string"
