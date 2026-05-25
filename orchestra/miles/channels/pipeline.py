"""MILES ingestion pipeline — guardrails → MILES → format response."""
from __future__ import annotations

import logging
from typing import Any

from orchestra.miles.channels.base import ChannelMessage, ChannelResponse
from orchestra.miles.channels.guardrails import ChannelGuardrails, GuardrailConfig

__all__ = ["IngestionPipeline"]

log = logging.getLogger("orchestra.miles.channels.pipeline")

_OPT_OUT_RESPONSE = (
    "You've been unsubscribed from M.I.L.E.S. "
    "Reply START or message us again to re-enable."
)

_RATE_LIMITED_RESPONSE = (
    "M.I.L.E.S: You're sending messages faster than I can process them. "
    "Please wait a moment."
)

_BLOCKED_RESPONSE = (
    "M.I.L.E.S: I can't process that message. "
    "If you believe this is an error, please contact support."
)

# Channel-specific formatting hints
_CHANNEL_MAX_LENGTH: dict[str, int] = {
    "slack": 4000,
    "whatsapp": 1600,
    "imessage": 2000,
    "gmail": 50_000,
    "instagram": 1000,
    "telegram": 4096,
}


def _format_for_channel(text: str, channel: str) -> str:
    """Trim and format a response for the target channel's constraints."""
    max_len = _CHANNEL_MAX_LENGTH.get(channel, 2000)
    if len(text) > max_len:
        text = text[: max_len - 3] + "…"
    return text


class IngestionPipeline:
    """Full message processing pipeline.

    Receives a ``ChannelMessage``, runs it through guardrails, passes the
    scrubbed text to MILES, and returns a formatted ``ChannelResponse``.

    Designed to be passed directly as the ``pipeline`` argument to
    ``ChannelHub``::

        hub = ChannelHub(consent=registry, pipeline=pipeline.process)
    """

    def __init__(
        self,
        miles: Any,                         # orchestra.miles.core.MILES
        guardrails: ChannelGuardrails,
        user_context: dict[str, Any] | None = None,
    ) -> None:
        self._miles = miles
        self._guardrails = guardrails
        self._user_context = user_context or {}

    async def process(self, message: ChannelMessage) -> ChannelResponse | None:
        """Run a single message through the full pipeline."""
        log.debug("Pipeline: %s/%s len=%d", message.channel, message.sender_id, len(message.text))

        # 1. Guardrails
        decision = await self._guardrails.check(message)

        if not decision.allowed:
            reason = (decision.reasons or ["unknown"])[0]
            log.info(
                "Guardrails blocked %s/%s: %s",
                message.channel, message.sender_id, reason,
            )
            if reason == "rate_limit_exceeded":
                reply_text = _RATE_LIMITED_RESPONSE
            elif reason in ("empty_message",):
                return None
            else:
                reply_text = _BLOCKED_RESPONSE

            return ChannelResponse(
                channel=message.channel,
                recipient_id=message.sender_id,
                text=_format_for_channel(reply_text, message.channel),
                thread_id=message.thread_id,
                subject=f"Re: {message.subject}" if message.subject else "",
            )

        # 2. Build context for MILES (channel + sender metadata)
        context_prefix = (
            f"[Message received via {message.channel.upper()} "
            f"from {message.sender_name} ({message.sender_id})"
        )
        if message.subject:
            context_prefix += f" | Subject: {message.subject}"
        if message.attachments:
            context_prefix += f" | Attachments: {len(message.attachments)}"
        context_prefix += "]"

        miles_input = f"{context_prefix}\n\n{decision.scrubbed_text or message.text}"

        # 3. Run MILES
        try:
            reply_text = await self._miles.run(
                miles_input,
                context=self._user_context.get(message.sender_id, []),
            )
        except Exception as exc:
            log.error("MILES.run failed for %s/%s: %s", message.channel, message.sender_id, exc)
            return None

        # 4. Format for channel
        formatted = _format_for_channel(reply_text, message.channel)

        return ChannelResponse(
            channel=message.channel,
            recipient_id=message.sender_id,
            text=formatted,
            thread_id=message.thread_id,
            subject=f"Re: {message.subject}" if message.subject else "",
        )
