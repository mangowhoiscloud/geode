"""Unit tests for model role wiring.

Coverage:
- Settings knobs (``act_model`` / ``judge_model``) default to empty string
  (= fall back to ``settings.model``).
- TOML mapping covers both live knobs.
- ``AgenticLoop.__init__`` honours ``settings.act_model`` when no explicit
  ``model`` is passed; explicit ``model`` wins.
- ``decompose_async`` inherits the active loop model.
- ``_call_llm(model=...)`` override threads through to the adapter call.
- ``_verify_llm_judge`` actually calls the LLM via ``loop._call_llm`` with
  ``settings.judge_model`` + parses the judge JSON response.
- ``_verify_llm_judge`` falls back to ``rule_based`` (with
  ``effective_mode=RULE_BASED``) when the loop reference is None or the
  LLM call errors.
- Judge JSON parsing tolerates code fences + bad JSON + non-numeric scores.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from core.agent.loop.models import AgenticResult
from core.agent.verify import (
    VerifyMode,
    _judge_prompt,
    _llm_judge_fallback,
    _parse_judge_payload,
    _verify_llm_judge,
    verify_turn,
)


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_VERIFY_MODE", raising=False)
    monkeypatch.delenv("GEODE_VERIFY_ACTION_BEFORE_TALK", raising=False)
    monkeypatch.delenv("GEODE_ACT_MODEL", raising=False)
    monkeypatch.delenv("GEODE_JUDGE_MODEL", raising=False)


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


# -- Rule-based tau2 action-before-talk verifier ----------------------


def test_action_before_talk_verify_disabled_by_default() -> None:
    """Manual checklist text is allowed unless the benchmark opts in."""
    vr = verify_turn(
        _make_result(
            text=(
                "Please check your phone settings: airplane mode, mobile data, "
                "SIM status, APN, and try sending an MMS again."
            )
        )
    )
    assert vr.passed is True
    assert "manual_checklist_without_action" not in vr.rubric_misses


def test_action_before_talk_verify_flags_checklist_without_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tau2 telecom runs should retry when the loop talks instead of acting."""
    monkeypatch.setenv("GEODE_VERIFY_ACTION_BEFORE_TALK", "1")
    vr = verify_turn(
        _make_result(
            text=(
                "Please check your phone settings: airplane mode, mobile data, "
                "SIM status, network mode, APN, and try sending an MMS again."
            )
        )
    )
    assert vr.passed is False
    assert "manual_checklist_without_action" in vr.rubric_misses
    assert vr.should_retry is True


def test_action_before_talk_verify_allows_tool_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule only catches no-action checklist turns."""
    monkeypatch.setenv("GEODE_VERIFY_ACTION_BEFORE_TALK", "1")
    vr = verify_turn(
        _make_result(
            text="I will inspect the network state first, then continue troubleshooting.",
            tool_calls=[{"name": "check_network_status", "arguments": {}}],
        )
    )
    assert vr.passed is True
    assert "manual_checklist_without_action" not in vr.rubric_misses


# -- Settings knob defaults --------------------------------------------


def test_settings_default_to_empty_string() -> None:
    """Live model-role knobs default to ``""`` so existing callers fall back
    to ``settings.model`` until they set a concrete value."""
    from core.config._settings import Settings

    s = Settings()
    assert s.act_model == ""
    assert s.judge_model == ""


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """``GEODE_ACT_MODEL`` / ``GEODE_JUDGE_MODEL`` env vars populate the
    knobs via pydantic AliasChoices."""
    from core.config._settings import Settings

    monkeypatch.setenv("GEODE_ACT_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("GEODE_JUDGE_MODEL", "claude-haiku-4-5-20251001")
    s = Settings()
    assert s.act_model == "claude-sonnet-4-6"
    assert s.judge_model == "claude-haiku-4-5-20251001"


def test_toml_mapping_covers_live_model_knobs() -> None:
    """Config cascade maps the live model role knobs."""
    from core.config import _TOML_TO_SETTINGS

    assert "llm.plan_model" not in _TOML_TO_SETTINGS
    assert _TOML_TO_SETTINGS["llm.act_model"] == "act_model"
    assert _TOML_TO_SETTINGS["llm.judge_model"] == "judge_model"


# -- AgenticLoop.__init__ uses act_model when no explicit model --------


def test_act_model_used_when_no_explicit_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``settings.act_model`` is set and caller doesn't pass an
    explicit model, ``AgenticLoop.model`` reflects ``act_model``."""
    from core.agent.loop.agent_loop import AgenticLoop

    fake_settings = SimpleNamespace(act_model="claude-sonnet-4-6")
    monkeypatch.setattr("core.config.settings", fake_settings)
    # Build a minimal loop — most kwargs are optional, but ConversationContext
    # + ToolExecutor are required. Use mocks.
    ctx = MagicMock()
    ctx.get_messages.return_value = []
    executor = MagicMock()
    loop = AgenticLoop(ctx, executor)
    assert loop.model == "claude-sonnet-4-6"


def test_explicit_model_wins_over_act_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller-passed ``model=...`` overrides ``settings.act_model``."""
    from core.agent.loop.agent_loop import AgenticLoop

    fake_settings = SimpleNamespace(act_model="claude-sonnet-4-6")
    monkeypatch.setattr("core.config.settings", fake_settings)
    ctx = MagicMock()
    ctx.get_messages.return_value = []
    executor = MagicMock()
    loop = AgenticLoop(ctx, executor, model="claude-opus-4-7")
    assert loop.model == "claude-opus-4-7"


def test_act_model_empty_falls_back_to_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty ``act_model`` falls back to ``ANTHROPIC_PRIMARY`` (the
    legacy pre-A6 default)."""
    from core.agent.loop.agent_loop import AgenticLoop
    from core.config import ANTHROPIC_PRIMARY

    fake_settings = SimpleNamespace(act_model="")
    monkeypatch.setattr("core.config.settings", fake_settings)
    ctx = MagicMock()
    ctx.get_messages.return_value = []
    executor = MagicMock()
    loop = AgenticLoop(ctx, executor)
    assert loop.model == ANTHROPIC_PRIMARY


# -- _call_llm model override -----------------------------------------


def test_call_llm_signature_accepts_model_override() -> None:
    """``_call_llm`` exposes a ``model`` keyword parameter (introspection
    check — exercises the signature contract without running an LLM)."""
    import inspect

    from core.agent.loop.agent_loop import AgenticLoop

    sig = inspect.signature(AgenticLoop._call_llm)
    assert "model" in sig.parameters
    param = sig.parameters["model"]
    assert param.default is None  # default falls back to self.model
    assert param.kind == inspect.Parameter.KEYWORD_ONLY


# -- Goal decomposition inherits loop model ---------------------------


def test_decompose_async_inherits_loop_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """``decompose_async`` threads the active loop model through
    ``loop._call_llm``."""
    import asyncio

    fake_settings = SimpleNamespace(model="claude-haiku-4-5")
    monkeypatch.setattr("core.config.settings", fake_settings)

    captured: dict[str, str] = {}

    async def _fake_call_llm(
        _system: str, _msgs: list, *, model: str | None = None, **_kwargs: object
    ) -> SimpleNamespace:
        captured["model"] = model or ""
        # Return None so decompose_async early-exits without parsing
        # (we only care which model was requested for the call).
        return None

    loop = SimpleNamespace(_call_llm=_fake_call_llm, _tools=[], model="claude-haiku-4-5")

    from core.agent.plan import decompose_async

    asyncio.run(decompose_async(loop, "comprehensive analysis and report"))
    assert captured["model"] == "claude-haiku-4-5"


def test_decompose_async_ignores_removed_plan_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale ``settings.plan_model`` attribute cannot split planner model
    selection away from the active loop."""
    import asyncio

    fake_settings = SimpleNamespace(plan_model="claude-opus-4-7", model="claude-haiku-4-5")
    monkeypatch.setattr("core.config.settings", fake_settings)
    captured: dict[str, str] = {}

    async def _fake_call_llm(
        _system: str, _msgs: list, *, model: str | None = None, **_kwargs: object
    ) -> SimpleNamespace:
        captured["model"] = model or ""
        return None

    loop = SimpleNamespace(_call_llm=_fake_call_llm, _tools=[], model="claude-opus-4-7")

    from core.agent.plan import decompose_async

    asyncio.run(decompose_async(loop, "comprehensive analysis and report"))
    assert captured["model"] == "claude-opus-4-7"


# -- LLM judge wiring -------------------------------------------------


def test_verify_llm_judge_calls_loop_call_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``loop`` is provided + judge_model set, the judge calls
    ``loop._call_llm`` with the judge model and parses the JSON response."""
    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")
    fake_settings = SimpleNamespace(judge_model="claude-haiku-4-5-20251001")
    monkeypatch.setattr("core.config.settings", fake_settings)

    captured: dict[str, str] = {}

    async def _fake_call_llm(
        system: str, messages: list, *, model: str | None = None
    ) -> SimpleNamespace:
        captured["model"] = model or ""
        captured["system"] = system
        return SimpleNamespace(text='{"passed": true, "score": 0.92, "reason": "ok"}')

    loop = SimpleNamespace(_call_llm=_fake_call_llm, model="claude-opus-4-7")
    result = _make_result(text="Did the thing", tool_calls=[{"name": "search"}])
    vr = _verify_llm_judge(result, loop=loop)
    assert vr.mode is VerifyMode.LLM_JUDGE
    assert vr.effective_mode is VerifyMode.LLM_JUDGE  # real judge ran
    assert vr.passed is True
    assert vr.score == pytest.approx(0.92)
    assert captured["model"] == "claude-haiku-4-5-20251001"
    assert "verifier" in captured["system"].lower()


def test_verify_llm_judge_judge_fail_records_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Judge FAIL response → ``passed=False`` + ``judge_fail`` rubric_miss
    + reflection_hint includes judge's reason."""
    fake_settings = SimpleNamespace(judge_model="claude-haiku-4-5-20251001")
    monkeypatch.setattr("core.config.settings", fake_settings)

    async def _fake_call_llm(
        system: str, messages: list, *, model: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(
            text='{"passed": false, "score": 0.1, "reason": "tool error masked the goal"}'
        )

    loop = SimpleNamespace(_call_llm=_fake_call_llm, model="claude-opus-4-7")
    vr = _verify_llm_judge(_make_result(text="weak output"), loop=loop)
    assert vr.passed is False
    assert vr.effective_mode is VerifyMode.LLM_JUDGE
    assert "judge_fail" in vr.rubric_misses
    assert vr.should_retry is True
    assert "tool error masked the goal" in vr.reflection_hint


def test_verify_llm_judge_falls_back_when_no_loop() -> None:
    """``loop=None`` → fallback to rule_based + ``effective_mode=RULE_BASED``."""
    vr = _verify_llm_judge(_make_result(text=""), loop=None)
    assert vr.mode is VerifyMode.LLM_JUDGE
    assert vr.effective_mode is VerifyMode.RULE_BASED


def test_verify_llm_judge_falls_back_on_exception() -> None:
    """Judge LLM exception → fallback. Telemetry shows the downgrade
    via ``effective_mode=RULE_BASED``."""

    async def _broken(_system: str, _msgs: list, *, model: str | None = None) -> None:
        raise RuntimeError("network down")

    loop = SimpleNamespace(_call_llm=_broken, model="claude-opus-4-7")
    vr = _verify_llm_judge(_make_result(text=""), loop=loop)
    assert vr.mode is VerifyMode.LLM_JUDGE
    assert vr.effective_mode is VerifyMode.RULE_BASED


def test_verify_llm_judge_falls_back_on_none_response() -> None:
    """``_call_llm`` returning None (e.g. all retries failed) → fallback."""

    async def _returns_none(_system: str, _msgs: list, *, model: str | None = None) -> None:
        return None

    loop = SimpleNamespace(_call_llm=_returns_none, model="claude-opus-4-7")
    vr = _verify_llm_judge(_make_result(text=""), loop=loop)
    assert vr.effective_mode is VerifyMode.RULE_BASED


# -- Judge JSON parsing -----------------------------------------------


def test_parse_judge_payload_clean_json() -> None:
    passed, score, reason = _parse_judge_payload('{"passed": true, "score": 0.85, "reason": "ok"}')
    assert passed is True
    assert score == pytest.approx(0.85)
    assert reason == "ok"


def test_parse_judge_payload_code_fence_wrapped() -> None:
    """Some models wrap JSON in ```json fences — strip them."""
    payload = '```json\n{"passed": false, "score": 0.2, "reason": "weak"}\n```'
    passed, score, reason = _parse_judge_payload(payload)
    assert passed is False
    assert score == pytest.approx(0.2)
    assert reason == "weak"


def test_parse_judge_payload_bad_json_treats_as_pass() -> None:
    """Unparseable → neutral pass with score=0.5 + ``judge_unparseable`` reason."""
    passed, score, reason = _parse_judge_payload("not even close to JSON")
    assert passed is True  # neutral
    assert score == pytest.approx(0.5)
    assert reason == "judge_unparseable"


def test_parse_judge_payload_non_numeric_score_defaults_half() -> None:
    """Score field that isn't a number → 0.5."""
    _passed, score, _reason = _parse_judge_payload('{"passed": true, "score": "high"}')
    assert score == pytest.approx(0.5)


def test_parse_judge_payload_score_clamped() -> None:
    """Scores outside [0, 1] are clamped."""
    _, score_high, _ = _parse_judge_payload('{"passed": true, "score": 5.0}')
    assert score_high == 1.0
    _, score_low, _ = _parse_judge_payload('{"passed": true, "score": -0.5}')
    assert score_low == 0.0


def test_judge_prompt_includes_turn_context() -> None:
    """The user-side prompt carries termination_reason / rounds / tool
    names / truncated text so the judge can rate the turn."""
    result = _make_result(
        text="long output " * 100,
        tool_calls=[{"name": "search"}, {"name": "fetch"}],
        termination_reason="natural",
    )
    prompt = _judge_prompt(result)
    assert "natural" in prompt
    assert "search" in prompt and "fetch" in prompt
    assert "rounds: 1" in prompt
    # Text truncated at 2000 chars
    assert len(prompt) < 3000


# -- Verify dispatcher wiring -----------------------------------------


def test_verify_turn_routes_llm_judge_through_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``verify_turn`` in llm_judge mode passes the loop ref through to
    ``_verify_llm_judge``."""
    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")

    async def _fake_call_llm(
        _system: str, _msgs: list, *, model: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(text='{"passed": true, "score": 1.0}')

    loop = SimpleNamespace(_call_llm=_fake_call_llm, model="claude-opus-4-7")
    vr = verify_turn(_make_result(text="OK"), loop=loop)
    assert vr.effective_mode is VerifyMode.LLM_JUDGE
    assert vr.passed is True


def test_llm_judge_fallback_preserves_rubric_misses() -> None:
    """Fallback path runs rule_based underneath so its rubric_misses
    + should_retry flow through to the LLM_JUDGE-labeled result."""
    result = _make_result(text="", tool_calls=[])  # rule-based: empty_turn
    vr = _llm_judge_fallback(result)
    assert vr.mode is VerifyMode.LLM_JUDGE
    assert vr.effective_mode is VerifyMode.RULE_BASED
    assert "empty_turn" in vr.rubric_misses
    assert vr.should_retry is True


# -- Async judge path (PR-CL-A6 Codex MCP HIGH #2 + MEDIUM #3) ----------


def test_verify_turn_async_routes_through_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``verify_turn_async`` in llm_judge mode awaits ``loop._call_llm``
    directly (no thread-pool hop). Verify the asyncio path lands the call
    + parses the response in the same event loop the caller is on."""
    import asyncio

    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")

    captured: dict[str, str] = {}

    async def _fake_call_llm(
        _system: str, _msgs: list, *, model: str | None = None
    ) -> SimpleNamespace:
        captured["model"] = model or ""
        return SimpleNamespace(text='{"passed": true, "score": 0.85, "reason": "ok"}')

    from core.agent.verify import verify_turn_async

    fake_settings = SimpleNamespace(judge_model="claude-haiku-4-5-20251001")
    monkeypatch.setattr("core.config.settings", fake_settings)
    loop = SimpleNamespace(_call_llm=_fake_call_llm, model="claude-opus-4-7")
    vr = asyncio.run(verify_turn_async(_make_result(text="OK"), loop=loop))
    assert vr.effective_mode is VerifyMode.LLM_JUDGE
    assert vr.passed is True
    assert vr.score == pytest.approx(0.85)
    assert captured["model"] == "claude-haiku-4-5-20251001"


def test_verify_turn_async_timeout_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the judge LLM call exceeds ``_JUDGE_CALL_TIMEOUT_S`` the
    async path catches the TimeoutError and falls back to rule_based
    (Codex MCP MEDIUM #3 fix). Patch the timeout to a tiny value to
    avoid sleeping in tests."""
    import asyncio

    from core.agent import verify as verify_mod

    monkeypatch.setattr(verify_mod, "_JUDGE_CALL_TIMEOUT_S", 0.05)

    async def _slow(_system: str, _msgs: list, *, model: str | None = None) -> SimpleNamespace:
        await asyncio.sleep(1.0)
        return SimpleNamespace(text='{"passed": true, "score": 1.0}')

    loop = SimpleNamespace(_call_llm=_slow, model="claude-opus-4-7")
    vr = asyncio.run(verify_mod._verify_llm_judge_async(_make_result(text=""), loop=loop))
    # Timeout → fallback to rule-based.
    assert vr.mode is VerifyMode.LLM_JUDGE
    assert vr.effective_mode is VerifyMode.RULE_BASED


def test_verify_turn_async_off_mode_returns_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OFF mode in async path returns passing sentinel without LLM call."""
    import asyncio

    monkeypatch.setenv("GEODE_VERIFY_MODE", "off")

    from core.agent.verify import verify_turn_async

    vr = asyncio.run(verify_turn_async(_make_result(text="", tool_calls=[]), loop=None))
    assert vr.passed is True
    assert vr.mode is VerifyMode.OFF


# -- Act-model drift (PR-CL-A6 Codex MCP HIGH #1) ----------------------


def test_drift_target_uses_act_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-DRIFT-CUT (2026-05-24) — drift target is unconditionally None.

    Pre-PR this returned ``settings.act_model`` (or ``settings.model``)
    so the per-turn drift sync would revert ``loop.model`` to the
    settings value. The auto-revert silently overrode operator
    ``/model`` selections and was cut at the source. The test now
    pins the no-op contract — the function must NEVER return a
    drift target, regardless of how settings diverge from
    ``loop.model``.
    """
    from core.agent.loop._model_switching import _settings_model_target

    fake_settings = SimpleNamespace(model="claude-opus-4-7", act_model="claude-sonnet-4-6")
    monkeypatch.setattr("core.config.settings", fake_settings)

    loop_stub = SimpleNamespace(
        model="claude-haiku-4-5-20251001",
        _disable_settings_drift=False,
        _drift_target_is_healthy=lambda _m: True,
    )
    target = _settings_model_target(loop_stub)
    assert target is None  # PR-DRIFT-CUT — auto-revert disabled


def test_drift_target_is_none_regardless_of_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Companion to the above — empty ``act_model`` also gets no target."""
    from core.agent.loop._model_switching import _settings_model_target

    fake_settings = SimpleNamespace(model="claude-opus-4-7", act_model="")
    monkeypatch.setattr("core.config.settings", fake_settings)

    loop_stub = SimpleNamespace(
        model="claude-haiku-4-5-20251001",
        _disable_settings_drift=False,
        _drift_target_is_healthy=lambda _m: True,
    )
    target = _settings_model_target(loop_stub)
    assert target is None


def test_drift_target_no_drift_when_already_matched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``loop.model`` already equals the act-model target, no drift."""
    from core.agent.loop._model_switching import _settings_model_target

    fake_settings = SimpleNamespace(model="claude-opus-4-7", act_model="claude-sonnet-4-6")
    monkeypatch.setattr("core.config.settings", fake_settings)

    loop_stub = SimpleNamespace(
        model="claude-sonnet-4-6",
        _disable_settings_drift=False,
        _drift_target_is_healthy=lambda _m: True,
    )
    assert _settings_model_target(loop_stub) is None


def test_judge_usage_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex MCP MEDIUM #4 — the judge LLM call's ``response`` is passed
    to ``loop._track_usage_async`` so judge cost surfaces in the session
    TokenTracker (rather than being silently untracked)."""
    import asyncio

    from core.agent.verify import _verify_llm_judge_async

    fake_settings = SimpleNamespace(judge_model="claude-haiku-4-5-20251001")
    monkeypatch.setattr("core.config.settings", fake_settings)

    recorded_responses: list[Any] = []

    async def _fake_call_llm(
        _system: str, _msgs: list, *, model: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(
            text='{"passed": true, "score": 0.9, "reason": "ok"}',
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        )

    async def _fake_track_usage(response: Any) -> None:
        recorded_responses.append(response)

    loop = SimpleNamespace(
        _call_llm=_fake_call_llm,
        _track_usage_async=_fake_track_usage,
        model="claude-opus-4-7",
    )
    asyncio.run(_verify_llm_judge_async(_make_result(text="OK"), loop=loop))
    assert len(recorded_responses) == 1
    assert recorded_responses[0].usage.input_tokens == 10


def test_judge_usage_track_failure_does_not_break_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Usage-tracking exception is swallowed — the judge result still
    returns normally (observability hygiene)."""
    import asyncio

    from core.agent.verify import _verify_llm_judge_async

    fake_settings = SimpleNamespace(judge_model="claude-haiku-4-5-20251001")
    monkeypatch.setattr("core.config.settings", fake_settings)

    async def _fake_call_llm(
        _system: str, _msgs: list, *, model: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(text='{"passed": true, "score": 1.0}')

    async def _broken_track(_response: Any) -> None:
        raise RuntimeError("tracker down")

    loop = SimpleNamespace(
        _call_llm=_fake_call_llm,
        _track_usage_async=_broken_track,
        model="claude-opus-4-7",
    )
    vr = asyncio.run(_verify_llm_judge_async(_make_result(text="OK"), loop=loop))
    assert vr.passed is True  # tracking failure didn't kill the judge result
    assert vr.effective_mode is VerifyMode.LLM_JUDGE
