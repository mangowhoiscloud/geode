"""Regression tests for prompt_toolkit prompt session key bindings.

Pins the 2026-06-11 input-UI contract:

* NO ``<any>`` / Backspace / Delete custom bindings — the previous CJK
  repaint patch (#1180) routed every unmatched key through a printable-only
  filter, turning arrows / Ctrl-A/E / history keys into no-ops.
* Wide-char repaint sync lives on ``Buffer.on_text_changed`` instead.
* A transient prompt_toolkit failure no longer disables line editing for
  the whole session; only 3 consecutive failures do.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import core.cli.prompt_session as prompt_session_mod
import pytest
from core.cli.prompt_session import (
    _apply_toolbar_visibility,
    _build_prompt_session,
    _invalidate_on_text_changed,
    _read_multiline_input,
)


def _binding_keys(binding: Any) -> tuple[str, ...]:
    return tuple(str(getattr(key, "value", key)) for key in binding.keys)


def _handler_names(key_bindings: Any) -> set[str]:
    return {binding.handler.__name__ for binding in key_bindings.bindings}


class _FakeEvent(list):
    """Mimics prompt_toolkit's Event: ``+= handler`` appends the handler."""

    def __iadd__(self, handler: Any) -> _FakeEvent:
        self.append(handler)
        return self


class _FakeBuffer:
    """Stands in for prompt_toolkit's default_buffer (`on_text_changed +=`)."""

    def __init__(self) -> None:
        self.on_text_changed = _FakeEvent()


class _FakePromptSession:
    captured: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).captured = dict(kwargs)
        self.default_buffer = _FakeBuffer()


def _build_with_fakes(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr("prompt_toolkit.PromptSession", _FakePromptSession)
    monkeypatch.setattr("prompt_toolkit.history.FileHistory", lambda path: path)
    return _build_prompt_session()


def test_prompt_session_keeps_default_editing_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only enter / esc+enter are custom; everything else stays DEFAULT.

    A custom ``<any>`` (Keys.Any) binding shadows prompt_toolkit's default
    bindings for every unmatched key, so arrows stop moving the cursor.
    """
    _build_with_fakes(monkeypatch)

    key_bindings = _FakePromptSession.captured["key_bindings"]
    handler_names = _handler_names(key_bindings)
    assert handler_names == {"_enter", "_newline"}

    for binding in key_bindings.bindings:
        assert "Keys.Any" not in _binding_keys(binding), (
            "<any> binding reintroduced — this swallows arrow keys; "
            "use Buffer.on_text_changed for repaint sync instead"
        )


def test_prompt_session_attaches_text_changed_repaint_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wide-char repaint sync is a buffer hook, not a key binding."""
    session = _build_with_fakes(monkeypatch)

    assert _invalidate_on_text_changed in session.default_buffer.on_text_changed


def test_prompt_session_uses_named_geode_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """The idle prompt names the REPL instead of showing a bare chevron."""
    _build_with_fakes(monkeypatch)

    assert "geode" in str(_FakePromptSession.captured["message"])


def test_invalidate_on_text_changed_invalidates_running_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = MagicMock()
    monkeypatch.setattr("prompt_toolkit.application.current.get_app", lambda: app)

    _invalidate_on_text_changed(MagicMock())

    app.invalidate.assert_called_once_with()


def _fail_then_succeed_session(fail_times: int) -> Any:
    """A fake session whose prompt() raises `fail_times` times, then returns."""
    state = {"calls": 0}

    class _Session:
        bottom_toolbar: Any = None

        def prompt(self) -> str:
            state["calls"] += 1
            if state["calls"] <= fail_times:
                raise RuntimeError("transient renderer error")
            return "ok"

    return _Session()


def _patch_read_input_collaborators(monkeypatch: pytest.MonkeyPatch, session: Any) -> MagicMock:
    monkeypatch.setattr(prompt_session_mod, "_prompt_session", session)
    monkeypatch.setattr(prompt_session_mod, "_prompt_failures", 0)
    monkeypatch.setattr(prompt_session_mod, "_get_prompt_session", lambda: session)
    monkeypatch.setattr(prompt_session_mod, "_apply_toolbar_visibility", lambda s: None)
    monkeypatch.setattr(prompt_session_mod, "_drain_stdin", lambda: None)
    monkeypatch.setattr(prompt_session_mod, "_restore_terminal", lambda: None)
    fallback_input = MagicMock(return_value="fallback")
    monkeypatch.setattr(prompt_session_mod.console, "input", fallback_input)
    return fallback_input


def test_transient_prompt_failure_does_not_disable_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One renderer hiccup must not downgrade the whole session to console.input."""
    session = _fail_then_succeed_session(fail_times=1)
    fallback_input = _patch_read_input_collaborators(monkeypatch, session)

    first = _read_multiline_input("> ")
    assert first == "fallback"
    assert fallback_input.call_count == 1
    # Not the permanent-disable sentinel: rebuilt lazily on the next call.
    assert prompt_session_mod._prompt_session is not False

    second = _read_multiline_input("> ")
    assert second == "ok"
    assert prompt_session_mod._prompt_failures == 0


def test_three_consecutive_failures_disable_prompt_toolkit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _fail_then_succeed_session(fail_times=10)
    _patch_read_input_collaborators(monkeypatch, session)

    for _round in range(3):
        assert _read_multiline_input("> ") == "fallback"

    assert prompt_session_mod._prompt_session is False
    assert prompt_session_mod._prompt_failures == 3


def test_toolbar_hidden_when_banner_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty banner (render -> None) hides the bar by un-setting the attribute.

    prompt_toolkit keys bar visibility on ``bottom_toolbar is not None``,
    not on the render return, so an empty render must clear the attribute
    to drop the cold-start "white line" (1-row reverse window).
    """

    def _empty_render() -> Any:
        return None

    monkeypatch.setattr("core.cli.prompt_session._toolbar_render", _empty_render)
    session = SimpleNamespace(bottom_toolbar=_empty_render)

    _apply_toolbar_visibility(session)

    assert session.bottom_toolbar is None


def test_toolbar_shown_when_banner_has_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populated banner (render -> truthy) restores the render callable."""

    def _content_render() -> Any:
        return "⬤ green"

    monkeypatch.setattr("core.cli.prompt_session._toolbar_render", _content_render)
    session = SimpleNamespace(bottom_toolbar=None)

    _apply_toolbar_visibility(session)

    assert session.bottom_toolbar is _content_render


def test_toolbar_visibility_noop_when_unstashed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No stashed render callable -> leave the attribute untouched (graceful)."""
    monkeypatch.setattr("core.cli.prompt_session._toolbar_render", None)
    sentinel = object()
    session = SimpleNamespace(bottom_toolbar=sentinel)

    _apply_toolbar_visibility(session)

    assert session.bottom_toolbar is sentinel
