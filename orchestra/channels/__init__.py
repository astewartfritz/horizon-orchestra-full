"""Horizon Orchestra — Channels Package.

Unified messaging gateway supporting Telegram, Discord, WhatsApp, and SMS.
Each channel is a concrete implementation of the abstract ``Channel`` base
class.  The ``ChannelGateway`` orchestrates registration, connection,
fan-out broadcast, and inbound message routing to the Orchestra agent.

Public API::

    from orchestra.channels import (
        ChannelGateway,
        Channel,
        ChannelMessage,
        ChannelConfig,
        TelegramChannel,
        DiscordChannel,
        WhatsAppChannel,
        SMSChannel,
    )

    gw = ChannelGateway(ChannelConfig(enabled_channels=["telegram"]))
    gw.register(TelegramChannel())
    await gw.connect_all({"telegram": {"token": "BOT_TOKEN"}})
    response = await gw.send("telegram", "123456789", "Hello!")
"""

from __future__ import annotations

from .gateway import (
    Channel,
    ChannelConfig,
    ChannelGateway,
    ChannelMessage,
    DiscordChannel,
    SMSChannel,
    TelegramChannel,
    WhatsAppChannel,
)

__all__ = [
    "ChannelGateway",
    "Channel",
    "ChannelMessage",
    "ChannelConfig",
    "TelegramChannel",
    "DiscordChannel",
    "WhatsAppChannel",
    "SMSChannel",
]
