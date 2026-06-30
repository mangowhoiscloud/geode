"""Unit tests for PR-CL-A1 — Dynamic Replan.

Coverage:
- :class:`Plan` + :class:`PlanStep` dataclass shape (frozen, slots,
  to_dict / to_json / current_step / advance / done).
- :func:`build_plan_from_decomposition` survives mocked / partial inputs.
- :func:`render_plan_for_prompt` emits a ``<plan>...</plan>`` block with
  current-step marker; empty plan → empty string.
- :func:`should_replan` env-knob policy: verify FAIL wins; cadence
  fires every N rounds; ``GEODE_REPLAN_ENABLED=false`` disables.
- :func:`parse_replan_response` handles code fences + bad JSON.
- :func:`replan_async` calls ``loop._call_llm`` with the active loop model,
  parses the response, records token usage via ``_track_usage_async``,
  returns None on timeout / bad JSON.
- SessionMetrics integration: ``set_active_plan`` / ``record_replan`` /
  ``record_step_attempt`` + ``to_session_row`` exposes telemetry.
- ``_verify_rule_based`` ``step_expected_mismatch`` rubric: fires only
  when active plan + current step has expected_outcome + text doesn't
  contain any expected token.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.loop.models import AgenticResult
from core.agent.plan import (
    DEFAULT_REPLAN_INTERVAL,
    Plan,
    PlanStep,
    build_plan_from_decomposition,
    parse_replan_response,
    render_plan_for_prompt,
    replan_async,
    should_replan,
)
from core.agent.verify import verify_turn
from core.observability.session_metrics import (
    current_session_metrics,
    session_metrics_scope,
)


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_REPLAN_ENABLED", raising=False)
    monkeypatch.delenv("GEODE_REPLAN_INTERVAL", raising=False)
    monkeypatch.delenv("GEODE_REPLAN_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("GEODE_VERIFY_MODE", raising=False)


def _make_result(
    *,
    text: str = "OK",
    tool_calls: list[dict] | None = None,
    termination_reason: str = "natural",
) -> AgenticResult:
    return AgenticResult(
        text=text,
        tool_calls=tool_calls or [],
        rounds=1,
        termination_reason=termination_reason,
    )


def _make_plan(*step_ids: str, current: int = 0) -> Plan:
    steps = tuple(
        PlanStep(id=sid, description=f"do {sid}", expected_outcome=f"finished {sid}")
        for sid in step_ids
    )
    return Plan(steps=steps, current=current)


# -- Plan / PlanStep shape --------------------------------------------


def test_plan_step_is_frozen() -> None:
    step = PlanStep(id="s1", description="x")
    with pytest.raises((AttributeError, TypeError)):
        step.id = "s2"  # type: ignore[misc]


def test_plan_is_frozen() -> None:
    plan = _make_plan("s1", "s2")
    with pytest.raises((AttributeError, TypeError)):
        plan.current = 1  # type: ignore[misc]


def test_plan_to_dict_round_trip() -> None:
    plan = Plan(
        steps=(
            PlanStep(id="s1", description="alpha", expected_outcome="α"),
            PlanStep(id="s2", description="beta", tool_name="search"),
        ),
        current=1,
        completed=(0,),
        reasoning="r",
        revision=2,
    )
    d = plan.to_dict()
    assert d["current"] == 1
    assert d["completed"] == [0]
    assert d["reasoning"] == "r"
    assert d["revision"] == 2
    assert d["steps"][0]["expected_outcome"] == "α"
    assert d["steps"][1]["tool_name"] == "search"


def test_plan_current_step() -> None:
    plan = _make_plan("s1", "s2", "s3", current=1)
    cur = plan.current_step()
    assert cur is not None
    assert cur.id == "s2"
    # Exhausted plan returns None.
    done = Plan(steps=plan.steps, current=3)
    assert done.current_step() is None
    assert done.done is True


def test_plan_advance_completed_marks_step() -> None:
    plan = _make_plan("s1", "s2", "s3")
    advanced = plan.advance(completed=True)
    assert advanced.current == 1
    assert advanced.completed == (0,)
    assert advanced.abandoned == ()


def test_plan_advance_abandoned_marks_step() -> None:
    plan = _make_plan("s1", "s2", "s3")
    advanced = plan.advance(completed=False)
    assert advanced.current == 1
    assert advanced.abandoned == (0,)
    assert advanced.completed == ()


def test_plan_advance_when_done_is_noop() -> None:
    plan = Plan(steps=(PlanStep(id="s1", description="x"),), current=1)
    assert plan.advance(completed=True) is plan


def test_remaining_steps() -> None:
    plan = _make_plan("s1", "s2", "s3", current=1)
    remaining = plan.remaining_steps()
    assert len(remaining) == 2
    assert remaining[0].id == "s2"


# -- build_plan_from_decomposition ------------------------------------


def test_build_plan_handles_none() -> None:
    assert build_plan_from_decomposition(None) is None


def test_build_plan_handles_empty_goals() -> None:
    decomp = SimpleNamespace(goals=[], reasoning="r")
    assert build_plan_from_decomposition(decomp) is None


def test_build_plan_extracts_goals() -> None:
    g1 = SimpleNamespace(
        id="g1",
        description="first",
        tool_name="search",
        tool_args={"q": "x"},
        depends_on=[],
        expected_outcome="found",
    )
    g2 = SimpleNamespace(
        id="g2",
        description="second",
        tool_name="fetch",
        tool_args={},
        depends_on=["g1"],
        expected_outcome="",
    )
    decomp = SimpleNamespace(goals=[g1, g2], reasoning="my plan")
    plan = build_plan_from_decomposition(decomp)
    assert plan is not None
    assert len(plan.steps) == 2
    assert plan.steps[0].id == "g1"
    assert plan.steps[0].expected_outcome == "found"
    assert plan.steps[1].depends_on == ("g1",)
    assert plan.reasoning == "my plan"


# -- render_plan_for_prompt -------------------------------------------


def test_render_empty_plan_returns_empty() -> None:
    assert render_plan_for_prompt(Plan(steps=())) == ""


def test_render_plan_includes_current_step_marker() -> None:
    plan = _make_plan("s1", "s2", "s3", current=1)
    rendered = render_plan_for_prompt(plan)
    assert rendered.startswith("<plan>")
    assert rendered.endswith("</plan>")
    assert "step 2/3" in rendered
    assert "s2: do s2" in rendered
    # Current step marker.
    assert "→ s2" in rendered


def test_render_plan_includes_expected_outcome() -> None:
    plan = Plan(steps=(PlanStep(id="s1", description="alpha", expected_outcome="α finished"),))
    rendered = render_plan_for_prompt(plan)
    assert "Expected outcome: α finished" in rendered


def test_render_plan_omits_section_on_done() -> None:
    plan = Plan(steps=(PlanStep(id="s1", description="x"),), current=1)
    assert render_plan_for_prompt(plan) == ""


# -- should_replan (trigger policy) -----------------------------------


def test_should_replan_off_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_REPLAN_ENABLED", "false")
    assert (
        should_replan(round_idx=5, plan=None, verify_failed=True, verify_should_retry=True) is None
    )


def test_should_replan_verify_fail_priority() -> None:
    """Verify FAIL wins over cadence."""
    trigger = should_replan(
        round_idx=2,  # not cadence boundary
        plan=_make_plan("s1"),
        verify_failed=True,
        verify_should_retry=True,
    )
    assert trigger == "verify_fail"


def test_should_replan_cadence_at_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_REPLAN_INTERVAL", "3")
    plan = _make_plan("s1")
    assert (
        should_replan(round_idx=3, plan=plan, verify_failed=False, verify_should_retry=False)
        == "cadence"
    )
    assert (
        should_replan(round_idx=6, plan=plan, verify_failed=False, verify_should_retry=False)
        == "cadence"
    )
    assert (
        should_replan(round_idx=4, plan=plan, verify_failed=False, verify_should_retry=False)
        is None
    )


def test_should_replan_no_op_round_zero() -> None:
    """Round 0 never triggers cadence (avoid replan-before-plan)."""
    assert (
        should_replan(
            round_idx=0,
            plan=_make_plan("s1"),
            verify_failed=False,
            verify_should_retry=False,
        )
        is None
    )


def test_should_replan_cadence_off_when_interval_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_REPLAN_INTERVAL", "0")
    assert (
        should_replan(
            round_idx=5,
            plan=_make_plan("s1"),
            verify_failed=False,
            verify_should_retry=False,
        )
        is None
    )


def test_should_replan_verify_fail_without_should_retry_is_skipped() -> None:
    """Hard fail (e.g. model_action_required) → no retry recommended →
    no replan even though verify_failed is True."""
    assert (
        should_replan(
            round_idx=2,
            plan=_make_plan("s1"),
            verify_failed=True,
            verify_should_retry=False,
        )
        is None
    )


def test_default_replan_interval_is_5() -> None:
    assert DEFAULT_REPLAN_INTERVAL == 5


# -- parse_replan_response --------------------------------------------


def test_parse_replan_clean_json() -> None:
    raw = (
        '{"steps": [{"id": "s1", "description": "first",'
        ' "expected_outcome": "done", "tool_name": "search"}],'
        ' "reasoning": "r"}'
    )
    parsed = parse_replan_response(raw)
    assert parsed is not None
    steps, reasoning = parsed
    assert len(steps) == 1
    assert steps[0].id == "s1"
    assert steps[0].expected_outcome == "done"
    assert reasoning == "r"


def test_parse_replan_code_fence_wrapped() -> None:
    raw = '```json\n{"steps": [{"id": "s1", "description": "x"}]}\n```'
    parsed = parse_replan_response(raw)
    assert parsed is not None
    assert len(parsed[0]) == 1


def test_parse_replan_bad_json_returns_none() -> None:
    assert parse_replan_response("not json") is None


def test_parse_replan_missing_steps_returns_none() -> None:
    assert parse_replan_response('{"reasoning": "no steps"}') is None


# -- replan_async (LLM call orchestration) ----------------------------


def test_replan_async_inherits_loop_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """``replan_async`` calls ``loop._call_llm`` with the active loop model."""
    fake_settings = SimpleNamespace(model="claude-haiku-4-5")
    monkeypatch.setattr("core.config.settings", fake_settings)
    captured: dict[str, str] = {}

    async def _fake_call_llm(
        _system: str, _msgs: list, *, model: str | None = None
    ) -> SimpleNamespace:
        captured["model"] = model or ""
        return SimpleNamespace(
            text='{"steps": [{"id": "s1", "description": "new step"}], "reasoning": "r"}',
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        )

    loop = SimpleNamespace(_call_llm=_fake_call_llm, model="claude-sonnet-4-6")
    plan = _make_plan("old1")
    new_plan = asyncio.run(
        replan_async(loop, plan=plan, turn_result=SimpleNamespace(text=""), trigger="verify_fail")
    )
    assert new_plan is not None
    assert new_plan.revision == 1  # prior revision was 0
    assert len(new_plan.steps) == 1
    assert new_plan.steps[0].id == "s1"
    assert captured["model"] == "claude-sonnet-4-6"


def test_replan_async_records_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """The response is fed to ``loop._track_usage_async`` so planner cost
    surfaces in the TokenTracker."""
    fake_settings = SimpleNamespace(model="m")
    monkeypatch.setattr("core.config.settings", fake_settings)
    recorded: list[Any] = []

    async def _fake_call_llm(
        _system: str, _msgs: list, *, model: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(text='{"steps": [{"id": "s1", "description": "x"}]}')

    async def _track(response: Any) -> None:
        recorded.append(response)

    loop = SimpleNamespace(_call_llm=_fake_call_llm, _track_usage_async=_track, model="m")
    asyncio.run(
        replan_async(loop, plan=None, turn_result=SimpleNamespace(text=""), trigger="cadence")
    )
    assert len(recorded) == 1


def test_replan_async_returns_none_on_bad_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unparseable JSON → None so caller keeps prior plan."""
    fake_settings = SimpleNamespace(model="m")
    monkeypatch.setattr("core.config.settings", fake_settings)

    async def _bad(_system: str, _msgs: list, *, model: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(text="not even close to JSON")

    loop = SimpleNamespace(_call_llm=_bad, model="m")
    result = asyncio.run(
        replan_async(loop, plan=None, turn_result=SimpleNamespace(text=""), trigger="cadence")
    )
    assert result is None


def test_replan_async_returns_none_on_exception() -> None:
    """LLM call raises → None, no leak."""

    async def _boom(_system: str, _msgs: list, *, model: str | None = None) -> SimpleNamespace:
        raise RuntimeError("network down")

    loop = SimpleNamespace(_call_llm=_boom, model="m")
    result = asyncio.run(
        replan_async(loop, plan=None, turn_result=SimpleNamespace(text=""), trigger="cadence")
    )
    assert result is None


# -- SessionMetrics integration ---------------------------------------


def test_session_metrics_set_active_plan() -> None:
    plan = _make_plan("s1", "s2")
    with session_metrics_scope(session_id="t-active"):
        m = current_session_metrics()
        m.set_active_plan(plan)
        assert m.active_plan is plan
        assert m.replan_attempts_on_current_step == 0


def test_session_metrics_record_replan() -> None:
    with session_metrics_scope(session_id="t-replan"):
        m = current_session_metrics()
        m.record_replan("verify_fail")
        assert m.replan_count == 1
        assert m.last_replan_trigger == "verify_fail"
        m.record_replan("cadence")
        assert m.replan_count == 2
        assert m.last_replan_trigger == "cadence"


def test_session_metrics_record_step_attempt() -> None:
    """Counter accumulates across replans on the same step (Codex MCP
    follow-up 2026-05-23). Only resets when caller explicitly passes
    ``reset_attempts=True`` to ``set_active_plan`` — typically the
    abandon path advancing to a new step."""
    with session_metrics_scope(session_id="t-attempt"):
        m = current_session_metrics()
        m.record_step_attempt()
        m.record_step_attempt()
        assert m.replan_attempts_on_current_step == 2
        # ``record_replan`` does NOT reset — counter survives.
        m.record_replan("cadence")
        assert m.replan_attempts_on_current_step == 2
        # ``set_active_plan`` with default ``reset_attempts=False`` does NOT reset.
        m.set_active_plan(_make_plan("new"))
        assert m.replan_attempts_on_current_step == 2
        # Explicit reset_attempts=True (abandon-advance path) resets.
        m.set_active_plan(_make_plan("after_advance"), reset_attempts=True)
        assert m.replan_attempts_on_current_step == 0


def test_session_row_exposes_plan_telemetry() -> None:
    plan = _make_plan("s1", "s2", "s3")
    with session_metrics_scope(session_id="t-row"):
        m = current_session_metrics()
        m.set_active_plan(plan)
        m.record_replan("verify_fail")
        row = m.to_session_row()
        assert row["replan_count"] == 1
        assert row["last_replan_trigger"] == "verify_fail"
        assert row["active_plan_revision"] == 0
        assert row["active_plan_step_count"] == 3


# -- verify integration (step_expected_mismatch) -----------------------


def test_step_expected_mismatch_fires_when_text_doesnt_match() -> None:
    """Active plan + non-empty expected_outcome + text without any
    expected token → ``step_expected_mismatch`` rubric_miss."""
    plan = Plan(
        steps=(
            PlanStep(
                id="s1",
                description="search arxiv",
                expected_outcome="arxiv paper found",
            ),
        )
    )
    with session_metrics_scope(session_id="t-mismatch"):
        current_session_metrics().set_active_plan(plan)
        result = _make_result(text="something totally unrelated to the goal")
        vr = verify_turn(result)
        assert "step_expected_mismatch" in vr.rubric_misses
        assert vr.should_retry is True


def test_step_expected_match_passes_when_token_present() -> None:
    """Text containing any non-trivial expected token → no mismatch."""
    plan = Plan(
        steps=(
            PlanStep(
                id="s1",
                description="search arxiv",
                expected_outcome="arxiv paper found",
            ),
        )
    )
    with session_metrics_scope(session_id="t-match"):
        current_session_metrics().set_active_plan(plan)
        result = _make_result(text="I found the arxiv paper at 1234.56789")
        vr = verify_turn(result)
        assert "step_expected_mismatch" not in vr.rubric_misses


def test_step_expected_mismatch_skipped_without_plan() -> None:
    """No active plan → never fires (pre-A1 behaviour preserved)."""
    with session_metrics_scope(session_id="t-noplan"):
        result = _make_result(text="anything goes")
        vr = verify_turn(result)
        assert "step_expected_mismatch" not in vr.rubric_misses


def test_step_expected_mismatch_skipped_when_expected_empty() -> None:
    """PlanStep without expected_outcome → mismatch never fires."""
    plan = Plan(steps=(PlanStep(id="s1", description="x", expected_outcome=""),))
    with session_metrics_scope(session_id="t-empty"):
        current_session_metrics().set_active_plan(plan)
        result = _make_result(text="literally anything")
        vr = verify_turn(result)
        assert "step_expected_mismatch" not in vr.rubric_misses


# -- Decomposition heuristics (PR-CL-A1-followup, 2026-05-23) ----------
# Coverage migrated from tests/test_goal_decomposer.py (DELETED with
# core/orchestration/goal_decomposer.py).


def test_is_clearly_simple_slash_command() -> None:
    """Slash commands always single-intent — bypass LLM."""
    from core.agent.plan import _is_clearly_simple

    assert _is_clearly_simple("/help") is True
    assert _is_clearly_simple("/login") is True
    assert _is_clearly_simple("/model claude-opus-4-7") is True


def test_is_clearly_simple_short_input() -> None:
    """Very short inputs (<15 chars) are almost always single-intent."""
    from core.agent.plan import _is_clearly_simple

    assert _is_clearly_simple("hi") is True
    assert _is_clearly_simple("뭐해") is True
    assert _is_clearly_simple("a" * 14) is True
    # Boundary — exactly 15 chars is NOT simple.
    assert _is_clearly_simple("a" * 15) is False


def test_is_clearly_simple_long_input() -> None:
    """Long, non-slash inputs require the compound check."""
    from core.agent.plan import _is_clearly_simple

    assert _is_clearly_simple("this is a longer request that needs analysis") is False


def test_has_compound_indicators_korean() -> None:
    """Korean compound markers fire."""
    from core.agent.plan import _has_compound_indicators

    assert _has_compound_indicators("Project Atlas 를 종합 평가") is True
    assert _has_compound_indicators("분석하고 리포트 만들어줘") is True
    assert _has_compound_indicators("검색하고 정리") is True
    assert _has_compound_indicators("전반적인 점검") is True


def test_has_compound_indicators_english() -> None:
    """English connectors / multi-step keywords fire."""
    from core.agent.plan import _has_compound_indicators

    assert _has_compound_indicators("search and summarize") is True
    assert _has_compound_indicators("comprehensive review") is True
    assert _has_compound_indicators("analyze and compare options") is True


def test_has_compound_indicators_negative() -> None:
    """Single-intent requests return False — no compound marker."""
    from core.agent.plan import _has_compound_indicators

    assert _has_compound_indicators("what is the time") is False
    assert _has_compound_indicators("show me the logs") is False


def test_build_tool_summary_empty() -> None:
    from core.agent.plan import _build_tool_summary

    assert _build_tool_summary([]) == "(no tools available)"


def test_build_tool_summary_cost_tier_label() -> None:
    """``[cost_tier]`` label preserves operator-visible tool tradeoffs (Codex LOW #3
    parity with legacy goal_decomposer._build_tool_summary)."""
    from core.agent.plan import _build_tool_summary

    tools = [
        {"name": "web_search", "description": "Search the web.", "cost_tier": "free"},
        {
            "name": "vision_analyze",
            "description": "Analyze an image. Returns structured tags.",
            "cost_tier": "expensive",
        },
        {"name": "memory_read", "description": "Read memory.", "cost_tier": ""},
    ]
    out = _build_tool_summary(tools)
    assert "**web_search** [free]: Search the web" in out
    assert "**vision_analyze** [expensive]: Analyze an image" in out
    # First-sentence truncation drops "Returns structured tags.".
    assert "Returns structured tags" not in out
    # Empty cost_tier → no bracket label.
    assert "**memory_read**: Read memory" in out


def test_decompose_async_skips_simple_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Heuristic gate short-circuits — no LLM call for slash command."""
    import asyncio

    from core.agent.plan import decompose_async

    called = {"hit": False}

    async def _fake_call_llm(*_args: Any, **_kw: Any) -> Any:
        called["hit"] = True
        return None

    loop = SimpleNamespace(_call_llm=_fake_call_llm, _tools=[], model="m")
    result = asyncio.run(decompose_async(loop, "/help"))
    assert result is None
    assert called["hit"] is False


def test_decompose_async_skips_no_compound(monkeypatch: pytest.MonkeyPatch) -> None:
    """No compound markers + long input → skip LLM (saves cost)."""
    import asyncio

    from core.agent.plan import decompose_async

    called = {"hit": False}

    async def _fake_call_llm(*_args: Any, **_kw: Any) -> Any:
        called["hit"] = True
        return None

    loop = SimpleNamespace(_call_llm=_fake_call_llm, _tools=[], model="m")
    result = asyncio.run(decompose_async(loop, "what is the weather forecast today"))
    assert result is None
    assert called["hit"] is False


def test_step_expected_mismatch_in_retryable_set() -> None:
    """The new code is in the retryable allowlist so PR-CL-A1 replan
    can recover from it."""
    from core.agent.verify import _RETRYABLE_MISSES

    assert "step_expected_mismatch" in _RETRYABLE_MISSES


def test_hard_fail_with_step_mismatch_skips_retry() -> None:
    """Codex MCP HIGH #1 (PR-CL-A1, 2026-05-23) — when
    ``model_action_required`` co-occurs with a retryable miss, retry
    must stay False so PR-CL-A1 doesn't loop on a billing/cost-cap
    event."""
    plan = Plan(steps=(PlanStep(id="s1", description="x", expected_outcome="found something"),))
    with session_metrics_scope(session_id="t-hardfail-mismatch"):
        current_session_metrics().set_active_plan(plan)
        result = _make_result(
            text="totally unrelated output",
            termination_reason="model_action_required",
        )
        vr = verify_turn(result)
        assert "step_expected_mismatch" in vr.rubric_misses
        assert "model_action_required" in vr.rubric_misses
        assert vr.should_retry is False  # hard fail wins


# -- _maybe_replan_async smoke (Codex MCP LOW #6) ----------------------


def test_maybe_replan_async_verify_fail_triggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: verify FAIL + active plan → ``_maybe_replan_async``
    calls ``replan_async`` (via stub) → installs new Plan, marks
    ``_prompt_dirty=True``, increments ``record_replan``."""
    from core.agent.loop.agent_loop import AgenticLoop

    fake_settings = SimpleNamespace(
        replan_enabled=True,
        replan_interval=5,
        replan_max_attempts=3,
    )
    monkeypatch.setattr("core.config.settings", fake_settings)

    new_plan_step = PlanStep(id="new1", description="revised")
    new_plan = Plan(steps=(new_plan_step,), revision=99)

    async def _fake_replan_async(
        loop: Any, *, plan: Any, turn_result: Any, trigger: str, **_kw: Any
    ) -> Plan:
        return new_plan

    import core.agent.plan as _plan_mod

    monkeypatch.setattr(_plan_mod, "replan_async", _fake_replan_async)

    initial_plan = _make_plan("s1")
    with session_metrics_scope(session_id="t-fail-trigger"):
        m = current_session_metrics()
        m.set_active_plan(initial_plan)
        m.last_verify_passed = False
        m.last_verify_should_retry = True

        stub = SimpleNamespace(
            _tool_processor=SimpleNamespace(tool_log=[]),
            _prompt_dirty=False,
        )
        bound = AgenticLoop._maybe_replan_async.__get__(stub, SimpleNamespace)
        asyncio.run(bound(2))
        assert stub._prompt_dirty is True
        assert m.active_plan is new_plan
        assert m.replan_count == 1
        assert m.last_replan_trigger == "verify_fail"


def test_maybe_replan_async_cadence_triggers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cadence trigger (interval=2, round 2) fires replan even without
    a verify FAIL."""
    from core.agent.loop.agent_loop import AgenticLoop

    fake_settings = SimpleNamespace(
        replan_enabled=True,
        replan_interval=2,
        replan_max_attempts=3,
    )
    monkeypatch.setattr("core.config.settings", fake_settings)

    async def _fake_replan_async(*_args: Any, **_kw: Any) -> Plan:
        return Plan(steps=(PlanStep(id="r1", description="x"),), revision=1)

    import core.agent.plan as _plan_mod

    monkeypatch.setattr(_plan_mod, "replan_async", _fake_replan_async)

    plan = _make_plan("s1")
    with session_metrics_scope(session_id="t-cadence"):
        m = current_session_metrics()
        m.set_active_plan(plan)
        # verify clean — only cadence should trigger
        m.last_verify_passed = True
        m.last_verify_should_retry = False

        stub = SimpleNamespace(
            _tool_processor=SimpleNamespace(tool_log=[]),
            _prompt_dirty=False,
        )
        bound = AgenticLoop._maybe_replan_async.__get__(stub, SimpleNamespace)
        asyncio.run(bound(2))
        assert m.last_replan_trigger == "cadence"


def test_maybe_replan_async_abandons_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex MCP HIGH #3 + follow-up — counter accumulates across replans
    on the same step (does not reset on successful planner call). After
    exceeding ``replan_max_attempts``, the loop advances the plan
    (abandoned=True) instead of calling the planner LLM."""
    from core.agent.loop.agent_loop import AgenticLoop

    fake_settings = SimpleNamespace(
        replan_enabled=True,
        replan_interval=0,  # cadence off
        replan_max_attempts=2,
    )
    monkeypatch.setattr("core.config.settings", fake_settings)

    planner_calls: list[int] = []

    async def _fake_replan_async(*_args: Any, **_kw: Any) -> Plan:
        planner_calls.append(1)
        return Plan(steps=(PlanStep(id="r1", description="x"),), revision=1)

    import core.agent.plan as _plan_mod

    monkeypatch.setattr(_plan_mod, "replan_async", _fake_replan_async)

    plan = _make_plan("s1", "s2")
    with session_metrics_scope(session_id="t-abandon"):
        m = current_session_metrics()
        m.set_active_plan(plan, reset_attempts=True)

        stub = SimpleNamespace(
            _tool_processor=SimpleNamespace(tool_log=[]),
            _prompt_dirty=False,
        )
        bound = AgenticLoop._maybe_replan_async.__get__(stub, SimpleNamespace)
        # Run 3 verify-fail rounds — each increments the per-step counter.
        # cap=2, so attempts 1+2 call the planner; attempt 3 triggers abandon.
        for _ in range(3):
            m.last_verify_passed = False
            m.last_verify_should_retry = True
            asyncio.run(bound(1))
        # Planner should have been called exactly twice (attempts 1, 2);
        # attempt 3 abandoned without a planner call.
        assert len(planner_calls) == 2
        # Plan should have advanced (abandoned current step).
        assert m.active_plan.current == 1 or len(m.active_plan.abandoned) >= 1
