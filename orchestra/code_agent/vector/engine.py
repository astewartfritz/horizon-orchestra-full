from __future__ import annotations

import ast
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CodeChunk:
    file_path: str
    start_line: int
    end_line: int
    content: str
    chunk_type: str = "code"  # code, docstring, comment, function, class
    name: str | None = None
    embedding: list[float] | None = None


@dataclass
class SearchResult:
    chunk: CodeChunk
    score: float


def simple_hash_embedding(text: str, dim: int = 128) -> list[float]:
    vec = [0.0] * dim
    tokens = re.findall(r'\w+', text.lower())
    for i, token in enumerate(tokens):
        h = hash(token + str(i)) % dim
        vec[abs(h)] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class VectorEngine:
    def __init__(self, db_path: str | Path = ".code-agent-vectors.db"):
        self.path = Path(db_path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                start_line INTEGER,
                end_line INTEGER,
                content TEXT,
                chunk_type TEXT,
                name TEXT,
                embedding BLOB
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_file
            ON chunks(file_path)
        """)
        self.conn.commit()

    def index_file(self, file_path: str) -> int:
        p = Path(file_path)
        if not p.exists():
            return 0
        text = p.read_text("utf-8", errors="replace")
        chunks = self._chunk_file(str(p), text)
        count = 0
        for chunk in chunks:
            emb = simple_hash_embedding(chunk.content)
            self.conn.execute(
                "INSERT INTO chunks (file_path, start_line, end_line, content, chunk_type, name, embedding) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chunk.file_path, chunk.start_line, chunk.end_line,
                 chunk.content, chunk.chunk_type, chunk.name,
                 json.dumps(emb)),
            )
            count += 1
        self.conn.commit()
        return count

    def index_directory(self, dir_path: str, glob_pattern: str = "**/*.py") -> int:
        root = Path(dir_path)
        total = 0
        for p in root.glob(glob_pattern):
            if p.is_file():
                total += self.index_file(str(p))
        return total

    def search(self, query: str, top_k: int = 10, file_filter: str | None = None) -> list[SearchResult]:
        query_emb = simple_hash_embedding(query)

        sql = "SELECT file_path, start_line, end_line, content, chunk_type, name, embedding FROM chunks"
        params: list[Any] = []
        if file_filter:
            sql += " WHERE file_path LIKE ?"
            params.append(f"%{file_filter}%")

        rows = self.conn.execute(sql, params).fetchall()
        scored: list[tuple[float, CodeChunk]] = []

        for row in rows:
            file_path, start_line, end_line, content, chunk_type, name, emb_blob = row
            if not emb_blob:
                continue
            stored_emb = json.loads(emb_blob)
            score = self._cosine_sim(query_emb, stored_emb)

            chunk = CodeChunk(
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                content=content,
                chunk_type=chunk_type,
                name=name,
            )
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [SearchResult(chunk=s[1], score=s[0]) for s in scored[:top_k]]

    def remove_file(self, file_path: str) -> None:
        self.conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
        self.conn.commit()

    def stats(self) -> dict[str, Any]:
        count = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        files = self.conn.execute("SELECT COUNT(DISTINCT file_path) FROM chunks").fetchone()[0]
        return {"chunks": count, "files": files}

    def close(self) -> None:
        self.conn.close()

    def _chunk_file(self, file_path: str, text: str) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = node.name
                    start = node.lineno or 1
                    end = node.end_lineno or start
                    content = "\n".join(text.splitlines()[start - 1:end])
                    chunks.append(CodeChunk(
                        file_path=file_path, start_line=start, end_line=end,
                        content=content, chunk_type="function", name=name,
                    ))
                elif isinstance(node, ast.ClassDef):
                    name = node.name
                    start = node.lineno or 1
                    end = node.end_lineno or start
                    content = "\n".join(text.splitlines()[start - 1:end])
                    chunks.append(CodeChunk(
                        file_path=file_path, start_line=start, end_line=end,
                        content=content, chunk_type="class", name=name,
                    ))
        except SyntaxError:
            pass

        if not chunks:
            lines = text.splitlines()
            chunk_size = 50
            for i in range(0, len(lines), chunk_size):
                chunk_lines = lines[i:i + chunk_size]
                chunks.append(CodeChunk(
                    file_path=file_path,
                    start_line=i + 1,
                    end_line=i + len(chunk_lines),
                    content="\n".join(chunk_lines),
                    chunk_type="code",
                ))

        return chunks

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na * nb == 0:
            return 0.0
        return dot / (na * nb)
