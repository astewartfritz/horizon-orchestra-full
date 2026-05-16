import asyncio
import tempfile
from pathlib import Path

import pytest

from code_agent.tools.file_ops import ReadTool, WriteTool, EditTool, GlobTool
from code_agent.tools.search import GrepTool
from code_agent.tools.base import ToolResult


@pytest.mark.asyncio
async def test_write_and_read():
    with tempfile.TemporaryDirectory() as tmp:
        fpath = str(Path(tmp) / "test.txt")
        write = WriteTool()
        result = await write(file_path=fpath, content="hello world")
        assert result
        assert "Wrote" in result.output

        read = ReadTool()
        result = await read(file_path=fpath)
        assert result
        assert "hello world" in result.output


@pytest.mark.asyncio
async def test_edit():
    with tempfile.TemporaryDirectory() as tmp:
        fpath = str(Path(tmp) / "test.txt")
        write = WriteTool()
        await write(file_path=fpath, content="foo\nbar\nbaz")

        edit = EditTool()
        result = await edit(file_path=fpath, old_string="bar", new_string="qux")
        assert result

        read = ReadTool()
        result = await read(file_path=fpath)
        assert "qux" in result.output
        assert "foo" in result.output


@pytest.mark.asyncio
async def test_glob():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.py").write_text("")
        (Path(tmp) / "b.py").write_text("")
        (Path(tmp) / "data").mkdir()
        (Path(tmp) / "data" / "c.py").write_text("")

        glob = GlobTool()
        result = await glob(pattern="**/*.py", path=tmp)
        assert result
        assert "a.py" in result.output
        assert "c.py" in result.output


@pytest.mark.asyncio
async def test_grep():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "test.py").write_text("def hello():\n    pass\n")
        (Path(tmp) / "other.py").write_text("goodbye\n")

        grep = GrepTool()
        result = await grep(pattern="hello", path=tmp)
        assert result
        assert "hello" in result.output


@pytest.mark.asyncio
async def test_read_directory():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "file1.txt").write_text("")
        (Path(tmp) / "subdir").mkdir()

        read = ReadTool()
        result = await read(file_path=tmp)
        assert result
        assert "file1.txt" in result.output
        assert "subdir/" in result.output


@pytest.mark.asyncio
async def test_read_nonexistent():
    read = ReadTool()
    result = await read(file_path="/nonexistent/path/file.txt")
    assert not result
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_edit_multiple_matches():
    with tempfile.TemporaryDirectory() as tmp:
        fpath = str(Path(tmp) / "test.txt")
        write = WriteTool()
        await write(file_path=fpath, content="foo\nfoo\nfoo")

        edit = EditTool()
        result = await edit(file_path=fpath, old_string="foo", new_string="bar")
        assert not result
        assert "multiple matches" in result.error.lower()
