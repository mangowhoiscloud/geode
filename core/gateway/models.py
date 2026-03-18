"""Gateway data models — InboundMessage and ChannelBinding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InboundMessage:
    """A message received from an external channel."""

    channel: str  # "slack", "discord", "telegram"
    channel_id: str  # Channel/chat identifier
    sender_id: str  # User identifier
    sender_name: str  # Display name
    content: str  # Message text
    timestamp: float  # Unix timestamp
    thread_id: str = ""  # Thread/reply identifier (optional)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelBinding:
    """Static routing rule for inbound messages.

    Binds an external channel to GEODE processing behavior.
    Most-specific binding wins (channel+channel_id > channel-only).
    """

    channel: str  # "slack", "discord", "telegram"
    channel_id: str = ""  # Specific channel/chat ID (empty = all)
    auto_respond: bool = True  # Auto-send response back to channel
    require_mention: bool = False  # Only respond when @mentioned
    allowed_tools: list[str] = field(default_factory=list)  # Empty = all tools
    max_rounds: int = 5  # AgenticLoop round limit for gateway messages
