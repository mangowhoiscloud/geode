"""Result-feedback handlers emit bounded, correlated RESULT_FEEDBACK events.

The event records feedback reported through a model tool; it does not establish
direct human authorship. These tests pin the verdict and physical tool-call
correlation payloads and the missing-subject no-op.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.agent.cognitive_state_ctx import (
    reset_tool_call_id,
    set_session_id,
    set_tool_call_id,
    set_turn_id,
)
from core.cli.tool_handlers.hitl import _build_hitl_handlers
from core.hooks.system import HookEvent
from core.hooks.tool_hooks import set_tool_hooks
from core.tools.base import ToolContext


def _handlers_with_recorder() -> tuple[dict, MagicMock]:
    hooks = MagicMock()
    set_tool_hooks(hooks)
    return _build_hitl_handlers(), hooks


def test_accept_fires_result_feedback() -> None:
    handlers, hooks = _handlers_with_recorder()
    handlers["accept_result"](subject="subj-1")
    hooks.trigger.assert_called_once()
    event, data = hooks.trigger.call_args[0]
    assert event == HookEvent.RESULT_FEEDBACK
    assert data == {"subject": "subj-1", "verdict": "accepted"}


def test_reject_fires_result_feedback_with_reason() -> None:
    handlers, hooks = _handlers_with_recorder()
    handlers["reject_result"](subject="subj-2", reason="off-target")
    event, data = hooks.trigger.call_args[0]
    assert event == HookEvent.RESULT_FEEDBACK
    assert data["verdict"] == "rejected"
    assert data["reason"] == "off-target"


def test_rate_fires_result_feedback_with_rating() -> None:
    handlers, hooks = _handlers_with_recorder()
    handlers["rate_result"](subject="subj-3", rating=4, comment="solid")
    event, data = hooks.trigger.call_args[0]
    assert event == HookEvent.RESULT_FEEDBACK
    assert data["verdict"] == "rated"
    assert data["rating"] == 4
    assert data["comment"] == "solid"


def test_missing_subject_does_not_persist() -> None:
    handlers, hooks = _handlers_with_recorder()
    handlers["accept_result"]()  # no subject → clarification, no feedback fired
    hooks.trigger.assert_not_called()


def test_feedback_carries_physical_tool_correlation() -> None:
    handlers, hooks = _handlers_with_recorder()
    set_session_id("context-session")
    set_turn_id("turn-1")
    token = set_tool_call_id("context-call")
    try:
        handlers["accept_result"](
            subject="result-1",
            _tool_context=ToolContext(
                session_id="tool-session",
                tool_call_id="tool-call",
            ),
        )
    finally:
        reset_tool_call_id(token)
        set_session_id("")
        set_turn_id("")

    _, data = hooks.trigger.call_args[0]
    assert data["session_id"] == "tool-session"
    assert data["turn_id"] == "turn-1"
    assert data["tool_call_id"] == "tool-call"
