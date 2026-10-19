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
    """Persist unread child messages before acknowledging their mailbox rows.

    An item is injected once per conversation: its ID joins the checkpointed
    admission receipt, and only IDs persisted by a successful checkpoint are
    acknowledged. A failed save or ack leaves the row unread for retry without
    duplicating it; after a crash the restored receipt matches the restored
    conversation, so a row is either already present or injected again.
    """
    try:
        from core.memory.collaboration import CollaborationStore

        store = CollaborationStore()
        mailbox = store.read_mailbox(loop._session_id)
    except Exception:
        log.warning("Collaboration mailbox read failed", exc_info=True)
        return 0
    if not mailbox:
        return 0

    # Trusted admission receipt: IDs already placed in this conversation but
    # not yet acknowledged. It is checkpointed with the messages (loop guards)
    # and scoped to this recipient, so no message text can suppress delivery.
    admitted = getattr(loop, "_admitted_mailbox_ids", None)
    if not isinstance(admitted, set):
        admitted = set()
        loop._admitted_mailbox_ids = admitted
    injected = 0
    for item in mailbox:
        if item.recipient_session_id != loop._session_id or item.id in admitted:
            continue
        marker = f"mailbox_id={item.id}"  # display only; never read back
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
        admitted.add(item.id)
        injected += 1

    try:
        checkpoint = getattr(loop, "_checkpoint", None)
        if checkpoint is None:
            return injected
        from . import _context

        _context.sync_messages_to_context(loop, messages)
        if not loop._save_checkpoint(user_input, round_idx):
            return injected
        persisted = [item.id for item in mailbox if item.id in admitted]
        store.ack_mailbox(loop._session_id, persisted)
        admitted.difference_update(persisted)
    except Exception:
        log.warning("Collaboration mailbox acknowledgement failed", exc_info=True)
    return injected
