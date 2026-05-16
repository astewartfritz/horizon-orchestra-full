"""Horizon Orchestra — Enterprise Webhook Delivery.

At-least-once delivery with exponential backoff, HMAC-SHA256 signing,
dead-letter queues, and full audit logging.

Quick start::

    from orchestra.webhooks import WebhookDeliveryEngine, WebhookEvent

    engine = WebhookDeliveryEngine()
    ep = await engine.register(
        "org_acme",
        "https://hooks.acme.com/orchestra",
        [WebhookEvent.TASK_COMPLETED],
        secret="whsec_my_signing_key_1234",
    )
    ids = await engine.emit(WebhookEvent.TASK_COMPLETED, "org_acme", {"task_id": "t-42"})
"""

from .delivery import (
    WebhookEvent,
    WebhookEndpoint,
    WebhookDelivery,
    WebhookDeliveryEngine,
)

__all__ = [
    "WebhookEvent",
    "WebhookEndpoint",
    "WebhookDelivery",
    "WebhookDeliveryEngine",
]
