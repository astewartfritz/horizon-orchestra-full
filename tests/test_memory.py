import tempfile
from pathlib import Path

import pytest

from code_agent.memory.base import NullMemory, JSONMemory, SQLiteMemory, MemoryEntry


@pytest.mark.asyncio
async def test_null_memory():
    mem = NullMemory()
    await mem.save(MemoryEntry(role="user", content="hello"))
    entries = await mem.load_recent()
    assert entries == []


@pytest.mark.asyncio
async def test_json_memory():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "memory.json"
        mem = JSONMemory(str(path))

        await mem.save(MemoryEntry(role="user", content="hello"))
        await mem.save(MemoryEntry(role="assistant", content="world"))

        entries = await mem.load_recent()
        assert len(entries) == 2
        assert entries[0].role == "user"
        assert entries[0].content == "hello"
        assert entries[1].role == "assistant"
        assert entries[1].content == "world"

        assert path.exists()

        await mem.clear()
        entries = await mem.load_recent()
        assert entries == []


@pytest.mark.asyncio
async def test_sqlite_memory():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "memory.db"
        mem = SQLiteMemory(str(path))

        await mem.save(MemoryEntry(role="user", content="test", name="echo"))
        entries = await mem.load_recent()
        assert len(entries) == 1
        assert entries[0].role == "user"
        assert entries[0].name == "echo"

        await mem.clear()
        entries = await mem.load_recent()
        assert entries == []
        mem.close()
