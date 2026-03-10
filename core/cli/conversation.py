"""ConversationContext — session-level multi-turn message history.

Maintains a sliding window of user/assistant messages for multi-turn
agentic conversations. Used by AgenticLoop to preserve context across
tool-use rounds and follow-up questions.
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

    Keeps the most recent ``max_turns`` user+assistant pairs to avoid
    exceeding the context window while enabling pronoun resolution and
    follow-up queries.
    """

    max_turns: int = 20
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

    @property
    def is_empty(self) -> bool:
        return len(self.messages) == 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _trim(self) -> None:
        """Keep only the last ``max_turns * 2`` messages.

        We preserve pairs so the message list always starts with a user
        message (required by the Anthropic API).
        """
        max_msgs = self.max_turns * 2
        if len(self.messages) <= max_msgs:
            return

        self.messages = self.messages[-max_msgs:]

        # Ensure first message is user role (Anthropic API requirement)
        while self.messages and self.messages[0]["role"] != "user":
            self.messages.pop(0)

        log.debug(
            "ConversationContext trimmed to %d messages (%d turns)",
            len(self.messages),
            self.turn_count,
        )
