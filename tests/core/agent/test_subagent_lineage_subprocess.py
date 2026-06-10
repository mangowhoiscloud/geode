"""Subagent lineage — subprocess path invariants.

Companion to ``test_subagent_lineage.py`` (which pins the in-process
PR-F wiring). Pins the subprocess thread:

    parent AgenticLoop (binds ContextVar)
      → SubAgentManager._build_worker_request reads it
      → WorkerRequest carries parent_session_key + parent_session_id
      → worker._run_agentic threads them into the child AgenticLoop
      → child Episode rows record both fields

Concern: PR-F-followup (2026-05-21). Pre-fix subprocess sub-agents
recorded ``parent_session_key=""`` and had no notion of
``parent_session_id`` at all.
"""

from __future__ import annotations

import inspect
from typing import Any

from core.agent.cognitive_state_ctx import (
    get_parent_session_id,
    set_parent_session_id,
    set_session_id,
)
from core.agent.worker import WorkerRequest
from core.memory.episodic import Episode

# ---------------------------------------------------------------------------
# New ContextVar — get/set parity
# ---------------------------------------------------------------------------


def test_parent_session_id_default_is_empty() -> None:
    set_parent_session_id("")
    assert get_parent_session_id() == ""


def test_parent_session_id_set_get_roundtrip() -> None:
    set_parent_session_id("s-parent-uuid-123")
    try:
        assert get_parent_session_id() == "s-parent-uuid-123"
    finally:
        set_parent_session_id("")


def test_parent_session_id_paired_get_set_in_all() -> None:
    from core.agent import cognitive_state_ctx

    assert hasattr(cognitive_state_ctx, "get_parent_session_id")
    assert hasattr(cognitive_state_ctx, "set_parent_session_id")
    assert "get_parent_session_id" in cognitive_state_ctx.__all__
    assert "set_parent_session_id" in cognitive_state_ctx.__all__


# ---------------------------------------------------------------------------
# Episode dataclass
# ---------------------------------------------------------------------------


def test_episode_has_parent_session_id_field() -> None:
    ep = Episode(
        timestamp_ns=1,
        session_id="s-child",
        round=0,
        tool_name="t",
        tool_input_head="",
        success=True,
        error=None,
        duration_ms=0.0,
    )
    assert ep.parent_session_id == ""


def test_episode_parent_session_id_round_trip_via_jsonl() -> None:
    import json

    ep = Episode(
        timestamp_ns=1,
        session_id="s-child",
        round=0,
        tool_name="t",
        tool_input_head="",
        success=True,
        error=None,
        duration_ms=0.0,
        parent_session_key="subject:foo:bar",
        parent_session_id="s-parent-uuid",
    )
    blob = json.loads(ep.to_jsonl())
    assert blob["parent_session_key"] == "subject:foo:bar"
    assert blob["parent_session_id"] == "s-parent-uuid"


# ---------------------------------------------------------------------------
# WorkerRequest schema
# ---------------------------------------------------------------------------


def test_worker_request_carries_lineage_fields() -> None:
    req = WorkerRequest(
        task_id="t1",
        parent_session_key="subject:foo:bar",
        parent_session_id="s-parent-uuid",
    )
    assert req.parent_session_key == "subject:foo:bar"
    assert req.parent_session_id == "s-parent-uuid"


def test_worker_request_lineage_defaults_empty() -> None:
    req = WorkerRequest(task_id="t1")
    assert req.parent_session_key == ""
    assert req.parent_session_id == ""


def test_worker_request_lineage_serialises_via_to_dict() -> None:
    req = WorkerRequest(
        task_id="t1",
        parent_session_key="subject:foo:bar",
        parent_session_id="s-parent-uuid",
    )
    blob = req.to_dict()
    assert blob["parent_session_key"] == "subject:foo:bar"
    assert blob["parent_session_id"] == "s-parent-uuid"


def test_worker_request_lineage_round_trip_via_from_dict() -> None:
    src = WorkerRequest(
        task_id="t1",
        parent_session_key="subject:foo:bar",
        parent_session_id="s-parent-uuid",
    )
    rebuilt = WorkerRequest.from_dict(src.to_dict())
    assert rebuilt.parent_session_key == "subject:foo:bar"
    assert rebuilt.parent_session_id == "s-parent-uuid"


def test_worker_request_lineage_from_dict_missing_keys_default_empty() -> None:
    """Older parents writing WorkerRequest dicts pre-lineage must still
    deserialise — both fields default to ``""``."""
    payload = {
        "task_id": "t1",
        "task_type": "analyze",
        "description": "hi",
    }
    rebuilt = WorkerRequest.from_dict(payload)
    assert rebuilt.parent_session_key == ""
    assert rebuilt.parent_session_id == ""


# ---------------------------------------------------------------------------
# SubAgentManager → WorkerRequest wiring
# ---------------------------------------------------------------------------


def test_build_worker_request_threads_parent_session_key_from_kwarg() -> None:
    """SubAgentManager carries ``parent_session_key`` from its
    constructor kwarg into every WorkerRequest it emits."""
    from typing import cast as _cast

    from core.agent.sub_agent import SubAgentManager, SubTask

    runner = _cast(Any, object())  # _build_worker_request does not touch it
    mgr = SubAgentManager(
        runner,
        parent_session_key="subject:foo:bar",
        action_handlers={},  # enable subprocess routing path
    )
    task = SubTask(task_id="t1", description="d", task_type="analyze")
    req = mgr._build_worker_request(task)
    assert req.parent_session_key == "subject:foo:bar"


def test_build_worker_request_reads_parent_session_id_from_contextvar() -> None:
    """SubAgentManager reads the parent's ``_session_id`` uuid from
    the ContextVar bound by the calling AgenticLoop."""
    from typing import cast as _cast

    from core.agent.sub_agent import SubAgentManager, SubTask

    runner = _cast(Any, object())
    mgr = SubAgentManager(
        runner,
        action_handlers={},
    )
    task = SubTask(task_id="t1", description="d", task_type="analyze")
    set_session_id("s-parent-uuid-from-loop")
    try:
        req = mgr._build_worker_request(task)
        assert req.parent_session_id == "s-parent-uuid-from-loop"
    finally:
        set_session_id("")


def test_build_worker_request_lineage_defaults_when_no_loop_bound() -> None:
    """Outside an agentic loop the ContextVar is empty, so the
    WorkerRequest records ``parent_session_id=""`` rather than raising."""
    from typing import cast as _cast

    from core.agent.sub_agent import SubAgentManager, SubTask

    runner = _cast(Any, object())
    mgr = SubAgentManager(
        runner,
        action_handlers={},
    )
    task = SubTask(task_id="t1", description="d", task_type="analyze")
    set_session_id("")
    req = mgr._build_worker_request(task)
    assert req.parent_session_id == ""
    assert req.parent_session_key == ""


# ---------------------------------------------------------------------------
# AgenticLoop kwarg + ContextVar binding
# ---------------------------------------------------------------------------


def test_agenticloop_constructor_accepts_parent_session_id_kwarg() -> None:
    from core.agent.loop.agent_loop import AgenticLoop

    sig = inspect.signature(AgenticLoop.__init__)
    assert "parent_session_id" in sig.parameters
    assert sig.parameters["parent_session_id"].default == ""


def test_session_start_signals_bind_parent_session_id() -> None:
    """``AgenticLoop._emit_session_start_signals`` must bind the
    constructor's ``parent_session_id`` into the ContextVar so the
    episodic recorder sees it on TOOL_EXEC_ENDED."""
    import asyncio
    from typing import cast as _cast

    from core.agent.cognitive_state import CognitiveState
    from core.agent.cognitive_state_ctx import get_parent_session_id
    from core.agent.loop.agent_loop import AgenticLoop

    class _StubCtx:
        def add_user_message(self, _msg: str) -> None:
            return None

    captured: dict[str, str] = {}

    async def _fake_emit_cognitive(self: AgenticLoop, _event, **_kwargs) -> None:
        captured["parent_session_id"] = get_parent_session_id()

    loop_obj = _cast(Any, AgenticLoop.__new__(AgenticLoop))
    loop_obj.context = _StubCtx()
    loop_obj.cognitive_state = CognitiveState()
    loop_obj._session_id = "s-child-uuid"
    loop_obj._parent_session_key = "subject:foo:bar"
    loop_obj._parent_session_id = "s-parent-uuid-bound"
    loop_obj._transcript = None
    loop_obj._hooks = None
    loop_obj.model = "claude-opus-4-7"
    loop_obj._provider = "anthropic"
    loop_obj._emit_cognitive = _fake_emit_cognitive.__get__(loop_obj, AgenticLoop)

    async def _run() -> None:
        result = await AgenticLoop._emit_session_start_signals(loop_obj, "hello")
        assert result is None

    asyncio.run(_run())
    assert captured["parent_session_id"] == "s-parent-uuid-bound"


# ---------------------------------------------------------------------------
# worker.py wiring — pin that AgenticLoop receives the lineage kwargs
# ---------------------------------------------------------------------------


def test_worker_run_agentic_passes_lineage_kwargs() -> None:
    """``_run_agentic`` must pass ``parent_session_key`` and
    ``parent_session_id`` from WorkerRequest into the AgenticLoop
    constructor. Pin the source so the wiring can't silently drop."""
    import core.agent.worker as worker_mod

    src = inspect.getsource(worker_mod._run_agentic)
    assert "parent_session_key=request.parent_session_key" in src
    assert "parent_session_id=request.parent_session_id" in src


# ---------------------------------------------------------------------------
# Bootstrap hook — Episode carries parent_session_id
# ---------------------------------------------------------------------------


def test_bootstrap_episodic_recorder_reads_parent_session_id() -> None:
    """The TOOL_EXEC_ENDED handler must read ``get_parent_session_id``
    and stamp ``Episode.parent_session_id`` so the child's Episodes
    actually carry the lineage value bound at session-start."""
    import core.wiring.bootstrap as bootstrap_mod

    src = inspect.getsource(bootstrap_mod)
    # Import is updated
    assert "get_parent_session_id," in src
    # Reader call exists
    assert "parent_session_id = get_parent_session_id()" in src
    # Episode constructor argument exists
    assert "parent_session_id=parent_session_id" in src
