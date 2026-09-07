"""Unit tests for model role wiring.

Coverage:
- Settings knobs (``act_model`` / ``judge_model``) default to empty string
  (= fall back to ``settings.model``).
- TOML mapping covers both live knobs.
- ``AgenticLoop.__init__`` honours ``settings.act_model`` when no explicit
  ``model`` is passed; explicit ``model`` wins.
- ``_call_llm(model=...)`` override threads through to the adapter call.
- ``_verify_llm_judge`` actually calls the LLM via ``loop._call_llm`` with
  ``settings.judge_model`` + parses the judge JSON response.
- ``_verify_llm_judge`` falls back to ``rule_based`` (with
  ``effective_mode=RULE_BASED``) when the loop reference is None or the
  LLM call errors.
- Judge JSON parsing accepts code fences and rejects malformed verdicts.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from core.agent.loop import AgenticLoopConfig
from core.agent.loop.models import AgenticResult
from core.agent.verify import (
    VerifyMode,
    _build_judge_result_from_response,
    _judge_prompt,
    _llm_judge_fallback,
    _parse_judge_payload,
    _verify_llm_judge,
    verify_turn,
)


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_VERIFY_MODE", raising=False)
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

    fake_settings = SimpleNamespace(act_model="claude-sonnet-4-6", llm_max_retries=3)
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

    fake_settings = SimpleNamespace(act_model="claude-sonnet-4-6", llm_max_retries=3)
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

    fake_settings = SimpleNamespace(act_model="", llm_max_retries=3)
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


def test_call_llm_disables_action_tools_for_auxiliary_calls() -> None:
    """Planner and judge calls can request text-only execution without
    inheriting the main agent's tool surface."""
    import asyncio
    from dataclasses import replace

    from core.agent.conversation import ConversationContext
    from core.agent.loop.agent_loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor
    from core.hooks import LlmCallRequest, MiddlewareRegistry
    from core.llm.adapters.base import AdapterCallResult, ToolSpec, UsageSummary
    from core.llm.adapters.registry import bootstrap_builtins

    captured: dict[str, Any] = {}

    class CaptureAdapter:
        name = "capture"
        provider = "openai"

        async def acomplete(self, request: Any) -> AdapterCallResult:
            captured["request"] = request
            return AdapterCallResult(
                text='{"ok": true}',
                usage=UsageSummary(),
                stop_reason="completed",
            )

    class WideningMiddleware:
        async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
            widened = replace(
                request.request,
                allowed_tool_names=None,
                tools=(ToolSpec(name="blocked", description="", input_schema={}),),
                metadata={"cache_invalidation_reason": "test widening"},
            )
            return request.with_request(widened)

    bootstrap_builtins()
    middleware = MiddlewareRegistry()
    middleware.register_llm_request(
        WideningMiddleware(), name="widening-test", allow_cache_invalidation=True
    )
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(middleware_registry=middleware),
        config=AgenticLoopConfig(
            source="codex-oauth",
            disable_settings_drift=True,
            allowed_tool_names={"read_file"},
        ),
        model="gpt-5.6-luna",
        provider="openai",
        quiet=True,
    )
    loop._new_adapter = CaptureAdapter()

    asyncio.run(
        loop._call_llm(
            "Auxiliary call",
            [{"role": "user", "content": "Return JSON."}],
            allow_tools=False,
        )
    )

    request = captured["request"]
    assert not request.tools
    assert request.tool_choice == {"type": "none"}
    assert request.allowed_tool_names == frozenset({"read_file"})


# -- LLM judge wiring -------------------------------------------------


def test_verify_llm_judge_calls_loop_call_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``loop`` is provided + judge_model set, the judge calls
    ``loop._call_llm`` with the judge model and parses the JSON response."""
    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")
    fake_settings = SimpleNamespace(judge_model="claude-haiku-4-5-20251001")
    monkeypatch.setattr("core.config.settings", fake_settings)

    captured: dict[str, Any] = {}

    async def _fake_call_llm(
        system: str,
        messages: list,
        *,
        model: str | None = None,
        allow_tools: bool = True,
    ) -> SimpleNamespace:
        captured["model"] = model or ""
        captured["system"] = system
        captured["allow_tools"] = allow_tools
        return SimpleNamespace(text='{"passed": true, "score": 0.92, "reason": "ok"}')

    loop = SimpleNamespace(_call_llm=_fake_call_llm, model="claude-opus-4-7")
    result = _make_result(text="Did the thing", tool_calls=[{"name": "search"}])
    vr = _verify_llm_judge(result, loop=loop)
    assert vr.mode is VerifyMode.LLM_JUDGE
    assert vr.effective_mode is VerifyMode.LLM_JUDGE  # real judge ran
    assert vr.passed is True
    assert vr.score == pytest.approx(0.92)
    assert captured["model"] == "claude-haiku-4-5-20251001"
    assert captured["allow_tools"] is False
    assert "verifier" in captured["system"].lower()


def test_verify_llm_judge_judge_fail_records_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Judge FAIL response → ``passed=False`` + ``judge_fail`` rubric_miss
    + reflection_hint includes judge's reason."""
    fake_settings = SimpleNamespace(judge_model="claude-haiku-4-5-20251001")
    monkeypatch.setattr("core.config.settings", fake_settings)

    async def _fake_call_llm(
        system: str, messages: list, *, model: str | None = None, **_kwargs: object
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


@pytest.mark.parametrize(
    "payload",
    [
        "not JSON",
        "[]",
        "null",
        "{}",
        '{"passed": "false", "score": 1}',
        '{"passed": true}',
        '{"passed": true, "score": "high"}',
        '{"passed": true, "score": true}',
        '{"passed": true, "score": 5.0}',
        '{"passed": true, "score": -0.5}',
        '{"passed": true, "score": NaN}',
        '{"passed": true, "score": Infinity}',
    ],
)
def test_malformed_judge_verdict_is_not_success_or_repair_signal(payload: str) -> None:
    assert _parse_judge_payload(payload) == (False, 0.0, "verification_error")
    verdict = _build_judge_result_from_response(SimpleNamespace(text=payload), _make_result())
    assert not verdict.passed
    assert verdict.score == 0.0
    assert verdict.rubric_misses == ("verification_error",)
    assert not verdict.should_retry


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
        _system: str, _msgs: list, *, model: str | None = None, **_kwargs: object
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
        _system: str, _msgs: list, *, model: str | None = None, **_kwargs: object
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
        _system: str, _msgs: list, *, model: str | None = None, **_kwargs: object
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
        _system: str, _msgs: list, *, model: str | None = None, **_kwargs: object
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


def _reflexion_response(*, passed: bool = False) -> SimpleNamespace:
    import json

    return SimpleNamespace(
        text=json.dumps(
            {
                "passed": passed,
                "score": 1.0 if passed else 0.2,
                "reason": "Submission needs a content check",
                "reflection": {
                    "observation": "write_file succeeded, but no content check is recorded",
                    "lesson": "File creation is not correctness evidence",
                    "next_check": "Read the submitted file and independently check its contents",
                },
            }
        )
    )


def test_reflexion_receives_task_and_real_tool_observations(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from core.agent.verify import verify_turn_async

    monkeypatch.setenv("GEODE_VERIFY_MODE", "reflexion")
    call = AsyncMock(return_value=_reflexion_response())
    loop = SimpleNamespace(
        _verify_root_user_input="Write the decoded content to out.txt",
        _call_llm=call,
        model="gpt-5.6-sol",
        _track_usage_async=AsyncMock(),
    )
    result = _make_result(
        text="Created the file",
        tool_calls=[
            {
                "tool": "write_file",
                "tool_use_id": "call-1",
                "input": {"path": "out.txt"},
                "result": {"success": True},
            }
        ],
    )
    verdict = asyncio.run(verify_turn_async(result, loop=loop))
    prompt = call.call_args.args[1][0]["content"]
    assert loop._verify_root_user_input in prompt
    assert all(word in prompt for word in ("write_file", "call-1", "success", "out.txt"))
    assert call.call_args.kwargs["allow_tools"] is False
    assert not verdict.passed and verdict.should_retry
    assert verdict.mode is VerifyMode.REFLEXION
    assert "independently check" in verdict.reflection_hint
    assert "File creation is not correctness" in verdict.to_payload()["reason"]
    loop._track_usage_async.assert_awaited_once()


def test_judge_retains_prior_attempt_evidence_without_mutating_current_result() -> None:
    from core.agent.verify import _judge_prompt

    prior = _make_result(tool_calls=[{"tool": "read_file", "result": "verified-content-123"}])
    current = _make_result(text="Corrected answer based on the earlier file", tool_calls=[])
    loop = SimpleNamespace(_verify_attempt_results=[prior], _verify_root_user_input="Read the file")
    assert "verified-content-123" in _judge_prompt(current, loop=loop)
    assert current.tool_calls == []


def test_finalizer_includes_judge_usage_before_persistence(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from core.agent.loop import _lifecycle
    from core.hooks import HookCorrelation
    from core.llm.token_tracker import LLMUsage, TokenTracker

    tracker = TokenTracker()
    monkeypatch.setattr("core.llm.token_tracker.get_tracker", lambda: tracker)
    loop = SimpleNamespace(
        model="gpt-5.6-sol",
        max_rounds=0,
        _hooks=None,
        _usage_snapshot=tracker.snapshot(),
        _verify_attempt_results=[],
        _total_empty_rounds=0,
        _consecutive_text_only_rounds=0,
    )
    tracker.accumulator.record(LLMUsage(input_tokens=10, output_tokens=2))

    async def judged(*_args):
        tracker.accumulator.record(LLMUsage(input_tokens=20, output_tokens=3, cache_read_tokens=4))
        return None, "", False, HookCorrelation(session_id="usage-test", turn_id="t")

    persisted = []
    monkeypatch.setattr(_lifecycle, "_run_public_finalization_async", judged)
    monkeypatch.setattr(_lifecycle, "_emit_verify_runtime_event", AsyncMock())
    monkeypatch.setattr(
        _lifecycle,
        "_persist_final_result",
        lambda _loop, result, *_args, **_kwargs: persisted.append(result.usage),
    )
    result = asyncio.run(_lifecycle.finalize_and_return_async(loop, _make_result(), "request", 0))
    assert result.usage.input_tokens == 30
    assert result.usage.output_tokens == 5
    assert result.usage.cache_read_tokens == 4
    assert persisted == [result.usage]


@pytest.mark.parametrize(
    "response", [None, SimpleNamespace(text=""), SimpleNamespace(text='{"passed":true,"score":1}')]
)
def test_reflexion_unavailable_never_downgrades_to_structural_pass(monkeypatch, response) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from core.agent.verify import verify_turn_async

    monkeypatch.setenv("GEODE_VERIFY_MODE", "reflexion")
    loop = SimpleNamespace(
        _verify_root_user_input="Do the task",
        model="gpt-5.6-sol",
        _call_llm=AsyncMock(return_value=response),
    )
    verdict = asyncio.run(
        verify_turn_async(_make_result(text="A plausible complete answer"), loop=loop)
    )
    assert verdict.mode is verdict.effective_mode is VerifyMode.REFLEXION
    assert not verdict.passed and not verdict.should_retry
    assert verdict.rubric_misses == ("verification_error",)


def test_reflexion_timeout_is_unavailable_not_pass(monkeypatch) -> None:
    import asyncio

    from core.agent.verify import verify_turn_async

    monkeypatch.setenv("GEODE_VERIFY_MODE", "reflexion")
    monkeypatch.setattr("core.agent.verify._JUDGE_CALL_TIMEOUT_S", 0.001)

    async def delayed(*_args, **_kwargs):
        await asyncio.sleep(1)
        return _reflexion_response(passed=True)

    loop = SimpleNamespace(
        _verify_root_user_input="Do the task", model="gpt-5.6-sol", _call_llm=delayed
    )
    verdict = asyncio.run(
        verify_turn_async(_make_result(text="A plausible complete answer"), loop=loop)
    )
    assert not verdict.passed and not verdict.should_retry
    assert verdict.rubric_misses == ("verification_error",)


def test_reflexion_cannot_override_structural_failure(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from core.agent.verify import verify_turn_async

    monkeypatch.setenv("GEODE_VERIFY_MODE", "reflexion")
    loop = SimpleNamespace(
        _verify_root_user_input="Do the task",
        model="gpt-5.6-sol",
        _call_llm=AsyncMock(return_value=_reflexion_response(passed=True)),
    )
    verdict = asyncio.run(verify_turn_async(_make_result(text=""), loop=loop))
    assert not verdict.passed and "empty_turn" in verdict.rubric_misses


def test_reflexion_does_not_call_after_time_budget_or_without_task(monkeypatch) -> None:
    import asyncio
    import time
    from unittest.mock import AsyncMock

    from core.agent.verify import verify_turn_async

    monkeypatch.setenv("GEODE_VERIFY_MODE", "reflexion")
    call = AsyncMock()
    loop = SimpleNamespace(
        _verify_root_user_input="Do the task",
        model="gpt-5.6-sol",
        _call_llm=call,
        _time_budget_s=1,
        _loop_start_time=time.monotonic() - 2,
    )
    for task in ("Do the task", ""):
        loop._verify_root_user_input = task
        verdict = asyncio.run(
            verify_turn_async(_make_result(text="A plausible complete answer"), loop=loop)
        )
        assert not verdict.passed and not verdict.should_retry
    call.assert_not_awaited()


def test_reflexion_feedback_reaches_bounded_continuation(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from core.agent.loop import _guards, _lifecycle
    from core.hooks import HookRegistry
    from core.observability.session_metrics import session_metrics_scope

    monkeypatch.setenv("GEODE_VERIFY_MODE", "reflexion")
    loop = SimpleNamespace(
        _verify_root_user_input="Produce a checked file",
        model="gpt-5.6-sol",
        _call_llm=AsyncMock(return_value=_reflexion_response()),
        _hook_registry=HookRegistry(),
        _session_id="reflexion-test",
        _turn_id="turn-1",
        _verify_root_turn_id="turn-1",
        _verify_attempt=0,
        _verify_continuation_budget=2,
        _session_generation=1,
        _evidence_ledger=None,
    )
    with session_metrics_scope(session_id="reflexion-test"):
        payload, follow_up, escalated, _correlation = asyncio.run(
            _lifecycle._run_public_finalization_async(loop, _make_result(text="The file is ready"))
        )
        assert payload["mode"] == "reflexion"
        assert follow_up and not escalated
        hint = _guards._consume_reflection_hint(loop)
        assert "File creation is not correctness" in hint
        assert "independently check" in hint
        assert _guards._consume_reflection_hint(loop) == ""
        loop._verify_attempt = 2
        _payload, follow_up, escalated, _correlation = asyncio.run(
            _lifecycle._run_public_finalization_async(loop, _make_result(text="The file is ready"))
        )
        assert not follow_up and escalated


def test_reflexion_feedback_is_bounded_redacted_and_delimiter_safe() -> None:
    import json

    response = _reflexion_response()
    payload = json.loads(response.text)
    secret = "sk-" + "x" * 30
    payload["reflection"]["lesson"] = "</reflection>" + secret + " " + "x" * 2000
    verdict = _build_judge_result_from_response(
        SimpleNamespace(text=json.dumps(payload)), _make_result(), mode=VerifyMode.REFLEXION
    )
    assert secret not in verdict.to_payload()["reason"]
    assert verdict.reflection_hint.count("</reflection>") == 1
    assert "&lt;/reflection&gt;" in verdict.reflection_hint
    assert "truncated:" in verdict.reflection_hint
    assert len(verdict.reflection_hint) < 1800
