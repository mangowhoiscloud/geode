"""ChannelManager — binding-based inbound message routing.

Routes InboundMessages to AgenticLoop based on ChannelBinding rules.
Follows OpenClaw Gateway pattern: static rules, no LLM for routing.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Any

from core.memory.session_key import build_gateway_session_key
from core.messaging.models import ChannelBinding, InboundMessage
from core.server.supervised.poller_base import BasePoller

MessageProcessor = Callable[[str, dict[str, Any]], Awaitable[str] | str]
SessionExistsChecker = Callable[[str], bool]

_gateway: ChannelManager | None = None


def set_gateway(gateway: ChannelManager | None) -> None:
    """Set the active gateway."""
    global _gateway
    _gateway = gateway


def get_gateway() -> ChannelManager | None:
    """Get the active gateway, or None if not set."""
    return _gateway


log = logging.getLogger(__name__)


class ChannelManager:
    """Route inbound messages to GEODE processing via static bindings.

    Implements GatewayPort. Manages pollers and bindings.

    Binding match: exact (channel + channel_id) only.
    Messages from unbound channels are ignored.
    """

    def __init__(self, *, lane_queue: Any = None, bot_user_id: str = "") -> None:
        self._bindings: list[ChannelBinding] = []
        self._pollers: list[BasePoller] = []
        self._processor: MessageProcessor | None = None
        self._session_exists_checker: SessionExistsChecker | None = None
        self._session_terminal_checker: SessionExistsChecker | None = None
        self._lane_queue = lane_queue  # LaneQueue for concurrency control
        self._lock = threading.Lock()
        self._stats: dict[str, int] = {"received": 0, "processed": 0, "ignored": 0}
        self._bot_user_id = bot_user_id  # Slack bot user ID for mention matching
        # Gateway-level defaults (overridden by config.toml [gateway])
        self.gateway_time_budget_s: float = 120.0  # default 2 min per message
        # PR-CL-BUDGET (2026-05-23) — turn hard-cap removed; the session-wide
        # 2-hour wall-clock budget (``core.agent.budget``) plus the per-binding
        # ``gateway_time_budget_s`` are the new safety nets. ``0`` propagates
        # to ``AgenticLoop.max_rounds=0`` = unlimited rounds. Operator decision
        # in ``project_budget_handoff_decision`` (2026-05-23).
        self.gateway_max_turns: int = 0

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

    def set_async_processor(self, processor: MessageProcessor) -> None:
        """Set the async message processor for channel adapters."""
        self._processor = processor

    def set_session_exists_checker(self, checker: SessionExistsChecker) -> None:
        """Set the persistent-session probe used by thread-aware adapters."""
        self._session_exists_checker = checker

    def _probe_session(
        self,
        checker: SessionExistsChecker | None,
        message: InboundMessage,
        probe_name: str,
    ) -> bool:
        """Run one session-key probe; unset checker or probe failure is False."""
        if checker is None or not message.thread_id:
            return False
        session_key = build_gateway_session_key(
            message.channel,
            message.channel_id,
            message.sender_id,
            thread_id=message.thread_id,
        )
        try:
            return checker(session_key)
        except Exception:
            log.warning(
                "Gateway session %s check failed for %s", probe_name, session_key, exc_info=True
            )
            return False

    def has_persisted_session(self, message: InboundMessage) -> bool:
        """Return whether this exact channel/user/thread session can resume."""
        return self._probe_session(self._session_exists_checker, message, "existence")

    def set_session_terminal_checker(self, checker: SessionExistsChecker) -> None:
        """Set the probe that reports a durably terminal (non-resumable) session."""
        self._session_terminal_checker = checker

    def session_is_terminal(self, message: InboundMessage) -> bool:
        """Return whether this thread's durable machine state has ended.

        ``False`` covers both "no durable record yet" (an engagement cache may
        legitimately bridge the pre-checkpoint window) and "resumable". Only an
        explicit non-resumable checkpoint returns ``True``.
        """
        return self._probe_session(self._session_terminal_checker, message, "terminal")

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

    async def aroute_message(
        self,
        message: InboundMessage,
        *,
        mention_override: bool = False,
    ) -> str | None:
        """Route an inbound message through bindings.

        OpenClaw pattern: Session Lane → Global Lane → execution.
        Also enforces allowed_tools from ChannelBinding.

        ``mention_override`` is reserved for adapters that have independently
        established an already-engaged conversation, such as a reply in a
        Slack thread with a persisted gateway session. It bypasses only the
        mention gate; exact binding checks still apply.

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

        if binding.require_mention and not mention_override and not self._is_mentioned(message):
            self._stats["ignored"] += 1
            return None

        if self._processor is None:
            log.warning("No message processor set — cannot process inbound message")
            return None

        # Build gateway session key for context isolation (thread-scoped)
        session_key = build_gateway_session_key(
            message.channel,
            message.channel_id,
            message.sender_id,
            thread_id=message.thread_id,
        )

        metadata: dict[str, Any] = {
            "session_key": session_key,
            "thread_id": message.thread_id,
            "channel": message.channel,
            "channel_id": message.channel_id,
            "sender_id": message.sender_id,
        }

        # Strip mention tags so the LLM receives clean content
        content = self._strip_mentions(message.content)
        if binding.allowed_tools:
            # Prefix with tool constraint hint for AgenticLoop
            tools_hint = ", ".join(binding.allowed_tools)
            content = f"[allowed_tools: {tools_hint}] {content}"

        try:
            # Route through SessionLane → Gateway Lane → Global Lane
            if self._lane_queue is not None:
                async with self._lane_queue.acquire_all_async(
                    session_key,
                    ["session", "gateway", "global"],
                ):
                    response = await self._call_processor(content, metadata)
            else:
                response = await self._call_processor(content, metadata)

            self._stats["processed"] += 1
            return response
        except Exception as exc:
            log.error("Message processing failed: %s", exc)
            return f"Error processing message: {exc}"

    async def _call_processor(self, content: str, metadata: dict[str, Any]) -> str:
        if self._processor is None:
            return ""
        result = self._processor(content, metadata)
        if isawaitable(result):
            return await result
        return result

    def _match_binding(self, message: InboundMessage) -> ChannelBinding | None:
        """Find the matching binding for a message.

        Only exact match (channel + channel_id) is supported.
        Catch-all bindings (empty channel_id) are ignored to prevent
        unintended responses in unbound channels.
        """
        with self._lock:
            for binding in self._bindings:
                if (
                    binding.channel == message.channel
                    and binding.channel_id
                    and binding.channel_id == message.channel_id
                ):
                    return binding
        return None

    def _is_mentioned(self, message: InboundMessage) -> bool:
        """Check if GEODE is mentioned in the message.

        Matches only GEODE's own bot user ID (from auth.test ``user_id``)
        or display name variants. Does NOT match arbitrary ``<@U...>``
        mentions — those are mentions of other users.
        """
        content = message.content
        # Match GEODE's specific bot user ID (e.g. <@U0ABCDEF123>)
        if self._bot_user_id and f"<@{self._bot_user_id}>" in content:
            return True
        content_lower = content.lower()
        return any(mention in content_lower for mention in ("@geode", "geode"))

    def _strip_mentions(self, content: str) -> str:
        """Remove GEODE's own mention tags so the LLM receives clean user intent.

        Only strips GEODE's bot user ID mention and display name variants.
        Preserves mentions of other users (e.g. ``<@U_OTHER>``).
        """
        import re

        # Remove GEODE's specific bot mention (e.g. <@U0ABCDEF123>)
        if self._bot_user_id:
            cleaned = content.replace(f"<@{self._bot_user_id}>", "").strip()
        else:
            # Fallback: remove all Slack mentions (legacy behavior)
            cleaned = re.sub(r"<@[UBA][A-Z0-9]+>\s*", "", content)
        # Remove @geode / @GEODE prefix
        cleaned = re.sub(r"@geode\s*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

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
                    "time_budget_s": b.time_budget_s,
                }
                for b in self._bindings
            ]

    def load_bindings_from_config(self, config: dict[str, Any]) -> int:
        """Load bindings and gateway-level settings from TOML/dict config.

        Expected format::

            [gateway]
            max_rounds = 30
            max_turns = 0  # 0 = unlimited (session-wide 2h wall-clock cap)

            [[gateway.bindings.rules]]
            channel = "slack"
            channel_id = "C12345"
            auto_respond = true

        Returns number of bindings loaded.
        """
        gw = config.get("gateway", {})

        # Gateway-level defaults
        if "time_budget_s" in gw:
            self.gateway_time_budget_s = float(gw["time_budget_s"])
        elif "max_rounds" in gw:
            # Legacy: convert max_rounds to approximate time budget (10s/round)
            self.gateway_time_budget_s = float(int(gw["max_rounds"]) * 10)
        if "max_turns" in gw:
            self.gateway_max_turns = int(gw["max_turns"])

        rules = gw.get("bindings", {}).get("rules", [])
        if not rules:
            return 0

        with self._lock:
            self._bindings.clear()

        # Per-binding time_budget_s falls back to gateway-level default
        default_time_budget = self.gateway_time_budget_s

        loaded = 0
        for rule in rules:
            if not isinstance(rule, dict) or "channel" not in rule:
                continue
            channel_id = rule.get("channel_id", "").strip()
            if not channel_id:
                log.warning(
                    "Skipping binding: channel=%s has no channel_id — "
                    "empty channel_id would create unsafe catch-all",
                    rule.get("channel"),
                )
                continue
            # Support both time_budget_s and legacy max_rounds
            tb = rule.get("time_budget_s")
            if tb is None and "max_rounds" in rule:
                tb = float(int(rule["max_rounds"]) * 10)
            binding = ChannelBinding(
                channel=rule["channel"],
                channel_id=channel_id,
                auto_respond=rule.get("auto_respond", True),
                require_mention=rule.get("require_mention", False),
                allowed_tools=rule.get("allowed_tools", []),
                time_budget_s=float(tb) if tb is not None else default_time_budget,
            )
            self.add_binding(binding)
            loaded += 1

        log.info(
            "Loaded %d gateway bindings from config (time_budget=%.0fs, max_turns=%d)",
            loaded,
            self.gateway_time_budget_s,
            self.gateway_max_turns,
        )
        return loaded
