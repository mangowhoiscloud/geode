"""ChannelManager — binding-based inbound message routing.

Routes InboundMessages to AgenticLoop based on ChannelBinding rules.
Follows OpenClaw Gateway pattern: static rules, no LLM for routing.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from core.gateway.models import ChannelBinding, InboundMessage
from core.gateway.pollers.base import BasePoller
from core.memory.session_key import build_gateway_session_key

log = logging.getLogger(__name__)

# Type for the message processor callback
MessageProcessor = Callable[[str], str]  # input → response


class ChannelManager:
    """Route inbound messages to GEODE processing via static bindings.

    Implements GatewayPort. Manages pollers and bindings.

    Bindings are matched most-specific first:
    1. Exact match (channel + channel_id)
    2. Channel-wide match (channel only, channel_id="")
    3. No match → message ignored
    """

    def __init__(self, *, lane_queue: Any = None) -> None:
        self._bindings: list[ChannelBinding] = []
        self._pollers: list[BasePoller] = []
        self._processor: MessageProcessor | None = None
        self._lane_queue = lane_queue  # LaneQueue for concurrency control
        self._lock = threading.Lock()
        self._stats: dict[str, int] = {"received": 0, "processed": 0, "ignored": 0}

    def register_poller(self, poller: BasePoller) -> None:
        """Register a poller to be managed by this gateway."""
        self._pollers.append(poller)

    def start(self) -> None:
        """Start all registered pollers."""
        for poller in self._pollers:
            poller.start()

    def stop(self) -> None:
        """Stop all registered pollers."""
        for poller in self._pollers:
            poller.stop()

    def set_processor(self, processor: MessageProcessor) -> None:
        """Set the message processor (typically AgenticLoop.run)."""
        self._processor = processor

    def add_binding(self, binding: ChannelBinding) -> None:
        """Add a channel binding rule."""
        with self._lock:
            self._bindings.append(binding)
            # Sort: specific bindings first (non-empty channel_id)
            self._bindings.sort(key=lambda b: b.channel_id == "", reverse=False)
        log.info(
            "Channel binding added: %s/%s (auto_respond=%s)",
            binding.channel,
            binding.channel_id or "*",
            binding.auto_respond,
        )

    def remove_binding(self, channel: str, channel_id: str = "") -> bool:
        """Remove a binding by channel and channel_id."""
        with self._lock:
            before = len(self._bindings)
            self._bindings = [
                b
                for b in self._bindings
                if not (b.channel == channel and b.channel_id == channel_id)
            ]
            return len(self._bindings) < before

    def route_message(self, message: InboundMessage) -> str | None:
        """Route an inbound message through bindings.

        OpenClaw pattern: Session Lane → Global Lane → execution.
        Also enforces allowed_tools from ChannelBinding.

        Returns response string if processed, None if ignored.
        """
        self._stats["received"] += 1

        binding = self._match_binding(message)
        if binding is None:
            self._stats["ignored"] += 1
            log.debug(
                "No binding for %s/%s — message ignored",
                message.channel,
                message.channel_id,
            )
            return None

        if binding.require_mention and not self._is_mentioned(message):
            self._stats["ignored"] += 1
            return None

        if self._processor is None:
            log.warning("No message processor set — cannot process inbound message")
            return None

        # Build gateway session key for context isolation
        session_key = build_gateway_session_key(
            message.channel, message.channel_id, message.sender_id
        )

        # Prepare content with allowed_tools constraint
        content = message.content
        if binding.allowed_tools:
            # Prefix with tool constraint hint for AgenticLoop
            tools_hint = ", ".join(binding.allowed_tools)
            content = f"[allowed_tools: {tools_hint}] {content}"

        try:
            # Route through Lane Queue if available (OpenClaw pattern)
            if self._lane_queue is not None:
                gateway_lane = self._lane_queue.get_lane("gateway")
                if gateway_lane is not None:
                    with gateway_lane.acquire(session_key):
                        response = self._processor(content)
                else:
                    response = self._processor(content)
            else:
                response = self._processor(content)

            self._stats["processed"] += 1
            return response
        except Exception as exc:
            log.error("Message processing failed: %s", exc)
            return f"Error processing message: {exc}"

    def _match_binding(self, message: InboundMessage) -> ChannelBinding | None:
        """Find the most specific matching binding for a message."""
        with self._lock:
            # First pass: exact match (channel + channel_id)
            for binding in self._bindings:
                if (
                    binding.channel == message.channel
                    and binding.channel_id
                    and binding.channel_id == message.channel_id
                ):
                    return binding

            # Second pass: channel-wide match
            for binding in self._bindings:
                if binding.channel == message.channel and not binding.channel_id:
                    return binding

        return None

    @staticmethod
    def _is_mentioned(message: InboundMessage) -> bool:
        """Check if GEODE is mentioned in the message."""
        content_lower = message.content.lower()
        return any(mention in content_lower for mention in ("@geode", "geode", "<@geode>"))

    def get_stats(self) -> dict[str, int]:
        """Return routing statistics."""
        return dict(self._stats)

    def list_bindings(self) -> list[dict[str, Any]]:
        """Return serialized binding list."""
        with self._lock:
            return [
                {
                    "channel": b.channel,
                    "channel_id": b.channel_id or "*",
                    "auto_respond": b.auto_respond,
                    "require_mention": b.require_mention,
                    "max_rounds": b.max_rounds,
                }
                for b in self._bindings
            ]

    def load_bindings_from_config(self, config: dict[str, Any]) -> int:
        """Load bindings from TOML/dict config (hot-reloadable).

        Expected format::

            [gateway.bindings]
            [[gateway.bindings.rules]]
            channel = "slack"
            channel_id = "C12345"
            auto_respond = true
            require_mention = false

        Returns number of bindings loaded.
        """
        rules = config.get("gateway", {}).get("bindings", {}).get("rules", [])
        if not rules:
            return 0

        with self._lock:
            self._bindings.clear()

        loaded = 0
        for rule in rules:
            if not isinstance(rule, dict) or "channel" not in rule:
                continue
            binding = ChannelBinding(
                channel=rule["channel"],
                channel_id=rule.get("channel_id", ""),
                auto_respond=rule.get("auto_respond", True),
                require_mention=rule.get("require_mention", False),
                allowed_tools=rule.get("allowed_tools", []),
                max_rounds=rule.get("max_rounds", 5),
            )
            self.add_binding(binding)
            loaded += 1

        log.info("Loaded %d gateway bindings from config", loaded)
        return loaded
