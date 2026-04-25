"""GEODE mascot — minimal axolotl face, Claude Code-style layout.

3-line layout mirroring Claude Code::

    ╲╲( ◕ ᵕ ◕ )╱╱  GEODE v0.10.0
                     claude-opus-4-6 · autonomous execution agent
                     ~/geode

Expression library (used across UI contexts):
    normal   ( ◕ ᵕ ◕ )   welcome, idle
    happy    ( ◕ ω ◕ )   success, done
    sleepy   ( ─ ᵕ ─ )   startup animation
    wink     ( ◕ ᵕ ˘ )   hint, tip
    sparkle  ( ✧ ᵕ ✧ )   discovery, high score
    thinking ( ◔ ᵕ ◔ )   processing
    surprise ( ◉ △ ◉ )   unexpected
    proud    ( ◕ ε ◕ )   achievement
    cry      ( ◕ д ◕ )   error, failure
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from rich.text import Text

from core.ui.console import console

_G = "mascot.gills"
_B = "mascot.body"
_D = "mascot.outline"


# -- Expressions ----------------------------------------------------------


@dataclass(frozen=True)
class Expression:
    left_eye: str
    mouth: str
    right_eye: str
    eye_style: str = "mascot.body"
    mouth_style: str = "mascot.outline"


EXPR: dict[str, Expression] = {
    "normal": Expression("◕", "ᵕ", "◕"),
    "happy": Expression("◕", "ω", "◕", mouth_style="brand"),
    "sleepy": Expression("─", "ᵕ", "─", eye_style="dim"),
    "wink": Expression("◕", "ᵕ", "˘"),
    "sparkle": Expression("✧", "ᵕ", "✧", eye_style="brand.gold"),
    "thinking": Expression("◔", "ᵕ", "◔"),
    "surprise": Expression("◉", "△", "◉"),
    "proud": Expression("◕", "ε", "◕", mouth_style="brand"),
    "cry": Expression("◕", "д", "◕", mouth_style="error"),
}


# -- Frame builder --------------------------------------------------------


def _face(expr: Expression) -> Text:
    """Build a single mascot face: ╲╲( ◕ ᵕ ◕ )╱╱"""
    t = Text()
    t.append("╲╲", _G)
    t.append("( ", _B)
    t.append(f"{expr.left_eye} ", expr.eye_style)
    t.append(expr.mouth, expr.mouth_style)
    t.append(f" {expr.right_eye}", expr.eye_style)
    t.append(" )", _B)
    t.append("╱╱", _G)
    return t


def _brand_line(
    expr: Expression,
    version: str,
    model: str,
    cwd: str,
) -> Text:
    """Build the full 3-line brand block.

    A 4th line is appended when an active plan is registered for the
    current model (Phase 5 v0.50.0): ``Plan: GLM Coding Lite (used 23/80,
    resets 2h 14m)`` so users see how much subscription quota they have
    left at a glance — the same role Claude Code's account/Usage tab
    plays.
    """
    pad = "                     "  # align lines 2-3 under text start

    t = Text()
    # Line 1: face + GEODE version
    t.append("  ")
    t.append_text(_face(expr))
    t.append("  ")
    t.append("GEODE", "header")
    t.append(f" v{version}")
    t.append("\n")

    # Line 2: model + description
    desc = "autonomous execution agent"
    t.append(f"  {pad}{model} · {desc}", "dim")
    t.append("\n")

    # Line 3: cwd
    t.append(f"  {pad}{cwd}", "dim")

    # Line 4 (optional): active plan summary
    plan_summary = _resolve_active_plan_summary(model)
    if plan_summary:
        t.append("\n")
        t.append(f"  {pad}{plan_summary}", "dim")

    return t


def _resolve_active_plan_summary(model: str) -> str:
    """Render a one-line plan/quota label for the mascot block.

    Returns "" when no plan is registered or routing isn't initialised.
    """
    try:
        from core.auth.plan_registry import resolve_routing

        target = resolve_routing(model)
        if target is None:
            return ""
        plan = target.plan
        label = f"Plan: {plan.display_name}"
        if plan.quota is None:
            return label
        from core.auth.plan_registry import get_plan_registry

        usage = get_plan_registry().usage_for(plan.id)
        remaining = usage.remaining_in_window(plan)
        used = int(usage.weighted_calls)
        if usage.next_reset_at > 0:
            mins = max(0, usage.seconds_until_reset() // 60)
            reset_label = f"resets {mins}m"
        else:
            reset_label = f"window {plan.quota.window_s // 3600}h"
        return f"{label} (used {used}/{plan.quota.max_calls} · {remaining} left · {reset_label})"
    except Exception:
        return ""


# -- Public API -----------------------------------------------------------


def play_mascot_animation(version: str, model: str, cwd: str) -> None:
    """Play a brief startup animation (~0.8s), then print final frame."""
    if not sys.stdout.isatty():
        render_mascot_static(version, model, cwd)
        return

    from rich.live import Live

    frames: list[tuple[str, float]] = [
        ("sleepy", 0.30),
        ("normal", 0.25),
        ("happy", 0.30),
    ]

    try:
        with Live(
            Text(""),
            console=console,
            refresh_per_second=20,
            transient=True,
        ) as live:
            for expr_name, delay in frames:
                block = _brand_line(
                    EXPR[expr_name],
                    version,
                    model,
                    cwd,
                )
                live.update(block)
                time.sleep(delay)

        # Final static frame persists
        render_mascot_static(version, model, cwd)
    except Exception:
        render_mascot_static(version, model, cwd)


def render_mascot_static(version: str, model: str, cwd: str) -> None:
    """Print the mascot brand block (no animation)."""
    block = _brand_line(EXPR["normal"], version, model, cwd)
    console.print()
    console.print(block, highlight=False)
    console.print()
