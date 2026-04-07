"""Horizon Orchestra — Plugin System.

Dynamic loading of skills and connectors from the filesystem at runtime.
Drop a Python file into ``~/.horizon/plugins/`` and it auto-registers.

Plugin structure::

    ~/.horizon/plugins/
    ├── my_connector.py    # must define a class inheriting Connector
    └── my_skill.py        # must define a class inheriting Skill

Usage::

    from orchestra.plugins import PluginLoader
    loader = PluginLoader()
    loader.discover()
    loader.register_all(tool_registry, connector_registry)
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Any

from .connectors.base import Connector, ConnectorRegistry
from .skills.base import Skill, SkillRegistry

__all__ = ["PluginLoader", "PluginInfo"]

log = logging.getLogger("orchestra.plugins")

DEFAULT_PLUGIN_DIRS = [
    Path.home() / ".horizon" / "plugins",
    Path("plugins"),
]


class PluginInfo:
    """Metadata about a discovered plugin."""

    def __init__(
        self,
        path: Path,
        plugin_type: str,
        cls: type,
        name: str,
    ) -> None:
        self.path = path
        self.plugin_type = plugin_type   # "connector" | "skill"
        self.cls = cls
        self.name = name
        self.loaded = False
        self.error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.plugin_type,
            "path": str(self.path),
            "loaded": self.loaded,
            "error": self.error,
        }


class PluginLoader:
    """Discovers and loads plugins from filesystem directories."""

    def __init__(self, plugin_dirs: list[Path] | None = None) -> None:
        self.plugin_dirs = plugin_dirs or DEFAULT_PLUGIN_DIRS
        self._plugins: list[PluginInfo] = []

    def discover(self) -> list[PluginInfo]:
        """Scan plugin directories for .py files containing Connector or Skill subclasses."""
        self._plugins.clear()

        for plugin_dir in self.plugin_dirs:
            if not plugin_dir.exists():
                continue

            for py_file in sorted(plugin_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                try:
                    plugins = self._load_module(py_file)
                    self._plugins.extend(plugins)
                except Exception as exc:
                    log.warning("Failed to load plugin %s: %s", py_file, exc)
                    self._plugins.append(PluginInfo(
                        path=py_file, plugin_type="unknown",
                        cls=type(None), name=py_file.stem,
                    ))
                    self._plugins[-1].error = str(exc)

        log.info(
            "Discovered %d plugins: %s",
            len(self._plugins),
            [p.name for p in self._plugins],
        )
        return self._plugins

    def _load_module(self, path: Path) -> list[PluginInfo]:
        """Load a Python module and extract Connector/Skill subclasses."""
        module_name = f"orchestra_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            raise ImportError(f"Cannot create module spec for {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        found: list[PluginInfo] = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Skip base classes and imported classes
            if obj.__module__ != module_name:
                continue

            if issubclass(obj, Connector) and obj is not Connector:
                info = PluginInfo(
                    path=path, plugin_type="connector",
                    cls=obj, name=getattr(obj, "name", name),
                )
                found.append(info)
                log.debug("Found connector plugin: %s in %s", name, path)

            elif issubclass(obj, Skill) and obj is not Skill:
                info = PluginInfo(
                    path=path, plugin_type="skill",
                    cls=obj, name=getattr(obj, "name", name),
                )
                found.append(info)
                log.debug("Found skill plugin: %s in %s", name, path)

        return found

    def register_all(
        self,
        tool_registry: Any = None,
        connector_registry: ConnectorRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> dict[str, int]:
        """Instantiate and register all discovered plugins.

        Returns a count of registered connectors and skills.
        """
        counts = {"connectors": 0, "skills": 0, "errors": 0}

        for plugin in self._plugins:
            if plugin.error:
                counts["errors"] += 1
                continue

            try:
                instance = plugin.cls()

                if plugin.plugin_type == "connector":
                    if connector_registry:
                        connector_registry.register(instance)
                    if tool_registry and hasattr(instance, "get_tool_definitions"):
                        # Will be registered when connected
                        pass
                    plugin.loaded = True
                    counts["connectors"] += 1

                elif plugin.plugin_type == "skill":
                    if skill_registry:
                        skill_registry.register(instance)
                        if tool_registry:
                            # Register this skill's tools
                            for tool_def in instance.get_tool_definitions():
                                fn = tool_def.get("function", {})
                                tool_name = fn.get("name", "")
                                if tool_name:
                                    _inst = instance
                                    _action = tool_name

                                    async def _handler(_s=_inst, _a=_action, **kwargs):
                                        import json
                                        result = await _s.execute(_a, kwargs)
                                        return json.dumps(result)

                                    tool_registry.register(
                                        name=tool_name,
                                        description=fn.get("description", ""),
                                        parameters=fn.get("parameters", {}),
                                        handler=_handler,
                                    )
                    plugin.loaded = True
                    counts["skills"] += 1

            except Exception as exc:
                plugin.error = str(exc)
                counts["errors"] += 1
                log.warning("Failed to register plugin %s: %s", plugin.name, exc)

        log.info(
            "Registered plugins: %d connectors, %d skills, %d errors",
            counts["connectors"], counts["skills"], counts["errors"],
        )
        return counts

    def list_plugins(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._plugins]

    @property
    def plugins(self) -> list[PluginInfo]:
        return list(self._plugins)
