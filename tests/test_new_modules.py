import tempfile
from pathlib import Path

import pytest

from code_agent.vector.engine import VectorEngine, simple_hash_embedding
from code_agent.vector.indexer import IndexerTool
from code_agent.analysis.parser import CodeAnalyzer
from code_agent.cost.tracker import CostTracker, TokenUsage
from code_agent.watcher.monitor import FileWatcher
from code_agent.watcher.tool import WatchTool
from code_agent.output.testgen import TestGenerator
from code_agent.plugins.loader import PluginLoader


@pytest.mark.asyncio
async def test_vector_engine():
    engine = VectorEngine(":memory:")
    file_path = str(Path(tempfile.mkdtemp()) / "test.py")
    Path(file_path).write_text("def hello():\n    return 'world'\n\ndef add(a, b):\n    return a + b\n")

    count = engine.index_file(file_path)
    assert count > 0

    results = engine.search("hello function", top_k=5)
    assert len(results) > 0
    assert any("hello" in r.chunk.content for r in results)

    stats = engine.stats()
    assert stats["chunks"] > 0
    assert stats["files"] > 0

    engine.close()


def test_simple_hash_embedding():
    emb1 = simple_hash_embedding("hello world")
    emb2 = simple_hash_embedding("hello world")
    emb3 = simple_hash_embedding("goodbye world")
    assert emb1 == emb2
    assert emb1 != emb3
    assert len(emb1) == 128


@pytest.mark.asyncio
async def test_analyzer():
    analyzer = CodeAnalyzer()
    code = """
import os
from pathlib import Path

def greet(name: str) -> str:
    return f"Hello {name}"

class Calculator:
    def add(self, a, b):
        return a + b
"""
    result = analyzer.analyze_text(code, "test.py")
    assert len(result.imports) == 2
    assert any(fn["name"] == "greet" for fn in result.functions)
    assert any(cls["name"] == "Calculator" for cls in result.classes)
    assert result.lines_of_code == 10


@pytest.mark.asyncio
async def test_analyze_tool():
    from code_agent.analysis.tool import AnalyzeTool

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "mod.py"
        p.write_text("def foo(): pass\nclass Bar: pass\n")

        tool = AnalyzeTool()
        result = await tool(path=str(p), action="summary")
        assert result
        assert "1 functions" in result.output
        assert "1 classes" in result.output

        result = await tool(path=str(p), action="functions")
        assert result
        assert "foo" in result.output


def test_cost_tracker():
    tracker = CostTracker()
    tracker.start_task("test task", "gpt-4o")
    tracker.record_usage(100, 50)
    entry = tracker.end_task("test task")
    assert entry.usage.input_tokens == 100
    assert entry.usage.output_tokens == 50
    assert entry.model == "gpt-4o"

    summary = tracker.summary()
    assert "100" in summary
    assert "50" in summary
    tracker.reset()


def test_token_usage_cost():
    usage = TokenUsage(input_tokens=1000, output_tokens=500)
    cost = usage.cost("gpt-4o")
    assert cost > 0
    assert usage.total == 1500


@pytest.mark.asyncio
async def test_watcher():
    watcher = FileWatcher()
    events = []

    def on_change(event):
        events.append(event)

    watcher.on_event(on_change)

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "test.txt"
        watcher.watch(str(p))
        watcher.start()

        p.write_text("hello")
        import time
        time.sleep(0.1)

        watcher.stop()

    assert len(events) >= 1


def test_test_generator():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "mymod.py"
        src.write_text("""
def add(a, b):
    return a + b

def multiply(x, y):
    return x * y

class Counter:
    def increment(self):
        pass
""")
        gen = TestGenerator()
        test_code = gen.generate(str(src), framework="pytest")
        assert "test_add" in test_code
        assert "test_multiply" in test_code
        assert "TestCounter" in test_code
        assert "import pytest" in test_code


@pytest.mark.asyncio
async def test_scaffold_tool():
    from code_agent.scaffold.generator import ScaffoldGenerator
    with tempfile.TemporaryDirectory() as tmp:
        tool = ScaffoldGenerator()
        result = await tool(template="python-script", name="hello", output_dir=str(Path(tmp) / "hello"))
        assert result
        assert "hello.py" in result.output
        assert (Path(tmp) / "hello" / "hello.py").exists()


def test_plugin_loader():
    from code_agent.tools import CORE_TOOLS
    assert len(CORE_TOOLS) >= 15


def test_tui_import():
    from code_agent.tui import CodeAgentTUI, run_tui
    assert CodeAgentTUI.__name__ == "CodeAgentTUI"
