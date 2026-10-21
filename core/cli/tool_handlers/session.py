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


def _read_result_limit(context: Any = None) -> tuple[int | None, str]:
    """The executing processor's offload/guard bound on one serialized result.

    Returns the bound in characters and the setting that imposes it.
    """
    from core.agent.tool_executor.result_token_guard import tool_result_char_limit

    model = getattr(context, "model", "")
    model = model if isinstance(model, str) else ""
    threshold: int | None = None  # no processor: the configured threshold
    processor = getattr(getattr(context, "agent_loop", None), "_tool_processor", None)
    if processor is not None:
        processor_model = getattr(processor, "_model", "")
        if isinstance(processor_model, str) and processor_model:
            model = processor_model
        store_threshold = getattr(getattr(processor, "_offload_store", None), "threshold", 0)
        threshold = store_threshold if isinstance(store_threshold, int) else 0
    limit = tool_result_char_limit(model, offload_threshold=threshold)
    guard = tool_result_char_limit(model, offload_threshold=0)
    setting = "subagent.max_tool_result_tokens" if limit == guard else "tool_offload.threshold"
    return limit, setting


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
        max_result_chars, limit_setting = _read_result_limit(context)
        try:
            return read_peer_messages(
                tool_principal(context),
                admitted if isinstance(admitted, set) else None,
                limit=int(kwargs.get("limit") or 5),
                max_result_chars=max_result_chars,
                limit_setting=limit_setting,
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
