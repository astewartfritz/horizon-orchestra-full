from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MigrationRule:
    name: str
    description: str
    pattern: str
    replacement: str
    file_pattern: str = "*.py"


@dataclass
class MigrationPlan:
    name: str
    description: str
    rules: list[MigrationRule] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)


_MIGRATIONS: dict[str, MigrationPlan] = {
    "flask-to-fastapi": MigrationPlan(
        name="flask-to-fastapi",
        description="Migrate Flask routes to FastAPI endpoints",
        rules=[
            MigrationRule("imports", "Replace Flask imports with FastAPI", "from flask import", "from fastapi import"),
            MigrationRule("app_init", "Replace Flask app init with FastAPI", 'app = Flask\\(__name__\\)', "app = FastAPI()"),
            MigrationRule("route", "Replace @app.route with decorators",
                r'@app\.route\(["\']([^"\']+)["\'],\s*methods=\[([^\]]+)\]\)',
                r'@app.api_route("\1", methods=[\2])'),
            MigrationRule("jsonify", "Replace jsonify with JSONResponse", r"jsonify\(", "JSONResponse("),
            MigrationRule("request_json", "Replace request.json", r"request\.json", "await request.json()"),
            MigrationRule("url_for", "Replace url_for", r"url_for\(([^)]+)\)", r"url_path_for(\1)"),
        ],
    ),
    "python2-to-python3": MigrationPlan(
        name="python2-to-python3",
        description="Migrate Python 2 code to Python 3",
        rules=[
            MigrationRule("print", "Replace print statement", r'print\s+(?!>>)(.+)$', r"print(\1)"),
            MigrationRule("except", "Replace except-as", r'except\s+(\w+)\s*,\s*(\w+)\s*:', r"except \1 as \2:"),
            MigrationRule("unicode", "Remove unicode prefix", r'unicode\(', r"str("),
            MigrationRule("basestring", "Replace basestring", r'basestring', r"str"),
            MigrationRule("xrange", "Replace xrange", r'xrange\(', r"range("),
            MigrationRule("iteritems", "Replace iteritems", r'\.iteritems\(\)', r".items()"),
            MigrationRule("itervalues", "Replace itervalues", r'\.itervalues\(\)', r".values()"),
            MigrationRule("raw_input", "Replace raw_input", r'raw_input\(', r"input("),
        ],
    ),
    "tensorflow1-to-tensorflow2": MigrationPlan(
        name="tensorflow1-to-tensorflow2",
        description="Migrate TensorFlow 1.x to 2.x",
        rules=[
            MigrationRule("session", "Replace session pattern", r'tf\.Session\(\)', r"tf.compat.v1.Session()"),
            MigrationRule("placeholder", "Replace placeholder", r'tf\.placeholder\(', r"tf.compat.v1.placeholder("),
            MigrationRule("global_vars_init", "Replace init", r'tf\.global_variables_initializer\(\)', r"tf.compat.v1.global_variables_initializer()"),
        ],
    ),
    "setup-py-to-pyproject": MigrationPlan(
        name="setup-py-to-pyproject",
        description="Migrate setup.py to pyproject.toml",
        rules=[
            MigrationRule("pep621", "Generate pyproject.toml from setup.py", "", ""),
        ],
    ),
}

_COMMON_REPLACEMENTS: list[tuple[str, str, str]] = [
    (r"typing\.List\[(.+?)\]", r"list[\1]", "Use builtin list"),
    (r"typing\.Dict\[(.+?)\]", r"dict[\1]", "Use builtin dict"),
    (r"typing\.Tuple\[(.+?)\]", r"tuple[\1]", "Use builtin tuple"),
    (r"typing\.Set\[(.+?)\]", r"set[\1]", "Use builtin set"),
    (r"typing\.Optional\[(.+?)\]", r"\1 | None", "Use union syntax"),
    (r"typing\.Union\[(.+?),\s*(.+?)\]", r"\1 | \2", "Use union syntax"),
    (r"@abc\.abstractmethod", r"@abstractmethod", "Simplify decorator"),
    (r"from typing import", r"from collections.abc import", "Modern typing"),
]


class CodeMigrator:
    def __init__(self, source_path: str = "."):
        self.source = Path(source_path).resolve()

    def list_plans(self) -> list[MigrationPlan]:
        return list(_MIGRATIONS.values())

    def get_plan(self, name: str) -> Optional[MigrationPlan]:
        return _MIGRATIONS.get(name)

    def analyze(self, plan_name: str) -> MigrationPlan:
        plan = _MIGRATIONS.get(plan_name)
        if not plan:
            raise ValueError(f"Unknown migration plan: {plan_name}")
        plan.changes = []

        files = list(self.source.rglob("*.py")) if self.source.is_dir() else [self.source]
        for fp in files:
            if "__pycache__" in str(fp):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for rule in plan.rules:
                if not rule.pattern:
                    continue
                try:
                    matches = list(re.finditer(rule.pattern, text, re.MULTILINE))
                except re.error:
                    continue
                for m in matches:
                    plan.changes.append({
                        "file": str(fp.relative_to(self.source) if fp.is_relative_to(self.source) else fp),
                        "line": text[:m.start()].count("\n") + 1,
                        "rule": rule.name,
                        "matched": m.group(),
                    })
        return plan

    def apply(self, plan_name: str, dry_run: bool = True) -> MigrationPlan:
        plan = self.analyze(plan_name)
        if dry_run:
            return plan

        files: dict[str, list[str, str]] = {}
        files_list = list(self.source.rglob("*.py")) if self.source.is_dir() else [self.source]
        for fp in files_list:
            if "__pycache__" in str(fp):
                continue
            try:
                files[str(fp)] = [fp.read_text(encoding="utf-8", errors="replace"), str(fp)]
            except Exception:
                continue

        for rule in plan.rules:
            if not rule.pattern:
                continue
            for fp_str, (text, _) in list(files.items()):
                try:
                    new_text = re.sub(rule.pattern, rule.replacement, text)
                    if new_text != text:
                        files[fp_str][0] = new_text
                except re.error:
                    continue

        for fp_str, (text, _) in files.items():
            Path(fp_str).write_text(text, encoding="utf-8")

        return plan

    def apply_common_fixes(self, dry_run: bool = True) -> list[dict]:
        results: list[dict] = []
        files = list(self.source.rglob("*.py")) if self.source.is_dir() else [self.source]

        for fp in files:
            if "__pycache__" in str(fp):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            changed = False
            for pattern, replacement, desc in _COMMON_REPLACEMENTS:
                try:
                    new_text = re.sub(pattern, replacement, text)
                    if new_text != text:
                        changed = True
                        text = new_text
                        results.append({"file": str(fp), "fix": desc})
                except re.error:
                    continue

            if changed and not dry_run:
                fp.write_text(text, encoding="utf-8")

        return results

    def summary_text(self, plan: MigrationPlan) -> str:
        changes = plan.changes
        lines = [
            f"Migration Plan: {plan.name}",
            f"Description: {plan.description}",
            f"{'=' * 60}",
            f"Total changes: {len(changes)}",
            "",
        ]
        if changes:
            grouped: dict[str, list] = {}
            for c in changes:
                grouped.setdefault(c["file"], []).append(c)
            for file_path, file_changes in sorted(grouped.items()):
                lines.append(f"\n{file_path}: {len(file_changes)} changes")
                for c in file_changes[:5]:
                    lines.append(f"  L{c['line']}: [{c['rule']}] {c['matched'][:80]}")
        return "\n".join(lines)
