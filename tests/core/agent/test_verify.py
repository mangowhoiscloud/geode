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

import asyncio
import inspect
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from core.agent.loop import _guards
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
from core.hooks import (
    HookAction,
    HookDecision,
    HookInvocation,
    HookName,
    HookRegistry,
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
    with session_metrics_scope(session_id="t-consume"):
        current_session_metrics().last_verify_reflection_hint = "<reflection>z</reflection>"
        assert _guards._consume_reflection_hint(object()) == "<reflection>z</reflection>"
        # Second call yields empty.
        assert _guards._consume_reflection_hint(object()) == ""
        # Stored value also cleared.
        assert current_session_metrics().last_verify_reflection_hint == ""


def test_consume_reflexion_hint_legacy_alias() -> None:
    """The old AgenticLoop method name remains as an alias."""
    with session_metrics_scope(session_id="t-consume-legacy"):
        current_session_metrics().last_verify_reflection_hint = "<reflection>z</reflection>"
        assert _guards._consume_reflexion_hint(object()) == "<reflection>z</reflection>"


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


def test_lifecycle_finalize_records_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production finalization path records the built-in verdict."""
    from core.agent.loop import _lifecycle

    result = _make_result(text="", tool_calls=[])  # rule-based: empty_turn
    loop = SimpleNamespace(
        _hook_registry=HookRegistry(),
        _session_id="",
        _turn_id="t-1",
        _verify_root_turn_id="t-1",
        _verify_attempt=0,
        _verify_continuation_budget=2,
        _session_generation=1,
        _evidence_ledger=None,
    )
    with session_metrics_scope(session_id="t-finalize"):
        payload, follow_up, escalated, _correlation = asyncio.run(
            _lifecycle._run_public_finalization_async(loop, result)
        )
        assert payload is not None
        assert payload["passed"] is False
        assert "empty_turn" in payload["rubric_misses"]
        assert "empty_turn" in follow_up
        assert escalated is False
        m = current_session_metrics()
        assert m.verify_fail_count == 1
        assert m.last_verify_reflection_hint.startswith("<reflection>")


def test_lifecycle_off_mode_skips_verify_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """OFF mode omits the internal verify payload and metrics row."""
    from core.agent.loop import _lifecycle

    monkeypatch.setenv("GEODE_VERIFY_MODE", "off")
    loop = SimpleNamespace(
        _hook_registry=HookRegistry(),
        _session_id="",
        _turn_id="t-1",
        _verify_root_turn_id="t-1",
        _verify_attempt=0,
        _verify_continuation_budget=2,
        _session_generation=1,
        _evidence_ledger=None,
    )
    with session_metrics_scope(session_id="t-off"):
        result = _make_result(text="", tool_calls=[])
        payload, _follow_up, _escalated, _correlation = asyncio.run(
            _lifecycle._run_public_finalization_async(loop, result)
        )
        assert payload is None
        assert current_session_metrics().verify_fail_count == 0


def test_finalizers_run_verify_before_lifecycle_hooks() -> None:
    """Reflection verification runs at the task-completion boundary before terminal
    lifecycle hooks are emitted."""
    from core.agent.loop import _lifecycle

    async_src = inspect.getsource(_lifecycle.finalize_and_return_async)

    assert async_src.index("await _run_public_finalization_async(") < async_src.index(
        "_persist_final_result("
    )
    assert async_src.index("_persist_final_result(") < async_src.index("RuntimeEvent.SESSION_ENDED")


def test_post_verify_failure_cannot_be_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop import _lifecycle

    registry = HookRegistry()
    registry.register(
        HookName.POST_VERIFY,
        lambda _invocation: HookDecision(action=HookAction.ACCEPT),
    )
    loop = SimpleNamespace(
        _hook_registry=registry,
        _session_id="",
        _turn_id="t-1",
        _verify_root_turn_id="t-1",
        _verify_attempt=0,
        _verify_continuation_budget=2,
        _session_generation=1,
        _evidence_ledger=None,
    )

    async def failed_verify(*args: object, **kwargs: object) -> VerifyResult:
        return VerifyResult(
            passed=False,
            mode=VerifyMode.RULE_BASED,
            rubric_misses=("tool_error",),
            should_retry=True,
        )

    monkeypatch.setattr("core.agent.verify.verify_turn_async", failed_verify)
    with session_metrics_scope(session_id="post-fail"):
        _payload, follow_up, escalated, _correlation = asyncio.run(
            _lifecycle._run_public_finalization_async(
                loop,
                _make_result(text="candidate"),
            )
        )

    assert escalated is True
    assert follow_up == ""


def test_empty_post_verify_policy_escalates_non_retryable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop import _lifecycle

    loop = SimpleNamespace(
        _hook_registry=HookRegistry(),
        _session_id="",
        _turn_id="t-1",
        _verify_root_turn_id="t-1",
        _verify_attempt=0,
        _verify_continuation_budget=2,
        _session_generation=1,
        _evidence_ledger=None,
    )

    async def hard_failure(*args: object, **kwargs: object) -> VerifyResult:
        return VerifyResult(
            passed=False,
            mode=VerifyMode.RULE_BASED,
            rubric_misses=("operator_action_required",),
            should_retry=False,
        )

    monkeypatch.setattr("core.agent.verify.verify_turn_async", hard_failure)
    with session_metrics_scope(session_id="post-hard-fail"):
        _payload, follow_up, escalated, _correlation = asyncio.run(
            _lifecycle._run_public_finalization_async(
                loop,
                _make_result(text="candidate"),
            )
        )

    assert follow_up == ""
    assert escalated is True


def test_post_verify_escalation_withholds_candidate_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop import _lifecycle
    from core.agent.loop.models import TerminationReason, TurnState
    from core.hooks import HookCorrelation

    checkpoint = SimpleNamespace(status="active")
    checkpoint.mark_paused = lambda _session_id: setattr(checkpoint, "status", "paused")
    checkpoint.current_status = lambda _session_id: checkpoint.status
    turn = TurnState(turn_id="t-1", termination_reason=TerminationReason.NATURAL)
    loop = SimpleNamespace(
        _verify_attempt_results=[],
        _checkpoint=checkpoint,
        _session_id="s-escalated",
        _turn_state=turn,
        _set_turn_termination=lambda reason: setattr(turn, "termination_reason", reason),
    )
    correlation = HookCorrelation(session_id="s-escalated", turn_id="t-1")

    monkeypatch.setattr(_lifecycle, "_prepare_final_result", lambda *_args, **_kwargs: None)

    async def escalate(*_args: object, **_kwargs: object):
        return None, "", True, correlation

    async def emit(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(_lifecycle, "_run_public_finalization_async", escalate)
    monkeypatch.setattr(_lifecycle, "_emit_verify_runtime_event", emit)
    monkeypatch.setattr(
        _lifecycle,
        "_persist_final_result",
        lambda *_args, **_kwargs: pytest.fail("escalated candidate was persisted"),
    )
    result = _make_result(text="withheld candidate")

    finalized = asyncio.run(_lifecycle.finalize_and_return_async(loop, result, "request", 0))

    assert finalized.text == ""
    assert finalized.pending_text == "withheld candidate"
    assert finalized.error == "external_verification_required"
    assert finalized.termination_reason is TerminationReason.EXTERNAL_VERIFICATION_REQUIRED
    assert turn.termination_reason is TerminationReason.EXTERNAL_VERIFICATION_REQUIRED
    assert checkpoint.status == "paused"


def test_post_verify_revision_returns_bounded_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop import _lifecycle

    registry = HookRegistry()
    registry.register(
        HookName.POST_VERIFY,
        lambda _invocation: HookDecision(
            action=HookAction.REVISE,
            instruction="Run the missing validation, then answer again.",
        ),
        name="reviewer",
    )
    recorded_decisions: list[dict[str, object]] = []
    loop = SimpleNamespace(
        _hook_registry=registry,
        _session_id="",
        _turn_id="t-1",
        _verify_root_turn_id="t-1",
        _verify_attempt=0,
        _verify_continuation_budget=2,
        _session_generation=1,
        _evidence_ledger=None,
        _timeline=SimpleNamespace(
            record_verification_decision=lambda **kwargs: recorded_decisions.append(kwargs)
        ),
    )

    async def passed_verify(*args: object, **kwargs: object) -> VerifyResult:
        return VerifyResult(passed=True, mode=VerifyMode.RULE_BASED)

    monkeypatch.setattr("core.agent.verify.verify_turn_async", passed_verify)
    with session_metrics_scope(session_id="post-revise"):
        _payload, follow_up, escalated, correlation = asyncio.run(
            _lifecycle._run_public_finalization_async(
                loop,
                _make_result(text="candidate"),
            )
        )

    assert escalated is False
    assert follow_up == "Run the missing validation, then answer again."
    assert correlation.turn_id == "t-1"
    assert correlation.verify_attempt == 0
    assert recorded_decisions[0]["policy_action"] == "revise"
    decisions = recorded_decisions[0]["decisions"]
    assert isinstance(decisions, list)
    assert decisions[0]["handler"] == "reviewer"


def test_verify_continuation_does_not_emit_or_persist_session_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop import _lifecycle
    from core.hooks import RuntimeEvent

    emitted: list[RuntimeEvent] = []

    class Hooks:
        async def emit_async(self, event: RuntimeEvent, _payload: object) -> None:
            emitted.append(event)

    recorded: list[str] = []
    timeline = SimpleNamespace(
        record_assistant_message=lambda text: recorded.append(text),
        record_session_end=lambda **_kwargs: pytest.fail("continuation ended the session"),
    )
    loop = SimpleNamespace(
        _timeline=timeline,
        _save_checkpoint=lambda *_args, **_kwargs: None,
        _hooks=Hooks(),
    )
    monkeypatch.setattr(
        _lifecycle,
        "_final_hook_payloads",
        lambda *_args, **_kwargs: ({"terminal": True}, {"turn": True}, {"reasoning": True}),
    )

    asyncio.run(
        _lifecycle._close_verify_attempt(
            loop,
            _make_result(text="candidate"),
            "request",
            1,
            {"passed": True},
        )
    )

    assert recorded == ["candidate"]
    assert RuntimeEvent.SESSION_ENDED not in emitted
    assert emitted == [RuntimeEvent.TURN_COMPLETED, RuntimeEvent.REASONING_METRICS]


def test_verify_continuation_stays_out_of_user_history_and_checkpoint() -> None:
    context = SimpleNamespace(
        add_system_event=lambda *_args: pytest.fail("policy entered user history")
    )
    recorded: list[str] = []
    checkpoint_inputs: list[str] = []

    async def admit_session_budget(_user_input: str) -> None:
        return None

    loop = SimpleNamespace(
        context=context,
        _timeline=SimpleNamespace(
            record_verification_continuation=lambda instruction, **_kwargs: recorded.append(
                instruction
            )
        ),
        _verify_root_turn_id="root-turn",
        _verify_root_user_input="original task",
        _verify_attempt=1,
        _save_checkpoint=lambda user_input, **_kwargs: checkpoint_inputs.append(user_input),
        _admit_session_budget=admit_session_budget,
    )

    with patch.object(_guards, "_admit_session_budget", new=AsyncMock(return_value=None)):
        result = asyncio.run(
            _guards._open_turn(
                loop,
                "repair instruction",
                verification_continuation=True,
            )
        )

    assert result is None
    assert recorded == ["repair instruction"]
    assert checkpoint_inputs == ["original task"]


def test_post_verify_timeout_preserves_the_builtin_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop import _lifecycle

    registry = HookRegistry()

    async def slow_policy(_invocation: HookInvocation) -> HookDecision:
        await asyncio.sleep(0.05)
        return HookDecision(action=HookAction.REVISE, instruction="too late")

    registry.register(
        HookName.POST_VERIFY,
        slow_policy,
        name="slow_policy",
        timeout_s=0.001,
    )
    loop = SimpleNamespace(
        _hook_registry=registry,
        _session_id="",
        _turn_id="t-1",
        _verify_root_turn_id="t-1",
        _verify_attempt=0,
        _verify_continuation_budget=2,
        _session_generation=1,
        _evidence_ledger=None,
    )

    async def passed_verify(*args: object, **kwargs: object) -> VerifyResult:
        return VerifyResult(passed=True, mode=VerifyMode.RULE_BASED)

    monkeypatch.setattr("core.agent.verify.verify_turn_async", passed_verify)
    with session_metrics_scope(session_id="post-timeout"):
        payload, follow_up, escalated, _correlation = asyncio.run(
            _lifecycle._run_public_finalization_async(
                loop,
                _make_result(text="candidate"),
            )
        )

    assert payload is not None
    assert payload["passed"] is True
    assert follow_up == ""
    assert escalated is False


def test_pre_verify_strengthening_is_monotone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.loop import _lifecycle

    observed_passed: list[bool] = []
    registry = HookRegistry()
    registry.register(
        HookName.PRE_VERIFY,
        lambda _invocation: HookDecision(
            action=HookAction.STRENGTHEN,
            instruction="Require a CI result.",
            additional_misses=("ci_missing",),
        ),
    )

    def observe_post(invocation: HookInvocation) -> HookDecision:
        observed_passed.append(bool(invocation.payload["passed"]))
        return HookDecision(action=HookAction.ESCALATE)

    registry.register(HookName.POST_VERIFY, observe_post)
    loop = SimpleNamespace(
        _hook_registry=registry,
        _session_id="",
        _turn_id="t-1",
        _verify_root_turn_id="t-1",
        _verify_attempt=0,
        _verify_continuation_budget=2,
        _session_generation=1,
        _evidence_ledger=None,
    )

    async def passed_verify(*args: object, **kwargs: object) -> VerifyResult:
        return VerifyResult(passed=True, mode=VerifyMode.RULE_BASED)

    monkeypatch.setattr("core.agent.verify.verify_turn_async", passed_verify)
    with session_metrics_scope(session_id="pre-strengthen"):
        payload, _follow_up, _escalated, _correlation = asyncio.run(
            _lifecycle._run_public_finalization_async(
                loop,
                _make_result(text="candidate"),
            )
        )

    assert payload is not None
    assert payload["passed"] is False
    assert payload["rubric_misses"] == ["ci_missing"]
    assert observed_passed == [False]


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


def test_verify_continuation_results_merge_before_final_persistence() -> None:
    from core.agent.loop import _lifecycle
    from core.llm.token_tracker import LLMUsage

    first = _make_result(
        text="first",
        tool_calls=[{"name": "search"}],
    )
    first.rounds = 2
    first.usage = LLMUsage(model="model", input_tokens=10, output_tokens=3, cost_usd=0.1)
    final = _make_result(
        text="final",
        tool_calls=[{"name": "verify"}],
    )
    final.rounds = 1
    final.usage = LLMUsage(model="model", input_tokens=5, output_tokens=2, cost_usd=0.2)
    loop = SimpleNamespace(
        _verify_attempt_results=[first],
        _total_empty_rounds=0,
        _consecutive_text_only_rounds=0,
    )

    _lifecycle._merge_verify_attempts(loop, final)

    assert final.rounds == 3
    assert [call["name"] for call in final.tool_calls] == ["search", "verify"]
    assert final.usage is not None
    assert final.usage.input_tokens == 15
    assert final.usage.output_tokens == 5
    assert final.usage.cost_usd == pytest.approx(0.3)
    assert final.reasoning_metrics["total_rounds"] == 3
    assert final.reasoning_metrics["tool_calls_total"] == 2
    assert loop._verify_attempt_results == []


def test_final_result_detaches_from_the_reusable_tool_log() -> None:
    from core.agent.loop import _lifecycle

    shared_log = [{"name": "search"}]
    result = _make_result(text="done")
    result.rounds = 1
    result.tool_calls = shared_log
    loop = SimpleNamespace(
        max_rounds=0,
        model="model",
        _usage_snapshot=None,
        _total_empty_rounds=0,
        _consecutive_text_only_rounds=0,
    )

    _lifecycle._prepare_final_result(loop, result, "work", 1, persist=False)
    shared_log.clear()

    assert result.tool_calls == [{"name": "search"}]


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


# -- Legacy DB compatibility ------------------------------------------


def test_session_manager_tolerates_legacy_verify_columns(tmp_path) -> None:
    """Legacy verify columns remain inert and load-compatible."""
    import sqlite3

    db_path = tmp_path / "legacy_a3.db"
    from core.memory.session_manager import SessionManager, SessionMeta

    mgr = SessionManager(db_path=db_path)
    verify_columns = (
        "verify_pass_count",
        "verify_fail_count",
        "last_verify_passed",
        "last_verify_mode",
        "last_verify_effective_mode",
        "last_verify_rubric_misses",
        "last_verify_should_retry",
    )
    fresh_columns = {row[1] for row in mgr._conn.execute("PRAGMA table_info(sessions)")}
    assert fresh_columns.isdisjoint(verify_columns)
    mgr.close()

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        ALTER TABLE sessions ADD COLUMN verify_pass_count INTEGER;
        ALTER TABLE sessions ADD COLUMN verify_fail_count INTEGER;
        ALTER TABLE sessions ADD COLUMN last_verify_passed INTEGER;
        ALTER TABLE sessions ADD COLUMN last_verify_mode TEXT;
        ALTER TABLE sessions ADD COLUMN last_verify_effective_mode TEXT;
        ALTER TABLE sessions ADD COLUMN last_verify_rubric_misses TEXT;
        ALTER TABLE sessions ADD COLUMN last_verify_should_retry INTEGER;
        """
    )
    conn.commit()
    conn.close()

    legacy = SessionManager(db_path=db_path)
    legacy.upsert(
        SessionMeta(
            session_id="legacy-a3",
            created_at=1.0,
            updated_at=1.0,
            status="active",
        )
    )
    assert legacy.get("legacy-a3") is not None
    legacy_columns = {row[1] for row in legacy._conn.execute("PRAGMA table_info(sessions)")}
    assert set(verify_columns) <= legacy_columns
    legacy.close()


def test_handoff_db_wiring(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-CL-BUDGET wiring fix (2026-05-23) — when the loop's
    ``_persist_handoff_request`` fires, the sessions row's
    ``handoff_state`` transitions empty → ``pending`` via the DB CAS."""
    from types import SimpleNamespace

    from core.agent.handoff import HandoffState, get_handoff
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
    _guards._persist_handoff_request(stub)
    snap = get_handoff(SessionManager()._conn, session_id="t-handoff-wire")
    assert snap is not None
    assert snap.state is HandoffState.PENDING
    assert snap.platform == "agentic_loop"
