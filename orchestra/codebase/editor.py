"""Horizon Orchestra — Multi-File Code Editor.

Surgical, diff-aware code editing with atomic batch operations and rollback.
Supports replace, insert, delete, append, and file creation operations,
all relative to a configurable ``repo_root``.

Usage::

    from orchestra.codebase.editor import CodeEditor, EditOperation, OperationType

    editor = CodeEditor(repo_root="/path/to/repo")
    result = editor.apply(EditOperation(
        file_path="src/main.py",
        operation=OperationType.REPLACE,
        old_text="def hello():",
        new_text="def hello(name: str):",
    ))
    print(result.diff_preview)
"""

from __future__ import annotations
# ── IngestionGate: scan every AI-generated file before writing ─────────────
try:
    from ..guardian.ingestion_gate import IngestionGate as _IngestionGateCls
    from ..guardian.audit_ledger import AuditLedger as _EditorLedger
    _INGESTION_GATE = _IngestionGateCls()
    _EDITOR_LEDGER = _EditorLedger()
    _GATE_ACTIVE = True
except Exception:
    _INGESTION_GATE = _EDITOR_LEDGER = None  # type: ignore
    _GATE_ACTIVE = False


import difflib
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

__all__ = [
    "OperationType",
    "EditOperation",
    "EditResult",
    "CodeEditor",
]

log = logging.getLogger("orchestra.codebase.editor")


# ---------------------------------------------------------------------------
# Enumerations & data structures
# ---------------------------------------------------------------------------

class OperationType(str, Enum):
    """Types of edit operations supported by the code editor."""

    REPLACE = "replace"
    INSERT_AFTER = "insert_after"
    INSERT_BEFORE = "insert_before"
    DELETE = "delete"
    APPEND = "append"
    CREATE_FILE = "create_file"


@dataclass
class EditOperation:
    """A single, atomic edit to apply to a file.

    Attributes:
        file_path: Path relative to the editor's ``repo_root``.
        operation: The type of edit to perform.
        new_text: Replacement or insertion text. Required for all operations
            except DELETE.
        old_text: Text to locate in the file. Required for REPLACE,
            INSERT_AFTER, INSERT_BEFORE, and DELETE.
        occurrence: Which occurrence to replace (1-based); 0 = all.
    """

    file_path: str
    operation: OperationType = OperationType.REPLACE
    old_text: str = ""
    new_text: str = ""
    occurrence: int = 1  # 1-based; 0 = replace all occurrences


@dataclass
class EditResult:
    """Outcome of a single edit operation.

    Attributes:
        success: Whether the operation completed without errors.
        file_path: The file that was edited (or attempted).
        operation: The operation that was applied.
        diff_preview: Unified diff showing what changed.
        error: Human-readable error message if ``success`` is False.
        lines_changed: Number of lines that were altered.
    """

    success: bool
    file_path: str
    operation: OperationType
    diff_preview: str = ""
    error: str = ""
    lines_changed: int = 0


# ---------------------------------------------------------------------------
# CodeEditor
# ---------------------------------------------------------------------------

class CodeEditor:
    """Multi-file code editor with surgical edits and batch rollback.

    All file paths in operations are treated as relative to ``repo_root``
    unless they are absolute paths that still fall within ``repo_root``.

    Args:
        repo_root: Root directory for all file operations. Defaults to
            the current working directory.
    """

    def __init__(self, repo_root: str | Path = ".") -> None:
        self.repo_root = Path(repo_root).resolve()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(self, op: EditOperation) -> EditResult:
        """Apply a single edit operation.

        Returns an :class:`EditResult` describing success or failure.
        The file is only written if the operation succeeds.
        """
        try:
            abs_path = self._resolve(op.file_path)

            if op.operation == OperationType.CREATE_FILE:
                return self._op_create_file(abs_path, op)

            if not abs_path.exists():
                return EditResult(
                    success=False,
                    file_path=op.file_path,
                    operation=op.operation,
                    error=f"File not found: {op.file_path}",
                )

            old_content = abs_path.read_text(encoding="utf-8", errors="replace")
            new_content, error = self._transform(old_content, op)
            if error:
                return EditResult(
                    success=False,
                    file_path=op.file_path,
                    operation=op.operation,
                    error=error,
                )

            diff = self._generate_diff(old_content, new_content, op.file_path)
            lines_changed = diff.count("\n+") + diff.count("\n-")
            abs_path.write_text(new_content, encoding="utf-8")
            log.debug("Applied %s to %s (%d lines changed)", op.operation, op.file_path, lines_changed)
            return EditResult(
                success=True,
                file_path=op.file_path,
                operation=op.operation,
                diff_preview=diff,
                lines_changed=lines_changed,
            )

        except Exception as exc:
            log.exception("Unexpected error applying %s to %s", op.operation, op.file_path)
            return EditResult(
                success=False,
                file_path=op.file_path,
                operation=op.operation,
                error=str(exc),
            )

    def apply_batch(self, ops: list[EditOperation]) -> list[EditResult]:
        """Apply a list of operations atomically.

        If **any** operation fails, all successful operations in the batch
        are rolled back using pre-operation backups. The method always
        returns the full list of results even when rolling back.

        Args:
            ops: Ordered list of operations to apply.

        Returns:
            List of :class:`EditResult` objects, one per operation.
        """
        if not ops:
            return []

        # Take backups of all files that will be modified
        backups: dict[str, str | None] = {}  # abs_path_str → original_content or None
        for op in ops:
            if op.operation == OperationType.CREATE_FILE:
                abs_path = self._resolve(op.file_path)
                if not abs_path.exists():
                    backups[str(abs_path)] = None  # will be created
                else:
                    backups[str(abs_path)] = abs_path.read_text(encoding="utf-8", errors="replace")
            else:
                abs_path = self._resolve(op.file_path)
                if abs_path.exists():
                    if str(abs_path) not in backups:
                        backups[str(abs_path)] = abs_path.read_text(encoding="utf-8", errors="replace")
                else:
                    backups[str(abs_path)] = None

        results: list[EditResult] = []
        failed = False

        for op in ops:
            result = self.apply(op)
            results.append(result)
            if not result.success:
                failed = True
                break

        if failed:
            log.warning("Batch failed at op %d; rolling back %d files", len(results), len(backups))
            self._rollback(backups)
            # Mark remaining ops as not-run
            for op in ops[len(results):]:
                results.append(EditResult(
                    success=False,
                    file_path=op.file_path,
                    operation=op.operation,
                    error="Batch rolled back due to earlier failure",
                ))

        return results

    def read_file(self, path: str) -> str:
        """Read and return the full content of a file.

        Args:
            path: Path relative to ``repo_root``.

        Returns:
            File content as a UTF-8 string.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        abs_path = self._resolve(path)
        if not abs_path.exists():
            raise FileNotFoundError(f"File not found: {path!r}")
        return abs_path.read_text(encoding="utf-8", errors="replace")

    def read_range(self, path: str, start_line: int, end_line: int) -> str:
        """Read a range of lines from a file (1-based, inclusive).

        Args:
            path: Path relative to ``repo_root``.
            start_line: First line to include (1-based).
            end_line: Last line to include (1-based, inclusive).

        Returns:
            Selected lines joined with newlines.
        """
        content = self.read_file(path)
        lines = content.splitlines(keepends=True)
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)
        return "".join(lines[start_idx:end_idx])

    def search_replace(
        self,
        path: str,
        pattern: str,
        replacement: str,
        regex: bool = False,
    ) -> EditResult:
        """Search for ``pattern`` in a file and replace all occurrences.

        Args:
            path: Path relative to ``repo_root``.
            pattern: Literal string or regex pattern to search for.
            replacement: Replacement text. Supports regex back-references
                when ``regex=True``.
            regex: If True, treat ``pattern`` as a regular expression.

        Returns:
            :class:`EditResult` describing the outcome.
        """
        try:
            abs_path = self._resolve(path)
            if not abs_path.exists():
                return EditResult(
                    success=False,
                    file_path=path,
                    operation=OperationType.REPLACE,
                    error=f"File not found: {path}",
                )

            old_content = abs_path.read_text(encoding="utf-8", errors="replace")
            if regex:
                new_content = re.sub(pattern, replacement, old_content)
            else:
                new_content = old_content.replace(pattern, replacement)

            diff = self._generate_diff(old_content, new_content, path)
            lines_changed = diff.count("\n+") + diff.count("\n-")
            abs_path.write_text(new_content, encoding="utf-8")
            log.debug("search_replace in %s: %d lines changed", path, lines_changed)
            return EditResult(
                success=True,
                file_path=path,
                operation=OperationType.REPLACE,
                diff_preview=diff,
                lines_changed=lines_changed,
            )

        except re.error as exc:
            return EditResult(
                success=False,
                file_path=path,
                operation=OperationType.REPLACE,
                error=f"Invalid regex pattern: {exc}",
            )
        except Exception as exc:
            log.exception("search_replace failed for %s", path)
            return EditResult(
                success=False,
                file_path=path,
                operation=OperationType.REPLACE,
                error=str(exc),
            )

    def create_file(self, path: str, content: str,
                     agent_id: str = "codebase-agent") -> EditResult:
        # ── IngestionGate scan before creating file ────────────────────────
        if _GATE_ACTIVE and _INGESTION_GATE is not None:
            try:
                import asyncio as _cig
                _report = _cig.run(_INGESTION_GATE.check(content, path, agent_id))
                if not _report.approved:
                    import logging as _log
                    _log.getLogger("orchestra.codebase.editor").error(
                        "[SECURITY] IngestionGate BLOCKED create of %s — violations: %s",
                        path, [str(v) for v in getattr(_report, 'blocking_violations', [])]
                    )
                    return EditResult(success=False, ops_applied=0, errors=[f"IngestionGate blocked: security violations detected in {path}"])
            except Exception:
                pass  # Gate unavailable — allow but log
        """Create a new file with the given content.

        Parent directories are created automatically. If the file already
        exists it will be overwritten.

        Args:
            path: Path relative to ``repo_root``.
            content: Initial file content.

        Returns:
            :class:`EditResult` describing the outcome.
        """
        op = EditOperation(
            file_path=path,
            operation=OperationType.CREATE_FILE,
            new_text=content,
        )
        return self.apply(op)

    # ------------------------------------------------------------------
    # Diff generation
    # ------------------------------------------------------------------

    def _generate_diff(self, old: str, new: str, filename: str = "file") -> str:
        """Generate a unified diff between *old* and *new* content.

        Args:
            old: Original file content.
            new: New file content after the edit.
            filename: Label used in the diff header.

        Returns:
            Unified diff string. Empty string if there are no changes.
        """
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}",
                lineterm="",
            )
        )
        return "\n".join(diff_lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        """Resolve *path* relative to ``repo_root``.

        Absolute paths are allowed only if they are under ``repo_root``.
        """
        p = Path(path)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self.repo_root / p).resolve()
        # Security: ensure the resolved path stays within repo_root
        try:
            resolved.relative_to(self.repo_root)
        except ValueError:
            raise PermissionError(
                f"Path {path!r} escapes repo_root {self.repo_root!r}"
            )
        return resolved

    def _transform(self, content: str, op: EditOperation) -> tuple[str, str]:
        """Apply *op* to *content*, returning (new_content, error_or_empty).

        Returns:
            Tuple of ``(new_content, error_message)``.  If the operation
            succeeds, ``error_message`` is an empty string.
        """
        if op.operation == OperationType.REPLACE:
            return self._op_replace(content, op)
        elif op.operation == OperationType.INSERT_AFTER:
            return self._op_insert_after(content, op)
        elif op.operation == OperationType.INSERT_BEFORE:
            return self._op_insert_before(content, op)
        elif op.operation == OperationType.DELETE:
            return self._op_delete(content, op)
        elif op.operation == OperationType.APPEND:
            return self._op_append(content, op)
        else:
            return content, f"Unknown operation: {op.operation}"

    def _op_replace(self, content: str, op: EditOperation) -> tuple[str, str]:
        """Replace ``old_text`` with ``new_text``."""
        if not op.old_text:
            return content, "old_text is required for REPLACE operation"
        if op.old_text not in content:
            return content, f"old_text not found in file: {op.old_text[:80]!r}"

        if op.occurrence == 0:
            # Replace all occurrences
            new_content = content.replace(op.old_text, op.new_text)
        else:
            # Replace the Nth occurrence (1-based)
            idx = -1
            for _ in range(op.occurrence):
                idx = content.find(op.old_text, idx + 1)
                if idx == -1:
                    return content, (
                        f"Occurrence {op.occurrence} of old_text not found"
                    )
            new_content = (
                content[:idx]
                + op.new_text
                + content[idx + len(op.old_text):]
            )

        return new_content, ""

    def _op_insert_after(self, content: str, op: EditOperation) -> tuple[str, str]:
        """Insert ``new_text`` immediately after the line containing ``old_text``."""
        if not op.old_text:
            return content, "old_text is required for INSERT_AFTER operation"

        lines = content.splitlines(keepends=True)
        insert_idx = None
        count = 0

        for i, line in enumerate(lines):
            if op.old_text in line:
                count += 1
                if op.occurrence == 0 or count == op.occurrence:
                    insert_idx = i + 1
                    if op.occurrence != 0:
                        break

        if insert_idx is None:
            return content, f"Anchor text not found: {op.old_text[:80]!r}"

        insert_text = op.new_text
        if not insert_text.endswith("\n"):
            insert_text += "\n"

        lines.insert(insert_idx, insert_text)
        return "".join(lines), ""

    def _op_insert_before(self, content: str, op: EditOperation) -> tuple[str, str]:
        """Insert ``new_text`` immediately before the line containing ``old_text``."""
        if not op.old_text:
            return content, "old_text is required for INSERT_BEFORE operation"

        lines = content.splitlines(keepends=True)
        insert_idx = None
        count = 0

        for i, line in enumerate(lines):
            if op.old_text in line:
                count += 1
                if op.occurrence == 0 or count == op.occurrence:
                    insert_idx = i
                    if op.occurrence != 0:
                        break

        if insert_idx is None:
            return content, f"Anchor text not found: {op.old_text[:80]!r}"

        insert_text = op.new_text
        if not insert_text.endswith("\n"):
            insert_text += "\n"

        lines.insert(insert_idx, insert_text)
        return "".join(lines), ""

    def _op_delete(self, content: str, op: EditOperation) -> tuple[str, str]:
        """Delete text matching ``old_text`` from the file."""
        if not op.old_text:
            return content, "old_text is required for DELETE operation"
        if op.old_text not in content:
            return content, f"old_text not found in file: {op.old_text[:80]!r}"

        if op.occurrence == 0:
            new_content = content.replace(op.old_text, "")
        else:
            idx = -1
            for _ in range(op.occurrence):
                idx = content.find(op.old_text, idx + 1)
                if idx == -1:
                    return content, f"Occurrence {op.occurrence} not found"
            new_content = content[:idx] + content[idx + len(op.old_text):]

        return new_content, ""

    def _op_append(self, content: str, op: EditOperation) -> tuple[str, str]:
        """Append ``new_text`` to the end of the file."""
        separator = "\n" if content and not content.endswith("\n") else ""
        return content + separator + op.new_text, ""

    def _op_create_file(self, abs_path: Path, op: EditOperation) -> EditResult:
        """Create a new file (or overwrite an existing one)."""
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            old_content = abs_path.read_text(encoding="utf-8", errors="replace") if abs_path.exists() else ""
            abs_path.write_text(op.new_text, encoding="utf-8")
            diff = self._generate_diff(old_content, op.new_text, op.file_path)
            log.info("Created file %s (%d bytes)", op.file_path, len(op.new_text))
            return EditResult(
                success=True,
                file_path=op.file_path,
                operation=OperationType.CREATE_FILE,
                diff_preview=diff,
                lines_changed=op.new_text.count("\n"),
            )
        except Exception as exc:
            return EditResult(
                success=False,
                file_path=op.file_path,
                operation=OperationType.CREATE_FILE,
                error=str(exc),
            )

    def _rollback(self, backups: dict[str, str | None]) -> None:
        """Restore files from pre-operation backups.

        Args:
            backups: Mapping from absolute path string to original content,
                or ``None`` if the file was newly created (and should be
                deleted on rollback).
        """
        for abs_path_str, original_content in backups.items():
            abs_path = Path(abs_path_str)
            try:
                if original_content is None:
                    # File was created by this batch; remove it
                    abs_path.unlink(missing_ok=True)
                    log.debug("Rollback: deleted %s", abs_path_str)
                else:
                    abs_path.write_text(original_content, encoding="utf-8")
                    log.debug("Rollback: restored %s", abs_path_str)
            except Exception as exc:
                log.error("Rollback failed for %s: %s", abs_path_str, exc)
