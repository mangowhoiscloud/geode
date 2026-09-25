"""Selected Jev reflection uses real loop/observer/accounting owners with fake HTTP."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig
from core.agent.loop.models import AgenticResult
from core.agent.tool_executor import ToolExecutor
from core.agent.verify import verify_turn_async
from core.config import settings
from core.hooks import HookEvent, HookSystem, MiddlewareRegistry
from core.llm import token_tracker, usage_store
from core.llm.adapters import typesafe
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink
from pydantic import SecretStr


@pytest.mark.parametrize("provider", ["typesafe", "openrouter"])
@pytest.mark.parametrize(
    "outcome",
    [
        "supported",
        "contradicted",
        "insufficient_evidence",
        "malformed",
        "wrong_route",
        "http_error",
    ],
)
def test_round_then_terminal_dispatch_once_with_native_usage_and_no_synthetic_belief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str, outcome: str
) -> None:
    monkeypatch.setattr(settings, "judgment_engine", "jev")
    monkeypatch.setattr(settings, "jev_provider", provider)
    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "openrouter_api_key", "test-secret")
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1")
    tracker = token_tracker.TokenTracker()
    monkeypatch.setattr(token_tracker, "get_tracker", lambda: tracker)
    monkeypatch.setattr(usage_store, "get_usage_store", lambda: usage_store.UsageStore(tmp_path))
    hooks = HookSystem()
    store = HookEventStore(tmp_path / "events.db")
    hooks.register_sink(HookPersistenceSink(store, session_key="judgment", run_id="test"))
    registry = MiddlewareRegistry(events=hooks)
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(middleware_registry=registry),
        hooks=hooks,
        config=AgenticLoopConfig(source="payg", session_id="judgment", disable_settings_drift=True),
        model="claude-sonnet-4-6",
        provider="anthropic",
        quiet=True,
    )
    loop._time_budget_s = 0
    loop._verify_root_user_input = "Return the observed value."
    from core.orchestration.compaction import _carry_forward

    loop.context.messages[:] = _carry_forward("Archived key: violet-signal. " + "s" * 3900, [])
    loop.context.add_user_message(
        "Earlier input " + "u" * 7800 + " Correction: multiplier 3.", origin="user_input"
    )
    loop.context.add_user_message("SYNTHETIC_NEW_AUTHORITY")
    loop.context.add_user_message(loop._verify_root_user_input, origin="user_input")
    loop.cognitive_state.goal = "Inspect the original file."
    loop.cognitive_state.hypotheses = ["The value may be known"]
    loop.cognitive_state.confidence = 0.4
    loop.cognitive_state.confidence_observed_round = 0
    requests: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        question = next(iter(payload["questions"]))
        final = question == "verdict"
        if final and outcome == "http_error":
            return httpx.Response(503, json={"error": "temporary failure"})
        selected = (
            outcome
            if final and outcome in payload["questions"][question]["criteria"]
            else "supported"
        )
        answer = {
            "type": "choice",
            "choice": selected,
            "probabilities": {
                name: 1.0 if name == selected else 0.0
                for name in payload["questions"][question]["criteria"]
            },
            "confidence": 1.0,
        }
        if final and outcome == "malformed":
            answer["choice"] = "invented-label"
        return httpx.Response(
            200,
            headers={"x-typesafe-request-id": f"request-{len(requests)}"},
            json={
                "id": f"gen-decision-{len(requests)}",
                "model": "wrong-model" if final and outcome == "wrong_route" else payload["model"],
                "provider": "TypeSafe",
                "answers": {question: answer},
                "usage": {"input_tokens": 110 if final else 70, "output_tokens": 0, "cost": 0.01},
            },
        )

    original_adapter = typesafe.SystemOneAdapter

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            monkeypatch.setattr(
                typesafe,
                "SystemOneAdapter",
                lambda provider, key: original_adapter(provider, key, client=client),
            )
            loop.cognitive_state.record_round(action="read", observation="value observed")
            await loop._maybe_reflect([{"tool_use_id": "read-1", "content": "Observed value: 7"}])
            from defusedxml.ElementTree import fromstring

            prompt = requests[0]["state"]["cognitive_state"]
            document = fromstring(f"<request>{prompt}</request>")
            assert document.findtext("current_request") == "Return the observed value."
            assert "Session initial request: 'Inspect the original file.'" in document.findtext(
                "cognitive_state", ""
            )
            assert loop.cognitive_state.goal == "Inspect the original file."
            retained_context = requests[0]["state"]["retained_task_context"]
            assert "Archived key: violet-signal" in retained_context
            assert "Correction: multiplier 3." in retained_context
            assert "derived_summary" in retained_context
            assert "SYNTHETIC_NEW_AUTHORITY" not in retained_context
            await loop._record_text_only_round(1, text="The value is 7.")
            assert len(requests) == 1  # no second reflection before final judgment
            return await verify_turn_async(
                AgenticResult(
                    text="The value is 7.",
                    termination_reason="natural",
                    tool_calls=[
                        {
                            "tool": "read_file",
                            "input": {"path": "evidence.txt"},
                            "result": "Final actual observation: value 7.",
                        }
                    ],
                ),
                loop=loop,
            )

    try:
        result = asyncio.run(run())
        assert len(requests) == 2
        final_evidence = requests[1]["state"]["tool_observations"]
        assert len(final_evidence) > 12_000
        assert "Final actual observation: value 7." in final_evidence
        assert final_evidence.index("Final actual observation: value 7.") > 12_000
        assert (
            requests[0]["state"]["retained_task_context"]
            in (requests[1]["state"]["tool_observations"])
        )
        assert loop.cognitive_state.hypotheses == ["The value may be known"]
        assert loop.cognitive_state.confidence == 0.4
        assert loop.cognitive_state.confidence_observed_round == 0
        assert loop.cognitive_state.subgoals == [
            "Continue the approach; independently verify the next required outcome."
        ]
        known = outcome != "http_error"
        assert len(tracker.accumulator.calls) == (2 if known else 1)
        assert sum(call.input_tokens for call in tracker.accumulator.calls) == (
            180 if known else 70
        )
        assert {call.model for call in tracker.accumulator.calls} == {
            typesafe.JEV_MODEL if provider == "typesafe" else typesafe.OPENROUTER_JEV_MODEL
        }
        assert result.passed is (outcome == "supported")
        if outcome in {"contradicted", "insufficient_evidence"}:
            assert result.should_retry and result.reflection_hint
            assert "Verification feedback" in result.reflection_hint
        elif outcome != "supported":
            assert not result.should_retry and not result.reflection_hint
            assert result.rubric_misses == ("verification_error",)
        ends = list(reversed(store.read(event_filter=HookEvent.LLM_CALL_ENDED.value)))
        assert len(ends) == 2
        assert [event.payload["purpose"] for event in ends] == [
            "cognitive_reflection",
            "turn_verification",
        ]
        assert [event.payload["provider"] for event in ends] == [provider, provider]
        assert ends[0].payload["usage"]["cached_input_tokens"] is None
        if provider == "openrouter":
            assert tracker.accumulator.total_cost_usd == (0.02 if known else 0.01)
    finally:
        hooks.close()


def test_jev_visual_evidence_is_unavailable_not_silently_discarded(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from core.config.session import SessionModelConfig

    monkeypatch.setattr(settings, "judgment_engine", "jev")
    monkeypatch.setattr(settings, "jev_provider", "typesafe")
    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("test-secret"))
    loop = SimpleNamespace(
        model="gpt-6-astra",
        _verify_root_user_input="Describe the screenshot",
        _model_settings=SessionModelConfig(
            model="gpt-6-astra",
            effort="high",
            source="payg",
            judgment_engine="jev",
            jev_provider="typesafe",
        ),
        _call_llm=AsyncMock(),
    )
    result = AgenticResult(
        text="It is correct",
        tool_calls=[
            {
                "tool_use_id": "image-1",
                "tool": "screenshot",
                "result": {"screenshot_omitted": True, "screenshot_sha256": "a" * 64},
            }
        ],
    )
    verdict = asyncio.run(verify_turn_async(result, loop=loop))
    assert verdict.reason == "jev_visual_evidence_unsupported"
    assert not verdict.passed and not verdict.should_retry
    loop._call_llm.assert_not_called()


def test_jev_reflection_snapshot_limit_does_not_discard_retained_correction(monkeypatch) -> None:
    from core.agent.cognitive_state import CognitiveState
    from core.agent.conversation import render_retained_task_context
    from core.agent.loop._reflection import reflect_async
    from core.orchestration.compaction import _carry_forward

    monkeypatch.setattr(settings, "judgment_engine", "jev")
    monkeypatch.setattr(settings, "jev_provider", "typesafe")
    monkeypatch.setattr(settings, "typesafe_api_key", SecretStr("test-secret"))
    context = ConversationContext(messages=_carry_forward("Archived key: violet-signal.", []))
    context.add_user_message("Correction: multiplier 3.", origin="user_input")
    task_context = render_retained_task_context(context.messages, current_request="Execute")
    state = CognitiveState(goal="Earlier legacy goal " + "x" * 15000)
    requests = []

    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "answers": {
                    "evidence": {
                        "type": "choice",
                        "choice": "supported",
                        "confidence": 1.0,
                        "probabilities": {
                            "supported": 1.0,
                            "contradicted": 0.0,
                            "insufficient_evidence": 0.0,
                        },
                    }
                },
            },
        )

    original_adapter = typesafe.SystemOneAdapter

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            monkeypatch.setattr(
                typesafe,
                "SystemOneAdapter",
                lambda provider, key: original_adapter(provider, key, client=client),
            )
            await reflect_async(
                state,
                [],
                current_request="Execute",
                task_context=task_context,
                model="gpt-6-sol",
                max_tokens=128,
            )

    asyncio.run(run())
    assert len(requests) == 1
    assert "[truncated:" in requests[0]["state"]["cognitive_state"]
    assert requests[0]["state"]["retained_task_context"] == task_context
    assert "Correction: multiplier 3." in task_context
