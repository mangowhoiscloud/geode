"""ui_probe — macOS accessibility (AX) structured perception.

The live pyobjc AX walk is unverified (needs a live macOS Accessibility
session); these tests pin the verified deliverable — the compact readout and
the availability/not-found/failure state machine — by mocking the AX seams
(``_ax_ready`` / ``_resolve_pid`` / ``_collect_ax_tree``).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core.tools import ui_probe as up
from core.tools.ui_probe import UiProbeTool, _format_element

_ELEMENTS = [
    {
        "depth": 0,
        "role": "AXWindow",
        "title": "Doc",
        "value": None,
        "enabled": True,
        "x": 0,
        "y": 0,
        "w": 800,
        "h": 600,
    },
    {
        "depth": 1,
        "role": "AXButton",
        "title": "Save",
        "value": None,
        "enabled": True,
        "x": 100,
        "y": 40,
        "w": 60,
        "h": 20,
    },
    {
        "depth": 1,
        "role": "AXTextField",
        "title": None,
        "desc": "search",
        "value": "hi",
        "enabled": False,
        "x": 200,
        "y": 40,
        "w": 120,
        "h": 20,
    },
]


def _run(coro: Any) -> dict[str, Any]:
    return asyncio.run(coro)


def test_format_element_center_and_flags() -> None:
    line = _format_element(_ELEMENTS[2])
    assert "AXTextField" in line
    assert "search" in line  # falls back to desc when title is absent
    assert "'hi'" in line  # value shown
    assert "[disabled]" in line
    assert "@(260,50)" in line  # center = x+w/2, y+h/2


def test_happy_path_returns_compact_readout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(up, "_ax_ready", lambda: (True, ""))
    monkeypatch.setattr(up, "_resolve_pid", lambda _name: 4242)
    monkeypatch.setattr(up, "_collect_ax_tree", lambda _pid, _d, _m: _ELEMENTS)
    out = _run(UiProbeTool().aexecute(app_name="Doc"))["result"]
    assert out["pid"] == 4242
    assert out["element_count"] == 3
    assert out["coord_space"] == "ax_points"
    assert "AXButton" in out["elements"] and "Save" in out["elements"]


def test_unavailable_is_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(up, "_ax_ready", lambda: (False, "install pyobjc..."))
    out = _run(UiProbeTool().aexecute())
    assert out["error_type"] == "dependency"
    assert "install pyobjc" in out["hint"]


def test_no_app_found_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(up, "_ax_ready", lambda: (True, ""))
    monkeypatch.setattr(up, "_resolve_pid", lambda _name: None)
    out = _run(UiProbeTool().aexecute(app_name="Nope"))
    assert out["error_type"] == "not_found"
    assert "Nope" in out["error"]


def test_enumeration_failure_is_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise RuntimeError("window vanished")

    monkeypatch.setattr(up, "_ax_ready", lambda: (True, ""))
    monkeypatch.setattr(up, "_resolve_pid", lambda _name: 7)
    monkeypatch.setattr(up, "_collect_ax_tree", _boom)
    out = _run(UiProbeTool().aexecute())
    assert out["error_type"] == "internal"
    assert "window vanished" in out["error"]


def test_ax_ready_rejects_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(up.sys, "platform", "linux")
    ready, reason = up._ax_ready()
    assert ready is False
    assert "macOS" in reason
