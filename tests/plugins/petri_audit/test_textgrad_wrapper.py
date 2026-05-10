"""TextGrad wrapper M4 enforcement tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from plugins.petri_audit.textgrad_wrapper import (
    MAX_TEXTGRAD_DEPTH,
    TextGradError,
    TextGradResult,
    apply_textual_gradient,
    guard_depth,
)

# ---------------------------------------------------------------------------
# guard_depth — direct M4 gate
# ---------------------------------------------------------------------------


def test_guard_depth_one_passes() -> None:
    guard_depth(1)


def test_guard_depth_zero_or_negative_raises() -> None:
    with pytest.raises(TextGradError, match="depth must be >= 1"):
        guard_depth(0)
    with pytest.raises(TextGradError, match="depth must be >= 1"):
        guard_depth(-3)


def test_guard_depth_greater_than_one_raises() -> None:
    with pytest.raises(TextGradError, match=r"M4 violation.*depth=2"):
        guard_depth(2)
    with pytest.raises(TextGradError, match=r"M4 violation.*depth=5"):
        guard_depth(5)


def test_guard_depth_chained_raises() -> None:
    with pytest.raises(TextGradError, match="chained=True is forbidden"):
        guard_depth(1, chained=True)


def test_max_depth_constant() -> None:
    assert MAX_TEXTGRAD_DEPTH == 1


# ---------------------------------------------------------------------------
# apply_textual_gradient — input validation
# ---------------------------------------------------------------------------


def test_empty_prompt_raises() -> None:
    with pytest.raises(TextGradError, match="prompt must not be empty"):
        apply_textual_gradient("", "rationale")


def test_empty_rationale_raises() -> None:
    with pytest.raises(TextGradError, match="judge_rationale must not be empty"):
        apply_textual_gradient("prompt", "")


def test_depth_two_raises_via_apply() -> None:
    with pytest.raises(TextGradError, match="M4 violation"):
        apply_textual_gradient("prompt", "rationale", depth=2)


def test_chained_true_raises_via_apply() -> None:
    with pytest.raises(TextGradError, match="chained=True is forbidden"):
        apply_textual_gradient("prompt", "rationale", chained=True)


# ---------------------------------------------------------------------------
# Dry-run path — no TextGrad import
# ---------------------------------------------------------------------------


def test_dry_run_returns_unchanged_prompt() -> None:
    result = apply_textual_gradient("orig", "rationale", dry_run=True)
    assert isinstance(result, TextGradResult)
    assert result.dry_run is True
    assert result.original_prompt == "orig"
    assert result.patched_prompt == "orig"
    assert result.depth == 1
    assert "dry-run" in result.notes[0]


def test_dry_run_to_dict_shape() -> None:
    result = apply_textual_gradient("orig", "rationale", dry_run=True)
    d = result.to_dict()
    expected = {
        "original_prompt",
        "patched_prompt",
        "judge_rationale",
        "depth",
        "dry_run",
        "notes",
    }
    assert set(d.keys()) == expected


# ---------------------------------------------------------------------------
# Live path — mocked TextGrad import
# ---------------------------------------------------------------------------


def test_live_without_reason_extra_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "textgrad", None)
    with pytest.raises(TextGradError, match=r"\[reason\] extra"):
        apply_textual_gradient("orig", "rationale", dry_run=False)


def test_live_calls_backward_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke-test the live path: TextGrad's API is mocked so nothing real happens."""
    captured: dict[str, object] = {"backward_calls": 0}

    class _Var:
        def __init__(self, value: str, **_kwargs: object) -> None:
            self.value = value

    class _Loss:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __call__(self, prompt_var: _Var, _feedback: _Var) -> _Loss:
            self._prompt = prompt_var
            return self

        def backward(self) -> None:
            captured["backward_calls"] = int(captured["backward_calls"]) + 1
            self._prompt.value = self._prompt.value + " (patched)"

    fake_tg = SimpleNamespace(
        get_engine=lambda: SimpleNamespace(),
        Variable=_Var,
        TextLoss=_Loss,
    )
    monkeypatch.setitem(sys.modules, "textgrad", fake_tg)

    result = apply_textual_gradient("orig", "rationale", depth=1, dry_run=False)
    assert captured["backward_calls"] == 1
    assert result.patched_prompt == "orig (patched)"
    assert result.dry_run is False
