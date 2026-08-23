"""Gateway data models — InboundMessage and ChannelBinding."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

GATEWAY_SCHEMA_VERSION = "geode.gateway.v1"
MAX_GATEWAY_CONTENT_BYTES = 64 * 1024
MAX_GATEWAY_METADATA_BYTES = 32 * 1024


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
    message_id: str = ""
    schema_version: str = GATEWAY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate the adapter-owned public gateway envelope."""
        if self.schema_version != GATEWAY_SCHEMA_VERSION:
            raise ValueError(f"Unsupported gateway schema version: {self.schema_version!r}")
        for name in ("channel", "channel_id", "sender_id", "sender_name", "thread_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > 1024:
                raise ValueError(f"Gateway {name} must be a string of at most 1024 chars")
        if not isinstance(self.content, str):
            raise ValueError("Gateway content must be a string")
        content_bytes = len(self.content.encode("utf-8"))
        if content_bytes > MAX_GATEWAY_CONTENT_BYTES:
            raise ValueError(f"Gateway content exceeds {MAX_GATEWAY_CONTENT_BYTES} bytes")
        if (
            isinstance(self.timestamp, bool)
            or not isinstance(self.timestamp, (int, float))
            or not math.isfinite(self.timestamp)
        ):
            raise ValueError("Gateway timestamp must be finite")
        if not isinstance(self.metadata, dict):
            raise ValueError("Gateway metadata must be a JSON object")
        try:
            metadata_bytes = json.dumps(
                self.metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Gateway metadata must be JSON-safe") from exc
        if len(metadata_bytes) > MAX_GATEWAY_METADATA_BYTES:
            raise ValueError(f"Gateway metadata exceeds {MAX_GATEWAY_METADATA_BYTES} bytes")
        if not isinstance(self.message_id, str) or len(self.message_id) > 256:
            raise ValueError("Gateway message_id must be a string of at most 256 chars")
        if not self.message_id:
            identity = "\0".join(
                (
                    self.channel,
                    self.channel_id,
                    self.sender_id,
                    self.thread_id,
                    str(self.timestamp),
                    self.content,
                )
            )
            self.message_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


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
    time_budget_s: float = 120.0  # Wall-clock timeout per message (seconds)
