"""Reflection settings and cadence on a real loop; external LLM calls are isolated."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any
from unittest.mock import create_autospec

import pytest
from core.agent.cognitive_state import CognitiveState
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig, _reflection
from core.agent.tool_executor import ToolExecutor
from core.config import _TOML_TO_SETTINGS, settings
from core.config._settings import Settings
from core.config.policy_source import EMPTY_POLICY_SOURCES
from core.hooks import HookCorrelation
from pydantic import ValidationError


def test_settings_carries_cognitive_reflection_interval() -> None:
    assert Settings.model_fields["cognitive_reflection_interval"].default == 1


def test_toml_map_carries_reflection_interval_key() -> None:
    assert _TOML_TO_SETTINGS["cognitive.reflection_interval"] == "cognitive_reflection_interval"


@pytest.mark.parametrize("interval", [0, -1])
def test_settings_rejects_interval_below_one(interval: int) -> None:
    with pytest.raises(ValidationError):
        Settings(cognitive_reflection_interval=interval)


def test_settings_normalizes_valid_legacy_interval_to_every_round() -> None:
    assert Settings(cognitive_reflection_interval=3).cognitive_reflection_interval == 1


def test_settings_carries_reflection_adaptive_default_false() -> None:
    assert Settings.model_fields["cognitive_reflection_adaptive"].default is False


def test_toml_map_carries_reflection_adaptive_key() -> None:
    assert _TOML_TO_SETTINGS["cognitive.reflection_adaptive"] == "cognitive_reflection_adaptive"


@pytest.fixture
def loop(monkeypatch: pytest.MonkeyPatch) -> AgenticLoop:
    # Existing autouse fixtures isolate state/auth; explicit source avoids inference.
    monkeypatch.setattr(settings, "cognitive_reflection_enabled", True)
    monkeypatch.setattr(settings, "cognitive_reflection_adaptive", False)
    monkeypatch.setattr(settings, "cognitive_reflection_model", "")
    return AgenticLoop(
        ConversationContext(),
        ToolExecutor(),
        config=AgenticLoopConfig(source="payg", session_id="reflection-cost-gate"),
        model="claude-sonnet-4-6",
        quiet=True,
    )


@pytest.fixture
def reflection_call(monkeypatch: pytest.MonkeyPatch) -> Any:
    call = create_autospec(_reflection.reflect_async, return_value=None)
    monkeypatch.setattr(_reflection, "reflect_async", call)
    return call


@pytest.mark.parametrize(
    ("interval", "adaptive", "confidence", "rounds"),
    [
        pytest.param(1, False, None, 5, id="every-round"),
        pytest.param(3, False, None, 10, id="legacy-every-third"),
        pytest.param(5, False, None, 11, id="legacy-every-fifth"),
        pytest.param(30, False, None, 30, id="thirty-round-session"),
        pytest.param(0, False, None, 3, id="defensive-zero"),
        pytest.param(-1, False, None, 3, id="defensive-negative"),
        pytest.param(3, True, 0.9, 10, id="legacy-high-confidence-stretch"),
        pytest.param(5, True, 0.2, 5, id="low-confidence"),
        pytest.param(3, True, 0.6, 7, id="mid-confidence"),
        pytest.param(3, True, None, 4, id="unknown-confidence"),
        pytest.param(3, False, 0.95, 7, id="adaptive-disabled"),
    ],
)
def test_reflection_cadence(
    monkeypatch: pytest.MonkeyPatch,
    loop: AgenticLoop,
    reflection_call: Any,
    interval: int,
    adaptive: bool,
    confidence: float | None,
    rounds: int,
) -> None:
    monkeypatch.setattr(settings, "cognitive_reflection_interval", interval)
    monkeypatch.setattr(settings, "cognitive_reflection_adaptive", adaptive)
    loop.cognitive_state.confidence = confidence
    observed: list[int] = []

    def record_round(state: CognitiveState, *_args: Any, **_kwargs: Any) -> None:
        observed.append(state.round_count)

    reflection_call.side_effect = record_round

    async def run_rounds() -> None:
        for _round in range(rounds):
            loop.cognitive_state.record_round(action="synthetic", observation="synthetic")
            await loop._maybe_reflect([])

    asyncio.run(run_rounds())
    # Legacy values remain a migration input, not an alternate cadence.
    assert observed == list(range(1, rounds + 1))
    assert reflection_call.await_count == rounds
    for call in reflection_call.await_args_list:
        assert call.kwargs["policy_sources"] is EMPTY_POLICY_SOURCES
        assert call.kwargs["middleware_registry"] is loop.executor.middleware_registry
        assert call.kwargs["correlation"] == asdict(
            HookCorrelation(session_id="reflection-cost-gate", session_generation=1)
        )


def test_legacy_disabled_toggle_cannot_skip_round_reflection(
    monkeypatch: pytest.MonkeyPatch, loop: AgenticLoop, reflection_call: Any
) -> None:
    monkeypatch.setattr(settings, "cognitive_reflection_enabled", False)
    # The runtime no longer reads the deprecated cadence fields.
    monkeypatch.setattr(settings, "cognitive_reflection_interval", None)
    loop.cognitive_state.record_round(action="synthetic", observation="synthetic")
    asyncio.run(loop._maybe_reflect([]))
    reflection_call.assert_awaited_once()
