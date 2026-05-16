from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SkillsRegistry:
    """Markdown/YAML playbooks that map natural-language intents to tool sequences.

    Skills are stored as .md or .yaml files in the .agent-skills/ directory.
    Each skill describes: intent trigger, required inputs, tool sequence, expected outputs.
    """

    def __init__(self, skills_dir: str = ".agent-skills"):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        for f in sorted(self.skills_dir.glob("*.md")):
            try:
                text = f.read_text("utf-8")
                self._parse_skill(f.stem, text)
            except Exception:
                pass
        for f in sorted(self.skills_dir.glob("*.yaml")):
            try:
                import yaml
                data = yaml.safe_load(f.read_text("utf-8"))
                if isinstance(data, dict) and "name" in data:
                    self._skills[data["name"]] = data
            except Exception:
                pass

    def _parse_skill(self, name: str, text: str) -> None:
        lines = text.strip().split("\n")
        metadata: dict[str, Any] = {"name": name, "steps": []}
        current_step: dict[str, Any] = {}
        for line in lines:
            if line.startswith("# "):
                metadata["title"] = line[2:].strip()
            elif line.startswith("> "):
                metadata.setdefault("description", "").append(line[2:])
            elif line.startswith("- "):
                step_text = line[2:].strip()
                if current_step:
                    metadata["steps"].append(current_step)
                current_step = {"action": step_text}
            elif line.startswith("  - ") and current_step:
                current_step.setdefault("args", []).append(line[4:].strip())
            elif line.startswith("Intent:"):
                metadata["intent"] = line[7:].strip()
            elif line.startswith("Inputs:"):
                metadata["inputs"] = line[7:].strip()
        if current_step:
            metadata["steps"].append(current_step)
        self._skills[name] = metadata

    def list(self) -> list[dict[str, Any]]:
        return [{"name": k, "title": v.get("title", k), "steps": len(v.get("steps", [])),
                 "description": v.get("description", "")} for k, v in self._skills.items()]

    def get(self, name: str) -> dict[str, Any] | None:
        return self._skills.get(name)

    def match_intent(self, text: str) -> list[dict[str, Any]]:
        """Find skills whose intent matches the given text."""
        results = []
        text_lower = text.lower()
        for name, skill in self._skills.items():
            intent = skill.get("intent", "").lower()
            if intent and intent in text_lower:
                results.append(skill)
        return results
