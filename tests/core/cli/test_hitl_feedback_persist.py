"""PR-PRE10-ROUND2: HITL feedback handlers persist verdicts via RESULT_FEEDBACK.

Pre-PR the operator's rate/accept/reject verdict was written to a closure-local
dict that nothing ever read. Now each handler fires
``HookEvent.RESULT_FEEDBACK``, which the wildcard RunLog subscriber persists to
the session JSONL. These assert the handlers fire the event with the right
verdict payload (and don't fire on a missing subject).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.cli.tool_handlers.hitl import _build_hitl_handlers
from core.hooks.system import HookEvent
from core.hooks.tool_hooks import set_tool_hooks


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
