"""Computer Use Harness — screenshot + mouse + keyboard for LLM agents.

Provider-agnostic execution harness that both Anthropic (computer_20251124)
and OpenAI (computer_use_preview) can delegate to. The LLM sees the screen
via screenshots and issues actions (click, type, scroll, screenshot).

Architecture:
  LLM → tool_use(action, coordinates, text) → ComputerUseHarness → local OS
  ComputerUseHarness → screenshot (base64 JPEG) → LLM

Dependencies:
  - pyautogui (mouse + keyboard + screenshot)
  - Pillow (image resize + encode)

macOS notes:
  - Requires Accessibility permission (System Settings → Privacy)
  - pyautogui uses Quartz APIs on macOS
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

log = logging.getLogger(__name__)

# Target resolution sent to LLM (smaller = cheaper tokens, matches Anthropic demo)
TARGET_WIDTH = 1280
TARGET_HEIGHT = 800


class ComputerUseHarness:
    """Local OS harness for computer-use actions.

    Stateless — each call is independent. Screenshot resolution is scaled
    to TARGET_WIDTH x TARGET_HEIGHT for consistent LLM input.
    """

    def __init__(
        self,
        *,
        target_width: int = TARGET_WIDTH,
        target_height: int = TARGET_HEIGHT,
        jpeg_quality: int = 75,
    ) -> None:
        self._target_width = target_width
        self._target_height = target_height
        self._jpeg_quality = jpeg_quality
        self._screen_width: int = 0
        self._screen_height: int = 0

    def _ensure_pyautogui(self) -> Any:
        """Lazy import pyautogui (avoids import cost when not used)."""
        try:
            import pyautogui

            pyautogui.FAILSAFE = True  # move mouse to corner to abort
            pyautogui.PAUSE = 0.05  # 50ms between actions
            return pyautogui
        except ImportError as exc:
            raise RuntimeError(
                "pyautogui is required for computer-use. "
                "Install with: uv pip install pyautogui"
            ) from exc

    def _get_screen_size(self) -> tuple[int, int]:
        """Get actual screen resolution."""
        pag = self._ensure_pyautogui()
        size = pag.size()
        self._screen_width = size.width
        self._screen_height = size.height
        return size.width, size.height

    def _scale_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Scale coordinates from LLM space (target) to screen space."""
        if not self._screen_width:
            self._get_screen_size()
        sx = int(x * self._screen_width / self._target_width)
        sy = int(y * self._screen_height / self._target_height)
        return sx, sy

    def _scale_to_target(self, x: int, y: int) -> tuple[int, int]:
        """Scale coordinates from screen space to LLM space (target)."""
        if not self._screen_width:
            self._get_screen_size()
        tx = int(x * self._target_width / self._screen_width)
        ty = int(y * self._target_height / self._screen_height)
        return tx, ty

    # -- Actions --

    def screenshot(self) -> str:
        """Capture screen and return as base64 JPEG (scaled to target size)."""
        pag = self._ensure_pyautogui()
        from PIL import Image

        img = pag.screenshot()
        self._screen_width, self._screen_height = img.size

        # Resize to target
        img = img.resize(
            (self._target_width, self._target_height),
            Image.LANCZOS,
        )

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self._jpeg_quality)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        click_count: int = 1,
    ) -> str:
        """Click at coordinates (in target/LLM space)."""
        pag = self._ensure_pyautogui()
        sx, sy = self._scale_to_screen(x, y)

        button_map = {"left": "left", "right": "right", "middle": "middle"}
        btn = button_map.get(button, "left")

        pag.click(sx, sy, clicks=click_count, button=btn)
        log.info("click(%d,%d) → screen(%d,%d) button=%s", x, y, sx, sy, btn)
        return self.screenshot()

    def double_click(self, x: int, y: int) -> str:
        """Double-click at coordinates."""
        return self.click(x, y, click_count=2)

    def type_text(self, text: str) -> str:
        """Type text using keyboard."""
        pag = self._ensure_pyautogui()
        # Chunk to avoid pyautogui buffer issues (Anthropic uses 50-char chunks)
        chunk_size = 50
        for i in range(0, len(text), chunk_size):
            pag.typewrite(text[i : i + chunk_size], interval=0.012)
        log.info("type_text(%d chars)", len(text))
        return self.screenshot()

    def key(self, keys: str) -> str:
        """Press key combination (e.g. 'ctrl+c', 'enter', 'alt+tab')."""
        pag = self._ensure_pyautogui()
        # Parse key combo
        parts = [k.strip().lower() for k in keys.split("+")]
        key_map = {
            "ctrl": "ctrl",
            "control": "ctrl",
            "alt": "alt",
            "option": "alt",
            "shift": "shift",
            "cmd": "command",
            "command": "command",
            "super": "command",
            "enter": "return",
            "return": "return",
            "esc": "escape",
            "escape": "escape",
            "tab": "tab",
            "space": "space",
            "backspace": "backspace",
            "delete": "delete",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
        }
        mapped = [key_map.get(p, p) for p in parts]

        if len(mapped) == 1:
            pag.press(mapped[0])
        else:
            pag.hotkey(*mapped)

        log.info("key(%s)", keys)
        return self.screenshot()

    def scroll(
        self,
        x: int,
        y: int,
        direction: str = "down",
        amount: int = 3,
    ) -> str:
        """Scroll at coordinates."""
        pag = self._ensure_pyautogui()
        sx, sy = self._scale_to_screen(x, y)
        pag.moveTo(sx, sy)

        scroll_map = {
            "up": amount,
            "down": -amount,
        }
        clicks = scroll_map.get(direction, -amount)
        pag.scroll(clicks)

        if direction in ("left", "right"):
            pag.hscroll(amount if direction == "right" else -amount)

        log.info("scroll(%d,%d) direction=%s amount=%d", x, y, direction, amount)
        return self.screenshot()

    def move(self, x: int, y: int) -> str:
        """Move mouse to coordinates."""
        pag = self._ensure_pyautogui()
        sx, sy = self._scale_to_screen(x, y)
        pag.moveTo(sx, sy)
        log.info("move(%d,%d) → screen(%d,%d)", x, y, sx, sy)
        return self.screenshot()

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
    ) -> str:
        """Drag from start to end coordinates."""
        pag = self._ensure_pyautogui()
        sx1, sy1 = self._scale_to_screen(start_x, start_y)
        sx2, sy2 = self._scale_to_screen(end_x, end_y)
        pag.moveTo(sx1, sy1)
        pag.drag(sx2 - sx1, sy2 - sy1, duration=0.5)
        log.info(
            "drag(%d,%d→%d,%d) → screen(%d,%d→%d,%d)",
            start_x, start_y, end_x, end_y, sx1, sy1, sx2, sy2,
        )
        return self.screenshot()

    def wait(self, ms: int = 1000) -> str:
        """Wait for specified milliseconds, then screenshot."""
        import time

        time.sleep(ms / 1000.0)
        return self.screenshot()

    # -- Dispatch (provider-agnostic) --

    def execute(self, action: str, **params: Any) -> dict[str, Any]:
        """Execute a computer-use action and return result with screenshot.

        This is the unified dispatch for both Anthropic and OpenAI actions.
        """
        handlers: dict[str, Any] = {
            "screenshot": lambda: self.screenshot(),
            "click": lambda: self.click(
                params.get("x", 0),
                params.get("y", 0),
                params.get("button", "left"),
                params.get("click_count", 1),
            ),
            "double_click": lambda: self.double_click(
                params.get("x", 0), params.get("y", 0)
            ),
            "type": lambda: self.type_text(params.get("text", "")),
            "key": lambda: self.key(params.get("keys", params.get("key", ""))),
            "keypress": lambda: self.key(params.get("keys", params.get("key", ""))),
            "scroll": lambda: self.scroll(
                params.get("x", 0),
                params.get("y", 0),
                params.get("direction", "down"),
                params.get("amount", 3),
            ),
            "move": lambda: self.move(params.get("x", 0), params.get("y", 0)),
            "drag": lambda: self.drag(
                params.get("start_x", params.get("x", 0)),
                params.get("start_y", params.get("y", 0)),
                params.get("end_x", 0),
                params.get("end_y", 0),
            ),
            "wait": lambda: self.wait(params.get("ms", 1000)),
            # Anthropic aliases
            "left_click": lambda: self.click(
                params.get("x", 0), params.get("y", 0), "left"
            ),
            "right_click": lambda: self.click(
                params.get("x", 0), params.get("y", 0), "right"
            ),
            "middle_click": lambda: self.click(
                params.get("x", 0), params.get("y", 0), "middle"
            ),
            "triple_click": lambda: self.click(
                params.get("x", 0), params.get("y", 0), "left", 3
            ),
            "cursor_position": lambda: self._get_cursor_position(),
        }

        handler = handlers.get(action)
        if handler is None:
            return {
                "error": f"Unknown computer-use action: {action}",
                "supported_actions": list(handlers.keys()),
            }

        try:
            screenshot_b64 = handler()
            return {
                "result": "success",
                "action": action,
                "screenshot": screenshot_b64,
            }
        except Exception as exc:
            log.error("Computer-use action %s failed: %s", action, exc)
            return {
                "error": f"Action '{action}' failed: {exc}",
                "action": action,
            }

    def _get_cursor_position(self) -> str:
        """Get current cursor position (in target space) + screenshot."""
        pag = self._ensure_pyautogui()
        pos = pag.position()
        tx, ty = self._scale_to_target(pos.x, pos.y)
        log.info("cursor_position: screen(%d,%d) → target(%d,%d)", pos.x, pos.y, tx, ty)
        return self.screenshot()

    def get_tool_params(self) -> dict[str, Any]:
        """Return Anthropic-compatible tool parameters for API call."""
        return {
            "type": "computer_20251124",
            "name": "computer",
            "display_width_px": self._target_width,
            "display_height_px": self._target_height,
        }
