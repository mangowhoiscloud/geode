"""Tests for computer-use harness."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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

    def test_emulated_computer_use_handler_strips_screenshot(self) -> None:
        from core.cli.tool_handlers.single_tool import _build_computer_use_handler

        with (
            patch(
                "core.llm.providers.anthropic.is_computer_use_enabled",
                return_value=True,
            ),
            patch.object(
                ComputerUseHarness,
                "aexecute",
                new=AsyncMock(
                    return_value={
                        "result": "success",
                        "action": "screenshot",
                        "screenshot": "BASE64DATA",
                        "observation": {"screenshot_sha256": "abc"},
                    }
                ),
            ),
        ):
            handler = _build_computer_use_handler()["computer_use"]
            result = asyncio.run(handler(action="capture"))

        assert result["result"] == "success"
        assert result["screenshot_omitted"] is True
        assert "screenshot" not in result
        assert "BASE64DATA" not in str(result)

    def test_emulated_computer_use_disabled_returns_permission_error(self) -> None:
        from core.cli.tool_handlers.single_tool import _build_computer_use_handler

        with patch(
            "core.llm.providers.anthropic.is_computer_use_enabled",
            return_value=False,
        ):
            handler = _build_computer_use_handler()["computer_use"]
            result = asyncio.run(handler(action="capture"))

        assert result["error_type"] == "permission"

    def test_emulated_computer_use_blocks_dangerous_key_combo(self) -> None:
        from core.tools.computer_use import execute_emulated_computer_use

        result = asyncio.run(
            execute_emulated_computer_use(
                ComputerUseHarness(),
                action="key",
                keys="cmd+shift+q",
            )
        )

        assert result["error_type"] == "permission"
        assert "blocked key combo" in result["error"]

    def test_locate_openai_subscription_does_not_call_glm(self) -> None:
        from core.tools.base import ToolContext
        from core.tools.computer_use import execute_emulated_computer_use

        h = ComputerUseHarness()

        async def fake_execute(action: str, **_params: object) -> dict[str, object]:
            assert action == "screenshot"
            return {
                "result": "success",
                "action": "screenshot",
                "screenshot": "BASE64DATA",
                "observation": {"screenshot_sha256": "abc"},
            }

        with (
            patch.object(h, "aexecute", new=fake_execute),
            patch("core.tools.computer_grounding.glm_locate", new=AsyncMock()) as glm_locate,
        ):
            result = asyncio.run(
                execute_emulated_computer_use(
                    h,
                    action="locate",
                    instruction="the TextEdit close button",
                    _tool_context=ToolContext(
                        provider="openai",
                        source="subscription",
                        model="gpt-5.5",
                        adapter_name="codex-oauth",
                    ),
                )
            )

        glm_locate.assert_not_awaited()
        assert result["error_type"] == "dependency"
        assert result["grounding"]["provider"] == "openai"
        assert result["grounding"]["source"] == "subscription"
        assert "ui_probe" in result["fallback_tools"]
        assert any("playwriter" in item for item in result["fallback_tools"])
        assert "implicit GLM fallback is disabled" in result["error"]
        assert "Do not blind-type" in result["hint"]
        assert "screenshot" not in result


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
        assert result["trajectory"]["metrics"]["total_actions"] == 3
        assert result["trajectory"]["metrics"]["final_has_screenshot"] is True
        assert result["trajectory"]["events"][1]["params"]["text"] == "<redacted:length=2>"

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
        assert result["trajectory"]["metrics"]["failed_actions"] == 1

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
        assert result["trajectory"]["metrics"]["failed_actions"] == 1

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

    def test_computer_gui_payload_is_transcript_safe(self) -> None:
        from core.agent.tool_executor.processor import ToolCallProcessor

        payload = ToolCallProcessor._computer_gui_payload(
            {"actions": [{"type": "screenshot"}]},
            {
                "screenshot": "BASE64DATA",
                "observation": {
                    "observation_id": "screen:abc",
                    "screenshot_sha256": "abc",
                    "target_width": 1280,
                    "target_height": 800,
                },
                "trajectory": {"metrics": {"total_actions": 1}},
            },
            "tu5",
        )

        assert payload["input_action_count"] == 1
        assert payload["observation"]["screenshot_sha256"] == "abc"
        assert "screenshot" not in payload
        assert "BASE64DATA" not in str(payload)

    def test_computer_tool_log_omits_screenshot_bytes(self) -> None:
        from core.agent.tool_executor.processor import ToolCallProcessor

        proc = ToolCallProcessor(
            executor=MagicMock(), op_logger=MagicMock(), error_recovery=MagicMock()
        )
        proc._record_tool_activity(
            "computer",
            {"action": "screenshot"},
            {
                "result": "success",
                "action": "screenshot",
                "screenshot": "BASE64DATA",
                "observation": {"screenshot_sha256": "abc"},
            },
            visible=True,
            tool_use_id="tu6",
        )

        stored = proc.tool_log[0]["result"]
        assert stored["screenshot_omitted"] is True
        assert "screenshot" not in stored
        assert "BASE64DATA" not in str(proc.tool_log)

    def test_sanitizer_preserves_non_tool_user_images(self) -> None:
        from core.tools.computer_observation import sanitize_computer_payload

        payload = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "data": "USER_IMAGE"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "base64", "data": "TOOL_SCREEN"},
                            }
                        ],
                    }
                ],
            },
        ]

        sanitized = sanitize_computer_payload(payload)

        assert sanitized[0]["content"][0]["source"]["data"] == "USER_IMAGE"
        assert "TOOL_SCREEN" not in str(sanitized)
        assert "image_omitted" in sanitized[1]["content"][0]["content"][0]["text"]


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
    @pytest.fixture(autouse=True)
    def _force_python_driver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, "computer_use_env", "host", raising=False)
        monkeypatch.setattr(settings, "computer_use_driver", "python", raising=False)

    def test_unknown_action(self):
        h = ComputerUseHarness()
        result = asyncio.run(h.aexecute("nonexistent_action"))
        assert "error" in result
        assert "Unknown" in result["error"]
        assert "supported_actions" in result
        assert result["error_kind"] == "unknown_action"
        assert result["recovery"]["policy"] == "replan"

    def test_screenshot_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "screenshot", return_value="base64data"):
            result = asyncio.run(h.aexecute("screenshot"))
        assert result["result"] == "success"
        assert result["action_status"] == "dispatched"
        assert result["requires_verification"] is False
        assert result["postcondition_verified"] is False
        assert result["screenshot"] == "base64data"
        assert result["observation"]["screenshot_sha256"]
        assert result["observation"]["target_width"] == 1280
        assert result["observation"]["surface"] == "desktop"

    def test_click_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "click", return_value="base64data"):
            result = asyncio.run(h.aexecute("click", x=100, y=200, button="left"))
        assert result["result"] == "success"
        assert result["action_status"] == "dispatched"
        assert result["requires_verification"] is True
        assert result["postcondition_verified"] is False
        assert "target application state is not proven" in result["verification_hint"]

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
    """Exercises the REAL Pillow encode path (Pillow is a dev-group dep). Mocking
    PIL away — as an earlier version did — hid the RGBA→JPEG bug: pyautogui
    returns RGBA on macOS, JPEG has no alpha, so ``img.save(format="JPEG")``
    raised ``OSError: cannot write mode RGBA as JPEG`` and every screenshot
    errored (the un-live-tested path masked it until the 2026-06-17 live E2E)."""

    def _capture(self, mode: str, size: tuple[int, int] = (2560, 1600)) -> bytes:
        import base64

        from PIL import Image

        src = Image.new(mode, size)
        h = ComputerUseHarness(target_width=1280, target_height=800)
        with patch.object(h, "_ensure_pyautogui") as mock_pag:
            mock_pag.return_value.screenshot.return_value = src
            result = h.screenshot()
        assert isinstance(result, str)
        return base64.b64decode(result)

    def test_screenshot_returns_jpeg_base64(self) -> None:
        pytest.importorskip("PIL")
        decoded = self._capture("RGB")
        assert decoded[:2] == b"\xff\xd8"  # JPEG SOI marker — a real encode

    def test_screenshot_converts_rgba_to_jpeg(self) -> None:
        """Regression guard: an RGBA source (macOS pyautogui) must NOT raise
        ``cannot write mode RGBA as JPEG`` — the harness converts to RGB first
        and emits a valid JPEG that re-opens as RGB."""
        pytest.importorskip("PIL")
        import io

        from PIL import Image

        decoded = self._capture("RGBA")
        assert decoded[:2] == b"\xff\xd8"  # JPEG SOI — no OSError on RGBA input
        reopened = Image.open(io.BytesIO(decoded))
        assert reopened.format == "JPEG"
        assert reopened.mode == "RGB"
