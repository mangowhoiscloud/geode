"""Unit tests for :mod:`core.agent.verify` — per-turn verify (Reflexion).

Coverage:
- ``VerifyMode`` StrEnum values
- ``VerifyResult`` dataclass shape (frozen, slots, to_payload)
- ``get_verify_mode`` env knob parsing (default + override + invalid fallback)
- ``_verify_rule_based`` catches: empty_turn, short_output, tool_error,
  model_action_required
- ``synthesize_reflexion_hint`` renders the verbal-RL block + empty on no misses
- ``verify_turn`` dispatcher: OFF / RULE_BASED / LLM_JUDGE (stub-falls-back)
- SessionMetrics integration: ``record_verify`` + ``last_verify_reflexion_hint``
- AgenticLoop hint consumption: ``_consume_reflexion_hint`` reads+clears
"""

from __future__ import annotations

import os

import pytest
from core.agent.loop.models import AgenticResult
from core.agent.verify import (
    DEFAULT_MIN_TEXT_CHARS,
    VerifyMode,
    VerifyResult,
    get_verify_mode,
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
        reflexion_hint="<reflexion>...</reflexion>",
        ts=123.4,
    )
    payload = vr.to_payload()
    assert payload["passed"] is False
    assert payload["mode"] == "rule_based"
    assert payload["rubric_misses"] == ["empty_turn"]
    assert payload["reflexion_hint"].startswith("<reflexion>")
    assert payload["score"] == 0.0


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
    assert vr.reflexion_hint.startswith("<reflexion>")


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


# -- Reflexion hint -----------------------------------------------------


def test_synthesize_hint_empty_on_no_misses() -> None:
    assert synthesize_reflexion_hint(()) == ""


def test_synthesize_hint_includes_reason_codes() -> None:
    """Each rubric_miss code surfaces in the hint body."""
    hint = synthesize_reflexion_hint(("empty_turn", "tool_error"))
    assert hint.startswith("<reflexion>")
    assert hint.endswith("</reflexion>")
    assert "empty_turn" in hint
    assert "tool_error" in hint


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
        assert m.last_verify_reflexion_hint == ""


def test_record_verify_fail() -> None:
    with session_metrics_scope(session_id="t-vf"):
        m = current_session_metrics()
        m.record_verify(
            passed=False,
            mode="rule_based",
            rubric_misses=("empty_turn",),
            reflexion_hint="<reflexion>x</reflexion>",
        )
        assert m.verify_fail_count == 1
        assert m.last_verify_passed is False
        assert m.last_verify_rubric_misses == ("empty_turn",)
        assert m.last_verify_reflexion_hint == "<reflexion>x</reflexion>"


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


# -- AgenticLoop reflexion-hint consume --------------------------------


def test_consume_reflexion_hint_clears_after_read() -> None:
    """``_consume_reflexion_hint`` returns the hint then leaves an empty slot
    so the same hint can't be injected into two consecutive arun's."""
    from core.agent.loop.agent_loop import AgenticLoop

    with session_metrics_scope(session_id="t-consume"):
        current_session_metrics().last_verify_reflexion_hint = "<reflexion>z</reflexion>"
        consume = AgenticLoop._consume_reflexion_hint.__get__(
            object(), object
        )  # bind to a bare stub
        assert consume() == "<reflexion>z</reflexion>"
        # Second call yields empty.
        assert consume() == ""
        # Stored value also cleared.
        assert current_session_metrics().last_verify_reflexion_hint == ""


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
    # Reflexion hint surfaces both codes.
    assert "tool_error" in multi_vr.reflexion_hint
    assert "model_action_required" in multi_vr.reflexion_hint


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
        assert m.last_verify_reflexion_hint.startswith("<reflexion>")


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
