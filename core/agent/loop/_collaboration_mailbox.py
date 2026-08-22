"""Durable child-message admission at an ``AgenticLoop`` round boundary."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


def admit_collaboration_messages(
    loop: AgenticLoop,
    messages: list[dict[str, Any]],
    *,
    user_input: str = "",
    round_idx: int = 0,
) -> int:
    """Persist unread child messages before acknowledging their mailbox rows."""
    try:
        from core.memory.collaboration import CollaborationStore

        store = CollaborationStore()
        mailbox = store.read_mailbox(loop._session_id)
    except Exception:
        log.warning("Collaboration mailbox read failed", exc_info=True)
        return 0
    if not mailbox:
        return 0

    injected = 0
    for item in mailbox:
        marker = f"mailbox_id={item.id}"
        if any(marker in str(message.get("content", "")) for message in messages):
            continue
        if item.kind == "message":
            event = "subagent_message"
            content = f"Parent follow-up: {item.payload.get('message', '')}"
        else:
            event = "subagent_completed"
            content = "Sub-agent completion: " + json.dumps(
                item.payload, ensure_ascii=False, sort_keys=True
            )
        marked_content = f"{content} ({marker})"
        loop.context.add_system_event(event, marked_content)
        messages.append({"role": "user", "content": f"[system:{event}] {marked_content}"})
        injected += 1

    try:
        checkpoint = getattr(loop, "_checkpoint", None)
        if checkpoint is None:
            return injected
        from . import _context

        _context.sync_messages_to_context(loop, messages)
        if not loop._save_checkpoint(user_input, round_idx):
            return injected
        store.ack_mailbox(loop._session_id, [item.id for item in mailbox])
    except Exception:
        log.warning("Collaboration mailbox acknowledgement failed", exc_info=True)
    return injected
