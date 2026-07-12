"""Two-axis interactive picker — model (↑↓) + effort level (←→).

v0.59.0 — mirrors the Claude Code ``ModelPicker.tsx`` UX
(`components/ModelPicker.tsx`, `keybindings/defaultBindings.ts`).
User direction 2026-04-28: "방향키로 조절할 수 있게 디벨롭하자.
claude-code 최근 ui/ux를 확인하면 돼" + render-shape spec showing
header + numbered rows + ``◉ xHigh effort (default) ← → to adjust`` +
footer.

Per-provider effort enum is grounded in each provider's official docs
(see ``platform.claude.com/docs/en/build-with-claude/effort``,
``openai-python/src/openai/types/shared/reasoning_effort.py``,
``codex-rs/protocol/src/openai_models.rs:43-51``,
``docs.z.ai/guides/capabilities/thinking-mode``). GLM uses a binary
``thinking.type`` (enabled/disabled) rather than a graded effort —
the picker shows two levels for GLM hybrids; for always-on models the
effort line shows ``[fixed]`` and arrow keys are no-op.

Raw-tty input. Up/Down moves between models, Left/Right cycles the
focused model's valid effort range, Enter confirms, q/ESC cancels.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from core.llm.model_capabilities import (
    ANTHROPIC_ADAPTIVE_MODELS,
    ANTHROPIC_XHIGH_MODELS,
)

# ---------------------------------------------------------------------------
# Per-provider effort enum table
# ---------------------------------------------------------------------------

_ANTHROPIC_ADAPTIVE_EFFORTS = ("low", "medium", "high", "max", "xhigh")
_OPENAI_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
# GPT-5.6 levels are exactly "none, low, medium, high, xhigh, max"
# (developers.openai.com/api/docs/models, 2026-07-13) — no "minimal",
# plus the new "max" above xhigh. Mirrors the adapter spec's
# reasoning_effort_values for the gpt-5.6 entries in _openai_common.py
# so the picker never persists a value the wire would clamp.
_OPENAI_REASONING_EFFORTS_56 = ("none", "low", "medium", "high", "xhigh", "max")
_GLM_HYBRID_EFFORTS = ("disabled", "enabled")

# PR-DRIFT-ANCHORS (2026-06-10) — the capability sets live in the single
# SoT ``core/llm/model_capabilities.py`` (the former "Keep these in sync"
# comment is retired along with the literal copies): the picker surfaces
# exactly the knobs the adapter request-shaping accepts, by construction.
_ANTHROPIC_ADAPTIVE_MODELS = ANTHROPIC_ADAPTIVE_MODELS
_ANTHROPIC_XHIGH_MODELS = ANTHROPIC_XHIGH_MODELS

_OPENAI_RESPONSES_MODELS_PREFIX = ("gpt-5",)

_GLM_HYBRID_MODELS = frozenset(
    {"glm-4.6", "glm-4.6v", "glm-4.5", "glm-4.5v", "glm-4.5-air", "glm-4.5-flash"}
)
_GLM_ALWAYS_ON_MODELS = frozenset(
    {
        # glm-5.2 has a thinking enable/disable + reasoning_effort knob, but the
        # GLM adapter (glm_payg / glm_coding_plan) does not send those params
        # (supports_thinking=False), so surfacing a toggle here would be a
        # picker-vs-adapter disconnect. Classify always-on like the rest of
        # GLM-5.x until the adapter wires thinking through (deferred follow-up).
        "glm-5.2",
        "glm-5.1",
        "glm-5",
        "glm-5-turbo",
        "glm-5v-turbo",
        "glm-4.7",
        "glm-4.7-flash",
        "glm-4.7-flashx",
    }
)


def supported_efforts(model: str, provider: str) -> tuple[str, ...]:
    """Return the valid effort enum for ``(model, provider)``.

    Empty tuple = "no effort knob" → picker shows ``[fixed]``.
    """
    if provider == "anthropic":
        if model in _ANTHROPIC_ADAPTIVE_MODELS:
            if model in _ANTHROPIC_XHIGH_MODELS:
                return _ANTHROPIC_ADAPTIVE_EFFORTS
            return _ANTHROPIC_ADAPTIVE_EFFORTS[:-1]
        return ()
    if provider in ("openai", "openai-codex"):
        if model.startswith("gpt-5.6"):
            return _OPENAI_REASONING_EFFORTS_56
        if any(model.startswith(p) for p in _OPENAI_RESPONSES_MODELS_PREFIX):
            return _OPENAI_REASONING_EFFORTS
        return ()
    if provider == "glm":
        if model in _GLM_HYBRID_MODELS:
            return _GLM_HYBRID_EFFORTS
        if model in _GLM_ALWAYS_ON_MODELS:
            return ()
        return ()
    return ()


def default_effort(model: str, provider: str) -> str | None:
    """The API default for the model — mirrors what the API uses when
    the caller doesn't specify."""
    levels = supported_efforts(model, provider)
    if not levels:
        return None
    if provider == "anthropic":
        # Anthropic API default is "high" per platform.claude.com docs.
        # Opus 4.7+ official guidance recommends "xhigh" as the *starting
        # point* for coding/agentic — surface it as the default for the
        # xhigh-capable models (4.7 / 4.8) so the picker shows what the
        # model actually wants.
        if model in _ANTHROPIC_XHIGH_MODELS:
            return "xhigh"
        return "high"
    if provider in ("openai", "openai-codex"):
        return "medium"
    if provider == "glm":
        return "enabled"
    return levels[0]


def cycle_effort(current: str, levels: tuple[str, ...], direction: int) -> str:
    """Cycle ``current`` by ``direction`` (-1=left, +1=right)."""
    if not levels:
        return current
    try:
        idx = levels.index(current)
    except ValueError:
        return levels[len(levels) // 2]
    return levels[(idx + direction) % len(levels)]


# ---------------------------------------------------------------------------
# Per-model descriptions (Claude Code-style "what's this model for")
# ---------------------------------------------------------------------------

_MODEL_DESCRIPTIONS: dict[str, str] = {
    # Anthropic
    "claude-fable-5": "Fable 5 with 1M context · Frontier reasoning, always-on thinking",
    "claude-opus-4-8": "Opus 4.8 with 1M context · Most capable for complex work",
    "claude-opus-4-7": "Opus 4.7 with 1M context · High-capability reasoning",
    "claude-opus-4-6": "Opus 4.6 · Strong general-purpose reasoning",
    "claude-sonnet-4-6": "Sonnet 4.6 · Best for everyday tasks",
    "claude-haiku-4-5": "Haiku 4.5 · Fastest for quick answers",
    # OpenAI / Codex
    "gpt-5.6-sol": "GPT-5.6 Sol · frontier tier, max-effort capable · API + subscription",
    "gpt-5.6-terra": "GPT-5.6 Terra · balanced intelligence/cost · API + subscription",
    "gpt-5.6-luna": "GPT-5.6 Luna · efficient high-volume tier · API + subscription",
    "gpt-5.5": "GPT-5.5 via ChatGPT subscription · subscription-routed",
    "gpt-5.4": "GPT-5.4 · PAYG balanced reasoning",
    "gpt-5.4-mini": "GPT-5.4 Mini · cheap + fast",
    "gpt-5.3-codex": "GPT-5.3 Codex · code-tuned, reasoning-aware",
    # GLM
    "glm-5.2": "GLM-5.2 · flagship reasoning · 1M-capable, automatic caching",
    "glm-5.1": "GLM-5.1 · always-on reasoning",
    "glm-5-turbo": "GLM-5 Turbo · faster + cheaper",
    "glm-4.7-flash": "GLM-4.7 Flash · low-latency tier",
}


def model_description(model_id: str) -> str:
    """Friendly per-model blurb for the picker. Falls back to the bare ID."""
    return _MODEL_DESCRIPTIONS.get(model_id, model_id)


# ---------------------------------------------------------------------------
# Effort symbols — mirror Claude Code's ◑/◐/◕/◉ disc family
# ---------------------------------------------------------------------------

_EFFORT_SYMBOLS: dict[str, str] = {
    # Graded levels — disc fills as effort climbs
    "none": "○",
    "minimal": "◔",
    "disabled": "○",
    "low": "◑",
    "medium": "◐",
    "high": "◕",
    "max": "◉",
    "xhigh": "◉",
    "enabled": "●",
}


def effort_symbol(level: str) -> str:
    return _EFFORT_SYMBOLS.get(level, "·")


def effort_label(level: str) -> str:
    """Display-cased effort name. ``xhigh`` → ``xHigh``, otherwise capitalised."""
    if level == "xhigh":
        return "xHigh"
    return level.capitalize()


@dataclass
class PickerResult:
    """Outcome of the picker.

    PR-A (2026-05-21) — added ``role`` so a single Enter persists to
    the *currently focused* agent role (primary / reflection / future:
    mutator). Defaults to ``"primary"`` for backward compatibility
    with callers that don't pass ``roles``.

    PR-PICKER-SPACE-STAGE (2026-06-12) — ``staged`` carries per-role
    picks applied with Space WITHOUT closing the picker (operator:
    three role tabs, Enter-only meant one pick per open). Each entry is
    ``(role_name, model_id)``; the final Enter pick is still
    ``(role, model_id)`` and is NOT duplicated into ``staged``. Esc /
    q discards staged picks (``cancelled=True`` + empty ``staged``).
    """

    model_id: str
    effort: str | None  # None → no effort knob applies for this model
    cancelled: bool = False
    role: str = "primary"
    staged: tuple[tuple[str, str], ...] = ()


# ---------------------------------------------------------------------------
# Raw-input loop
# ---------------------------------------------------------------------------

_KEY_UP = "UP"
_KEY_DOWN = "DOWN"
_KEY_LEFT = "LEFT"
_KEY_RIGHT = "RIGHT"
_KEY_ENTER = "ENTER"
_KEY_QUIT = "QUIT"
_KEY_TAB = "TAB"
_KEY_SPACE = "SPACE"


def _read_key() -> str:
    """Block until a single key press, return a normalised name."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 != "[":
                return _KEY_QUIT
            ch3 = sys.stdin.read(1)
            return {"A": _KEY_UP, "B": _KEY_DOWN, "C": _KEY_RIGHT, "D": _KEY_LEFT}.get(ch3, "")
        if ch in ("\r", "\n"):
            return _KEY_ENTER
        if ch == "\t":
            return _KEY_TAB
        if ch == " ":
            return _KEY_SPACE
        if ch in ("q", "Q"):
            return _KEY_QUIT
        if ch == "\x03":
            raise KeyboardInterrupt
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _fit_to_width(line: str, width: int | None = None) -> str:
    """Truncate ``line`` so its VISIBLE length fits one terminal row.

    PR-PICKER-NO-WRAP (2026-06-12) — ``_clear_lines`` rewinds exactly the
    number of logical lines ``_render`` counted; a line that soft-wraps
    occupies more physical rows than counted, so each repaint cleared too
    few rows and the picker scrolled upward over prior output. ANSI SGR
    sequences are zero-width; a truncated line gets a reset appended so
    an open color never bleeds into the next row.
    """
    if width is None:
        import shutil

        width = shutil.get_terminal_size(fallback=(120, 24)).columns
    budget = max(width - 1, 10)
    visible = 0
    out_chars: list[str] = []
    i = 0
    while i < len(line):
        match = _ANSI_RE.match(line, i)
        if match:
            out_chars.append(match.group(0))
            i = match.end()
            continue
        if visible >= budget:
            out_chars.append("\033[0m")
            break
        out_chars.append(line[i])
        visible += 1
        i += 1
    return "".join(out_chars)


def _render(
    profiles: list[tuple[str, str, str, str, bool, str | None]],
    cursor: int,
    effort_per_model: dict[str, str | None],
    initial_model: str,
    *,
    roles: list[tuple[str, str, str]] | None = None,
    role_cursor: int = 0,
    role_initials: dict[str, str] | None = None,
    show_effort: bool = True,
) -> int:
    """Render the picker. Returns lines written so the caller can rewind.

    Tuple shape: ``(model_id, provider, label, cost, available, forced_method)``.
    ``available`` (M5) toggles a ``(login required)`` suffix and dims
    the row when no credential route exists. ``forced_method`` (M2)
    is ``None`` when ``settings.forced_login_method[provider]`` is at
    its default; non-None values surface a ``(forced: <method>)``
    badge so a user who pinned the PAYG escape hatch sees the
    override before selecting.

    PR-A (2026-05-21) — when ``roles`` is supplied
    (``[(name, label, description), ...]``), a role-tab strip is
    drawn at the top with the currently-focused role highlighted.
    ``role_initials`` carries the current per-role model id so each
    tab can show its own ✔ marker (the focused role's model gets the
    ✔; other roles' selections appear next to their tab label).
    """
    out = sys.stdout
    lines = 0

    out.write("\n  \033[1mSelect model\033[0m\n")
    out.write(
        _fit_to_width(
            "  \033[2mSwitch between LLM models. Applies to this session and future sessions. "
            "Models with effort knobs let you tune reasoning depth with ←→ arrows.\033[0m"
        )
        + "\n\n"
    )
    lines += 4

    # PR-A — role tabs above the model list. Only render when more
    # than one role is registered; single-role callers (legacy
    # behaviour) skip the strip so the existing UX is unchanged.
    if roles and len(roles) > 1:
        tab_parts: list[str] = []
        for i, (_name, role_label, _desc) in enumerate(roles):
            if i == role_cursor:
                tab_parts.append(f"\033[1;36m[ {role_label} ]\033[0m")
            else:
                tab_parts.append(f"\033[2m[ {role_label} ]\033[0m")
        out.write(
            _fit_to_width("  " + " ".join(tab_parts) + "  \033[2m(Tab to cycle)\033[0m") + "\n"
        )
        if 0 <= role_cursor < len(roles):
            out.write(_fit_to_width(f"  \033[2m{roles[role_cursor][2]}\033[0m") + "\n")
        out.write("\n")
        lines += 3

    # Compute label column width so descriptions align
    label_width = max(len(p[2]) for p in profiles) + 2

    for i, (mid, _prov, label, _cost, available, forced_method) in enumerate(profiles):
        cursor_marker = "❯" if i == cursor else " "
        is_initial = mid == initial_model
        default_check = " ✔" if is_initial else "  "
        index = f"{i + 1}."
        desc = model_description(mid)
        avail_suffix = "" if available else "  \033[2m(login required)\033[0m"
        forced_suffix = f"  \033[2m(forced: {forced_method})\033[0m" if forced_method else ""
        suffixes = f"{avail_suffix}{forced_suffix}"
        if i == cursor:
            highlight = "1;36" if available else "0;36"
            row = (
                f"  \033[{highlight}m{cursor_marker} {index} {label:<{label_width}}"
                f"{default_check}\033[0m"
                f"  \033[2m{desc}\033[0m{suffixes}"
            )
        else:
            row_open = "\033[2m" if not available else ""
            row_close = "\033[0m" if not available else ""
            row = (
                f"  {row_open}{cursor_marker} {index} {label:<{label_width}}{default_check}"
                f"{row_close}  \033[2m{desc}\033[0m{suffixes}"
            )
        # PR-PICKER-NO-WRAP (2026-06-12) — clamp each row to the terminal
        # width. A row that WRAPS occupies 2+ physical lines while the
        # repaint accounting counts 1, so every ↑↓ repaint cleared too few
        # lines and the picker crept upward over previous output
        # (operator: "화살표로 이동하면 위로 출력이 쏠려").
        out.write(_fit_to_width(row) + "\n")
        lines += 1

    # Effort line for the focused model. PR-A fix-up #1 — when the
    # focused role has ``has_effort=False`` (e.g. reflection) we
    # render an explicit "no effort knob" hint instead of the disc +
    # ← → adjuster, which the dispatcher would silently ignore.
    out.write("\n")
    lines += 1
    # PR-PICKER-ROLE-CONFIRM (2026-06-12) — name the focused role in the
    # confirm hint. Operators on the Reflection / Mutator tabs reported
    # "no key confirms the change": Enter always confirmed, but the hint
    # said only "Enter to confirm" (and an unchanged pick closed with no
    # output at all — fixed in commands/model.py). The role-named hint
    # makes the confirm target explicit.
    focused_role_label = ""
    if roles and len(roles) > 1 and 0 <= role_cursor < len(roles):
        focused_role_label = roles[role_cursor][1]
    # PR-PICKER-SPACE-STAGE (2026-06-12) — with multiple role tabs, Space
    # applies to the focused role WITHOUT closing (set all three in one
    # session); Enter confirms everything and closes.
    confirm_hint = (
        f"Space to set {focused_role_label} · Tab next role · "
        "Enter to confirm & close · Esc to discard"
        if focused_role_label
        else "Enter to confirm · Esc to exit"
    )
    if not show_effort:
        out.write("  \033[2m· No effort knob for this role · ←→ disabled\033[0m\n")
        lines += 1
        out.write(_fit_to_width(f"\n  \033[2m{confirm_hint}\033[0m") + "\n")
        lines += 2
        out.flush()
        return lines
    cur_mid, cur_prov, _cur_label, _cur_cost, _cur_avail, _cur_forced = profiles[cursor]
    levels = supported_efforts(cur_mid, cur_prov)
    current = effort_per_model.get(cur_mid)
    default = default_effort(cur_mid, cur_prov)
    if not levels:
        out.write("  \033[2m· No effort knob for this model\033[0m\n")
    else:
        sym = effort_symbol(current or default or "")
        name = effort_label(current or default or "")
        suffix = " (default)" if current == default else ""
        out.write(
            _fit_to_width(
                f"  \033[1;36m{sym}\033[0m {name} effort\033[2m{suffix}\033[0m"
                f"  \033[2m← → to adjust\033[0m"
            )
            + "\n"
        )
    lines += 1

    out.write(_fit_to_width(f"\n  \033[2m{confirm_hint}\033[0m") + "\n")
    lines += 2
    out.flush()
    return lines


def _clear_lines(n: int) -> None:
    out = sys.stdout
    for _ in range(n):
        out.write("\033[F\033[2K")
    out.flush()


def pick_model_and_effort(
    profiles: list[tuple[str, str, str, str, bool, str | None]],
    current_model: str,
    current_effort: str,
    *,
    roles: list[tuple[str, str, str]] | None = None,
    initial_role: str = "primary",
    role_initial_models: dict[str, str] | None = None,
    role_has_effort: dict[str, bool] | None = None,
) -> PickerResult:
    """Run the interactive picker.

    profiles: ordered list of
    ``(model_id, provider, label, cost, available, forced_method)`` tuples.
    The ``available`` flag (M5) marks whether the user has a usable
    credential — selecting an unavailable model returns the existing
    selection unchanged so the caller can show a ``(login required)``
    notice instead of bouncing off ``_check_provider_key`` later.
    ``forced_method`` (M2) is the normalised value of
    ``settings.forced_login_method[provider]`` when the user has
    explicitly overridden the default routing (``"apikey"`` etc.), or
    ``None`` when at default — the picker renders a ``(forced: …)``
    badge so the override stays visible at selection time.

    PR-A (2026-05-21) — when ``roles`` is supplied
    (``[(name, label, description), ...]`` for each registered agent
    role), the picker draws a tab strip at the top and lets Tab cycle
    between roles. ``initial_role`` selects the focused tab on entry
    (must match one of the names in ``roles`` or defaults to the
    first). ``role_initial_models`` carries the *current* model id
    per role so cycling Tab re-anchors the cursor to that role's
    selection. When ``roles`` is None or has length 1, the picker
    behaves identically to its single-axis predecessor.

    Returns PickerResult with the chosen model + effort + role, or
    cancelled=True on q/ESC.
    """
    if not profiles:
        return PickerResult(model_id=current_model, effort=None, cancelled=True)

    # Normalise role state. Roles list of one (or None) means
    # single-role mode — same UX as before.
    if roles is None or len(roles) <= 1:
        role_names: list[str] = ["primary"]
        role_tabs: list[tuple[str, str, str]] = []
    else:
        role_names = [r[0] for r in roles]
        role_tabs = list(roles)
    role_cursor = role_names.index(initial_role) if initial_role in role_names else 0
    role_initial_models = dict(role_initial_models or {})
    # Per-role anchor model — falls back to ``current_model`` (which
    # is the focused role's current selection) when not supplied.
    role_initial_models.setdefault(role_names[role_cursor], current_model)

    cursor = next(
        (i for i, (mid, *_rest) in enumerate(profiles) if mid == current_model),
        0,
    )

    effort_per_model: dict[str, str | None] = {}
    for mid, prov, *_rest in profiles:
        levels = supported_efforts(mid, prov)
        if not levels:
            effort_per_model[mid] = None
            continue
        if mid == current_model and current_effort in levels:
            effort_per_model[mid] = current_effort
        else:
            effort_per_model[mid] = default_effort(mid, prov)

    role_has_effort = dict(role_has_effort or {})
    # PR-PICKER-SPACE-STAGE (2026-06-12) — picks applied with Space per
    # role; returned on Enter, discarded on Esc/q.
    staged_picks: dict[str, str] = {}
    initial_for_render = role_initial_models.get(role_names[role_cursor], current_model)
    show_effort = role_has_effort.get(role_names[role_cursor], True)
    line_count = _render(
        profiles,
        cursor,
        effort_per_model,
        initial_for_render,
        roles=role_tabs or None,
        role_cursor=role_cursor,
        role_initials=role_initial_models,
        show_effort=show_effort,
    )
    while True:
        try:
            key = _read_key()
        except KeyboardInterrupt:
            _clear_lines(line_count)
            return PickerResult(
                model_id=current_model,
                effort=current_effort,
                cancelled=True,
                role=role_names[role_cursor],
            )
        if key == _KEY_QUIT:
            _clear_lines(line_count)
            return PickerResult(
                model_id=current_model,
                effort=current_effort,
                cancelled=True,
                role=role_names[role_cursor],
            )
        if key == _KEY_ENTER:
            chosen_mid, chosen_prov, _label, _cost, available, _forced = profiles[cursor]
            if not available:
                # M5 — block the selection so the caller can render a
                # "Login first" hint. Treat as cancellation so settings
                # don't shift to a model the LLM call would reject.
                # Staged picks are intentionally discarded — a cancel
                # exit never half-applies.
                _clear_lines(line_count)
                return PickerResult(
                    model_id=current_model,
                    effort=current_effort,
                    cancelled=True,
                    role=role_names[role_cursor],
                )
            _clear_lines(line_count)
            final_role = role_names[role_cursor]
            return PickerResult(
                model_id=chosen_mid,
                effort=effort_per_model.get(chosen_mid),
                cancelled=False,
                role=final_role,
                staged=tuple(
                    (role_name, mid)
                    for role_name, mid in staged_picks.items()
                    if role_name != final_role
                ),
            )
        if key == _KEY_SPACE and len(role_names) > 1:
            # PR-PICKER-SPACE-STAGE (2026-06-12) — apply the focused row
            # to the focused ROLE without closing, so all three role tabs
            # can be set in one picker session (Enter-only closed after
            # a single pick). The tab strip's per-role marker updates
            # immediately via role_initial_models; Esc discards.
            staged_mid, _prov, _label, _cost, staged_available, _forced = profiles[cursor]
            if staged_available:
                staged_role = role_names[role_cursor]
                staged_picks[staged_role] = staged_mid
                role_initial_models[staged_role] = staged_mid
        elif key == _KEY_TAB and len(role_names) > 1:
            role_cursor = (role_cursor + 1) % len(role_names)
            # Re-anchor cursor to the new role's current model so the
            # picker's highlight follows the role-switch instead of
            # staying on whichever row the user was hovering.
            new_anchor = role_initial_models.get(role_names[role_cursor])
            if new_anchor is not None:
                cursor = next(
                    (i for i, (mid, *_rest) in enumerate(profiles) if mid == new_anchor),
                    cursor,
                )
        elif key == _KEY_UP:
            cursor = (cursor - 1) % len(profiles)
        elif key == _KEY_DOWN:
            cursor = (cursor + 1) % len(profiles)
        elif key in (_KEY_LEFT, _KEY_RIGHT):
            # PR-A fix-up #1 — block ←→ entirely for roles whose
            # has_effort=False so the user gets no false signal that
            # they're tuning anything.
            if not role_has_effort.get(role_names[role_cursor], True):
                continue
            mid, prov, *_rest = profiles[cursor]
            levels = supported_efforts(mid, prov)
            if not levels:
                continue
            current = effort_per_model.get(mid) or default_effort(mid, prov) or levels[0]
            new = cycle_effort(current, levels, direction=1 if key == _KEY_RIGHT else -1)
            effort_per_model[mid] = new
        else:
            continue
        _clear_lines(line_count)
        initial_for_render = role_initial_models.get(role_names[role_cursor], current_model)
        show_effort = role_has_effort.get(role_names[role_cursor], True)
        line_count = _render(
            profiles,
            cursor,
            effort_per_model,
            initial_for_render,
            roles=role_tabs or None,
            role_cursor=role_cursor,
            role_initials=role_initial_models,
            show_effort=show_effort,
        )
