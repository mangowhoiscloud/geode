"""M5 — /model picker surfaces login-state.

Pre-fix the picker rendered every entry in ``MODEL_PROFILES`` regardless
of whether the user had registered a credential for that provider.
Selecting an unauthenticated model bounced off the ``_check_provider_key``
warning on the next LLM call — by then the settings had already shifted,
so the user saw a confusing "model switched, but it doesn't work" state.

Contracts pinned here:

1. ``commands._state.model_available(model_id)`` delegates to
   ``resolve_routing(model_id)`` and is False when no credential route
   exists.
2. The interactive picker tuple carries an ``available`` flag as the
   5th element. ``pick_model_and_effort`` returns ``cancelled=True``
   when the user presses Enter on an unavailable entry, leaving the
   current settings untouched.
3. ``/model <name>`` for an unauthenticated provider prints a
   "login required" hint *before* applying the change.
4. Non-interactive ``/model`` (no-tty) appends ``(login required)`` to
   unavailable rows so a curl-driven caller sees the same status.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Contract 1 — model_available helper
# ---------------------------------------------------------------------------


def test_model_available_true_when_resolve_routing_returns_target() -> None:
    """A non-None ``RoutingTarget`` means the model has a credential route."""
    from core.cli.commands import _state

    with patch(
        "core.llm.strategies.plan_registry.resolve_routing",
        return_value=MagicMock(),  # any non-None RoutingTarget stand-in
    ):
        assert _state.model_available("claude-opus-4-7") is True


def test_model_available_false_when_resolve_routing_returns_none() -> None:
    """A None RoutingTarget means no credential route — picker should
    flag the entry as (login required)."""
    from core.cli.commands import _state

    with patch("core.llm.strategies.plan_registry.resolve_routing", return_value=None):
        assert _state.model_available("claude-opus-4-7") is False


def test_model_available_swallows_routing_exceptions() -> None:
    """Defensive: a broken plan registry must not lock the picker."""
    from core.cli.commands import _state

    with patch(
        "core.llm.strategies.plan_registry.resolve_routing",
        side_effect=RuntimeError("plan registry unavailable"),
    ):
        assert _state.model_available("claude-opus-4-7") is False


# ---------------------------------------------------------------------------
# Contract 2 — picker tuple carries 5th 'available' element
# ---------------------------------------------------------------------------


def test_picker_unavailable_enter_returns_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enter on an unavailable row must not mutate the settings —
    return cancelled=True so the caller surfaces a login hint."""
    from core.cli import effort_picker

    profiles: list[tuple[str, str, str, str, bool, str | None]] = [
        ("claude-opus-4-7", "anthropic", "Opus 4.7", "$$$", True, None),
        ("gpt-5.5", "openai-codex", "GPT-5.5", "$$", False, None),  # unavailable
    ]

    keys = iter([effort_picker._KEY_DOWN, effort_picker._KEY_ENTER])

    def fake_read_key() -> str:
        return next(keys)

    monkeypatch.setattr(effort_picker, "_read_key", fake_read_key)
    monkeypatch.setattr(effort_picker, "_render", lambda *a, **k: 0)
    monkeypatch.setattr(effort_picker, "_clear_lines", lambda n: None)

    result = effort_picker.pick_model_and_effort(
        profiles,
        current_model="claude-opus-4-7",
        current_effort="high",
    )
    assert result.cancelled is True, (
        "Enter on an unavailable model must return cancelled=True — "
        "otherwise settings shift to a model the next call would reject."
    )
    assert result.model_id == "claude-opus-4-7", "current model must stay unchanged"


def test_picker_available_enter_returns_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity — Enter on an available row still works."""
    from core.cli import effort_picker

    profiles: list[tuple[str, str, str, str, bool, str | None]] = [
        ("claude-opus-4-7", "anthropic", "Opus 4.7", "$$$", True, None),
        ("claude-sonnet-4-6", "anthropic", "Sonnet 4.6", "$$", True, None),
    ]

    keys = iter([effort_picker._KEY_DOWN, effort_picker._KEY_ENTER])

    def fake_read_key() -> str:
        return next(keys)

    monkeypatch.setattr(effort_picker, "_read_key", fake_read_key)
    monkeypatch.setattr(effort_picker, "_render", lambda *a, **k: 0)
    monkeypatch.setattr(effort_picker, "_clear_lines", lambda n: None)

    result = effort_picker.pick_model_and_effort(
        profiles,
        current_model="claude-opus-4-7",
        current_effort="high",
    )
    assert result.cancelled is False
    assert result.model_id == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Contract 3 — /model <name> for unauthenticated provider prints hint
# ---------------------------------------------------------------------------


def test_cmd_model_explicit_name_unauthenticated_prints_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``/model claude-opus-4-7`` when no anthropic profile registered
    must emit the (login required) hint and skip ``_apply_model``."""
    from core.cli.commands import model as _model_mod

    apply_called: list[Any] = []

    def fake_apply(profile, effort=None):  # type: ignore[no-untyped-def]
        apply_called.append(profile)

    with (
        patch("core.cli.commands.model.model_available", return_value=False),
        patch("core.cli.commands.model._apply_model", side_effect=fake_apply),
    ):
        _model_mod.cmd_model("claude-opus-4-7")

    out = capsys.readouterr().out
    assert "has no authenticated profile" in out, (
        f"login-required hint missing from output: {out!r}"
    )
    assert apply_called == [], (
        "_apply_model must NOT run when the model is unauthenticated — "
        "otherwise settings shift before the user sees the hint."
    )
