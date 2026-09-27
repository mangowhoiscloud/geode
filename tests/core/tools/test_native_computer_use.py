"""Native action translation validates inputs without touching a desktop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from core.tools.computer_use import ComputerUseHarness, execute_native_computer_use


@pytest.mark.parametrize(
    "action,params,expected_action,expected",
    [
        ("left_click", {"coordinate": [10, 20]}, "left_click", {"x": 10, "y": 20}),
        ("mouse_move", {"coordinate": [30, 40]}, "move", {"x": 30, "y": 40}),
        (
            "left_click_drag",
            {"start_coordinate": [10, 20], "coordinate": [30, 40]},
            "drag",
            {"start_x": 10, "start_y": 20, "end_x": 30, "end_y": 40},
        ),
        (
            "scroll",
            {"coordinate": [10, 20], "scroll_direction": "left", "scroll_amount": 4},
            "scroll",
            {"x": 10, "y": 20, "direction": "left", "amount": 4},
        ),
        ("wait", {"duration": 0.25}, "wait", {"ms": 250}),
        ("wait", {"ms": 250}, "wait", {"ms": 250}),
        ("wait", {"duration": 0.25, "ms": "ignored"}, "wait", {"ms": 250}),
        ("key", {"text": "Return"}, "key", {"keys": "Return"}),
    ],
)
def test_native_parameters_match_harness(action, params, expected_action, expected) -> None:
    harness = MagicMock(spec=ComputerUseHarness)
    harness.aexecute = AsyncMock(return_value={"result": "success"})
    asyncio.run(execute_native_computer_use(harness, action=action, **params))
    harness.aexecute.assert_awaited_once_with(expected_action, **expected)


@pytest.mark.parametrize(
    "cursor",
    [
        {"observation": {"cursor": {"x": 77, "y": 88}}},
        {"cursor": [77, 88]},
    ],
)
def test_omitted_click_coordinate_uses_observed_cursor(cursor) -> None:
    harness = MagicMock(spec=ComputerUseHarness)
    harness.aexecute = AsyncMock(side_effect=[cursor, {"result": "success"}])
    asyncio.run(execute_native_computer_use(harness, action="left_click"))
    assert harness.aexecute.await_args_list == [
        call("cursor_position"),
        call("left_click", x=77, y=88),
    ]


def test_missing_cursor_fails_without_clicking_origin() -> None:
    harness = MagicMock(spec=ComputerUseHarness)
    harness.aexecute = AsyncMock(return_value={"result": "success"})
    result = asyncio.run(execute_native_computer_use(harness, action="left_click"))
    assert result["error_type"] == "validation"
    harness.aexecute.assert_awaited_once_with("cursor_position")


@pytest.mark.parametrize(
    "action,params",
    [
        ("zoom", {"region": [1, 2, 3, 4]}),
        ("hold_key", {"text": "shift", "duration": 1}),
        ("left_mouse_down", {}),
        ("left_mouse_up", {}),
        ("mouse_move", {}),
        ("left_click", {"coordinate": [True, 0]}),
        ("left_click", {"coordinate": [-1, 0]}),
        ("left_click", {"coordinate": [1280, 0]}),
        ("left_click", {"coordinate": [1]}),
        ("left_click", {"coordinate": [1, 2], "text": "shift"}),
        ("left_click_drag", {"coordinate": [1, 2]}),
        ("scroll", {"scroll_direction": "diagonal"}),
        ("scroll", {"scroll_amount": -1}),
        ("key", {"text": "Tab", "repeat": 0}),
        ("key", {"text": "Tab", "repeat": 101}),
        ("wait", {"duration": float("nan")}),
        ("wait", {"duration": 10**1000}),
        ("wait", {"ms": 10**1000}),
        ("wait", {"duration": 301}),
    ],
)
def test_invalid_native_actions_have_no_desktop_effects(action, params) -> None:
    harness = MagicMock(spec=ComputerUseHarness)
    harness.aexecute = AsyncMock()
    result = asyncio.run(execute_native_computer_use(harness, action=action, **params))
    assert result["error_type"] == "validation"
    harness.aexecute.assert_not_awaited()


def test_repeat_stops_at_first_failure() -> None:
    harness = MagicMock(spec=ComputerUseHarness)
    harness.aexecute = AsyncMock(side_effect=[{"result": "success"}, {"error": "failed"}])
    result = asyncio.run(execute_native_computer_use(harness, action="key", text="Tab", repeat=3))
    assert result == {"error": "failed"}
    assert harness.aexecute.await_args_list == [call("key", keys="Tab")] * 2


def test_horizontal_scroll_does_not_add_vertical_scroll() -> None:
    harness = ComputerUseHarness()
    pag = MagicMock()
    with (
        patch.object(harness, "_ensure_pyautogui", return_value=pag),
        patch.object(harness, "screenshot", return_value="jpeg"),
    ):
        harness.scroll(10, 20, "left", 3)
    pag.hscroll.assert_called_once_with(-3)
    pag.scroll.assert_not_called()


def test_helper_timeout_covers_valid_native_wait() -> None:
    harness = ComputerUseHarness()
    with patch(
        "core.tools.computer_use._helper_request_sync", return_value={"result": "success"}
    ) as helper:
        harness._helper_execute_sync("wait", {"ms": 300_000})
    assert helper.call_args.kwargs["timeout_s"] == 310
