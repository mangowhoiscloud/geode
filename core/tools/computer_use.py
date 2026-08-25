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
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.paths import COMPUTER_USE_HELPER_APP_DIR
from core.tools.computer_observation import enrich_computer_result

log = logging.getLogger(__name__)

# Target resolution sent to LLM (smaller = cheaper tokens, matches Anthropic demo)
TARGET_WIDTH = 1280
TARGET_HEIGHT = 800


_BLOCKED_KEY_COMBOS: tuple[frozenset[str], ...] = (
    frozenset({"cmd", "shift", "backspace"}),
    frozenset({"cmd", "option", "backspace"}),
    frozenset({"cmd", "ctrl", "q"}),
    frozenset({"cmd", "shift", "q"}),
    frozenset({"cmd", "option", "shift", "q"}),
    frozenset({"win", "l"}),
    frozenset({"ctrl", "option", "delete"}),
    frozenset({"ctrl", "option", "del"}),
    frozenset({"option", "f4"}),
)

_KEY_ALIASES = {
    "command": "cmd",
    "control": "ctrl",
    "alt": "option",
    "windows": "win",
    "super": "win",
    "meta": "win",
}

_BLOCKED_TYPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"curl\s+[^|]*\|\s*bash", re.IGNORECASE),
    re.compile(r"curl\s+[^|]*\|\s*sh", re.IGNORECASE),
    re.compile(r"wget\s+[^|]*\|\s*bash", re.IGNORECASE),
    re.compile(r"\bsudo\s+rm\s+-[rf]", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+/\s*$", re.IGNORECASE),
    re.compile(r":\s*\(\)\s*\{\s*:\|:\s*&\s*\}", re.IGNORECASE),
)


def computer_use_driver() -> str:
    """Resolve host computer-use driver: auto | python | helper."""
    from core.config import settings

    driver = str(getattr(settings, "computer_use_driver", "") or "auto").strip().lower()
    if driver in {"auto", "python", "helper"}:
        return driver
    log.warning("computer_use_driver=%r is invalid — falling back to 'auto'", driver)
    return "auto"


def _default_helper_path() -> Path:
    return COMPUTER_USE_HELPER_APP_DIR / "Contents" / "MacOS" / "geode-computer-helper"


def computer_use_helper_path() -> Path | None:
    """Return the configured/default helper path only when it is executable."""
    from core.config import settings

    def _usable(path: Path) -> bool:
        return path.is_file() and os.access(path, os.X_OK)

    explicit = str(getattr(settings, "computer_use_helper_path", "") or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if _usable(path) else None
    default = _default_helper_path()
    if _usable(default):
        return default
    found = shutil.which("geode-computer-helper")
    if found:
        path = Path(found)
        return path if _usable(path) else None
    return None


def _helper_request_sync(
    action: str,
    params: dict[str, Any] | None = None,
    *,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    helper = computer_use_helper_path()
    if helper is None:
        return {
            "error": "computer-use helper is not installed",
            "error_type": "dependency",
            "driver": "macos_helper",
            "hint": "Build it with: geode setup",
        }
    payload = {
        "action": action,
        "params": params or {},
        "target_width": target_width,
        "target_height": target_height,
    }
    try:
        proc = subprocess.run(  # noqa: S603
            [str(helper)],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "error": f"computer-use helper failed to run: {exc}",
            "error_type": "dependency",
            "driver": "macos_helper",
        }
    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    if not stdout:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        return {
            "error": f"computer-use helper returned no JSON (exit={proc.returncode}): {stderr}",
            "error_type": "dependency",
            "driver": "macos_helper",
        }
    try:
        result = json.loads(stdout)
    except ValueError:
        return {
            "error": f"computer-use helper returned invalid JSON: {stdout[:240]}",
            "error_type": "dependency",
            "driver": "macos_helper",
        }
    if not isinstance(result, dict):
        return {
            "error": f"computer-use helper returned non-object JSON: {str(result)[:120]}",
            "error_type": "dependency",
            "driver": "macos_helper",
        }
    return result


def computer_use_helper_status() -> dict[str, Any]:
    """Probe the macOS helper without touching Python pyautogui/pyobjc."""
    return _helper_request_sync("status", timeout_s=10.0)


def _canon_key_combo(keys: str) -> frozenset[str]:
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", keys) if p.strip()]
    return frozenset(_KEY_ALIASES.get(p, p) for p in parts)


def _blocked_key_combo(keys: str) -> list[str] | None:
    combo = _canon_key_combo(keys)
    for blocked in _BLOCKED_KEY_COMBOS:
        if blocked.issubset(combo):
            return sorted(blocked)
    return None


def _blocked_type_pattern(text: str) -> str | None:
    for pattern in _BLOCKED_TYPE_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def _strip_screenshot(result: dict[str, Any]) -> dict[str, Any]:
    """Return a computer-use result safe for normal function-tool channels.

    Native ``computer`` tool results are serialized as image blocks. The
    emulated ``computer_use`` function path is different: OpenAI/Codex function
    outputs are text payloads, so raw base64 would bloat context and can be
    misinterpreted as a native ``computer_call_output`` on replay. Keep compact
    observation metadata and drop the image bytes.
    """
    out = dict(result)
    if out.pop("screenshot", None) is not None:
        out["screenshot_omitted"] = True
        out["screenshot_omitted_reason"] = (
            "computer_use is a normal function tool; screenshots are reduced to "
            "observation metadata to avoid base64 context bloat. Use action='locate' "
            "only when visual grounding is supported for the active provider/source; "
            "otherwise use ui_probe, browser DOM tools, playwriter, or keyboard navigation."
        )
    return out


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
        self._last_cursor_target: tuple[int, int] | None = None

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
        """Move the cursor and verify that the operating system accepted it.

        macOS can silently discard Quartz input events when the active driver
        lacks Accessibility permission. ``pyautogui.moveTo`` may then return
        normally even though the cursor did not move, so success requires a
        bounded postcondition check.
        """
        pag = self._ensure_pyautogui()
        sx, sy = self._scale_to_screen(x, y)
        pag.moveTo(sx, sy)
        observed = pag.position()
        if abs(int(observed.x) - sx) > 2 or abs(int(observed.y) - sy) > 2:
            raise PermissionError(
                "mouse move postcondition failed: requested "
                f"screen({sx},{sy}), observed screen({observed.x},{observed.y}); "
                "grant Accessibility permission to the GEODE desktop driver "
                "and re-run `geode doctor`"
            )
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

    def _target_size(self) -> tuple[int, int]:
        return (self._target_width, self._target_height)

    def _screen_size(self) -> tuple[int, int]:
        return (self._screen_width, self._screen_height)

    def _cursor_for_action(self, action: str, params: dict[str, Any]) -> tuple[int, int] | None:
        if action == "cursor_position":
            return self._last_cursor_target
        if action in {
            "click",
            "double_click",
            "move",
            "scroll",
            "left_click",
            "right_click",
            "middle_click",
            "triple_click",
        }:
            return (int(params.get("x", 0) or 0), int(params.get("y", 0) or 0))
        if action == "drag":
            return (
                int(params.get("end_x", 0) or 0),
                int(params.get("end_y", 0) or 0),
            )
        return None

    def _enrich_result(
        self,
        result: dict[str, Any],
        *,
        action: str,
        params: dict[str, Any] | None = None,
        env: str = "host",
    ) -> dict[str, Any]:
        return enrich_computer_result(
            result,
            action=action,
            target_size=self._target_size(),
            screen_size=self._screen_size(),
            env=env,
            cursor=self._cursor_for_action(action, params or {}),
        )

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
            return self._enrich_result(
                {
                    "error": f"Unknown computer-use action: {action}",
                    "supported_actions": list(handlers.keys()),
                },
                action=action,
                params=params,
            )

        try:
            screenshot_b64 = handler()
            result: dict[str, Any] = {
                "result": "success",
                "action": action,
                "screenshot": screenshot_b64,
            }
            if action == "move":
                result["postcondition_verified"] = True
            return self._enrich_result(
                result,
                action=action,
                params=params,
            )
        except Exception as exc:
            log.error("Computer-use action %s failed: %s", action, exc)
            return self._enrich_result(
                {
                    "error": f"Action '{action}' failed: {exc}",
                    "action": action,
                },
                action=action,
                params=params,
            )

    async def aexecute(self, action: str, **params: Any) -> dict[str, Any]:
        """Dispatch one action through the configured host desktop driver."""
        driver = computer_use_driver()
        if driver == "helper" or (driver == "auto" and computer_use_helper_path() is not None):
            return await asyncio.to_thread(self._helper_execute_sync, action, params)
        return await asyncio.to_thread(self._execute_sync, action, **params)

    def _helper_execute_sync(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch one host action to the signed macOS helper app.

        The helper is the CLI-friendly equivalent of an app/plugin permission
        owner: macOS TCC grants Accessibility / Screen Recording to the helper
        bundle, while GEODE continues to run as a CLI/daemon and talks to it via
        stdin/stdout JSON.
        """
        result = _helper_request_sync(
            action,
            params,
            target_width=self._target_width,
            target_height=self._target_height,
        )
        width = result.get("screen_width")
        height = result.get("screen_height")
        if isinstance(width, int) and isinstance(height, int):
            self._screen_width = width
            self._screen_height = height
        return self._enrich_result(result, action=action, params=params, env="host-helper")

    def _get_cursor_position(self) -> str:
        """Get current cursor position (in target space) + screenshot."""
        pag = self._ensure_pyautogui()
        pos = pag.position()
        tx, ty = self._scale_to_target(pos.x, pos.y)
        self._last_cursor_target = (tx, ty)
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


async def execute_emulated_computer_use(
    harness: ComputerUseHarness,
    *,
    action: str = "capture",
    instruction: str = "",
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    click_count: int = 1,
    text: str = "",
    keys: str = "",
    direction: str = "down",
    amount: int = 3,
    start_x: int | None = None,
    start_y: int | None = None,
    end_x: int | None = None,
    end_y: int | None = None,
    ms: int = 1000,
    capture_after: bool = True,
    _tool_context: Any | None = None,
) -> dict[str, Any]:
    """Run a model-agnostic computer-use action through the local harness.

    This is the subscription-model workaround path: the model sees a normal
    JSON function named ``computer_use`` instead of a provider-native hosted
    computer tool. The result is deliberately text/JSON-safe, so it strips raw
    screenshots and asks callers to use ``locate`` for visual grounding.
    """
    action = (action or "capture").strip().lower()
    if action == "capture":
        result = await harness.aexecute("screenshot")
        return _strip_screenshot(
            {
                **result,
                "mode": "emulated",
                "hint": (
                    "For visual target selection, call computer_use with "
                    "action='locate' and a concise instruction, then click the "
                    "returned coordinates."
                ),
            }
        )

    if action == "locate":
        if not instruction.strip():
            return {
                "error": "computer_use action='locate' requires instruction",
                "error_type": "validation",
                "hint": "Describe the UI element to locate, e.g. 'the blue Submit button'.",
            }
        shot = await harness.aexecute("screenshot")
        screenshot_b64 = shot.get("screenshot") if isinstance(shot, dict) else None
        if not isinstance(screenshot_b64, str) or not screenshot_b64:
            return _strip_screenshot(
                {
                    **(shot if isinstance(shot, dict) else {}),
                    "error": "Unable to capture screenshot for visual grounding",
                    "error_type": "dependency",
                    "hint": "Check computer-use permissions and desktop driver readiness.",
                }
            )
        try:
            from core.tools.computer_grounding import (
                VisualGroundingUnavailableError,
                locate_with_active_provider,
            )

            point = await locate_with_active_provider(
                screenshot_b64,
                instruction,
                target_width=harness._target_width,
                target_height=harness._target_height,
                tool_context=_tool_context,
            )
        except VisualGroundingUnavailableError as exc:
            log.info("computer_use locate unavailable: %s", exc)
            return _strip_screenshot(
                {
                    **shot,
                    "error": str(exc),
                    "error_type": "dependency",
                    "recoverable": True,
                    "grounding": {
                        "provider": exc.provider,
                        "source": exc.source,
                        "status": "unsupported_for_active_source",
                    },
                    "fallback_tools": [
                        "ui_probe",
                        "browser DOM tools (browser_snapshot/browser_execute_js)",
                        "playwriter for login-required Chrome sessions",
                        "keyboard navigation",
                        "GLM route for visual locate",
                    ],
                    "hint": (
                        "Use ui_probe for macOS Accessibility structure when available, "
                        "browser DOM tools for web pages, playwriter for login-required "
                        "Chrome sessions, or safe keyboard navigation. To use GLM visual "
                        "grounding, route the turn through a GLM provider/source explicitly. "
                        "Do not blind-type until focus/target has been independently verified."
                    ),
                }
            )
        except Exception as exc:
            log.warning("computer_use locate failed: %s", exc)
            return _strip_screenshot(
                {
                    **shot,
                    "error": f"visual grounding failed: {exc}",
                    "error_type": "dependency",
                    "hint": (
                        "The active provider's visual grounding path is unavailable. "
                        "Try ui_probe, keyboard navigation, or a coordinate-based action "
                        "only if the target is known."
                    ),
                }
            )
        if point is None:
            return _strip_screenshot(
                {
                    **shot,
                    "result": "not_found",
                    "action": "locate",
                    "instruction": instruction,
                    "hint": "Rephrase the target or narrow the active window, then retry locate.",
                }
            )
        return _strip_screenshot(
            {
                **shot,
                "result": "success",
                "action": "locate",
                "instruction": instruction,
                "coordinate": [point[0], point[1]],
                "hint": "Use action='click' with these x/y coordinates, or inspect again.",
            }
        )

    if action == "key":
        blocked = _blocked_key_combo(keys)
        if blocked:
            return {
                "error": f"blocked key combo: {blocked}",
                "error_type": "permission",
                "recoverable": False,
                "hint": "Destructive system shortcuts are hard-blocked.",
            }
    if action == "type":
        pattern = _blocked_type_pattern(text)
        if pattern:
            return {
                "error": f"blocked pattern in typed text: {pattern!r}",
                "error_type": "permission",
                "recoverable": False,
                "hint": "Dangerous shell patterns cannot be typed via computer_use.",
            }

    dispatch_action = action
    params: dict[str, Any] = {}
    if action in {"click", "double_click", "move"}:
        if x is None or y is None:
            return {"error": f"{action} requires x and y", "error_type": "validation"}
        params = {"x": x, "y": y}
        if action == "click":
            params["button"] = button
            params["click_count"] = click_count
    elif action in {"right_click", "middle_click", "triple_click"}:
        if x is None or y is None:
            return {"error": f"{action} requires x and y", "error_type": "validation"}
        dispatch_action = {
            "right_click": "right_click",
            "middle_click": "middle_click",
            "triple_click": "triple_click",
        }[action]
        params = {"x": x, "y": y}
    elif action == "scroll":
        if x is None or y is None:
            return {"error": "scroll requires x and y", "error_type": "validation"}
        params = {"x": x, "y": y, "direction": direction, "amount": amount}
    elif action == "drag":
        missing = [
            name
            for name, value in {
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
            }.items()
            if value is None
        ]
        if missing:
            return {
                "error": f"drag requires {', '.join(missing)}",
                "error_type": "validation",
            }
        params = {
            "start_x": start_x,
            "start_y": start_y,
            "end_x": end_x,
            "end_y": end_y,
        }
    elif action == "type":
        params = {"text": text}
    elif action == "key":
        params = {"keys": keys}
    elif action == "wait":
        params = {"ms": ms}
    elif action == "cursor_position":
        params = {}
    else:
        return {
            "error": f"Unknown computer_use action: {action}",
            "error_type": "validation",
            "supported_actions": [
                "capture",
                "locate",
                "click",
                "double_click",
                "right_click",
                "middle_click",
                "triple_click",
                "move",
                "scroll",
                "drag",
                "type",
                "key",
                "wait",
                "cursor_position",
            ],
        }

    result = await harness.aexecute(dispatch_action, **params)
    safe = _strip_screenshot(result)
    if capture_after:
        safe["post_action_observation"] = safe.get("observation", {})
    return safe
