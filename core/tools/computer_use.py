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

import asyncio
import base64
import io
import logging
from typing import Any

log = logging.getLogger(__name__)

# Target resolution sent to LLM (smaller = cheaper tokens, matches Anthropic demo)
TARGET_WIDTH = 1280
TARGET_HEIGHT = 800


def computer_use_env() -> str:
    """Resolve the execution environment: "host" (default) | "sandbox".

    Function-local settings read so a mid-session config reload is honoured
    (mirrors the routing-constant accessors).

    Fail-safe on a misconfig: host execution drives the operator's REAL desktop,
    so it requires an EXACT "host" (or unset = documented default). A non-empty
    invalid value (a config.toml typo bypasses the pydantic validator via
    ``object.__setattr__``) must NOT silently fall through to host — it routes to
    "sandbox" (which fails loud if no container) so a typo can never re-expose
    the real desktop.
    """
    from core.config import settings

    env = str(getattr(settings, "computer_use_env", "") or "").strip().lower()
    if env in {"host", "sandbox"}:
        return env
    if not env:
        return "host"  # documented default
    log.warning(
        "computer_use_env=%r is invalid — routing to 'sandbox' (fail-loud) so a "
        "typo cannot silently drive the real desktop. Set 'host' or 'sandbox'.",
        env,
    )
    return "sandbox"


def _sandbox_url() -> str:
    from core.config import settings

    return str(getattr(settings, "computer_use_sandbox_url", "") or "").rstrip("/")


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
            import pyautogui  # type: ignore[import-untyped]

            pyautogui.FAILSAFE = True  # move mouse to corner to abort
            pyautogui.PAUSE = 0.05  # 50ms between actions
            return pyautogui
        except ImportError as exc:
            raise RuntimeError(
                "pyautogui is required for computer-use. Install with: uv pip install pyautogui"
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
            Image.Resampling.LANCZOS,
        )

        # JPEG has no alpha channel. pyautogui/Pillow returns RGBA on macOS (and
        # P/LA for some sources), so a direct JPEG save raises "cannot write mode
        # RGBA as JPEG". Convert to RGB first. (Surfaced by the 2026-06-17 live
        # E2E: every screenshot errored here, so computer-use never actually
        # round-tripped — the bug hid behind the un-live-tested path.)
        if img.mode != "RGB":
            img = img.convert("RGB")
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
            start_x,
            start_y,
            end_x,
            end_y,
            sx1,
            sy1,
            sx2,
            sy2,
        )
        return self.screenshot()

    def wait(self, ms: int = 1000) -> str:
        """Wait for specified milliseconds, then screenshot."""
        import time

        time.sleep(ms / 1000.0)
        return self.screenshot()

    # -- Dispatch (provider-agnostic) --

    def _execute_sync(self, action: str, **params: Any) -> dict[str, Any]:
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
            "double_click": lambda: self.double_click(params.get("x", 0), params.get("y", 0)),
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
            "left_click": lambda: self.click(params.get("x", 0), params.get("y", 0), "left"),
            "right_click": lambda: self.click(params.get("x", 0), params.get("y", 0), "right"),
            "middle_click": lambda: self.click(params.get("x", 0), params.get("y", 0), "middle"),
            "triple_click": lambda: self.click(params.get("x", 0), params.get("y", 0), "left", 3),
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

    async def aexecute(self, action: str, **params: Any) -> dict[str, Any]:
        """Dispatch one action — host (local OS) or sandbox (in-container shim).

        Phase E: when ``computer_use_env() == "sandbox"`` the action is POSTed to
        the container shim instead of running local pyautogui, so the host never
        touches a display. fail-loud: a sandbox error is surfaced as an error
        result and NEVER falls back to host execution.
        """
        if computer_use_env() == "sandbox":
            return await asyncio.to_thread(self._sandbox_execute_sync, action, params)
        return await asyncio.to_thread(self._execute_sync, action, **params)

    def _sandbox_execute_sync(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """POST one action to the in-container shim and return its result.

        The shim (Docker + Xvfb virtual desktop, see ``docker/computer-use-
        sandbox/``) runs the SAME action vocabulary against its own pyautogui +
        Xvfb display and returns ``{"result"/"error", "action", "screenshot"}``
        — identical shape to :meth:`_execute_sync`. On any transport failure we
        return an error result; we do NOT run the action on the host (that would
        be a fail-open hole: the operator opted into isolation).

        # container isolation unverified — live test required (CANNOT §4d):
        # no Docker host available to exercise the round-trip.
        """
        import httpx

        base = _sandbox_url()
        if not base:
            return {
                "error": "computer_use_env=sandbox but computer_use_sandbox_url is empty",
                "action": action,
            }
        try:
            resp = httpx.post(f"{base}/cmd", json={"action": action, "params": params}, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            if not isinstance(result, dict):
                return {
                    "error": f"sandbox returned non-object: {str(result)[:120]}",
                    "action": action,
                }
            return result
        except (httpx.HTTPError, ValueError, OSError) as exc:
            # fail-loud: surface the error, never touch the host desktop.
            return {
                "error": f"computer-use sandbox unreachable ({base}/cmd): {exc}",
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
