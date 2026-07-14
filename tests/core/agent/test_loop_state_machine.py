"""AgenticLoop state-machine contracts.

Three invariants introduced by the FSM formalization:

1. State-space closure — every terminal ``AgenticResult`` is born in
   exactly ONE place (``AgenticLoop._terminal_result``) with a
   :class:`TerminationReason` member; no inline string reasons remain.
2. Snapshot completeness — ``collect_guard_state``/``apply_guard_state``
   round-trip the guard counters the conversation messages don't carry,
   and the checkpoint persists them.
3. Session-status transitions — ``SessionStatus`` writes go through the
   transition primitives (save→active, mark_paused, mark_completed).
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from core.agent.convergence import ConvergenceDetector
from core.agent.loop import _lifecycle
from core.agent.loop.models import TerminationReason
from core.memory.session_checkpoint import SessionCheckpoint, SessionState, SessionStatus

_AGENT_LOOP_SRC = (
    Path(__file__).resolve().parents[3] / "core" / "agent" / "loop" / "agent_loop.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. State-space closure (source ratchet)
# ---------------------------------------------------------------------------


def test_terminal_results_born_in_one_place():
    """``AgenticResult(`` appears once in agent_loop.py — inside
    ``_terminal_result``. New exits must route through the choke-point."""
    assert _AGENT_LOOP_SRC.count("AgenticResult(") == 1


def test_no_inline_string_termination_reasons():
    """No ``termination_reason=<string literal>`` in code — either quote
    style, any spacing (docstring mentions wrapped in backticks exempt)."""
    assert re.search(r"(?<!`)termination_reason\s*=\s*[\"']", _AGENT_LOOP_SRC) is None


def test_enum_covers_documented_terminal_alphabet():
    expected = {
        "natural",
        "forced_text",
        "max_rounds",
        "time_budget_expired",
        "session_time_budget_handoff",
        "session_time_budget_expired",
        "context_exhausted",
        "cost_budget_exceeded",
        "billing_error",
        "model_action_required",
        "model_refusal",
        "user_clarification_needed",
        "convergence_detected",
        "repeated_success_no_progress",
        "input_blocked",
        "user_cancelled",
        "actionable_partial",
        "tool_use_yield",
        "llm_error",
        "unknown",
    }
    assert {member.value for member in TerminationReason} == expected


def test_enum_members_compare_equal_to_legacy_strings():
    """StrEnum keeps every existing string comparison working."""
    assert TerminationReason.USER_CLARIFICATION_NEEDED == "user_clarification_needed"
    assert TerminationReason.CONTEXT_EXHAUSTED == "context_exhausted"
    assert str(TerminationReason.MAX_ROUNDS) == "max_rounds"


# ---------------------------------------------------------------------------
# 2. Snapshot completeness
# ---------------------------------------------------------------------------


def _fake_loop() -> SimpleNamespace:
    return SimpleNamespace(
        _consecutive_text_only_rounds=0,
        _consecutive_llm_failures=0,
        _total_empty_rounds=0,
        _budget_warned=False,
        _low_confidence_replan_armed=True,
        _consecutive_tool_tracker=[],
        _convergence=ConvergenceDetector(),
        _session_id="",
        cognitive_state=None,
    )


def test_guard_state_roundtrip():
    src = _fake_loop()
    src._consecutive_text_only_rounds = 1
    src._consecutive_llm_failures = 3
    src._total_empty_rounds = 2
    src._budget_warned = True
    src._consecutive_tool_tracker = [("grep_files", "sig-a"), ("read_file", "sig-b")]
    src._convergence.total_consecutive_tool_errors = 2
    src._convergence.recent_errors = ["boom", "boom"]
    src._convergence.repeated_success_streak = 4
    src._convergence.last_success_tool = "list_dir"

    snapshot = _lifecycle.collect_guard_state(src)

    dst = _fake_loop()
    _lifecycle.apply_guard_state(dst, snapshot)

    assert dst._consecutive_text_only_rounds == 1
    assert dst._consecutive_llm_failures == 3
    assert dst._total_empty_rounds == 2
    assert dst._budget_warned is True
    assert dst._consecutive_tool_tracker == [("grep_files", "sig-a"), ("read_file", "sig-b")]
    assert dst._convergence.to_snapshot() == src._convergence.to_snapshot()


def test_apply_guard_state_is_replacement_not_merge():
    """A legacy checkpoint (no loop_guards) must RESET a reused loop's
    counters — never inherit the previous conversation's guard state."""
    dst = _fake_loop()
    dst._consecutive_llm_failures = 4
    dst._budget_warned = True
    dst._consecutive_tool_tracker = [("grep_files", "sig-a")]
    dst._convergence.total_consecutive_tool_errors = 3

    _lifecycle.apply_guard_state(dst, {})

    assert dst._consecutive_llm_failures == 0
    assert dst._budget_warned is False
    assert dst._consecutive_tool_tracker == []
    assert dst._convergence.total_consecutive_tool_errors == 0
    assert dst._low_confidence_replan_armed is True  # fresh-loop default


def test_apply_guard_state_coerces_malformed_values():
    """A malformed checkpoint can never leave the loop half-restored."""
    dst = _fake_loop()
    _lifecycle.apply_guard_state(
        dst,
        {
            "consecutive_llm_failures": None,
            "consecutive_text_only_rounds": "not-a-number",
            "consecutive_tool_tracker": "garbage",
            "convergence": "garbage",
        },
    )
    assert dst._consecutive_llm_failures == 0
    assert dst._consecutive_text_only_rounds == 0
    assert dst._consecutive_tool_tracker == []
    assert dst._convergence.to_snapshot() == ConvergenceDetector().to_snapshot()


def test_restore_loop_state_is_the_single_surgery():
    dst = _fake_loop()
    state = SimpleNamespace(
        session_id="s-resume-1",
        cognitive_state={},
        loop_guards={"consecutive_text_only_rounds": 1, "budget_warned": True},
    )
    _lifecycle.restore_loop_state(dst, state)
    assert dst._session_id == "s-resume-1"
    assert dst.cognitive_state is not None
    assert dst._consecutive_text_only_rounds == 1
    assert dst._budget_warned is True


def test_checkpoint_persists_loop_guards(tmp_path):
    cp = SessionCheckpoint(tmp_path / "sessions")
    guards = {
        "consecutive_text_only_rounds": 1,
        "consecutive_llm_failures": 2,
        "total_empty_rounds": 1,
        "budget_warned": True,
        "consecutive_tool_tracker": [["grep_files", "sig-a"]],
        "convergence": ConvergenceDetector().to_snapshot(),
    }
    cp.save(SessionState(session_id="s-guards", messages=[], loop_guards=guards))
    loaded = cp.load("s-guards")
    assert loaded is not None
    assert loaded.loop_guards == guards


# ---------------------------------------------------------------------------
# 3. Session-status transitions
# ---------------------------------------------------------------------------


def _index_status(tmp_path, session_id: str) -> str:
    from core.memory.session_manager import SessionManager

    mgr = SessionManager(tmp_path / "sessions" / "sessions.db")
    try:
        meta = mgr.get(session_id)
        return meta.status if meta else "missing"
    finally:
        mgr.close()


def test_session_status_transitions(tmp_path):
    cp = SessionCheckpoint(tmp_path / "sessions")
    cp.save(SessionState(session_id="s-status", messages=[]))
    assert cp.load("s-status").status == SessionStatus.ACTIVE

    cp.mark_paused("s-status")
    assert cp.load("s-status").status == SessionStatus.PAUSED
    # Both SoTs move together — geode session list reads the SQLite index.
    assert _index_status(tmp_path, "s-status") == SessionStatus.PAUSED
    assert any(s.session_id == "s-status" for s in cp.list_resumable())

    cp.mark_completed("s-status")
    assert cp.load("s-status").status == SessionStatus.COMPLETED
    assert _index_status(tmp_path, "s-status") == SessionStatus.COMPLETED
    assert all(s.session_id != "s-status" for s in cp.list_resumable())

    # COMPLETED is terminal — a further mark_error is an illegal edge and
    # must be refused (v0.99.329 transition enforcement).
    cp.mark_error("s-status")
    assert cp.load("s-status").status == SessionStatus.COMPLETED


def test_mark_paused_missing_session_is_noop(tmp_path):
    cp = SessionCheckpoint(tmp_path / "sessions")
    cp.mark_paused("does-not-exist")  # must not raise


# ---------------------------------------------------------------------------
# 4. Transition-graph enforcement (v0.99.329)
# ---------------------------------------------------------------------------


def test_illegal_transition_out_of_terminal_is_refused(tmp_path, caplog):
    cp = SessionCheckpoint(tmp_path / "sessions")
    cp.save(SessionState(session_id="s-term", messages=[]))
    cp.mark_completed("s-term")

    with caplog.at_level("WARNING"):
        cp.mark_paused("s-term")
        assert cp.transition("s-term", SessionStatus.ACTIVE) is False

    assert cp.load("s-term").status == SessionStatus.COMPLETED
    assert "Illegal session transition" in caplog.text


def test_error_is_terminal_too(tmp_path):
    cp = SessionCheckpoint(tmp_path / "sessions")
    cp.save(SessionState(session_id="s-err", messages=[]))
    cp.mark_error("s-err")
    assert cp.transition("s-err", SessionStatus.COMPLETED) is False
    assert cp.load("s-err").status == SessionStatus.ERROR


def test_paused_repark_is_idempotent(tmp_path):
    cp = SessionCheckpoint(tmp_path / "sessions")
    cp.save(SessionState(session_id="s-park", messages=[]))
    cp.mark_paused("s-park")
    cp.mark_paused("s-park")  # PAUSED -> PAUSED legal (re-park)
    assert cp.load("s-park").status == SessionStatus.PAUSED


def test_reopen_edge(tmp_path):
    cp = SessionCheckpoint(tmp_path / "sessions")
    cp.save(SessionState(session_id="s-re", messages=[]))
    cp.mark_completed("s-re")

    assert cp.reopen("s-re") is True
    assert cp.load("s-re").status == SessionStatus.ACTIVE
    assert cp.reopen("s-re") is True  # non-terminal -> no-op success
    assert cp.reopen("does-not-exist") is False


def test_save_on_terminal_is_implicit_reopen_with_warning(tmp_path, caplog):
    cp = SessionCheckpoint(tmp_path / "sessions")
    cp.save(SessionState(session_id="s-imp", messages=[]))
    cp.mark_completed("s-imp")

    with caplog.at_level("WARNING"):
        cp.save(SessionState(session_id="s-imp", messages=[{"role": "user", "content": "x"}]))

    assert "implicit reopen" in caplog.text
    # The turn's data is never dropped — the machine re-entered ACTIVE.
    assert cp.load("s-imp").status == SessionStatus.ACTIVE


def test_unknown_status_normalizes_to_error(tmp_path, caplog):
    import json as _json

    cp = SessionCheckpoint(tmp_path / "sessions")
    cp.save(SessionState(session_id="s-junk", messages=[]))
    state_file = tmp_path / "sessions" / "s-junk" / "state.json"
    data = _json.loads(state_file.read_text())
    data["status"] = "definitely-not-a-status"
    state_file.write_text(_json.dumps(data))

    with caplog.at_level("WARNING"):
        loaded = cp.load("s-junk")
    assert loaded is not None
    assert loaded.status == SessionStatus.ERROR
    assert "Unknown session status" in caplog.text


def test_transitions_ledger_records_every_edge(tmp_path):
    """Observability — the automaton's audit trail catches every edge kind."""
    import json as _json

    cp = SessionCheckpoint(tmp_path / "sessions")
    cp.save(SessionState(session_id="s-led", messages=[]))
    cp.mark_paused("s-led")  # transition active -> paused
    cp.mark_completed("s-led")  # transition paused -> completed
    cp.mark_paused("s-led")  # refused (terminal)
    cp.reopen("s-led")  # reopen completed -> active
    cp.mark_completed("s-led")  # transition active -> completed
    cp.save(SessionState(session_id="s-led", messages=[]))  # implicit_reopen

    ledger = tmp_path / "sessions" / "transitions.jsonl"
    rows = [_json.loads(line) for line in ledger.read_text().splitlines()]
    edges = [(r["edge"], r["from"], r["to"]) for r in rows]
    assert ("save", None, "active") in edges  # absent -> active (first save)
    assert ("transition", "active", "paused") in edges
    assert ("refused", "completed", "paused") in edges
    assert ("reopen", "completed", "active") in edges
    assert ("implicit_reopen", "completed", "active") in edges
    assert all(r["session_id"] == "s-led" and r["ts"] > 0 for r in rows)
