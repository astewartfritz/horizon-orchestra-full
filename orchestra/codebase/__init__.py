"""Horizon Orchestra — Codebase Agent.

Full repository awareness: indexing, AST parsing, multi-file editing,
git operations, test-driven development loop, and multi-agent worktrees.
"""

from .indexer import RepoIndexer, FileIndex, SymbolIndex
from .editor import CodeEditor, EditOperation, EditResult
from .git_ops import GitOps, GitConfig
from .tdd_loop import TDDLoop, TDDConfig
from .worktrees import WorktreeManager, Worktree, MergeResult
from .hardening import CodeValidator, TestCoverageAnalyzer, CodeQualityGate, ValidationReport

__all__ = [
    "RepoIndexer", "FileIndex", "SymbolIndex",
    "CodeEditor", "EditOperation", "EditResult",
    "GitOps", "GitConfig",
    "TDDLoop", "TDDConfig",
    "WorktreeManager", "Worktree", "MergeResult",
    "CodeValidator", "TestCoverageAnalyzer", "CodeQualityGate", "ValidationReport",
]
