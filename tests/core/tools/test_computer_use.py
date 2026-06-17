"""Tests for computer-use harness."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.tools.computer_use import ComputerUseHarness


class TestHandlerActionForwarding:
    """The single-tool handler must forward ``action`` positionally WITHOUT
    leaving it in ``kwargs`` — the loop delivers ``{"action": ..., "x": ...}``
    and the pre-fix ``aexecute(action, **kwargs)`` raised "got multiple values
    for argument 'action'" on every non-default call (latent because the tool
    was never live-exercised)."""

    def test_action_not_passed_twice(self) -> None:
        from core.cli.tool_handlers.single_tool import _build_computer_use_handler

        with (
            patch(
                "core.llm.providers.anthropic.is_computer_use_enabled",
                return_value=True,
            ),
            patch.object(
                ComputerUseHarness,
                "aexecute",
                new=AsyncMock(return_value={"result": "success"}),
            ) as mock_exec,
        ):
            handler = _build_computer_use_handler()["computer"]
            result = asyncio.run(handler(action="click", x=10, y=20))

        assert result["result"] == "success"
        # action forwarded positionally; kwargs carry only the params.
        mock_exec.assert_awaited_once_with("click", x=10, y=20)


class TestOpenAIBatchedActions:
    """OpenAI Responses GA ``computer_call`` delivers a BATCHED ``actions[]``
    array (the adapter maps it onto ``input.actions``). The handler must run
    each action in order, return the FINAL screenshot, and report per-action
    errors honestly. The single-``action`` Anthropic path must still work.
    """

    _ENABLED = "core.llm.providers.anthropic.is_computer_use_enabled"

    def test_batched_actions_run_in_order_final_screenshot(self) -> None:
        from core.cli.tool_handlers.single_tool import _build_computer_use_handler

        calls: list[tuple[str, dict]] = []

        async def fake_exec(self: object, action: str, **params: object) -> dict:
            calls.append((action, dict(params)))
            return {"result": "success", "action": action, "screenshot": f"shot-{action}"}

        with (
            patch(self._ENABLED, return_value=True),
            patch.object(ComputerUseHarness, "aexecute", new=fake_exec),
        ):
            handler = _build_computer_use_handler()["computer"]
            result = asyncio.run(
                handler(
                    actions=[
                        {"type": "click", "x": 10, "y": 20, "button": "left"},
                        {"type": "type", "text": "hi"},
                        {"type": "screenshot"},
                    ]
                )
            )

        assert [name for name, _ in calls] == ["click", "type", "screenshot"]
        assert calls[0][1] == {"x": 10, "y": 20, "button": "left"}
        assert calls[1][1] == {"text": "hi"}
        # FINAL screenshot wins (the screen state the model sees next turn).
        assert result["screenshot"] == "shot-screenshot"
        assert "errors" not in result

    def test_keypress_list_joined_scroll_and_drag_remapped(self) -> None:
        from core.cli.tool_handlers.single_tool import _openai_action_to_harness

        # keypress: GA ``keys`` list → ``+``-joined combo string.
        name, params = _openai_action_to_harness({"type": "keypress", "keys": ["ctrl", "c"]})
        assert name == "keypress"
        assert params == {"keys": "ctrl+c"}

        # scroll: GA ``scroll_x``/``scroll_y`` → direction + amount.
        name, params = _openai_action_to_harness(
            {"type": "scroll", "x": 5, "y": 6, "scroll_x": 0, "scroll_y": 120}
        )
        assert name == "scroll"
        assert params["direction"] == "down"
        assert params["amount"] == 120

        # drag: GA ``path`` (array of points) → start/end coords.
        name, params = _openai_action_to_harness(
            {"type": "drag", "path": [{"x": 1, "y": 2}, {"x": 30, "y": 40}]}
        )
        assert name == "drag"
        assert params == {"start_x": 1, "start_y": 2, "end_x": 30, "end_y": 40}

    def test_batched_actions_collect_errors_honestly(self) -> None:
        from core.cli.tool_handlers.single_tool import _build_computer_use_handler

        async def fake_exec(self: object, action: str, **params: object) -> dict:
            if action == "double_click":
                return {"error": "no display", "action": action}
            return {"result": "success", "action": action, "screenshot": "ok"}

        with (
            patch(self._ENABLED, return_value=True),
            patch.object(ComputerUseHarness, "aexecute", new=fake_exec),
        ):
            handler = _build_computer_use_handler()["computer"]
            result = asyncio.run(
                handler(
                    actions=[
                        {"type": "double_click", "x": 1, "y": 2},
                        {"type": "screenshot"},
                    ]
                )
            )

        assert result["errors"] == [{"action": "double_click", "error": "no display"}]

    def test_final_action_error_still_yields_screenshot(self) -> None:
        """Regression (Codex HIGH): when the FINAL (or only) batched action errors
        with no screenshot, the handler must still capture one — else the pending
        ``computer_call`` gets no serializable ``computer_call_output`` and the
        loop stalls. The error is still surfaced honestly."""
        from core.cli.tool_handlers.single_tool import _build_computer_use_handler

        async def fake_exec(self: object, action: str, **params: object) -> dict:
            if action == "screenshot":
                return {"result": "success", "action": action, "screenshot": "recovered"}
            return {"error": "no display", "action": action}  # no screenshot key

        with (
            patch(self._ENABLED, return_value=True),
            patch.object(ComputerUseHarness, "aexecute", new=fake_exec),
        ):
            handler = _build_computer_use_handler()["computer"]
            result = asyncio.run(handler(actions=[{"type": "click", "x": 1, "y": 2}]))

        assert result["errors"] == [{"action": "click", "error": "no display"}]
        assert result["screenshot"] == "recovered"

    def test_unmapped_action_reaches_harness_for_honest_error(self) -> None:
        """An unknown GA action type must reach the harness (which returns an
        honest ``error`` dict) — never a silent skip."""
        from core.cli.tool_handlers.single_tool import _openai_action_to_harness

        name, params = _openai_action_to_harness({"type": "teleport", "x": 1})
        assert name == "teleport"
        assert params == {}
        # The harness rejects an unknown action name with an error (not a crash).
        result = asyncio.run(ComputerUseHarness().aexecute(name, **params))
        assert "error" in result

    def test_empty_batch_falls_back_to_screenshot(self) -> None:
        from core.cli.tool_handlers.single_tool import _build_computer_use_handler

        async def fake_exec(self: object, action: str, **params: object) -> dict:
            return {"result": "success", "action": action, "screenshot": "current"}

        with (
            patch(self._ENABLED, return_value=True),
            patch.object(ComputerUseHarness, "aexecute", new=fake_exec),
        ):
            handler = _build_computer_use_handler()["computer"]
            result = asyncio.run(handler(actions=[]))

        assert result["screenshot"] == "current"

    def test_pending_safety_checks_echoed_as_acknowledged(self) -> None:
        from core.cli.tool_handlers.single_tool import _build_computer_use_handler

        async def fake_exec(self: object, action: str, **params: object) -> dict:
            return {"result": "success", "action": action, "screenshot": "s"}

        checks = [{"id": "sc_1", "code": "malicious_instructions"}]
        with (
            patch(self._ENABLED, return_value=True),
            patch.object(ComputerUseHarness, "aexecute", new=fake_exec),
        ):
            handler = _build_computer_use_handler()["computer"]
            result = asyncio.run(
                handler(
                    actions=[{"type": "screenshot"}],
                    pending_safety_checks=checks,
                )
            )

        assert result["acknowledged_safety_checks"] == checks

    def test_single_action_anthropic_path_preserved(self) -> None:
        """No ``actions`` list → the legacy single-``action`` path runs."""
        from core.cli.tool_handlers.single_tool import _build_computer_use_handler

        with (
            patch(self._ENABLED, return_value=True),
            patch.object(
                ComputerUseHarness,
                "aexecute",
                new=AsyncMock(return_value={"result": "success"}),
            ) as mock_exec,
        ):
            handler = _build_computer_use_handler()["computer"]
            result = asyncio.run(handler(action="click", x=10, y=20))

        assert result["result"] == "success"
        mock_exec.assert_awaited_once_with("click", x=10, y=20)


class TestComputerResultImageBlock:
    """The screenshot must reach the model as an IMAGE content block, not base64
    text — otherwise the model is blind on the next turn AND the token guard /
    offload store corrupt the (huge) base64 string."""

    def test_serialize_computer_result_emits_image_block(self) -> None:
        from core.agent.tool_executor.processor import ToolCallProcessor

        block = ToolCallProcessor._serialize_computer_result(
            {"result": "success", "action": "screenshot", "screenshot": "BASE64DATA"},
            "tu_1",
        )
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "tu_1"
        content = block["content"]
        assert isinstance(content, list)
        images = [c for c in content if c.get("type") == "image"]
        texts = [c for c in content if c.get("type") == "text"]
        assert images[0]["source"] == {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": "BASE64DATA",
        }
        # The base64 blob must NOT leak into the text block (it would be
        # truncated/offloaded and is unreadable to the model anyway).
        assert "BASE64DATA" not in texts[0]["text"]
        assert "success" in texts[0]["text"]

    def test_serialize_dispatches_computer_to_image_path(self) -> None:
        from core.agent.tool_executor.processor import ToolCallProcessor

        proc = ToolCallProcessor(
            executor=MagicMock(), op_logger=MagicMock(), error_recovery=MagicMock()
        )
        result = {"result": "success", "action": "click", "screenshot": "IMG"}
        block = asyncio.run(proc._serialize_tool_result(result, "tu2", "computer"))
        assert isinstance(block["content"], list)
        assert any(c.get("type") == "image" for c in block["content"])

    def test_non_computer_result_stays_json_text(self) -> None:
        from core.agent.tool_executor.processor import ToolCallProcessor

        proc = ToolCallProcessor(
            executor=MagicMock(), op_logger=MagicMock(), error_recovery=MagicMock()
        )
        block = asyncio.run(proc._serialize_tool_result({"ok": True}, "tu3", "read_file"))
        assert isinstance(block["content"], str)

    def test_computer_error_without_screenshot_stays_text(self) -> None:
        """A failed computer action returns no screenshot → normal text path."""
        from core.agent.tool_executor.processor import ToolCallProcessor

        proc = ToolCallProcessor(
            executor=MagicMock(), op_logger=MagicMock(), error_recovery=MagicMock()
        )
        block = asyncio.run(proc._serialize_tool_result({"error": "no display"}, "tu4", "computer"))
        assert isinstance(block["content"], str)


class TestCoordinateScaling:
    def test_scale_to_screen(self):
        h = ComputerUseHarness(target_width=1280, target_height=800)
        h._screen_width = 2560
        h._screen_height = 1600
        sx, sy = h._scale_to_screen(640, 400)
        assert sx == 1280
        assert sy == 800

    def test_scale_to_target(self):
        h = ComputerUseHarness(target_width=1280, target_height=800)
        h._screen_width = 2560
        h._screen_height = 1600
        tx, ty = h._scale_to_target(1280, 800)
        assert tx == 640
        assert ty == 400

    def test_scale_identity_same_resolution(self):
        h = ComputerUseHarness(target_width=1280, target_height=800)
        h._screen_width = 1280
        h._screen_height = 800
        sx, sy = h._scale_to_screen(100, 200)
        assert sx == 100
        assert sy == 200


class TestExecuteDispatch:
    def test_unknown_action(self):
        h = ComputerUseHarness()
        result = asyncio.run(h.aexecute("nonexistent_action"))
        assert "error" in result
        assert "Unknown" in result["error"]
        assert "supported_actions" in result

    def test_screenshot_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "screenshot", return_value="base64data"):
            result = asyncio.run(h.aexecute("screenshot"))
        assert result["result"] == "success"
        assert result["screenshot"] == "base64data"

    def test_click_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "click", return_value="base64data"):
            result = asyncio.run(h.aexecute("click", x=100, y=200, button="left"))
        assert result["result"] == "success"

    def test_type_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "type_text", return_value="base64data"):
            result = asyncio.run(h.aexecute("type", text="hello world"))
        assert result["result"] == "success"

    def test_key_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "key", return_value="base64data"):
            result = asyncio.run(h.aexecute("key", keys="ctrl+c"))
        assert result["result"] == "success"

    def test_scroll_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "scroll", return_value="base64data"):
            result = asyncio.run(h.aexecute("scroll", x=0, y=0, direction="down"))
        assert result["result"] == "success"

    def test_anthropic_aliases(self):
        h = ComputerUseHarness()
        with patch.object(h, "click", return_value="base64data"):
            r1 = asyncio.run(h.aexecute("left_click", x=10, y=20))
            r2 = asyncio.run(h.aexecute("right_click", x=10, y=20))
            r3 = asyncio.run(h.aexecute("middle_click", x=10, y=20))
        assert r1["result"] == "success"
        assert r2["result"] == "success"
        assert r3["result"] == "success"

    def test_error_handling(self):
        h = ComputerUseHarness()
        with patch.object(h, "screenshot", side_effect=RuntimeError("no display")):
            result = asyncio.run(h.aexecute("screenshot"))
        assert "error" in result
        assert "no display" in result["error"]


class TestGetToolParams:
    def test_anthropic_params(self):
        h = ComputerUseHarness(target_width=1280, target_height=800)
        params = h.get_tool_params()
        assert params["type"] == "computer_20251124"
        assert params["name"] == "computer"
        assert params["display_width_px"] == 1280
        assert params["display_height_px"] == 800


class TestScreenshot:
    def test_screenshot_returns_base64(self):
        h = ComputerUseHarness()
        mock_img = MagicMock()
        mock_img.size = (2560, 1600)
        mock_resized = MagicMock()
        mock_img.resize.return_value = mock_resized

        def fake_save(buf, **kwargs):
            buf.write(b"\xff\xd8fake_jpeg_data")

        mock_resized.save = fake_save

        mock_image_module = MagicMock()
        mock_image_module.LANCZOS = 1

        with (
            patch.object(h, "_ensure_pyautogui") as mock_pag,
            patch.dict("sys.modules", {"PIL": MagicMock(), "PIL.Image": mock_image_module}),
        ):
            mock_pag.return_value.screenshot.return_value = mock_img
            result = h.screenshot()

        assert isinstance(result, str)
        import base64

        decoded = base64.b64decode(result)
        assert len(decoded) > 0
