"""Regression tests for prompt_toolkit prompt session key bindings."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from core.cli.prompt_session import _apply_toolbar_visibility, _build_prompt_session


def _binding_keys(binding: Any) -> tuple[str, ...]:
    return tuple(str(getattr(key, "value", key)) for key in binding.keys)


def _handler_names(key_bindings: Any) -> set[str]:
    return {binding.handler.__name__ for binding in key_bindings.bindings}


def _find_binding(key_bindings: Any, *keys: str) -> Any:
    expected = tuple(keys)
    for binding in key_bindings.bindings:
        binding_keys = _binding_keys(binding)
        if binding_keys == expected or (expected == ("<any>",) and binding_keys == ("Keys.Any",)):
            return binding
    raise AssertionError(f"missing key binding: {expected}")


def test_prompt_session_any_binding_inserts_cjk_and_invalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakePromptSession:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("prompt_toolkit.PromptSession", FakePromptSession)
    monkeypatch.setattr("prompt_toolkit.history.FileHistory", lambda path: path)

    _build_prompt_session()

    key_bindings = captured["key_bindings"]
    any_binding = _find_binding(key_bindings, "<any>")

    current_buffer = MagicMock()
    app = MagicMock()
    event = SimpleNamespace(
        data="가",
        key_sequence=[SimpleNamespace(key="가")],
        current_buffer=current_buffer,
        app=app,
    )

    any_binding.handler(event)

    current_buffer.insert_text.assert_called_once_with("가")
    app.invalidate.assert_called_once_with()


def test_prompt_session_preserves_specific_edit_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakePromptSession:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("prompt_toolkit.PromptSession", FakePromptSession)
    monkeypatch.setattr("prompt_toolkit.history.FileHistory", lambda path: path)

    _build_prompt_session()

    key_bindings = captured["key_bindings"]
    assert {
        "_enter",
        "_newline",
        "_backspace",
        "_delete",
        "_insert_printable",
    } <= _handler_names(key_bindings)


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ("", ""),
        ("\x1b", "escape"),
        ("\x1b[D", "left"),
    ],
)
def test_prompt_session_any_binding_ignores_non_printable_keys(
    monkeypatch: pytest.MonkeyPatch,
    data: str,
    key: str,
) -> None:
    captured: dict[str, Any] = {}

    class FakePromptSession:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("prompt_toolkit.PromptSession", FakePromptSession)
    monkeypatch.setattr("prompt_toolkit.history.FileHistory", lambda path: path)

    _build_prompt_session()

    any_binding = _find_binding(captured["key_bindings"], "<any>")
    current_buffer = MagicMock()
    app = MagicMock()
    event = SimpleNamespace(
        data=data,
        key_sequence=[SimpleNamespace(key=key)],
        current_buffer=current_buffer,
        app=app,
    )

    any_binding.handler(event)

    current_buffer.insert_text.assert_not_called()
    app.invalidate.assert_not_called()


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
