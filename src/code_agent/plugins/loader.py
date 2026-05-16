from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any

from code_agent.tools.base import Tool


def discover_tools(module_path: str) -> list[type[Tool]]:
    module = importlib.import_module(module_path)
    tools: list[type[Tool]] = []
    for name, obj in inspect.getmembers(module):
        if (inspect.isclass(obj) and issubclass(obj, Tool) and obj is not Tool
                and obj.__module__ == module.__name__):
            tools.append(obj)
    return tools


def load_tool_module(file_path: str) -> list[type[Tool]]:
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Plugin not found: {file_path}")

    import importlib.util
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    if not spec or not spec.loader:
        raise ImportError(f"Could not load plugin: {file_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tools: list[type[Tool]] = []
    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and issubclass(obj, Tool) and obj is not Tool:
            tools.append(obj)
    return tools


class PluginLoader:
    def __init__(self):
        self._loaded: dict[str, list[type[Tool]]] = {}

    def load_package(self, package_name: str) -> list[type[Tool]]:
        tools = discover_tools(package_name)
        self._loaded[package_name] = tools
        return tools

    def load_file(self, file_path: str) -> list[type[Tool]]:
        tools = load_tool_module(file_path)
        self._loaded[file_path] = tools
        return tools

    def load_directory(self, dir_path: str) -> dict[str, list[type[Tool]]]:
        root = Path(dir_path)
        results: dict[str, list[type[Tool]]] = {}
        for p in root.glob("**/*.py"):
            if p.name.startswith("_"):
                continue
            try:
                tools = load_tool_module(str(p))
                if tools:
                    results[str(p)] = tools
            except Exception:
                continue
        self._loaded.update(results)
        return results

    def all_tools(self) -> list[type[Tool]]:
        result: list[type[Tool]] = []
        for tools in self._loaded.values():
            result.extend(tools)
        return result

    def scan_entry_points(self) -> list[type[Tool]]:
        tools: list[type[Tool]] = []
        for ep in pkgutil.iter_modules():
            if "code_agent_tool" in ep.name or "code_agent_plugin" in ep.name:
                try:
                    mod = importlib.import_module(ep.name)
                    found = [obj for _, obj in inspect.getmembers(mod)
                             if inspect.isclass(obj) and issubclass(obj, Tool) and obj is not Tool]
                    tools.extend(found)
                except Exception:
                    continue
        return tools
