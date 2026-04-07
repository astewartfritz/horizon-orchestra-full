"""Tests for the newest modules: cloud parity, long-horizon, adaptive context,
token streaming, architecture wiring, and mobile PWA stack.

Run with: pytest tests/test_new_modules.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ===================================================================
# 1. Cloud modules — boto3 guard
# ===================================================================

class TestCloudBoto3Guards:
    """Verify cloud modules import even without boto3."""

    def test_websocket_relay_imports(self):
        from orchestra.cloud.websocket_relay import WebSocketRelay, WebSocketFrame, _HAS_BOTO3
        assert isinstance(_HAS_BOTO3, bool)

    def test_cloud_files_imports(self):
        from orchestra.cloud.files import CloudFiles, _HAS_BOTO3
        assert isinstance(_HAS_BOTO3, bool)

    def test_cloud_sessions_imports(self):
        from orchestra.cloud.sessions import CloudSessionStore, _HAS_BOTO3
        assert isinstance(_HAS_BOTO3, bool)

    def test_websocket_frame_serialization(self):
        from orchestra.cloud.websocket_relay import WebSocketFrame
        frame = WebSocketFrame(type="token", data={"text": "hello"}, sequence=1)
        j = json.loads(frame.to_json())
        assert j["type"] == "token"
        assert j["data"]["text"] == "hello"
        assert j["sequence"] == 1
        assert "timestamp" in j

    def test_websocket_relay_requires_boto3(self):
        from orchestra.cloud.websocket_relay import WebSocketRelay, _HAS_BOTO3
        if not _HAS_BOTO3:
            with pytest.raises(RuntimeError, match="boto3 is required"):
                WebSocketRelay()

    def test_cloud_files_requires_boto3(self):
        from orchestra.cloud.files import CloudFiles, _HAS_BOTO3
        if not _HAS_BOTO3:
            with pytest.raises(RuntimeError, match="boto3 is required"):
                CloudFiles(bucket="test")

    def test_cloud_sessions_requires_boto3(self):
        from orchestra.cloud.sessions import CloudSessionStore, _HAS_BOTO3
        if not _HAS_BOTO3:
            with pytest.raises(RuntimeError, match="boto3 is required"):
                CloudSessionStore()

    def test_cloud_init_exports(self):
        from orchestra.cloud import (
            WebSocketRelay, WebSocketFrame,
            CloudFiles, CloudSessionStore,
            ComputeBackend, LambdaRuntime, TerafabRuntime,
        )
        assert WebSocketRelay is not None


# ===================================================================
# 2. Long-Horizon Runner
# ===================================================================

class TestLongHorizon:
    """Test long_horizon.py components."""

    def test_imports(self):
        from orchestra.long_horizon import (
            LongHorizonRunner, CheckpointStore, ProgressTracker,
            LongHorizonResult, LongHorizonConfig, _HAS_BOTO3,
        )
        assert isinstance(_HAS_BOTO3, bool)

    def test_config_defaults(self):
        from orchestra.long_horizon import LongHorizonConfig
        cfg = LongHorizonConfig()
        assert cfg.max_runtime_hours == 4.0
        assert cfg.checkpoint_interval_minutes == 5.0
        assert cfg.max_tool_calls == 1000
        assert cfg.lambda_timeout_seconds == 840.0
        assert cfg.model == "kimi-k2.5"

    def test_checkpoint_store_local_fallback(self):
        from orchestra.long_horizon import CheckpointStore
        store = CheckpointStore(use_local_fallback=True)
        # Should use local fallback when boto3 not available
        assert store._use_local is True

    def test_progress_tracker(self):
        from orchestra.long_horizon import ProgressTracker
        tracker = ProgressTracker()
        assert tracker is not None

    def test_result_dataclass(self):
        from orchestra.long_horizon import LongHorizonResult
        result = LongHorizonResult(
            task_id="test-123",
            status="completed",
            result="done",
            steps_completed=10,
            total_steps=10,
            tool_calls=42,
            duration_seconds=120.0,
        )
        assert result.task_id == "test-123"
        assert result.status == "completed"


# ===================================================================
# 3. Adaptive Context
# ===================================================================

class TestAdaptiveContext:
    """Test adaptive_context.py components."""

    def test_imports(self):
        from orchestra.adaptive_context import (
            AdaptiveContext, AdaptiveContextConfig,
            TokenCounter, PriorityMessage,
        )

    def test_config_defaults(self):
        from orchestra.adaptive_context import AdaptiveContextConfig
        cfg = AdaptiveContextConfig()
        assert cfg.max_tokens == 262144  # Kimi K2.5
        assert cfg.compress_threshold_pct == 80.0
        assert cfg.min_recent_turns == 5

    def test_token_counter(self):
        from orchestra.adaptive_context import TokenCounter
        counter = TokenCounter(encoding="chars/4")
        count = counter.count("Hello, world!")
        assert count > 0
        assert isinstance(count, int)

    def test_priority_message(self):
        from orchestra.adaptive_context import PriorityMessage
        msg = PriorityMessage(role="system", content="You are helpful.", priority=1)
        assert msg.role == "system"
        assert msg.priority == 1

    def test_adaptive_context_creation(self):
        from orchestra.adaptive_context import AdaptiveContext, AdaptiveContextConfig
        # Requires a router arg — use None as stub since we're just testing creation
        ctx = AdaptiveContext(config=AdaptiveContextConfig(token_counter="chars/4"), router=None)
        assert ctx is not None


# ===================================================================
# 4. Token Streaming
# ===================================================================

class TestTokenStreaming:
    """Test token_streaming.py components."""

    def test_imports(self):
        from orchestra.token_streaming import (
            TokenStreamer, StreamChunk,
            BufferedStreamer, StreamingConfig,
        )

    def test_config_defaults(self):
        from orchestra.token_streaming import StreamingConfig
        cfg = StreamingConfig()
        assert cfg.enable_sse is True
        assert cfg.enable_websocket is True
        assert cfg.heartbeat_interval == 15.0
        assert cfg.buffer_size == 1

    def test_stream_chunk(self):
        from orchestra.token_streaming import StreamChunk
        chunk = StreamChunk(type="token", content="Hello")
        assert chunk.type == "token"
        assert chunk.content == "Hello"

    def test_streamer_creation(self):
        from orchestra.token_streaming import TokenStreamer, StreamingConfig
        streamer = TokenStreamer(config=StreamingConfig())
        assert streamer is not None


# ===================================================================
# 5. Architecture Wiring
# ===================================================================

class TestArchitectureWiring:
    """Verify arch_a and arch_c have the new capabilities."""

    def test_arch_a_imports(self):
        from orchestra.arch_a import MonolithicAgent, MonolithicConfig
        assert MonolithicConfig is not None

    def test_arch_a_config_new_fields(self):
        from orchestra.arch_a import MonolithicConfig
        cfg = MonolithicConfig()
        assert hasattr(cfg, "enable_adaptive_context")
        assert hasattr(cfg, "enable_long_horizon")
        assert hasattr(cfg, "enable_token_streaming")

    def test_arch_a_has_long_horizon_method(self):
        from orchestra.arch_a import MonolithicAgent
        assert hasattr(MonolithicAgent, "run_long_horizon")
        assert asyncio.iscoroutinefunction(MonolithicAgent.run_long_horizon)

    def test_arch_a_has_stream_sse(self):
        from orchestra.arch_a import MonolithicAgent
        assert hasattr(MonolithicAgent, "stream_sse")

    def test_arch_c_imports(self):
        from orchestra.arch_c import SwarmAgent, SwarmConfig
        assert SwarmConfig is not None

    def test_arch_c_config_new_fields(self):
        from orchestra.arch_c import SwarmConfig
        cfg = SwarmConfig()
        assert hasattr(cfg, "enable_adaptive_context")
        assert hasattr(cfg, "enable_long_horizon")
        assert hasattr(cfg, "enable_token_streaming")

    def test_arch_c_has_long_horizon_method(self):
        from orchestra.arch_c import SwarmAgent
        assert hasattr(SwarmAgent, "run_long_horizon")

    def test_arch_c_has_stream_sse(self):
        from orchestra.arch_c import SwarmAgent
        assert hasattr(SwarmAgent, "stream_sse")


# ===================================================================
# 6. Mobile PWA Stack
# ===================================================================

class TestMobilePWA:
    """Test mobile/ module components."""

    def test_mobile_init_imports(self):
        from orchestra.mobile import (
            manifest, service_worker, offline_queue,
            push_notifications, touch_ui, app_shell,
        )

    def test_manifest_generator(self):
        from orchestra.mobile.manifest import ManifestGenerator
        gen = ManifestGenerator()
        m = gen.build()
        assert m["name"] == "Horizon Orchestra"
        assert m["short_name"] == "Orchestra"
        assert m["theme_color"] == "#01696F"
        assert m["display"] == "standalone"
        assert len(m.get("icons", [])) > 0

    def test_service_worker_generator(self):
        from orchestra.mobile.service_worker import ServiceWorkerGenerator
        gen = ServiceWorkerGenerator()
        js = gen.build()
        assert "self.addEventListener" in js or "addEventListener" in js
        assert "install" in js.lower()
        assert "fetch" in js.lower()

    def test_offline_queue_js(self):
        from orchestra.mobile.offline_queue import OfflineQueueJS
        gen = OfflineQueueJS()
        js = gen.build()
        assert "IndexedDB" in js or "indexedDB" in js
        assert "enqueue" in js

    def test_push_notifications_import(self):
        from orchestra.mobile.push_notifications import PushNotificationManager

    def test_touch_ui_generator(self):
        from orchestra.mobile.touch_ui import TouchUIGenerator
        gen = TouchUIGenerator()
        bundle = gen.build_full_bundle()
        # bundle may be a dict with html/css/js keys or a string
        if isinstance(bundle, dict):
            combined = " ".join(str(v) for v in bundle.values())
        else:
            combined = str(bundle)
        assert "orchestra" in combined.lower() or "MILES" in combined or "miles" in combined.lower()
        assert "nav" in combined.lower()

    def test_app_shell_generator(self):
        from orchestra.mobile.app_shell import AppShellGenerator
        gen = AppShellGenerator()
        html = gen.build()
        assert "manifest.json" in html
        assert "serviceWorker" in html or "sw.js" in html


# ===================================================================
# 7. Full import smoke test
# ===================================================================

class TestFullImportSmoke:
    """Verify every module in orchestra/ imports without error."""

    def test_all_122_modules(self):
        import importlib
        failures = []
        count = 0
        for root, dirs, files in os.walk("orchestra"):
            for f in files:
                if f.endswith(".py") and "__pycache__" not in root:
                    mod = os.path.join(root, f).replace("/", ".").replace(".py", "")
                    try:
                        importlib.import_module(mod)
                        count += 1
                    except Exception as e:
                        failures.append(f"{mod}: {e}")
        assert len(failures) == 0, f"Import failures:\\n" + "\\n".join(failures)
        assert count >= 120, f"Expected 120+ modules, got {count}"
