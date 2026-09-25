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
``docs.z.ai/guides/capabilities/thinking-mode``). The picker reads the same
per-model contracts as request shaping. GLM-5.2 and GLM-5.3 have distinct
effort ranges; an unverified model shows ``[fixed]``.

Raw-tty input. Up/Down moves between models, Left/Right cycles the
focused model's valid effort range, Enter confirms, q/ESC cancels.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from core.llm.adapters._openai_common import get_openai_model_spec
from core.llm.model_capabilities import get_anthropic_model_spec
from core.llm.providers.glm import get_glm_model_spec


def supported_efforts(model: str, provider: str) -> tuple[str, ...]:
    """Return the valid effort enum for ``(model, provider)``.

    Empty tuple = "no effort knob" → picker shows ``[fixed]``.
    """
    if provider == "anthropic":
        spec = get_anthropic_model_spec(model)
        return spec.effort_values if spec is not None else ()
    if provider == "openrouter" and model.startswith("openrouter/openai/"):
        model = model.removeprefix("openrouter/openai/")
        provider = "openai"
    if provider in ("openai", "openai-codex"):
        return get_openai_model_spec(model).reasoning_effort_values or ()
    if provider == "glm":
        glm_spec = get_glm_model_spec(model)
        return glm_spec.reasoning_effort_values if glm_spec is not None else ()
    return ()


def default_effort(model: str, provider: str) -> str | None:
    """Use the same model contract as request shaping."""
    if not supported_efforts(model, provider):
        return None
    if provider == "anthropic":
        spec = get_anthropic_model_spec(model)
        return spec.default_effort if spec is not None else None
    if provider == "glm":
        glm_spec = get_glm_model_spec(model)
        return glm_spec.default_effort if glm_spec is not None else None
    return "medium"


def cycle_effort(current: str, levels: tuple[str, ...], direction: int) -> str:
    """Cycle ``current`` by ``direction`` (-1=left, +1=right)."""
    if not levels:
        return current
    try:
        idx = levels.index(current)
    except ValueError:
        # A persisted unsupported value can sit between native levels.
        # Move only on explicit arrow input, in the requested direction without
        # turning a first left-arrow press into a higher effort.
        order = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
        if current in order and all(level in order for level in levels):
            index = order.index(current)
            if direction > 0:
                return next((level for level in levels if order.index(level) > index), levels[-1])
            return next(
                (level for level in reversed(levels) if order.index(level) < index), levels[0]
            )
        return levels[len(levels) // 2]
    return levels[(idx + direction) % len(levels)]


# ---------------------------------------------------------------------------
# Per-model descriptions (Claude Code-style "what's this model for")
# ---------------------------------------------------------------------------

_MODEL_DESCRIPTIONS: dict[str, str] = {
    # Anthropic
    "claude-fable-5-1": "Fable 5.1 · demanding reasoning · 1M context",
    "claude-opus-5-5": "Opus 5.5 · agentic coding · 1M context",
    "claude-opus-5": "Opus 5 · adaptive thinking · 1M context",
    "claude-sonnet-5": "Sonnet 5 · speed and intelligence · 1M context",
    "gpt-6-sol": "GPT-6 Sol · coding and everyday work · API + subscription",
    "gpt-6-luna": "GPT-6 Luna · efficient routine work · API + subscription",
    "glm-5.3": "GLM-5.3 · reasoning · 1M context",
    "glm-5.3-flash": "GLM-5.3 Flash · multimodal · 1M context",
    "glm-5.3-flashx": "GLM-5.3 FlashX · multimodal · PAYG",
    "claude-fable-5": "Fable 5 with 1M context · Frontier reasoning, always-on thinking",
    "claude-opus-4-8": "Opus 4.8 · prior generation · 1M context",
    "claude-opus-4-7": "Opus 4.7 with 1M context · High-capability reasoning",
    "claude-opus-4-6": "Opus 4.6 · Strong general-purpose reasoning",
    "claude-sonnet-4-6": "Sonnet 4.6 · Best for everyday tasks",
    "claude-haiku-4-5": "Haiku 4.5 · Fastest for quick answers",
    # OpenAI / Codex
    "gpt-6-astra": "GPT-6 Astra · hardest end-to-end work · rollout-gated API + subscription",
    "gpt-5.6-sol": "GPT-5.6 Sol · frontier tier, max-effort capable · API + subscription",
    "gpt-5.6-terra": "GPT-5.6 Terra · balanced intelligence/cost · API + subscription",
    "gpt-5.6-luna": "GPT-5.6 Luna · efficient high-volume tier · API + subscription",
    "gpt-5.5": "GPT-5.5 · API + subscription (Codex retirement: 2026-10-14)",
    "gpt-5.4": "GPT-5.4 · Platform API · retired from ChatGPT subscription",
    "gpt-5.4-mini": "GPT-5.4 Mini · Platform API · retired from ChatGPT subscription",
    "gpt-5.3-codex": "GPT-5.3 Codex · Platform API · deprecated for ChatGPT subscription",
    # OpenRouter
    "openrouter/openrouter/free": "Dynamic free-model route · smoke tests only",
    "openrouter/openrouter/auto": "Dynamic model route · variable provider and cost",
    # GLM
    "glm-5.2": "GLM-5.2 · flagship reasoning · 1M-capable, automatic caching",
    "glm-5.1": "GLM-5.1 · hybrid reasoning",
    "glm-5-turbo": "GLM-5 Turbo · historical configured model",
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
    ``(role_name, model_id, effort)``; the final Enter pick is still
    ``(role, model_id)`` and is NOT duplicated into ``staged``. Esc /
    q discards staged picks (``cancelled=True`` + empty ``staged``).
    """

    model_id: str
    effort: str | None  # None → no effort knob applies for this model
    cancelled: bool = False
    role: str = "primary"
    staged: tuple[tuple[str, str, str | None], ...] = ()


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
    ``available`` (M5) toggles an ``(unavailable)`` suffix and dims
    the row for missing credentials or source retirement. ``forced_method`` (M2)
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

    # The running version sits in the title so a stale binary (for example a
    # lagging Homebrew formula lane) is visible the moment the picker opens,
    # instead of surfacing as "model X is missing" confusion.
    from core import __version__

    out.write(f"\n  \033[1mSelect model\033[0m \033[2m· GEODE v{__version__}\033[0m\n")
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
        avail_suffix = "" if available else "  \033[2m(unavailable)\033[0m"
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
    if not levels:
        out.write("  \033[2m· No effort knob for this model\033[0m\n")
    else:
        options = "  ".join(
            f"\033[1;36m{effort_symbol(level)} {effort_label(level)}\033[0m"
            if level == current
            else effort_label(level)
            for level in levels
        )
        out.write(_fit_to_width(f"  Effort: {options}  \033[2m← → to choose\033[0m") + "\n")
        if current not in levels:
            out.write(
                _fit_to_width(
                    f"  Saved effort {current!r} is unsupported; choose with ← → before confirming."
                )
                + "\n"
            )
            lines += 1
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
    role_model_availability: dict[str, dict[str, bool]] | None = None,
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
    effort_model = role_initial_models.get("primary", current_model)
    for mid, prov, *_rest in profiles:
        levels = supported_efforts(mid, prov)
        if not levels:
            effort_per_model[mid] = None
            continue
        # Opening and confirming the current model must not rewrite explicit
        # effort. Unsupported saved values remain separate from the choices;
        # only explicit arrow input selects a supported value.
        if mid == effort_model:
            effort_per_model[mid] = current_effort
        else:
            effort_per_model[mid] = default_effort(mid, prov)

    role_has_effort = dict(role_has_effort or {})
    # PR-PICKER-SPACE-STAGE (2026-06-12) — picks applied with Space per
    # role; returned on Enter, discarded on Esc/q.
    staged_picks: dict[str, tuple[str, str | None]] = {}
    initial_for_render = role_initial_models.get(role_names[role_cursor], current_model)
    show_effort = role_has_effort.get(role_names[role_cursor], True)

    # Source eligibility can differ per role (e.g. subscription primary and
    # explicitly PAYG mutator). Keep one stable row order; only admission dims.
    def profiles_for_role() -> list[tuple[str, str, str, str, bool, str | None]]:
        availability = (role_model_availability or {}).get(role_names[role_cursor], {})
        return [
            (mid, prov, label, cost, availability.get(mid, available), forced)
            for mid, prov, label, cost, available, forced in profiles
        ]

    def effort_is_selectable(model: str, provider: str) -> bool:
        if not role_has_effort.get(role_names[role_cursor], True):
            return True
        levels = supported_efforts(model, provider)
        return not levels or effort_per_model.get(model) in levels

    line_count = _render(
        profiles_for_role(),
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
            chosen_mid, chosen_prov, _label, _cost, available, _forced = profiles_for_role()[cursor]
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
            if not effort_is_selectable(chosen_mid, chosen_prov):
                continue
            _clear_lines(line_count)
            final_role = role_names[role_cursor]
            return PickerResult(
                model_id=chosen_mid,
                effort=(
                    effort_per_model.get(chosen_mid)
                    if role_has_effort.get(final_role, True)
                    else None
                ),
                cancelled=False,
                role=final_role,
                staged=tuple(
                    (role_name, mid, staged_effort)
                    for role_name, (mid, staged_effort) in staged_picks.items()
                    if role_name != final_role
                ),
            )
        if key == _KEY_SPACE and len(role_names) > 1:
            # PR-PICKER-SPACE-STAGE (2026-06-12) — apply the focused row
            # to the focused ROLE without closing, so all three role tabs
            # can be set in one picker session (Enter-only closed after
            # a single pick). The tab strip's per-role marker updates
            # immediately via role_initial_models; Esc discards.
            staged_mid, staged_prov, _label, _cost, staged_available, _forced = profiles_for_role()[
                cursor
            ]
            if staged_available and effort_is_selectable(staged_mid, staged_prov):
                staged_role = role_names[role_cursor]
                staged_picks[staged_role] = (
                    staged_mid,
                    effort_per_model.get(staged_mid)
                    if role_has_effort.get(staged_role, True)
                    else None,
                )
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
            profiles_for_role(),
            cursor,
            effort_per_model,
            initial_for_render,
            roles=role_tabs or None,
            role_cursor=role_cursor,
            role_initials=role_initial_models,
            show_effort=show_effort,
        )
