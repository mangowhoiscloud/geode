"""UI Probe — structured macOS accessibility (AX) perception.

A cheaper, more reliable first rung than a screenshot for "what is on screen".
The ``computer_use`` harness perceives the desktop as pixels: every step ships a
1280x800 JPEG (~1.5k tokens) to the model, and the model clicks by eyeballing
coordinates. For native macOS apps the accessibility tree already carries the
same information as *text* — each control's role, title, value, enabled state,
and on-screen rectangle — so the agent can perceive the UI in a few hundred
tokens and read exact element rectangles instead of guessing from an image.

Perception ladder (GenericAgent computer_use.md, mirrored): window/app probe ->
accessibility tree -> visual detection/OCR -> vision model. This tool is the
second rung; ``computer_use`` screenshots remain the fallback when AX is
unavailable (games, custom-drawn canvases) or insufficient.

Scope / live-status:
- The **structured readout** (role/title/value/enabled + AX rectangle) is the
  verified deliverable, exercised against a mocked AX layer in tests.
- Mapping an AX rectangle to a ``computer_use`` *click* coordinate involves
  logical-point -> physical-pixel -> target-space scaling (Retina dpr, multi
  display) that cannot be calibrated without a live macOS AX session:
  rectangles are returned in AX logical points as reported, tagged
  ``coord_space="ax_points"``. Click-coordinate mapping is
  ``unverified — live test required``.
- Gated by the OS accessibility permission (AXIsProcessTrusted); no extra env
  flag — the permission prompt is the guard, same as any screen reader.

pyobjc is a soft dependency (``pyobjc-framework-ApplicationServices`` +
``pyobjc-framework-Cocoa``): absent it, the tool returns an actionable
dependency error rather than raising.
"""

from __future__ import annotations

import asyncio
import platform
from typing import Any

_INSTALL_HINT = (
    "Install the macOS accessibility bridge: "
    "pip install pyobjc-framework-ApplicationServices pyobjc-framework-Cocoa"
)
_PERMISSION_HINT = (
    "Grant Accessibility permission to this process in "
    "System Settings > Privacy & Security > Accessibility, then retry."
)
_MAX_ELEMENTS = 200


def _ax_ready() -> tuple[bool, str]:
    """Return (ready, reason). ready=False carries a human/LLM-actionable reason."""
    # platform.system() (not sys.platform) — mypy narrows the sys.platform
    # literal per --platform, marking the pyobjc block unreachable on the Linux
    # CI runner. A runtime call is not narrowed, so the code stays reachable
    # (and honest) on every platform.
    if platform.system() != "Darwin":
        return False, "ui_probe is macOS-only (accessibility AX API)."
    try:
        from ApplicationServices import AXIsProcessTrusted
    except ImportError:
        return False, _INSTALL_HINT
    if not AXIsProcessTrusted():
        return False, _PERMISSION_HINT
    return True, ""


def _resolve_pid(app_name: str | None) -> int | None:
    """Frontmost app pid when *app_name* is None, else match by localized name.

    Mirrors GenericAgent macljqCtrl._resolve_pid discipline: exact bundle id ->
    exact localized name -> substring, to avoid same-vendor prefix mismatches.
    Returns None when nothing matches.
    """
    from AppKit import NSWorkspace

    ws = NSWorkspace.sharedWorkspace()
    if not app_name:
        front = ws.frontmostApplication()
        return int(front.processIdentifier()) if front else None
    key = app_name.lower()
    apps = list(ws.runningApplications())
    for a in apps:
        if (a.bundleIdentifier() or "") == app_name:
            return int(a.processIdentifier())
    for a in apps:
        if (a.localizedName() or "").lower() == key:
            return int(a.processIdentifier())
    for a in apps:
        if key in (a.localizedName() or "").lower():
            return int(a.processIdentifier())
    return None


def _collect_ax_tree(pid: int, max_depth: int, max_elements: int) -> list[dict[str, Any]]:
    """Enumerate the app's AX control tree → list of element dicts.

    Each dict: depth/role/title/desc/value/enabled/x/y/w/h (AX logical points).
    Zero-size nodes are skipped but still recursed. This is the pyobjc seam —
    tests monkeypatch it to avoid needing a live desktop.
    """
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
        AXValueGetValue,
        kAXChildrenAttribute,
        kAXDescriptionAttribute,
        kAXEnabledAttribute,
        kAXPositionAttribute,
        kAXRoleAttribute,
        kAXSizeAttribute,
        kAXTitleAttribute,
        kAXValueCGPointType,
        kAXValueCGSizeType,
        kAXWindowsAttribute,
    )

    def attr(el: Any, key: Any) -> Any:
        err, val = AXUIElementCopyAttributeValue(el, key, None)
        return val if err == 0 else None

    out: list[dict[str, Any]] = []

    def walk(el: Any, depth: int) -> None:
        if depth > max_depth or len(out) >= max_elements:
            return
        value = attr(el, "AXValue")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            value = None  # AXValueRef (coords etc.) — not a display value
        x = y = w = h = 0.0
        pos, size = attr(el, kAXPositionAttribute), attr(el, kAXSizeAttribute)
        if pos is not None:
            ok, pt = AXValueGetValue(pos, kAXValueCGPointType, None)
            if ok:
                x, y = pt.x, pt.y
        if size is not None:
            ok, sz = AXValueGetValue(size, kAXValueCGSizeType, None)
            if ok:
                w, h = sz.width, sz.height
        if w > 0 and h > 0:
            enabled = attr(el, kAXEnabledAttribute)
            out.append(
                {
                    "depth": depth,
                    "role": attr(el, kAXRoleAttribute),
                    "title": attr(el, kAXTitleAttribute),
                    "desc": attr(el, kAXDescriptionAttribute),
                    "value": value,
                    "enabled": bool(enabled) if enabled is not None else None,
                    "x": round(x),
                    "y": round(y),
                    "w": round(w),
                    "h": round(h),
                }
            )
        for child in attr(el, kAXChildrenAttribute) or []:
            walk(child, depth + 1)

    app_el = AXUIElementCreateApplication(pid)
    for win in attr(app_el, kAXWindowsAttribute) or []:
        walk(win, 0)
    return out


def _format_element(el: dict[str, Any]) -> str:
    """One compact line per element: indent by depth, role/title/value + rect."""
    parts = [f"{el.get('role') or '?'}"]
    for key in ("title", "desc"):
        v = el.get(key)
        if v:
            parts.append(f'"{v}"')
            break
    val = el.get("value")
    if val not in (None, ""):
        parts.append(f"={val!r}")
    if el.get("enabled") is False:
        parts.append("[disabled]")
    cx, cy = el["x"] + el["w"] // 2, el["y"] + el["h"] // 2
    parts.append(f"@({cx},{cy}) {el['w']}x{el['h']}")
    indent = "  " * min(int(el.get("depth", 0)), 8)
    return indent + " ".join(parts)


class UiProbeTool:
    """Read the macOS accessibility tree of an app as compact text."""

    @property
    def name(self) -> str:
        return "ui_probe"

    @property
    def description(self) -> str:
        return (
            "Perceive a macOS app's UI structurally via accessibility "
            "(role/title/value/rect) — cheaper than a screenshot."
        )

    def _run(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.base import tool_error

        ready, reason = _ax_ready()
        if not ready:
            return tool_error(
                f"ui_probe unavailable: {reason}",
                error_type="dependency",
                recoverable=False,
                hint=reason,
            )
        app_name: str | None = kwargs.get("app_name")
        max_depth: int = int(kwargs.get("max_depth", 12))
        try:
            pid = _resolve_pid(app_name)
        except Exception as exc:  # AppKit lookup blew up
            return tool_error(
                f"ui_probe: app lookup failed: {exc}",
                error_type="internal",
                hint="Retry, or pass an exact app_name / bundle id.",
            )
        if pid is None:
            return tool_error(
                f"ui_probe: no running app matching {app_name!r}"
                if app_name
                else "ui_probe: no frontmost application",
                error_type="not_found",
                recoverable=True,
                hint="Open/focus the target app, or pass app_name.",
            )
        try:
            elements = _collect_ax_tree(pid, max_depth, _MAX_ELEMENTS)
        except Exception as exc:
            return tool_error(
                f"ui_probe: AX enumeration failed: {exc}",
                error_type="internal",
                hint="The window may have closed mid-scan; retry.",
                context={"pid": pid},
            )
        lines = [_format_element(e) for e in elements]
        return {
            "result": {
                "pid": pid,
                "app_name": app_name,
                "coord_space": "ax_points",  # logical points; see module docstring
                "element_count": len(elements),
                "truncated": len(elements) >= _MAX_ELEMENTS,
                "elements": "\n".join(lines),
            }
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        # AX/pyobjc calls are blocking C bridges → keep them off the event loop.
        kwargs.pop("_tool_context", None)
        return await asyncio.to_thread(self._run, **kwargs)

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("_tool_context", None)
        return self._run(**kwargs)
