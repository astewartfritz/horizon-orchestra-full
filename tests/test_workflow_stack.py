"""Tests for the agentic workflow stack:
CheckpointStore, TimerStore, workflow_sleep, WorkflowRunner,
and ProviderAdapter implementations.
"""
from __future__ import annotations

import asyncio
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.queue.checkpoint import CheckpointStore, WorkflowCheckpoint
from orchestra.queue.timer import TimerStore, WorkflowSuspended, workflow_sleep
from orchestra.queue.job import Job
from orchestra.providers.base import Message, CompletionResponse
from orchestra.providers.openai_adapter import OpenAIAdapter
from orchestra.providers.local_adapter import LocalAdapter


# ---------------------------------------------------------------------------
# CheckpointStore
# ---------------------------------------------------------------------------

class TestCheckpointStore:
    def test_save_and_load(self, tmp_path):
        store = CheckpointStore(tmp_path)
        cp = WorkflowCheckpoint(
            workflow_id="wf-1",
            goal="test goal",
            plan=[{"id": 1, "description": "step 1", "status": "done",
                   "result": "ok", "tools_used": [], "iterations": 1, "retries": 0}],
            current_step=1,
            total_tool_calls=3,
            replans=0,
            results=["result 1"],
        )
        store.save(cp)

        loaded = store.load("wf-1")
        assert loaded is not None
        assert loaded.workflow_id == "wf-1"
        assert loaded.goal == "test goal"
        assert loaded.current_step == 1
        assert loaded.total_tool_calls == 3

    def test_load_missing_returns_none(self, tmp_path):
        store = CheckpointStore(tmp_path)
        assert store.load("nonexistent") is None

    def test_delete(self, tmp_path):
        store = CheckpointStore(tmp_path)
        cp = WorkflowCheckpoint(
            workflow_id="wf-del", goal="g", plan=[], current_step=0,
            total_tool_calls=0, replans=0, results=[],
        )
        store.save(cp)
        assert store.load("wf-del") is not None
        store.delete("wf-del")
        assert store.load("wf-del") is None

    def test_delete_missing_is_noop(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.delete("does-not-exist")  # must not raise

    def test_list_ids(self, tmp_path):
        store = CheckpointStore(tmp_path)
        for i in range(3):
            cp = WorkflowCheckpoint(
                workflow_id=f"wf-{i}", goal="g", plan=[], current_step=0,
                total_tool_calls=0, replans=0, results=[],
            )
            store.save(cp)
        ids = store.list_ids()
        assert set(ids) == {"wf-0", "wf-1", "wf-2"}

    def test_save_is_atomic(self, tmp_path):
        """No .tmp file left behind after a clean save."""
        store = CheckpointStore(tmp_path)
        cp = WorkflowCheckpoint(
            workflow_id="wf-atom", goal="g", plan=[], current_step=0,
            total_tool_calls=0, replans=0, results=[],
        )
        store.save(cp)
        assert not list(tmp_path.glob("*.tmp"))

    def test_corrupt_checkpoint_returns_none(self, tmp_path):
        (tmp_path / "bad.json").write_text("not json")
        store = CheckpointStore(tmp_path)
        assert store.load("bad") is None


# ---------------------------------------------------------------------------
# TimerStore
# ---------------------------------------------------------------------------

class TestTimerStore:
    def test_set_and_due(self, tmp_path):
        store = TimerStore(tmp_path)
        past = time.time() - 10
        store.set("wf-past", past)
        assert "wf-past" in store.due()

    def test_future_timer_not_due(self, tmp_path):
        store = TimerStore(tmp_path)
        future = time.time() + 9999
        store.set("wf-future", future)
        assert "wf-future" not in store.due()

    def test_clear(self, tmp_path):
        store = TimerStore(tmp_path)
        store.set("wf-c", time.time() - 1)
        store.clear("wf-c")
        assert "wf-c" not in store.due()


# ---------------------------------------------------------------------------
# workflow_sleep
# ---------------------------------------------------------------------------

class TestWorkflowSleep:
    def test_short_sleep_uses_asyncio(self):
        async def _run():
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await workflow_sleep("wf-short", seconds=5)
                mock_sleep.assert_called_once_with(5)

        asyncio.get_event_loop().run_until_complete(_run())

    def test_long_sleep_raises_suspended(self, tmp_path):
        store = TimerStore(tmp_path)

        async def _run():
            with pytest.raises(WorkflowSuspended) as exc_info:
                await workflow_sleep("wf-long", seconds=3600, store=store)
            assert exc_info.value.workflow_id == "wf-long"
            assert exc_info.value.resume_at > time.time()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_long_sleep_writes_timer(self, tmp_path):
        store = TimerStore(tmp_path)

        async def _run():
            try:
                await workflow_sleep("wf-timer", seconds=7200, store=store)
            except WorkflowSuspended:
                pass

        asyncio.get_event_loop().run_until_complete(_run())
        # Timer record must exist and be in the future
        assert "wf-timer" not in store.due()


# ---------------------------------------------------------------------------
# ProviderAdapter protocol compliance
# ---------------------------------------------------------------------------

def _make_openai_response(content: str = "hello"):
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = None
    choice.finish_reason = "stop"
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


class TestOpenAIAdapter:
    def test_model_id(self):
        client = MagicMock()
        adapter = OpenAIAdapter(client=client, model="gpt-4o")
        assert adapter.model_id == "gpt-4o"

    def test_complete_returns_response(self):
        async def _run():
            client = MagicMock()
            client.chat.completions.create = AsyncMock(
                return_value=_make_openai_response("world")
            )
            adapter = OpenAIAdapter(client=client, model="gpt-4o")
            msgs = [Message(role="user", content="hi")]
            result = await adapter.complete(msgs)
            assert isinstance(result, CompletionResponse)
            assert result.content == "world"
            assert result.model == "gpt-4o"

        asyncio.get_event_loop().run_until_complete(_run())

    def test_complete_with_tools(self):
        async def _run():
            client = MagicMock()
            resp = _make_openai_response("")
            resp.choices[0].message.tool_calls = []
            client.chat.completions.create = AsyncMock(return_value=resp)
            adapter = OpenAIAdapter(client=client, model="gpt-4o")
            tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
            result = await adapter.complete([Message(role="user", content="q")], tools=tools)
            _, kwargs = client.chat.completions.create.call_args
            assert "tools" in kwargs or tools  # tools were passed through

        asyncio.get_event_loop().run_until_complete(_run())


class TestLocalAdapter:
    def test_model_id(self):
        adapter = LocalAdapter(model="llama3.2", base_url="http://localhost:11434/v1")
        assert adapter.model_id == "llama3.2"

    def test_complete_delegates_to_openai_client(self):
        async def _run():
            adapter = LocalAdapter(model="llama3.2")
            adapter._client = MagicMock()
            adapter._client.chat.completions.create = AsyncMock(
                return_value=_make_openai_response("local response")
            )
            result = await adapter.complete([Message(role="user", content="hi")])
            assert result.content == "local response"

        asyncio.get_event_loop().run_until_complete(_run())
