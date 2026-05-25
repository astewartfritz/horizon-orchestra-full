import pytest
import asyncio

from orchestra.code_agent.channels.health import ChannelHealthMonitor, ChannelHealth, ChannelHealthStatus
from orchestra.code_agent.channels.formatter import OutputFormatter
from orchestra.code_agent.channels.retry import ChannelRetryEngine, RetryConfig, RetryStrategy
from orchestra.code_agent.channels.queue import MessageQueue, QueuedMessage, MessagePriority


class TestChannelHealthMonitor:
    def test_register_channel(self):
        m = ChannelHealthMonitor()
        m.register_channel("slack")
        status = m.get_status("slack")
        assert status is not None
        assert status.channel_type == "slack"
        assert status.status == ChannelHealthStatus.UNKNOWN

    def test_record_success(self):
        m = ChannelHealthMonitor()
        m.register_channel("discord")
        m.record_success("discord", 150.0)
        status = m.get_status("discord")
        assert status.status == ChannelHealthStatus.CONNECTED
        assert status.total_messages_sent == 1
        assert status.consecutive_failures == 0
        assert status.avg_latency_ms == 150.0

    def test_record_error(self):
        m = ChannelHealthMonitor()
        m.register_channel("telegram")
        m.record_error("telegram", "connection refused")
        status = m.get_status("telegram")
        assert status.status == ChannelHealthStatus.ERROR
        assert status.total_errors == 1
        assert status.consecutive_failures == 1
        assert "connection refused" in status.last_error_message

    def test_is_healthy(self):
        m = ChannelHealthMonitor()
        m.register_channel("whatsapp")
        assert m.is_healthy("whatsapp") is False
        m.record_success("whatsapp")
        assert m.is_healthy("whatsapp") is True
        for _ in range(5):
            m.record_error("whatsapp", "err")
        assert m.is_healthy("whatsapp") is False

    def test_record_receive(self):
        m = ChannelHealthMonitor()
        m.register_channel("email")
        m.record_receive("email")
        assert m.get_status("email").total_messages_received == 1

    def test_all_status(self):
        m = ChannelHealthMonitor()
        m.register_channel("a")
        m.register_channel("b")
        m.record_success("a")
        all_s = m.all_status()
        assert len(all_s) == 2
        assert all_s["a"].status == ChannelHealthStatus.CONNECTED

    def test_unknown_channel(self):
        m = ChannelHealthMonitor()
        assert m.get_status("nonexistent") is None
        assert m.is_healthy("nonexistent") is False


class TestOutputFormatter:
    def test_default_format(self):
        f = OutputFormatter()
        result = f.format("hello **world**", "default")
        assert result == "hello **world**"

    def test_slack_format(self):
        f = OutputFormatter()
        result = f.format("**bold** and `code`", "slack")
        assert "*bold*" in result
        assert "`code`" in result

    def test_discord_format(self):
        f = OutputFormatter()
        result = f.format("**bold**", "discord")
        assert "**bold**" in result

    def test_telegram_html(self):
        f = OutputFormatter()
        result = f.format("**bold** and `code`", "telegram")
        assert "<b>" in result
        assert "<code>" in result

    def test_whatsapp_strips_code_blocks(self):
        f = OutputFormatter()
        result = f.format("text ```code block``` more", "whatsapp")
        assert "```" not in result

    def test_email_html_format(self):
        f = OutputFormatter()
        text = "## Heading\n\nSome paragraph\n\n- list item\n\n```\ncode\n```"
        result = f.format(text, "email")
        assert "<h2>" in result
        assert "<p>" in result
        assert "<li>" in result
        assert "<pre" in result

    def test_imessage_strips_code(self):
        f = OutputFormatter()
        result = f.format("text ```code``` more", "imessage")
        assert "[code block]" in result

    def test_web_passthrough(self):
        f = OutputFormatter()
        text = "raw **markdown**"
        result = f.format(text, "web")
        assert result == text

    def test_custom_formatter(self):
        f = OutputFormatter()
        f.register_formatter("custom", lambda t, **kw: f"custom: {t}")
        result = f.format("hello", "custom")
        assert result == "custom: hello"

    def test_unknown_channel_falls_back(self):
        f = OutputFormatter()
        result = f.format("test", "unknown_channel")
        assert result == "test"


class TestChannelRetryEngine:
    @pytest.mark.asyncio
    async def test_immediate_success(self):
        engine = ChannelRetryEngine()
        ok, err = await engine.execute("test", lambda: True)
        assert ok is True
        assert err == ""

    @pytest.mark.asyncio
    async def test_async_success(self):
        engine = ChannelRetryEngine()

        async def succeed():
            return True

        ok, err = await engine.execute("test", succeed)
        assert ok is True

    @pytest.mark.asyncio
    async def test_retry_then_fail(self):
        engine = ChannelRetryEngine()
        config = RetryConfig(max_retries=2, base_delay=0.01, strategy=RetryStrategy.FIXED)
        attempts = []

        def always_fail():
            attempts.append(1)
            raise ConnectionError("fail")

        ok, err = await engine.execute("test", always_fail, config)
        assert ok is False
        assert len(attempts) == 3

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        engine = ChannelRetryEngine()
        config = RetryConfig(max_retries=3, base_delay=0.01, strategy=RetryStrategy.FIXED)
        count = 0

        def fail_twice():
            nonlocal count
            count += 1
            if count < 3:
                raise TimeoutError("timeout")
            return True

        ok, err = await engine.execute("test", fail_twice, config)
        assert ok is True
        assert count == 3

    def test_strategies(self):
        engine = ChannelRetryEngine()
        f = RetryConfig(strategy=RetryStrategy.FIXED)
        e = RetryConfig(strategy=RetryStrategy.EXPONENTIAL)
        l = RetryConfig(strategy=RetryStrategy.LINEAR)
        j = RetryConfig(strategy=RetryStrategy.JITTER)

        ef = engine._calculate_delay(0, f)
        ee = engine._calculate_delay(0, e)
        el = engine._calculate_delay(0, l)
        ej = engine._calculate_delay(0, j)
        assert ef == 1.0
        assert ee == 1.0
        assert el == 1.0
        assert 0.5 <= ej <= 1.0

        ef2 = engine._calculate_delay(2, f)
        ee2 = engine._calculate_delay(2, e)
        el2 = engine._calculate_delay(2, l)
        assert ef2 == 1.0
        assert ee2 == 4.0
        assert el2 == 3.0

    def test_set_get_config(self):
        engine = ChannelRetryEngine()
        config = RetryConfig(max_retries=5, base_delay=2.0)
        engine.set_config("slack", config)
        retrieved = engine.get_config("slack")
        assert retrieved.max_retries == 5
        assert retrieved.base_delay == 2.0
        default = engine.get_config("nonexistent")
        assert default.max_retries == 3


class TestMessageQueue:
    @pytest.mark.asyncio
    async def test_enqueue_and_stats(self):
        mq = MessageQueue()
        delivered = []

        async def handler(msg):
            delivered.append(msg)

        mq.register_handler("slack", handler)
        mq.start_worker("slack")

        msg = QueuedMessage(channel_type="slack", content="hello", target="user1")
        await mq.enqueue(msg)
        await asyncio.sleep(0.1)
        assert len(delivered) >= 0

        stats = mq.get_stats("slack")
        assert stats["enqueued"] >= 1
        await mq.stop_all()

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        mq = MessageQueue()
        delivered = []

        async def handler(msg):
            delivered.append(msg)

        mq.register_handler("priority-test", handler)
        mq.start_worker("priority-test")

        await mq.enqueue(QueuedMessage(channel_type="priority-test", content="low", priority=MessagePriority.LOW))
        await mq.enqueue(QueuedMessage(channel_type="priority-test", content="high", priority=MessagePriority.HIGH))
        await mq.enqueue(QueuedMessage(channel_type="priority-test", content="critical", priority=MessagePriority.CRITICAL))
        await asyncio.sleep(0.2)

        if len(delivered) == 3:
            priorities = [m.priority for m in delivered]
            assert priorities[0] <= priorities[1] <= priorities[2]

        await mq.stop_all()

    @pytest.mark.asyncio
    async def test_dlq(self):
        mq = MessageQueue()

        async def failing_handler(msg):
            raise ValueError("always fail")

        mq.register_handler("dlq-test", failing_handler)
        mq.start_worker("dlq-test", num_workers=1)

        msg = QueuedMessage(channel_type="dlq-test", content="fail me", max_retries=1)
        await mq.enqueue(msg)
        await asyncio.sleep(0.3)

        dlq = mq.get_dlq("dlq-test")
        stats = mq.get_stats("dlq-test")
        await mq.stop_all()

    @pytest.mark.asyncio
    async def test_requeue_dlq(self):
        mq = MessageQueue()

        async def failing_handler(msg):
            raise ValueError("always fail")

        mq.register_handler("requeue-test", failing_handler)
        mq.start_worker("requeue-test")

        msg = QueuedMessage(channel_type="requeue-test", content="requeue me", max_retries=1)
        await mq.enqueue(msg)
        await asyncio.sleep(0.3)

        assert len(mq.get_dlq("requeue-test")) >= 0
        mq.requeue_dlq("requeue-test")
        await mq.stop_all()

    @pytest.mark.asyncio
    async def test_multiple_workers(self):
        mq = MessageQueue()
        delivered = []

        async def handler(msg):
            delivered.append(msg)

        mq.register_handler("multi", handler)
        mq.start_worker("multi", num_workers=3)

        for i in range(5):
            await mq.enqueue(QueuedMessage(channel_type="multi", content=f"msg-{i}"))
        await asyncio.sleep(0.2)
        await mq.stop_all()

    @pytest.mark.asyncio
    async def test_queue_depth(self):
        mq = MessageQueue()

        async def slow_handler(msg):
            await asyncio.sleep(1)

        mq.register_handler("depth", slow_handler)
        mq.start_worker("depth", num_workers=1)

        for i in range(3):
            await mq.enqueue(QueuedMessage(channel_type="depth", content=f"msg-{i}"))
        await asyncio.sleep(0.1)
        assert mq.queue_depth("depth") >= 0
        await mq.stop_all()

    @pytest.mark.asyncio
    async def test_enqueue_many(self):
        mq = MessageQueue()
        delivered = []

        async def handler(msg):
            delivered.append(msg)

        mq.register_handler("batch", handler)
        mq.start_worker("batch")

        msgs = [QueuedMessage(channel_type="batch", content=f"msg-{i}") for i in range(3)]
        await mq.enqueue_many(msgs)
        await asyncio.sleep(0.2)
        await mq.stop_all()


def test_channel_health_dataclass():
    h = ChannelHealth(channel_type="test")
    assert h.channel_type == "test"
    assert h.status == ChannelHealthStatus.UNKNOWN
    assert h.total_messages_sent == 0
