"""PR-C — reflection cost gate (``cognitive_reflection_interval``).

PR-3 fires 1 LLM call per tool-use round; 30-round sessions paid
30 extra Haiku calls. PR-C adds the ``cognitive_reflection_interval``
setting (default 1 = current behaviour, no regression). When set
to N > 1 the reflection node runs on rounds 1, 1+N, 1+2N, ... so
the first round always sees an LLM-derived belief snapshot and
subsequent calls are thinned to every Nth round.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from core.agent.cognitive_state import CognitiveState

# ---------------------------------------------------------------------------
# Settings field + TOML map
# ---------------------------------------------------------------------------


def test_settings_carries_cognitive_reflection_interval() -> None:
    from core.config._settings import Settings

    fields = Settings.model_fields
    assert "cognitive_reflection_interval" in fields
    assert fields["cognitive_reflection_interval"].default == 1


def test_toml_map_carries_reflection_interval_key() -> None:
    from core.config import _TOML_TO_SETTINGS

    assert _TOML_TO_SETTINGS["cognitive.reflection_interval"] == "cognitive_reflection_interval"


def test_settings_rejects_interval_below_one() -> None:
    """The ``ge=1`` validator must reject ``0`` / negatives so an
    operator can't accidentally disable reflection via the interval
    knob (they should use ``cognitive_reflection_enabled=False``
    explicitly)."""
    from core.config._settings import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(cognitive_reflection_interval=0)


# ---------------------------------------------------------------------------
# _maybe_reflect gate behaviour
# ---------------------------------------------------------------------------


class _Recorder:
    """Captures whether reflect_async was invoked + which round."""

    def __init__(self) -> None:
        self.calls: list[int] = []  # round_count at each call

    async def fake_reflect_async(
        self,
        state: CognitiveState,
        _tool_results: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        provider: str | None = None,
        source: str | None = None,
    ) -> None:
        self.calls.append(state.round_count)


@pytest.fixture
def _stub_reflect_async(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Patch reflect_async in the lazy-imported namespace so
    _maybe_reflect doesn't touch the real LLM path."""
    recorder = _Recorder()
    from core.agent.loop import _reflection

    monkeypatch.setattr(_reflection, "reflect_async", recorder.fake_reflect_async)
    return recorder


def _maybe_reflect_runner(
    state: CognitiveState,
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    *,
    interval: int,
    adaptive: bool = False,
) -> None:
    """Synchronous helper — stamps interval + adaptive knob, runs
    _maybe_reflect. ``adaptive=False`` default keeps the pre-existing
    fixed-interval tests deterministic regardless of state.confidence."""
    from core.config import settings

    object.__setattr__(settings, "cognitive_reflection_interval", interval)
    object.__setattr__(settings, "cognitive_reflection_adaptive", adaptive)

    # Build a minimal stub for AgenticLoop._maybe_reflect — bypass
    # __init__ (which wires the entire runtime). Bind the bound
    # method via descriptor.__get__ so it sees a fake `self` with
    # only the attributes the method touches.
    from core.agent.loop.agent_loop import AgenticLoop

    class _StubSelf:
        cognitive_state = state
        model = "claude-sonnet-4-6"
        _provider = "anthropic"
        _source = "api_key"
        _new_adapter = object()

    bound = AgenticLoop._maybe_reflect.__get__(_StubSelf(), _StubSelf)
    asyncio.run(bound([]))


def test_interval_one_runs_every_round(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """Default ``interval=1`` matches PR-3 behaviour — every round
    triggers reflection."""
    state = CognitiveState()
    for r in range(1, 6):
        state.round_count = r
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=1)
    assert _stub_reflect_async.calls == [1, 2, 3, 4, 5]


def test_interval_three_runs_rounds_one_four_seven(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """``interval=3`` — first round always runs, then every 3rd."""
    state = CognitiveState()
    for r in range(1, 11):
        state.round_count = r
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=3)
    # rounds 1, 4, 7, 10 reflect; 2, 3, 5, 6, 8, 9 skipped
    assert _stub_reflect_async.calls == [1, 4, 7, 10]


def test_interval_five_runs_rounds_one_six_eleven(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    state = CognitiveState()
    for r in range(1, 12):
        state.round_count = r
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=5)
    assert _stub_reflect_async.calls == [1, 6, 11]


def test_interval_30_session_only_runs_first(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """User-supplied scenario — 30-round session with interval=30
    should fire ONCE on round 1, saving 29 LLM calls."""
    state = CognitiveState()
    for r in range(1, 31):
        state.round_count = r
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=30)
    assert _stub_reflect_async.calls == [1]


def test_interval_treats_zero_or_negative_as_one(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """Defensive — even if some downstream sets the field to 0
    (bypassing the pydantic validator via ``object.__setattr__``),
    ``_maybe_reflect`` clamps to 1 so reflection still runs (no
    silent disable)."""
    state = CognitiveState()
    state.round_count = 1
    _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=0)
    assert _stub_reflect_async.calls == [1]


def test_disabled_toggle_short_circuits_before_interval_check(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """If ``cognitive_reflection_enabled=False`` the interval gate is
    irrelevant. The enabled toggle must win."""
    from core.config import settings

    state = CognitiveState()
    state.round_count = 1
    object.__setattr__(settings, "cognitive_reflection_enabled", False)
    try:
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=1)
        assert _stub_reflect_async.calls == []
    finally:
        object.__setattr__(settings, "cognitive_reflection_enabled", True)


# ---------------------------------------------------------------------------
# _maybe_reflect source pin — the gate must be IN the method body
# ---------------------------------------------------------------------------


def test_maybe_reflect_reads_interval_setting() -> None:
    """Pin that the gate is implemented in ``_maybe_reflect`` body —
    a refactor that drops the modulo check would surface here, not
    in production behaviour."""
    from core.agent.loop.agent_loop import AgenticLoop

    src = inspect.getsource(AgenticLoop._maybe_reflect)
    assert "cognitive_reflection_interval" in src
    assert "round_count" in src
    assert "interval" in src
    # The "first round always runs" property is implemented via
    # ``(round_count - 1) % interval == 0`` — pin the modulo form so
    # a future refactor doesn't accidentally flip to ``round_count %
    # interval`` (which would skip round 1).
    assert "(round_count - 1) % interval" in src or "(round_count-1) % interval" in src


# ---------------------------------------------------------------------------
# Confidence-adaptive cadence (GAP 1 — confidence consumers)
# ---------------------------------------------------------------------------


def test_settings_carries_reflection_adaptive_default_true() -> None:
    from core.config._settings import Settings

    fields = Settings.model_fields
    assert "cognitive_reflection_adaptive" in fields
    assert fields["cognitive_reflection_adaptive"].default is True


def test_toml_map_carries_reflection_adaptive_key() -> None:
    from core.config import _TOML_TO_SETTINGS

    assert _TOML_TO_SETTINGS["cognitive.reflection_adaptive"] == "cognitive_reflection_adaptive"


def test_high_confidence_stretches_interval(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """confidence >= 0.8 doubles the effective interval (3 → 6):
    reflections land on rounds 1, 7 instead of 1, 4, 7, 10."""
    state = CognitiveState()
    state.confidence = 0.9
    for r in range(1, 11):
        state.round_count = r
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=3, adaptive=True)
    assert _stub_reflect_async.calls == [1, 7]


def test_low_confidence_forces_every_round(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """confidence < 0.4 collapses the interval to 1 — belief updates
    every round while the loop is unsure."""
    state = CognitiveState()
    state.confidence = 0.2
    for r in range(1, 6):
        state.round_count = r
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=5, adaptive=True)
    assert _stub_reflect_async.calls == [1, 2, 3, 4, 5]


def test_mid_confidence_keeps_base_interval(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """0.4 <= confidence < 0.8 — neither stretch nor force."""
    state = CognitiveState()
    state.confidence = 0.6
    for r in range(1, 8):
        state.round_count = r
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=3, adaptive=True)
    assert _stub_reflect_async.calls == [1, 4, 7]


def test_confidence_none_uses_base_interval(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """No reflection has run yet (confidence None) — base interval."""
    state = CognitiveState()
    assert state.confidence is None
    for r in range(1, 5):
        state.round_count = r
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=3, adaptive=True)
    assert _stub_reflect_async.calls == [1, 4]


def test_adaptive_off_ignores_confidence(
    monkeypatch: pytest.MonkeyPatch, _stub_reflect_async: _Recorder
) -> None:
    """cognitive_reflection_adaptive=False — fixed interval wins even
    at high confidence."""
    state = CognitiveState()
    state.confidence = 0.95
    for r in range(1, 8):
        state.round_count = r
        _maybe_reflect_runner(state, monkeypatch, _stub_reflect_async, interval=3, adaptive=False)
    assert _stub_reflect_async.calls == [1, 4, 7]
