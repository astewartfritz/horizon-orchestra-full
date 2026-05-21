from fastapi import APIRouter, HTTPException

from orchestra.code_agent.channels.health import ChannelHealthMonitor, ChannelHealthStatus
from orchestra.code_agent.channels.formatter import OutputFormatter
from orchestra.code_agent.channels.retry import ChannelRetryEngine, RetryConfig, RetryStrategy
from orchestra.code_agent.channels.queue import MessageQueue, QueuedMessage, MessagePriority


_health_monitor: ChannelHealthMonitor | None = None
_formatter: OutputFormatter | None = None
_retry_engine: ChannelRetryEngine | None = None
_message_queue: MessageQueue | None = None


def get_health_monitor() -> ChannelHealthMonitor:
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = ChannelHealthMonitor()
    return _health_monitor


def get_formatter() -> OutputFormatter:
    global _formatter
    if _formatter is None:
        _formatter = OutputFormatter()
    return _formatter


def get_retry_engine() -> ChannelRetryEngine:
    global _retry_engine
    if _retry_engine is None:
        _retry_engine = ChannelRetryEngine()
    return _retry_engine


def get_message_queue() -> MessageQueue:
    global _message_queue
    if _message_queue is None:
        _message_queue = MessageQueue()
    return _message_queue


def register_channel_gateway_routes(app, prefix: str = "/api/channels/v2"):
    router = APIRouter(prefix=prefix)
    health = get_health_monitor()
    formatter = get_formatter()
    retry = get_retry_engine()
    mq = get_message_queue()

    @router.get("/health")
    async def channel_health():
        return {
            "channels": {
                k: {
                    "status": v.status.value,
                    "consecutive_failures": v.consecutive_failures,
                    "total_messages_sent": v.total_messages_sent,
                    "total_messages_received": v.total_messages_received,
                    "total_errors": v.total_errors,
                    "avg_latency_ms": round(v.avg_latency_ms, 2),
                    "last_error": v.last_error_message,
                }
                for k, v in health.all_status().items()
            },
            "queue_stats": mq.get_stats(),
        }

    @router.get("/health/{channel_type}")
    async def channel_health_detail(channel_type: str):
        h = health.get_status(channel_type)
        if not h:
            raise HTTPException(404, "Channel not found")
        return {
            "channel_type": h.channel_type,
            "status": h.status.value,
            "last_ok": h.last_ok,
            "last_error": h.last_error,
            "consecutive_failures": h.consecutive_failures,
            "total_messages_sent": h.total_messages_sent,
            "total_messages_received": h.total_messages_received,
            "total_errors": h.total_errors,
            "avg_latency_ms": round(h.avg_latency_ms, 2),
            "last_error_message": h.last_error_message,
            "queue_depth": mq.queue_depth(channel_type),
        }

    @router.post("/format")
    async def format_message(body: dict):
        text = body.get("text", "")
        channel = body.get("channel", "default")
        kwargs = body.get("kwargs", {})
        formatted = formatter.format(text, channel, **kwargs)
        return {"original": text, "channel": channel, "formatted": formatted}

    @router.post("/retry-config")
    async def set_retry_config(body: dict):
        channel = body.get("channel", "")
        if not channel:
            raise HTTPException(400, "channel is required")
        config = RetryConfig(
            max_retries=body.get("max_retries", 3),
            base_delay=body.get("base_delay", 1.0),
            max_delay=body.get("max_delay", 60.0),
            strategy=RetryStrategy(body.get("strategy", "exponential")),
        )
        retry.set_config(channel, config)
        return {"channel": channel, "config": {
            "max_retries": config.max_retries,
            "base_delay": config.base_delay,
            "max_delay": config.max_delay,
            "strategy": config.strategy.value,
        }}

    @router.post("/enqueue")
    async def enqueue_message(body: dict):
        channel = body.get("channel_type", "")
        if not channel:
            raise HTTPException(400, "channel_type is required")
        if channel not in mq.get_stats({}):
            raise HTTPException(400, f"No handler registered for channel {channel}. Register a handler first.")

        msg = QueuedMessage(
            priority=MessagePriority(body.get("priority", "normal")),
            channel_type=channel,
            target=body.get("target", ""),
            content=body.get("content", ""),
            sender_id=body.get("sender_id", "api"),
            max_retries=body.get("max_retries", 3),
            trace_id=body.get("trace_id", ""),
        )
        await mq.enqueue(msg)
        return {"message_id": msg.id, "channel": channel, "priority": msg.priority}

    @router.get("/queue/stats")
    async def queue_stats(channel_type: str | None = None):
        return mq.get_stats(channel_type)

    @router.get("/queue/dlq/{channel_type}")
    async def get_dlq(channel_type: str):
        dlq = mq.get_dlq(channel_type)
        return {
            "channel": channel_type,
            "count": len(dlq),
            "messages": [
                {"id": m.id, "content_preview": m.content[:100], "retry_count": m.retry_count}
                for m in dlq
            ],
        }

    @router.post("/queue/requeue-dlq/{channel_type}")
    async def requeue_dlq(channel_type: str):
        mq.requeue_dlq(channel_type)
        return {"status": "requeued"}

    @router.post("/register-channel")
    async def register_channel(body: dict):
        channel_type = body.get("channel_type", "")
        if not channel_type:
            raise HTTPException(400, "channel_type is required")
        health.register_channel(channel_type)

        async def handler(msg: QueuedMessage):
            health.record_success(channel_type)
            return True
        mq.register_handler(channel_type, handler)
        mq.start_worker(channel_type)
        return {"channel_type": channel_type, "status": "registered"}

    app.include_router(router)
