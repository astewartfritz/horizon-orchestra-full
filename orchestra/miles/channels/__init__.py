"""MILES multi-channel ingestion — public API."""
from orchestra.miles.channels.base import (
    ChannelAdapter,
    ChannelHub,
    ChannelMessage,
    ChannelResponse,
    ConsentRegistry,
    MessageHandler,
)
from orchestra.miles.channels.guardrails import (
    ChannelGuardrails,
    GuardrailConfig,
    GuardrailDecision,
)
from orchestra.miles.channels.pipeline import IngestionPipeline
from orchestra.miles.channels.slack import SlackChannelAdapter
from orchestra.miles.channels.telegram import TelegramChannelAdapter
from orchestra.miles.channels.gmail import GmailChannelAdapter
from orchestra.miles.channels.whatsapp import WhatsAppChannelAdapter
from orchestra.miles.channels.instagram import InstagramChannelAdapter
from orchestra.miles.channels.imessage import IMessageChannelAdapter

__all__ = [
    # Core
    "ChannelMessage",
    "ChannelResponse",
    "ChannelAdapter",
    "ConsentRegistry",
    "ChannelHub",
    "MessageHandler",
    # Guardrails
    "GuardrailConfig",
    "GuardrailDecision",
    "ChannelGuardrails",
    # Pipeline
    "IngestionPipeline",
    # Adapters
    "SlackChannelAdapter",
    "TelegramChannelAdapter",
    "GmailChannelAdapter",
    "WhatsAppChannelAdapter",
    "InstagramChannelAdapter",
    "IMessageChannelAdapter",
]
