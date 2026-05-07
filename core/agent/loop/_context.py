"""Context-window/message helpers + system-prompt assembly.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7). Each
function takes the ``AgenticLoop`` as the first parameter (``loop``)
and reads/writes its state. The class methods on ``AgenticLoop`` are
thin one-line delegators.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.agent.system_prompt import build_system_prompt as _build_system_prompt
from core.llm.prompts import AGENTIC_SUFFIX

if TYPE_CHECKING:
    from .loop import AgenticLoop

log = logging.getLogger(__name__)


def sync_messages_to_context(loop: AgenticLoop, messages: list[dict[str, Any]]) -> None:
    """Replace context messages with the full messages list.

    During the agentic loop, intermediate tool-use messages are appended
    only to the local ``messages`` list.  This method syncs them back to
    ``self.context`` so the next user turn sees the full history.
    """
    loop.context.messages = list(messages)


def notify_context_event(
    loop: AgenticLoop, event_type: str, *, original_count: int, new_count: int
) -> None:
    """Notify user of context compression. Delegates to ContextWindowManager."""
    loop._ctx_mgr._notify_context_event(
        event_type, original_count=original_count, new_count=new_count
    )


def maybe_prune_messages(loop: AgenticLoop, messages: list[dict[str, Any]]) -> None:
    """Prune old messages. Delegates to ContextWindowManager."""
    loop._ctx_mgr.maybe_prune_messages(messages)


def check_context_overflow(loop: AgenticLoop, system: str, messages: list[dict[str, Any]]) -> None:
    """Check context window usage. Delegates to ContextWindowManager."""
    loop._ctx_mgr.check_context_overflow(system, messages, loop.model, loop._provider)


def aggressive_context_recovery(
    loop: AgenticLoop, system: str, messages: list[dict[str, Any]]
) -> int:
    """Last-resort context recovery. Delegates to ContextWindowManager."""
    return loop._ctx_mgr.aggressive_context_recovery(system, messages, loop.model, loop._provider)


def repair_messages(messages: list[dict[str, Any]]) -> None:
    """Remove orphaned tool_result messages. Delegates to ContextWindowManager."""
    from core.agent.context_manager import ContextWindowManager

    ContextWindowManager.repair_messages(messages)


def build_system_prompt(loop: AgenticLoop) -> str:
    """Build the system prompt with skill context and agentic suffix."""
    base = _build_system_prompt(model=loop.model)
    # Inject skill context into placeholder
    skill_ctx = ""
    if loop._skill_registry is not None:
        skill_ctx = loop._skill_registry.get_context_block()
    base = base.replace("{skill_context}", skill_ctx or "No skills loaded.")
    prompt = base + "\n" + AGENTIC_SUFFIX
    if loop._system_suffix:
        prompt += "\n\n" + loop._system_suffix
    return prompt
