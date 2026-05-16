from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MdSection:
    heading: str
    level: int
    content: str
    children: list[MdSection] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    pairs: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "heading": self.heading,
            "content": self.content.strip(),
        }
        if self.pairs:
            d["pairs"] = self.pairs
        if self.items:
            d["items"] = self.items
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class MdConfig:
    frontmatter: dict[str, Any] = field(default_factory=dict)
    sections: list[MdSection] = field(default_factory=list)
    raw_text: str = ""

    def get_section(self, name: str) -> MdSection | None:
        for s in self.sections:
            if s.heading.lower() == name.lower():
                return s
            for c in s.children:
                if c.heading.lower() == name.lower():
                    return c
        return None

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.frontmatter:
            return self.frontmatter[key]
        for s in self.sections:
            if key in s.pairs:
                return s.pairs[key]
            if s.heading.lower() == key.lower():
                return s
        return default

    def to_dict(self) -> dict[str, Any]:
        return {
            "frontmatter": self.frontmatter,
            "sections": [s.to_dict() for s in self.sections],
        }


_YAML_LINE = re.compile(r"^(\s*[\w.-]+)\s*:\s*(.*)$")
_LIST_ITEM = re.compile(r"^[\s]*[-*+]\s+(.*)$")
_NUMBERED_ITEM = re.compile(r"^[\s]*\d+[.)]\s+(.*)$")
_CODE_BLOCK = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def parse_md(file_path: str | Path) -> MdConfig:
    """Parse a Markdown file into structured config data."""
    path = Path(file_path)
    raw = path.read_text("utf-8") if path.exists() else file_path
    return parse_md_text(raw)


def parse_md_text(text: str) -> MdConfig:
    """Parse Markdown text into structured config data."""
    config = MdConfig(raw_text=text)

    # Strip code blocks before parsing (but keep for reference)
    code_blocks: list[tuple[str, str]] = []
    def _save_code(m: re.Match) -> str:
        lang = m.group(1)
        code = m.group(2)
        code_blocks.append((lang, code))
        return f"```{lang}\n...\n```"
    text_no_code = _CODE_BLOCK.sub(_save_code, text)

    # Extract YAML frontmatter
    if text_no_code.startswith("---"):
        end = text_no_code.find("---", 3)
        if end != -1:
            fm_text = text_no_code[3:end]
            config.frontmatter = _parse_yaml_lines(fm_text)
            text_no_code = text_no_code[end + 3:]

    # Parse sections by headings
    lines = text_no_code.split("\n")
    current_section: MdSection | None = None
    current_parent: MdSection | None = None
    section_stack: list[MdSection] = []

    for line in lines:
        stripped = line.strip()
        hm = _HEADING.match(line)
        if hm:
            level = len(hm.group(1))
            heading = hm.group(2).strip()
            new_section = MdSection(heading=heading, level=level, content="")
            if level == 1 or not section_stack:
                config.sections.append(new_section)
                section_stack = [new_section]
            else:
                while section_stack and section_stack[-1].level >= level:
                    section_stack.pop()
                if section_stack:
                    section_stack[-1].children.append(new_section)
                else:
                    config.sections.append(new_section)
                section_stack.append(new_section)
            current_section = new_section
            current_parent = section_stack[-2] if len(section_stack) >= 2 else None
            continue

        if current_section is None:
            continue

        # Parse key: value pairs
        ym = _YAML_LINE.match(stripped)
        if ym:
            key = ym.group(1).strip()
            val = ym.group(2).strip()
            current_section.pairs[key] = val
            current_section.content += line + "\n"
            continue

        # Parse list items
        lm = _LIST_ITEM.match(stripped)
        if lm:
            current_section.items.append(lm.group(1).strip())
            current_section.content += line + "\n"
            continue

        nm = _NUMBERED_ITEM.match(stripped)
        if nm:
            current_section.items.append(nm.group(1).strip())
            current_section.content += line + "\n"
            continue

        current_section.content += line + "\n"

    # Restore code blocks into section content (best effort)
    _restore_code_blocks(config, code_blocks)

    return config


def _parse_yaml_lines(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    stack: list[tuple[str, Any, int]] = [("", result, -1)]
    current_key: str | None = None
    pending_list_key: str | None = None
    pending_list_parent: dict | None = None

    for line in text.split("\n"):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        # List item (- item)
        lm = _LIST_ITEM.match(stripped)
        if lm and current_key:
            while len(stack) > 1 and indent <= stack[-1][2]:
                stack.pop()
            current_dict = stack[-1][1]
            if not isinstance(current_dict, dict):
                continue
            # Initialize list if needed
            if pending_list_key:
                current_dict[pending_list_key] = current_dict.get(pending_list_key, [])
                if isinstance(current_dict[pending_list_key], dict):
                    current_dict[pending_list_key] = []
                current_dict[pending_list_key].append(lm.group(1).strip())
            continue

        # Key: value
        ym = _YAML_LINE.match(stripped)
        if ym:
            key = ym.group(1).strip()
            val = ym.group(2).strip()
            current_key = key
            pending_list_key = key

            # Navigate to correct parent based on indent
            while len(stack) > 1 and indent <= stack[-1][2]:
                stack.pop()
            current_dict = stack[-1][1]

            if not isinstance(current_dict, dict):
                continue

            if not val:
                # Could be nested dict or list - defer decision until we see next line
                placeholder: dict[str, Any] | list = {}
                current_dict[key] = placeholder
                stack.append((key, placeholder, indent))
            else:
                pending_list_key = None
                parsed = _parse_yaml_value(val)
                current_dict[key] = parsed

    return result


def _parse_yaml_value(val: str) -> Any:
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    if val.isdigit():
        return int(val)
    if _is_float(val):
        return float(val)
    if val.startswith("[") and val.endswith("]"):
        return [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
    return val.strip("'\"")


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _restore_code_blocks(config: MdConfig, blocks: list[tuple[str, str]]) -> None:
    """Re-insert code blocks into the last matching section."""
    if not blocks:
        return
    for lang, code in blocks:
        for section in config.sections:
            if f"```{lang}\n...\n```" in section.content:
                section.content = section.content.replace(
                    f"```{lang}\n...\n```", f"```{lang}\n{code}```"
                )
                section.pairs[f"code_{lang}"] = code
                break


def extract_frontmatter(file_path: str | Path) -> dict[str, Any]:
    """Quick extraction of just the YAML frontmatter."""
    path = Path(file_path)
    if not path.exists():
        return {}
    text = path.read_text("utf-8")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return _parse_yaml_lines(text[3:end])
    return {}
