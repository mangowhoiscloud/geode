"""ConversationContext — session-level multi-turn message history.

Maintains user/assistant messages for multi-turn agentic conversations.
Used by AgenticLoop to preserve context across tool-use rounds and
follow-up questions.

With 1M context models and server-side ``clear_tool_uses`` context
management, aggressive client-side trimming is unnecessary. The default
``max_turns=200`` acts as a safety net, not a performance optimisation.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    """Session-level conversation history for multi-turn agentic interactions.

    Keeps the most recent ``max_turns`` user+assistant pairs as a safety
    net.  With 1M context models and server-side ``clear_tool_uses``,
    the primary context management is handled server-side; this limit
    only guards against extreme runaway sessions.
    """

    max_turns: int = 200
    messages: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_user_message(self, text: str) -> None:
        """Append a user message and trim if needed."""
        self.messages.append({"role": "user", "content": text})
        self._trim()

    def add_assistant_message(self, content: Any) -> None:
        """Append an assistant message (text or content blocks)."""
        self.messages.append({"role": "assistant", "content": content})
        self._trim()

    def add_tool_result(self, tool_results: list[dict[str, Any]]) -> None:
        """Append tool results as a user message (Anthropic convention)."""
        self.messages.append({"role": "user", "content": tool_results})
        self._trim()

    def get_messages(self) -> list[dict[str, Any]]:
        """Return a deep copy of messages for an API call."""
        return copy.deepcopy(self.messages)

    def clear(self) -> None:
        """Clear all messages."""
        self.messages.clear()

    @property
    def turn_count(self) -> int:
        """Number of user messages (approximate turn count)."""
        return sum(1 for m in self.messages if m["role"] == "user")

    def add_system_event(self, event_type: str, content: str) -> None:
        """Inject a system event as a user message (non-tool-result).

        Used for out-of-band notifications such as sub-agent completion
        announcements (OpenClaw Spawn+Announce pattern).  The event is
        wrapped in a structured text block so the LLM can distinguish
        system events from user input.
        """
        formatted = f"[system:{event_type}] {content}"
        self.messages.append({"role": "user", "content": formatted})
        self._trim()
        log.debug("System event injected: type=%s len=%d", event_type, len(content))

    @property
    def is_empty(self) -> bool:
        return len(self.messages) == 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _trim(self) -> None:
        """Keep only the last ``max_turns * 2`` messages.

        Preserves tool_use/tool_result pairs: after slicing, any orphaned
        tool_result blocks (whose tool_use was trimmed away) are removed
        to prevent Anthropic API 400 errors.
        """
        max_msgs = self.max_turns * 2
        if len(self.messages) <= max_msgs:
            return

        self.messages = self.messages[-max_msgs:]

        # Ensure first message is user role (Anthropic API requirement)
        while self.messages and self.messages[0]["role"] != "user":
            self.messages.pop(0)

        # Sanitize orphaned tool_result blocks.
        # A tool_result in a user message must reference a tool_use_id
        # in the immediately preceding assistant message.
        self._sanitize_tool_pairs()

        log.debug(
            "ConversationContext trimmed to %d messages (%d turns)",
            len(self.messages),
            self.turn_count,
        )

    def _sanitize_tool_pairs(self) -> None:
        """Remove orphaned tool_result blocks from conversation history.

        Scans user messages with list content; for each tool_result block,
        checks that the preceding assistant message has a matching tool_use.
        Orphans are dropped silently.
        """
        sanitized: list[dict[str, Any]] = []
        for i, msg in enumerate(self.messages):
            if msg["role"] == "user" and isinstance(msg.get("content"), list):
                # Collect valid tool_use IDs from preceding assistant message
                prev_tool_ids: set[str] = set()
                if i > 0 and self.messages[i - 1]["role"] == "assistant":
                    prev = self.messages[i - 1]
                    for blk in prev.get("content") or []:
                        if isinstance(blk, dict) and blk.get("type") == "tool_use":
                            prev_tool_ids.add(blk["id"])

                valid_content: list[Any] = []
                dropped = 0
                for blk in msg["content"]:
                    if (
                        isinstance(blk, dict)
                        and blk.get("type") == "tool_result"
                        and blk.get("tool_use_id") not in prev_tool_ids
                    ):
                        dropped += 1
                        continue
                    valid_content.append(blk)

                if dropped:
                    log.debug("Dropped %d orphaned tool_result blocks at index %d", dropped, i)

                if valid_content:
                    sanitized.append({**msg, "content": valid_content})
                # else: entire message was orphaned tool_results — drop it
            else:
                sanitized.append(msg)

        self.messages = sanitized
