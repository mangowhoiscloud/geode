"""R6.9 peer-session tool handlers bound to the runtime's trusted session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.memory.session_peers import (
    SessionPrincipal,
    fork_session,
    read_peer_messages,
    send_peer_message,
)
from core.tools.handlers.registration import UniqueEntries


def tool_principal(context: Any = None) -> SessionPrincipal:
    """Bind the caller from the executing loop, never from tool arguments."""
    from core.agent.cognitive_state_ctx import get_parent_session_id, get_session_id

    loop = getattr(context, "agent_loop", None)
    parent = get_parent_session_id() or str(getattr(loop, "_parent_session_id", "") or "")
    if not parent and getattr(context, "is_subagent", False):
        parent = "subagent"  # fail closed: a worker without a recorded parent
    return SessionPrincipal(
        session_id=str(getattr(context, "session_id", "") or get_session_id()),
        parent_session_id=parent,
    )


def _build_session_handlers(sessions_dir: Path | None = None) -> UniqueEntries[str, Any]:
    """Build the model-facing peer message, read, and fork handlers."""

    def handle_send_session_message(**kwargs: Any) -> dict[str, Any]:
        try:
            receipt = send_peer_message(
                tool_principal(kwargs.get("_tool_context")),
                str(kwargs.get("session_id") or ""),
                str(kwargs.get("message") or ""),
                sessions_dir=sessions_dir,
            )
        except ValueError as exc:
            return {"error": str(exc), "error_type": "rejected"}
        return receipt.to_dict()

    def handle_fork_session(**kwargs: Any) -> dict[str, Any]:
        try:
            receipt = fork_session(
                tool_principal(kwargs.get("_tool_context")),
                str(kwargs.get("source_session_id") or ""),
                sessions_dir=sessions_dir,
            )
        except ValueError as exc:
            return {"error": str(exc), "error_type": "rejected"}
        return receipt.to_dict()

    def handle_read_session_messages(**kwargs: Any) -> dict[str, Any]:
        context = kwargs.get("_tool_context")
        loop = getattr(context, "agent_loop", None)
        admitted = getattr(loop, "_admitted_mailbox_ids", None)
        try:
            return read_peer_messages(
                tool_principal(context),
                admitted if isinstance(admitted, set) else None,
                limit=int(kwargs.get("limit") or 20),
                sessions_dir=sessions_dir,
            )
        except ValueError as exc:
            return {"error": str(exc), "error_type": "rejected"}

    return UniqueEntries(
        (
            ("send_session_message", handle_send_session_message),
            ("fork_session", handle_fork_session),
            ("read_session_messages", handle_read_session_messages),
        )
    )
