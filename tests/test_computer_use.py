"""Tests for computer-use harness."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.tools.computer_use import ComputerUseHarness


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
        result = h.execute("nonexistent_action")
        assert "error" in result
        assert "Unknown" in result["error"]
        assert "supported_actions" in result

    def test_screenshot_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "screenshot", return_value="base64data"):
            result = h.execute("screenshot")
        assert result["result"] == "success"
        assert result["screenshot"] == "base64data"

    def test_click_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "click", return_value="base64data"):
            result = h.execute("click", x=100, y=200, button="left")
        assert result["result"] == "success"

    def test_type_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "type_text", return_value="base64data"):
            result = h.execute("type", text="hello world")
        assert result["result"] == "success"

    def test_key_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "key", return_value="base64data"):
            result = h.execute("key", keys="ctrl+c")
        assert result["result"] == "success"

    def test_scroll_action(self):
        h = ComputerUseHarness()
        with patch.object(h, "scroll", return_value="base64data"):
            result = h.execute("scroll", x=0, y=0, direction="down")
        assert result["result"] == "success"

    def test_anthropic_aliases(self):
        h = ComputerUseHarness()
        with patch.object(h, "click", return_value="base64data"):
            r1 = h.execute("left_click", x=10, y=20)
            r2 = h.execute("right_click", x=10, y=20)
            r3 = h.execute("middle_click", x=10, y=20)
        assert r1["result"] == "success"
        assert r2["result"] == "success"
        assert r3["result"] == "success"

    def test_error_handling(self):
        h = ComputerUseHarness()
        with patch.object(h, "screenshot", side_effect=RuntimeError("no display")):
            result = h.execute("screenshot")
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
