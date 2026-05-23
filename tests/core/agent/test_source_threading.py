"""Source threading invariants — SubTask → WorkerRequest → AgenticLoop.

Pins v0.99.40 Follow-up A: when a parent picker resolves a per-role
``RoleBinding.source`` (one of ``"payg"`` / ``"subscription"`` / ``"adapter"``),
that value must reach the spawned worker's :class:`AgenticLoop`.
Regression here means the operator's per-role auth choice silently collapses
back onto ``ProfileRotator``'s global type-priority.
"""

from __future__ import annotations

import pytest
from core.agent.sub_agent import SubTask
from core.agent.worker import WorkerRequest


def test_subtask_default_source_is_empty_legacy() -> None:
    """Unset source means legacy routing — no behaviour change for old callers."""
    task = SubTask(task_id="t1", description="d", task_type="analyze")
    assert task.source == ""


def test_subtask_accepts_concrete_source() -> None:
    """SubTask carries a concrete adapter source for picker-driven flows."""
    task = SubTask(task_id="t1", description="d", task_type="analyze", source="subscription")
    assert task.source == "subscription"


def test_worker_request_serialisation_round_trip() -> None:
    """``source`` survives the wire encode / decode used by the worker subprocess."""
    req = WorkerRequest(task_id="t1", source="adapter")
    encoded = req.to_dict()
    assert encoded["source"] == "adapter"
    decoded = WorkerRequest.from_dict(encoded)
    assert decoded.source == "adapter"


def test_worker_request_legacy_payload_decodes_with_empty_source() -> None:
    """Backward-compat: old wire payloads without ``source`` decode safely."""
    legacy_payload = {
        "task_id": "t1",
        "task_type": "analyze",
        "description": "d",
    }
    req = WorkerRequest.from_dict(legacy_payload)
    assert req.source == ""


@pytest.mark.parametrize("source", ["payg", "subscription", "adapter", ""])
def test_worker_request_accepts_all_source_shapes(source: str) -> None:
    req = WorkerRequest(task_id="t1", source=source)
    assert req.source == source
