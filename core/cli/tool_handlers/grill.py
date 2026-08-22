"""Typed ``/grill`` tree tool handlers."""

from __future__ import annotations

from typing import Any

from core.memory.grills import GrillStatus, GrillStore
from core.tools.handlers.registration import UniqueEntries


def _build_grill_handlers(store: GrillStore | None = None) -> UniqueEntries[str, Any]:
    grill_store = store or GrillStore()

    def _session_id() -> str:
        from core.agent.cognitive_state_ctx import get_session_id

        return get_session_id()

    def _record(grill: Any, *, trigger: str) -> None:
        from core.agent.cognitive_state_ctx import get_tool_call_id
        from core.observability.session_timeline import (
            SessionEventKind,
            current_session_timeline,
        )

        timeline = current_session_timeline()
        if timeline is not None:
            kind = (
                SessionEventKind.GRILL_COMPLETED
                if grill.status is GrillStatus.COMPLETE
                else SessionEventKind.GRILL_UPDATED
            )
            timeline.record_control_state(
                kind,
                grill,
                trigger=trigger,
                call_id=get_tool_call_id(),
            )

    def _mark_prompt_dirty() -> None:
        from core.cli.session_state import get_current_loop

        loop = get_current_loop()
        if loop is not None:
            loop._prompt_dirty = True

    def handle_get_grill(**_: Any) -> dict[str, Any]:
        grill = grill_store.get(_session_id())
        return {"status": "ok", "grill": grill.to_dict() if grill else None}

    def handle_update_grill(**kwargs: Any) -> dict[str, Any]:
        action = str(kwargs.get("action") or "")
        try:
            if action == "define":
                grill = grill_store.define(_session_id(), kwargs.get("nodes"))
            elif action == "answer":
                grill = grill_store.answer(
                    _session_id(),
                    str(kwargs.get("node_id") or ""),
                    str(kwargs.get("answer") or ""),
                )
            elif action == "complete":
                grill = grill_store.complete(_session_id())
            else:
                raise ValueError("update_grill action must be define, answer, or complete")
        except (TypeError, ValueError) as exc:
            return {"error": str(exc), "action": action}
        _record(grill, trigger=f"update_grill:{action}")
        _mark_prompt_dirty()
        return {"status": "ok", "action": action, "grill": grill.to_dict()}

    return UniqueEntries((("get_grill", handle_get_grill), ("update_grill", handle_update_grill)))


__all__ = ["_build_grill_handlers"]
