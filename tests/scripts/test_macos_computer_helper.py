"""Cross-platform contract checks for the macOS computer-use helper source."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "macos" / "geode_computer_helper.swift"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_keyboard_events_use_the_login_session_source() -> None:
    source = _source()
    assert "func loginSessionEventSource() -> CGEventSource" in source
    assert "CGEventSource(stateID: .combinedSessionState)" in source
    assert "keyboardEventSource: nil" not in source


def test_unicode_input_posts_complete_grapheme_buffers() -> None:
    source = _source()
    assert "for character in text" in source
    assert "Array(String(character).utf16)" in source
    assert "stringLength: buffer.count" in source
    assert "for unit in text.utf16" not in source


def test_mouse_move_checks_dispatch_and_postcondition() -> None:
    source = _source()
    assert "let warpError = CGWarpMouseCursorPosition(point)" in source
    assert "guard warpError == .success" in source
    assert "mouse move postcondition failed" in source
    assert source.count("CGWarpMouseCursorPosition(") == 1
    assert source.count("warpCursor(to:") >= 2
    assert 'response["postcondition_verified"] = true' in source


def test_mutating_actions_fail_closed_on_permission_or_event_creation() -> None:
    source = _source()
    assert "mutatingActions.contains(action), !AXIsProcessTrusted()" in source
    assert 'fail("failed to create a mouse event", type: "permission")' in source
    assert 'fail("failed to create a scroll event", type: "permission")' in source
    assert "event?.post" not in source
    assert "down?.post" not in source
    assert "up?.post" not in source


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None,
    reason="Swift/CoreGraphics typecheck requires a macOS toolchain",
)
def test_swift_helper_typechecks_on_macos() -> None:
    swiftc = shutil.which("swiftc")
    assert swiftc is not None
    subprocess.run(  # noqa: S603 - resolved absolute compiler path; no shell
        [
            swiftc,
            "-typecheck",
            str(SOURCE),
            "-framework",
            "AppKit",
            "-framework",
            "ApplicationServices",
            "-framework",
            "CoreGraphics",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
