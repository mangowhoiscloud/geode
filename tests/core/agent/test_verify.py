"""Unit tests for :mod:`core.agent.verify` — per-turn verify.

Coverage:
- ``VerifyMode`` StrEnum values
- ``VerifyResult`` dataclass shape (frozen, slots, to_payload)
- ``get_verify_mode`` env knob parsing (default + override + invalid fallback)
- ``_verify_rule_based`` catches: empty_turn, short_output, tool_error,
  model_action_required
- ``synthesize_reflection_hint`` renders the failure-reflection block
- ``verify_turn`` dispatcher: OFF / RULE_BASED / LLM_JUDGE (stub-falls-back)
- SessionMetrics integration: ``record_verify`` + ``last_verify_reflection_hint``
- AgenticLoop hint consumption: ``_consume_reflection_hint`` reads+clears
"""

from __future__ import annotations

import inspect
import os

import pytest
from core.agent.loop.models import AgenticResult
from core.agent.verify import (
    DEFAULT_MIN_TEXT_CHARS,
    VerifyMode,
    VerifyResult,
    get_verify_mode,
    synthesize_reflection_hint,
    synthesize_reflexion_hint,
    verify_turn,
)
from core.observability.session_metrics import (
    current_session_metrics,
    session_metrics_scope,
)


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear verify-related env vars so each test starts at known defaults."""
    monkeypatch.delenv("GEODE_VERIFY_MODE", raising=False)
    monkeypatch.delenv("GEODE_VERIFY_MIN_TEXT_CHARS", raising=False)


def _make_result(
    *,
    text: str = "OK",
    tool_calls: list[dict] | None = None,
    termination_reason: str = "natural",
) -> AgenticResult:
    """Minimal AgenticResult fixture — only the fields verify reads."""
    return AgenticResult(
        text=text,
        tool_calls=tool_calls or [],
        rounds=1,
        termination_reason=termination_reason,
    )


# -- VerifyMode + VerifyResult shape ------------------------------------


def test_verify_mode_values() -> None:
    assert VerifyMode.OFF.value == "off"
    assert VerifyMode.RULE_BASED.value == "rule_based"
    assert VerifyMode.LLM_JUDGE.value == "llm_judge"


def test_verify_result_frozen() -> None:
    """Immutable so a recorded result can cross threads safely."""
    vr = VerifyResult(passed=True, mode=VerifyMode.RULE_BASED)
    with pytest.raises((AttributeError, TypeError)):
        vr.passed = False  # type: ignore[misc]


def test_verify_result_to_payload() -> None:
    """Payload shape — hook + telemetry consumers read these keys."""
    vr = VerifyResult(
        passed=False,
        mode=VerifyMode.RULE_BASED,
        score=0.0,
        rubric_misses=("empty_turn",),
        reflection_hint="<reflection>...</reflection>",
        ts=123.4,
    )
    payload = vr.to_payload()
    assert payload["passed"] is False
    assert payload["mode"] == "rule_based"
    assert payload["rubric_misses"] == ["empty_turn"]
    assert payload["reflection_hint"].startswith("<reflection>")
    assert payload["reflexion_hint"] == payload["reflection_hint"]
    assert payload["score"] == 0.0


def test_verify_result_accepts_reflexion_hint_legacy_kwarg() -> None:
    """The constructor accepts the old spelling while storing canonical state."""
    vr = VerifyResult(
        passed=False,
        mode=VerifyMode.RULE_BASED,
        reflexion_hint="<reflection>legacy</reflection>",
    )
    assert vr.reflection_hint == "<reflection>legacy</reflection>"
    assert vr.reflexion_hint == vr.reflection_hint


# -- Mode resolution ----------------------------------------------------


def test_get_verify_mode_default() -> None:
    """No env → rule_based default."""
    assert get_verify_mode() is VerifyMode.RULE_BASED


def test_get_verify_mode_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_VERIFY_MODE", "off")
    assert get_verify_mode() is VerifyMode.OFF


def test_get_verify_mode_llm_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")
    assert get_verify_mode() is VerifyMode.LLM_JUDGE


def test_get_verify_mode_unknown_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typo → silent fallback to default + warning. Don't crash."""
    monkeypatch.setenv("GEODE_VERIFY_MODE", "bogus_mode")
    assert get_verify_mode() is VerifyMode.RULE_BASED


# -- Rule-based checks -------------------------------------------------


def test_rule_based_passes_normal_turn() -> None:
    """Tool-using turn with reasonable text → pass."""
    result = _make_result(
        text="Calling the search tool",
        tool_calls=[{"name": "search", "error": False}],
    )
    vr = verify_turn(result)
    assert vr.passed is True
    assert vr.mode is VerifyMode.RULE_BASED
    assert vr.rubric_misses == ()


def test_rule_based_flags_empty_turn() -> None:
    """No text + no tool calls → empty_turn."""
    result = _make_result(text="", tool_calls=[])
    vr = verify_turn(result)
    assert vr.passed is False
    assert "empty_turn" in vr.rubric_misses
    assert vr.reflection_hint.startswith("<reflection>")
    assert vr.reflexion_hint == vr.reflection_hint


def test_rule_based_flags_short_output() -> None:
    """Below MIN_TEXT_CHARS without tool calls → short_output."""
    result = _make_result(text="x" * (DEFAULT_MIN_TEXT_CHARS - 1), tool_calls=[])
    vr = verify_turn(result)
    assert "short_output" in vr.rubric_misses


def test_rule_based_short_output_ok_when_tool_used() -> None:
    """Short text paired with a tool call is legit (acknowledgement)."""
    result = _make_result(
        text="hi",
        tool_calls=[{"name": "search"}],
    )
    vr = verify_turn(result)
    assert vr.passed is True


def test_rule_based_flags_tool_error() -> None:
    """Any tool call with error=True → tool_error."""
    result = _make_result(
        text="I called the tool",
        tool_calls=[
            {"name": "search", "error": False},
            {"name": "fetch", "error": True},
        ],
    )
    vr = verify_turn(result)
    assert "tool_error" in vr.rubric_misses


def test_rule_based_flags_model_action_required() -> None:
    """Termination signaling operator intervention → model_action_required."""
    result = _make_result(
        text="Cost cap hit",
        tool_calls=[],
        termination_reason="model_action_required",
    )
    vr = verify_turn(result)
    assert "model_action_required" in vr.rubric_misses


def test_rule_based_min_chars_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """``GEODE_VERIFY_MIN_TEXT_CHARS`` lifts the short-output threshold."""
    monkeypatch.setenv("GEODE_VERIFY_MIN_TEXT_CHARS", "100")
    result = _make_result(text="x" * 50, tool_calls=[])
    vr = verify_turn(result)
    assert "short_output" in vr.rubric_misses


# -- Reflection hint ----------------------------------------------------


def test_synthesize_hint_empty_on_no_misses() -> None:
    assert synthesize_reflection_hint(()) == ""


def test_synthesize_hint_includes_reason_codes() -> None:
    """Each rubric_miss code surfaces in the hint body."""
    hint = synthesize_reflection_hint(("empty_turn", "tool_error"))
    assert hint.startswith("<reflection>")
    assert hint.endswith("</reflection>")
    assert "empty_turn" in hint
    assert "tool_error" in hint


def test_synthesize_reflexion_hint_legacy_alias() -> None:
    """Older callers using the paper spelling get the canonical block."""
    assert synthesize_reflexion_hint(("empty_turn",)).startswith("<reflection>")


# -- Mode dispatch ------------------------------------------------------


def test_off_mode_skips_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """OFF mode returns passing sentinel without running rule checks."""
    monkeypatch.setenv("GEODE_VERIFY_MODE", "off")
    result = _make_result(text="", tool_calls=[])  # would fail rule-based
    vr = verify_turn(result)
    assert vr.passed is True
    assert vr.mode is VerifyMode.OFF
    assert vr.rubric_misses == ()


def test_llm_judge_falls_back_to_rule_based_in_this_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_JUDGE wiring stub uses rule-based until PR-CL-A6 lands. Mode label
    in the result reflects the requested mode (not silent downgrade)."""
    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")
    result = _make_result(text="", tool_calls=[])
    vr = verify_turn(result)
    assert vr.mode is VerifyMode.LLM_JUDGE  # surfaced intent
    assert vr.passed is False  # rule-based logic ran underneath
    assert "empty_turn" in vr.rubric_misses


# -- SessionMetrics integration ----------------------------------------


def test_record_verify_pass() -> None:
    with session_metrics_scope(session_id="t-vp"):
        m = current_session_metrics()
        m.record_verify(passed=True, mode="rule_based")
        assert m.verify_pass_count == 1
        assert m.verify_fail_count == 0
        assert m.last_verify_passed is True
        assert m.last_verify_reflection_hint == ""


def test_record_verify_fail() -> None:
    with session_metrics_scope(session_id="t-vf"):
        m = current_session_metrics()
        m.record_verify(
            passed=False,
            mode="rule_based",
            rubric_misses=("empty_turn",),
            reflection_hint="<reflection>x</reflection>",
        )
        assert m.verify_fail_count == 1
        assert m.last_verify_passed is False
        assert m.last_verify_rubric_misses == ("empty_turn",)
        assert m.last_verify_reflection_hint == "<reflection>x</reflection>"
        assert m.last_verify_reflexion_hint == m.last_verify_reflection_hint


def test_session_row_exposes_verify_telemetry() -> None:
    with session_metrics_scope(session_id="t-vr"):
        m = current_session_metrics()
        m.record_verify(passed=False, mode="rule_based", rubric_misses=("empty_turn",))
        row = m.to_session_row()
        assert row["verify_pass_count"] == 0
        assert row["verify_fail_count"] == 1
        assert row["last_verify_passed"] is False
        assert row["last_verify_mode"] == "rule_based"
        assert row["last_verify_rubric_misses"] == ["empty_turn"]


# -- AgenticLoop reflection-hint consume -------------------------------


def test_consume_reflection_hint_clears_after_read() -> None:
    """``_consume_reflection_hint`` returns the hint then leaves an empty slot
    so the same hint can't be injected into two consecutive arun's."""
    from core.agent.loop.agent_loop import AgenticLoop

    with session_metrics_scope(session_id="t-consume"):
        current_session_metrics().last_verify_reflection_hint = "<reflection>z</reflection>"
        consume = AgenticLoop._consume_reflection_hint.__get__(
            object(), object
        )  # bind to a bare stub
        assert consume() == "<reflection>z</reflection>"
        # Second call yields empty.
        assert consume() == ""
        # Stored value also cleared.
        assert current_session_metrics().last_verify_reflection_hint == ""


def test_consume_reflexion_hint_legacy_alias() -> None:
    """The old AgenticLoop method name remains as an alias."""
    from core.agent.loop.agent_loop import AgenticLoop

    with session_metrics_scope(session_id="t-consume-legacy"):
        current_session_metrics().last_verify_reflection_hint = "<reflection>z</reflection>"
        consume = AgenticLoop._consume_reflexion_hint.__get__(object(), object)
        assert consume() == "<reflection>z</reflection>"


def test_verify_turn_crash_treats_as_pass() -> None:
    """If the verify path itself raises, return a passing sentinel — the
    observability layer must not break the run it observes."""

    # Build a result that triggers a rule-based check, then monkeypatch
    # ``_verify_rule_based`` to raise so we exercise the except branch.
    import core.agent.verify as verify_module

    original = verify_module._verify_rule_based

    def boom(_result: AgenticResult) -> VerifyResult:
        raise RuntimeError("boom")

    verify_module._verify_rule_based = boom  # type: ignore[assignment]
    try:
        vr = verify_turn(_make_result(text=""))
        assert vr.passed is True
    finally:
        verify_module._verify_rule_based = original  # type: ignore[assignment]


def test_env_does_not_leak_between_tests() -> None:
    """Smoke — autouse ``reset_env`` clears the env so this test sees default."""
    assert os.environ.get("GEODE_VERIFY_MODE") is None
    assert get_verify_mode() is VerifyMode.RULE_BASED


def test_rule_based_multi_miss_combination() -> None:
    """Codex MCP LOW #5 — a single turn can flag multiple rubric codes
    simultaneously. Empty text + tool error → both codes surface."""
    result = _make_result(
        text="",
        tool_calls=[{"name": "search", "error": True}],
    )
    vr = verify_turn(result)
    assert vr.passed is False
    # ``empty_turn`` doesn't fire when tool_calls is non-empty, so the
    # genuine multi-miss case is ``model_action_required + tool_error``.
    multi_result = _make_result(
        text="",
        tool_calls=[{"name": "search", "error": True}],
        termination_reason="model_action_required",
    )
    multi_vr = verify_turn(multi_result)
    assert "tool_error" in multi_vr.rubric_misses
    assert "model_action_required" in multi_vr.rubric_misses
    assert len(multi_vr.rubric_misses) >= 2
    # Reflection hint surfaces both codes.
    assert "tool_error" in multi_vr.reflection_hint
    assert "model_action_required" in multi_vr.reflection_hint


def test_effective_mode_distinguishes_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex MCP LOW #4 — ``mode`` records operator intent, ``effective_mode``
    records the path that actually ran. LLM_JUDGE → RULE_BASED fallback
    surfaces both values."""
    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")
    vr = verify_turn(_make_result(text=""))
    assert vr.mode is VerifyMode.LLM_JUDGE
    assert vr.effective_mode is VerifyMode.RULE_BASED
    payload = vr.to_payload()
    assert payload["mode"] == "llm_judge"
    assert payload["effective_mode"] == "rule_based"


def test_effective_mode_off_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    """OFF mode has no fallback — both modes match."""
    monkeypatch.setenv("GEODE_VERIFY_MODE", "off")
    vr = verify_turn(_make_result())
    assert vr.mode is VerifyMode.OFF
    assert vr.effective_mode is VerifyMode.OFF


def test_lifecycle_finalize_sync_records_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex MCP LOW #5 — sync ``finalize_and_return`` path drives
    ``_run_turn_verify`` → ``record_verify`` even when ``loop._hooks`` is
    None (Codex HIGH #1 invariant). Asserts SessionMetrics state after."""
    from types import SimpleNamespace

    from core.agent.loop._lifecycle import _run_turn_verify

    result = _make_result(text="", tool_calls=[])  # rule-based: empty_turn
    loop = SimpleNamespace(_hooks=None)
    with session_metrics_scope(session_id="t-sync-finalize"):
        payload = _run_turn_verify(loop, result)
        assert payload is not None
        assert payload["passed"] is False
        assert "empty_turn" in payload["rubric_misses"]
        m = current_session_metrics()
        assert m.verify_fail_count == 1
        assert m.last_verify_reflection_hint.startswith("<reflection>")


def test_lifecycle_run_turn_verify_off_mode_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_run_turn_verify`` returns None when mode is OFF so the caller
    can skip the hook fire."""
    from types import SimpleNamespace

    from core.agent.loop._lifecycle import _run_turn_verify

    monkeypatch.setenv("GEODE_VERIFY_MODE", "off")
    loop = SimpleNamespace(_hooks=None)
    with session_metrics_scope(session_id="t-off"):
        result = _make_result(text="", tool_calls=[])
        payload = _run_turn_verify(loop, result)
        assert payload is None
        assert current_session_metrics().verify_fail_count == 0


def test_finalizers_run_verify_before_lifecycle_hooks() -> None:
    """Reflection verification runs at the task-completion boundary before terminal
    lifecycle hooks are emitted."""
    from core.agent.loop import _lifecycle

    sync_src = inspect.getsource(_lifecycle.finalize_and_return)
    async_src = inspect.getsource(_lifecycle.finalize_and_return_async)

    assert sync_src.index("verify_payload = _run_turn_verify(") < sync_src.index(
        "HookEvent.SESSION_ENDED"
    )
    assert async_src.index("verify_payload = await _run_turn_verify_async(") < async_src.index(
        "HookEvent.SESSION_ENDED"
    )


def test_final_hook_payloads_include_verify_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SESSION_ENDED and TURN_COMPLETED payloads carry the final verify
    result when verify/reflection is enabled."""
    from types import SimpleNamespace

    from core.agent.loop import _lifecycle

    monkeypatch.setattr(
        "core.llm.adapters.dispatch.get_session_adapter_usage",
        lambda: {},
    )
    monkeypatch.setattr(
        "core.llm.adapters.dispatch.end_session_adapter_tracking",
        lambda: None,
    )
    loop = SimpleNamespace(
        model="gpt-5.5",
        _provider="openai-codex",
        _session_id="s-final",
        _parent_session_id="",
        _new_adapter=None,
        _last_emitted_session_id="",
    )
    result = _make_result(text="done", tool_calls=[])
    verify_payload = {"passed": True, "mode": "rule_based"}

    session_ended, turn_completed, _metrics = _lifecycle._final_hook_payloads(
        loop,
        result,
        "do work",
        verify_payload=verify_payload,
    )

    assert session_ended["turn_verify"] is verify_payload
    assert turn_completed["turn_verify"] is verify_payload


def test_should_retry_signal_for_recoverable_miss() -> None:
    """Codex MCP MEDIUM #4 — ``should_retry`` True for recoverable misses
    (``empty_turn`` / ``short_output`` / ``tool_error``)."""
    result = _make_result(text="", tool_calls=[])
    vr = verify_turn(result)
    assert vr.passed is False
    assert "empty_turn" in vr.rubric_misses
    assert vr.should_retry is True


def test_should_retry_false_for_hard_fail_only() -> None:
    """``model_action_required`` alone is a hard fail — operator must
    intervene (cost cap / billing). Retry would waste tokens."""
    result = _make_result(
        text="Cost cap hit",
        tool_calls=[],
        termination_reason="model_action_required",
    )
    vr = verify_turn(result)
    assert "model_action_required" in vr.rubric_misses
    # Hard fail only — no retryable miss accompanies it.
    if vr.rubric_misses == ("model_action_required",):
        assert vr.should_retry is False


def test_should_retry_false_when_hard_fail_co_occurs() -> None:
    """Codex MCP HIGH #1 (PR-CL-A1 update, 2026-05-23) — hard fail
    (``model_action_required``) ALWAYS wins, even when a retryable miss
    (e.g. ``tool_error``) co-occurs. Pre-A1 the ``any(...)`` check let
    the recoverable miss flip should_retry True alongside a hard fail,
    looping the agent on a billing/cost-cap event."""
    result = _make_result(
        text="",
        tool_calls=[{"name": "search", "error": True}],
        termination_reason="model_action_required",
    )
    vr = verify_turn(result)
    assert "tool_error" in vr.rubric_misses
    assert "model_action_required" in vr.rubric_misses
    assert vr.should_retry is False  # hard fail wins
    payload = vr.to_payload()
    assert payload["should_retry"] is False


def test_should_retry_true_for_pure_recoverable_miss() -> None:
    """Without ``model_action_required``, a retryable miss flips
    should_retry True (the normal recoverable-error path)."""
    result = _make_result(
        text="I tried",
        tool_calls=[{"name": "search", "error": True}],
    )
    vr = verify_turn(result)
    assert "tool_error" in vr.rubric_misses
    assert "model_action_required" not in vr.rubric_misses
    assert vr.should_retry is True


def test_payload_includes_should_retry() -> None:
    """Hook consumers read ``should_retry`` from the payload directly."""
    vr = verify_turn(_make_result(text=""))
    payload = vr.to_payload()
    assert "should_retry" in payload
    assert payload["should_retry"] is True


# -- DB persistence (sessions table verify_* columns) ------------------


def test_db_persistence_verify_state_round_trip(tmp_path) -> None:
    """Codex MCP / user directive (2026-05-23): verify telemetry must
    survive a SessionManager close+reopen cycle. Round-trip the verify
    state through ``upsert_verify_state`` / ``get_verify_state``."""
    from core.memory.session_manager import SessionManager, SessionMeta

    db_path = tmp_path / "round_trip.db"
    mgr = SessionManager(db_path=db_path)
    mgr.upsert(
        SessionMeta(
            session_id="t-persist-vr",
            created_at=1.0,
            updated_at=1.0,
            status="active",
            model="claude-opus-4-7",
        )
    )
    mgr.upsert_verify_state(
        "t-persist-vr",
        verify_pass_count=2,
        verify_fail_count=1,
        last_verify_passed=False,
        last_verify_mode="rule_based",
        last_verify_effective_mode="rule_based",
        last_verify_rubric_misses=("empty_turn", "tool_error"),
        last_verify_should_retry=True,
    )
    # Reopen — cross-process semantics simulated by a fresh manager.
    mgr2 = SessionManager(db_path=db_path)
    state = mgr2.get_verify_state("t-persist-vr")
    assert state is not None
    assert state["verify_pass_count"] == 2
    assert state["verify_fail_count"] == 1
    assert state["last_verify_passed"] is False
    assert state["last_verify_mode"] == "rule_based"
    assert state["last_verify_effective_mode"] == "rule_based"
    assert state["last_verify_rubric_misses"] == ["empty_turn", "tool_error"]
    assert state["last_verify_should_retry"] is True


def test_db_persistence_no_session_row_returns_false(tmp_path) -> None:
    """``upsert_verify_state`` returns False when the session row hasn't
    been ``upsert``-ed — silent no-op so verify telemetry never breaks
    the run it observes."""
    from core.memory.session_manager import SessionManager

    mgr = SessionManager(db_path=tmp_path / "ghost.db")
    updated = mgr.upsert_verify_state(
        "ghost-session",
        verify_pass_count=0,
        verify_fail_count=1,
        last_verify_passed=False,
        last_verify_mode="rule_based",
        last_verify_effective_mode="rule_based",
        last_verify_rubric_misses=("empty_turn",),
        last_verify_should_retry=True,
    )
    assert updated is False
    assert mgr.get_verify_state("ghost-session") is None


def test_db_persistence_legacy_migration_adds_verify_cols(tmp_path) -> None:
    """Pre-PR-CL-A3 DB lacking verify columns gets them via ALTER TABLE
    when SessionManager opens it. Idempotent on re-open."""
    import sqlite3

    db_path = tmp_path / "legacy_a3.db"
    # Build a legacy schema with only the handoff cols (post-BUDGET) but
    # no verify cols.
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            model TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'anthropic',
            user_input TEXT NOT NULL DEFAULT '',
            round_count INTEGER NOT NULL DEFAULT 0,
            message_count INTEGER NOT NULL DEFAULT 0,
            handoff_state TEXT NOT NULL DEFAULT '',
            handoff_platform TEXT NOT NULL DEFAULT '',
            handoff_error TEXT NOT NULL DEFAULT '',
            handoff_triggered_at REAL NOT NULL DEFAULT 0.0
        );
        INSERT INTO sessions (session_id, created_at, updated_at)
        VALUES ('legacy-a3', 1.0, 1.0);
        """
    )
    conn.commit()
    conn.close()

    from core.memory.session_manager import SessionManager

    mgr = SessionManager(db_path=db_path)
    cols = {r[1] for r in mgr._conn.execute("PRAGMA table_info(sessions)").fetchall()}
    for new_col in (
        "verify_pass_count",
        "verify_fail_count",
        "last_verify_passed",
        "last_verify_mode",
        "last_verify_effective_mode",
        "last_verify_rubric_misses",
        "last_verify_should_retry",
    ):
        assert new_col in cols, f"migration missed {new_col}"
    state = mgr.get_verify_state("legacy-a3")
    assert state is not None
    assert state["verify_pass_count"] == 0  # defaults
    assert state["last_verify_passed"] is True  # default 1


def test_lifecycle_persists_to_db(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: ``_run_turn_verify`` calls ``_persist_verify_state``
    which writes to the SessionManager's sessions row. Verify the row
    reflects the verify outcome after one turn."""
    from types import SimpleNamespace

    from core.agent.loop._lifecycle import _run_turn_verify
    from core.memory.session_manager import SessionManager, SessionMeta

    # Redirect the default sessions DB into tmp_path so we don't touch
    # the user's real ~/.geode/projects/.../sessions.db.
    monkeypatch.setattr(
        "core.memory.session_manager._get_default_db_path",
        lambda: tmp_path / "lifecycle.db",
    )
    mgr = SessionManager()
    mgr.upsert(
        SessionMeta(
            session_id="t-lc-persist",
            created_at=1.0,
            updated_at=1.0,
            status="active",
        )
    )
    loop = SimpleNamespace(_hooks=None, _session_id="t-lc-persist")
    result = _make_result(text="", tool_calls=[])  # rule-based: empty_turn fail
    with session_metrics_scope(session_id="t-lc-persist"):
        payload = _run_turn_verify(loop, result)
        assert payload is not None
        assert payload["passed"] is False
        assert payload["should_retry"] is True
        # Enriched payload (LOW #8).
        assert payload["session_id"] == "t-lc-persist"
        assert "rounds" in payload
        assert "termination_reason" in payload
        assert "tool_call_count" in payload
    state = SessionManager().get_verify_state("t-lc-persist")
    assert state is not None
    assert state["verify_fail_count"] == 1
    assert state["last_verify_passed"] is False
    assert state["last_verify_should_retry"] is True
    assert state["last_verify_rubric_misses"] == ["empty_turn"]


def test_handoff_db_wiring(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-CL-BUDGET wiring fix (2026-05-23) — when the loop's
    ``_persist_handoff_request`` fires, the sessions row's
    ``handoff_state`` transitions empty → ``pending`` via the DB CAS."""
    from types import SimpleNamespace

    from core.agent.handoff import HandoffState, get_handoff
    from core.agent.loop.agent_loop import AgenticLoop
    from core.memory.session_manager import SessionManager, SessionMeta

    monkeypatch.setattr(
        "core.memory.session_manager._get_default_db_path",
        lambda: tmp_path / "handoff_wiring.db",
    )
    mgr = SessionManager()
    mgr.upsert(
        SessionMeta(
            session_id="t-handoff-wire",
            created_at=1.0,
            updated_at=1.0,
            status="active",
        )
    )

    # Bind ``_persist_handoff_request`` to a stub with the session_id field.
    stub = SimpleNamespace(_session_id="t-handoff-wire")
    bound = AgenticLoop._persist_handoff_request.__get__(stub, SimpleNamespace)
    bound()
    snap = get_handoff(SessionManager()._conn, session_id="t-handoff-wire")
    assert snap is not None
    assert snap.state is HandoffState.PENDING
    assert snap.platform == "agentic_loop"
