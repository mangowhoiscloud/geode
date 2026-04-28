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

import sys
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Per-provider effort enum table
# ---------------------------------------------------------------------------

_ANTHROPIC_ADAPTIVE_EFFORTS = ("low", "medium", "high", "max", "xhigh")
_OPENAI_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
_GLM_HYBRID_EFFORTS = ("disabled", "enabled")

_ANTHROPIC_ADAPTIVE_MODELS = frozenset({"claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6"})
_ANTHROPIC_XHIGH_MODELS = frozenset({"claude-opus-4-7"})

_OPENAI_RESPONSES_MODELS_PREFIX = ("gpt-5",)

_GLM_HYBRID_MODELS = frozenset(
    {"glm-4.6", "glm-4.6v", "glm-4.5", "glm-4.5v", "glm-4.5-air", "glm-4.5-flash"}
)
_GLM_ALWAYS_ON_MODELS = frozenset(
    {
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
        # Opus 4.7 official guidance recommends "xhigh" as the *starting
        # point* for coding/agentic — surface it as the default for that
        # model so the picker shows what the model actually wants.
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
    "claude-opus-4-7": "Opus 4.7 with 1M context · Most capable for complex work",
    "claude-opus-4-6": "Opus 4.6 · Strong general-purpose reasoning",
    "claude-sonnet-4-6": "Sonnet 4.6 · Best for everyday tasks",
    "claude-haiku-4-5": "Haiku 4.5 · Fastest for quick answers",
    # OpenAI / Codex
    "gpt-5.5": "GPT-5.5 via Codex Plus · subscription-routed",
    "gpt-5.4": "GPT-5.4 · PAYG balanced reasoning",
    "gpt-5.4-mini": "GPT-5.4 Mini · cheap + fast",
    "gpt-5.3-codex": "GPT-5.3 Codex · code-tuned, reasoning-aware",
    # GLM
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
    """Outcome of the two-axis picker."""

    model_id: str
    effort: str | None  # None → no effort knob applies for this model
    cancelled: bool = False


# ---------------------------------------------------------------------------
# Raw-input loop
# ---------------------------------------------------------------------------

_KEY_UP = "UP"
_KEY_DOWN = "DOWN"
_KEY_LEFT = "LEFT"
_KEY_RIGHT = "RIGHT"
_KEY_ENTER = "ENTER"
_KEY_QUIT = "QUIT"


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
        if ch in ("q", "Q"):
            return _KEY_QUIT
        if ch == "\x03":
            raise KeyboardInterrupt
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _render(
    profiles: list[tuple[str, str, str, str]],
    cursor: int,
    effort_per_model: dict[str, str | None],
    initial_model: str,
) -> int:
    """Render the picker. Returns lines written so the caller can rewind.

    Layout (mirrors the user-supplied spec):

        Select model
        Switch between models. Applies to this session.

        ❯ 1. {label} {default-marker}     {description}
          2. {label}                       {description}
          ...

        ◉ {Effort} effort {(default)} ← → to adjust

        Enter to confirm · Esc to exit
    """
    out = sys.stdout
    lines = 0

    out.write("\n  \033[1mSelect model\033[0m\n")
    out.write(
        "  \033[2mSwitch between LLM models. Applies to this session and future sessions. "
        "Models with effort knobs let you tune reasoning depth with ←→ arrows.\033[0m\n\n"
    )
    lines += 4

    # Compute label column width so descriptions align
    label_width = max(len(p[2]) for p in profiles) + 2

    for i, (mid, _prov, label, _cost) in enumerate(profiles):
        cursor_marker = "❯" if i == cursor else " "
        is_initial = mid == initial_model
        default_check = " ✔" if is_initial else "  "
        index = f"{i + 1}."
        desc = model_description(mid)
        if i == cursor:
            out.write(
                f"  \033[1;36m{cursor_marker} {index} {label:<{label_width}}{default_check}\033[0m"
                f"  \033[2m{desc}\033[0m\n"
            )
        else:
            out.write(
                f"  {cursor_marker} {index} {label:<{label_width}}{default_check}"
                f"  \033[2m{desc}\033[0m\n"
            )
        lines += 1

    # Effort line for the focused model
    out.write("\n")
    lines += 1
    cur_mid, cur_prov, _cur_label, _cur_cost = profiles[cursor]
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
            f"  \033[1;36m{sym}\033[0m {name} effort\033[2m{suffix}\033[0m"
            f"  \033[2m← → to adjust\033[0m\n"
        )
    lines += 1

    out.write("\n  \033[2mEnter to confirm · Esc to exit\033[0m\n")
    lines += 2
    out.flush()
    return lines


def _clear_lines(n: int) -> None:
    out = sys.stdout
    for _ in range(n):
        out.write("\033[F\033[2K")
    out.flush()


def pick_model_and_effort(
    profiles: list[tuple[str, str, str, str]],
    current_model: str,
    current_effort: str,
) -> PickerResult:
    """Run the interactive picker.

    profiles: ordered list of (model_id, provider, label, cost) tuples.
    Returns PickerResult with the chosen model + effort, or
    cancelled=True on q/ESC.
    """
    if not profiles:
        return PickerResult(model_id=current_model, effort=None, cancelled=True)

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

    line_count = _render(profiles, cursor, effort_per_model, current_model)
    while True:
        try:
            key = _read_key()
        except KeyboardInterrupt:
            _clear_lines(line_count)
            return PickerResult(model_id=current_model, effort=current_effort, cancelled=True)
        if key == _KEY_QUIT:
            _clear_lines(line_count)
            return PickerResult(model_id=current_model, effort=current_effort, cancelled=True)
        if key == _KEY_ENTER:
            _clear_lines(line_count)
            chosen_mid, chosen_prov, *_rest = profiles[cursor]
            return PickerResult(
                model_id=chosen_mid,
                effort=effort_per_model.get(chosen_mid),
                cancelled=False,
            )
        if key == _KEY_UP:
            cursor = (cursor - 1) % len(profiles)
        elif key == _KEY_DOWN:
            cursor = (cursor + 1) % len(profiles)
        elif key in (_KEY_LEFT, _KEY_RIGHT):
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
        line_count = _render(profiles, cursor, effort_per_model, current_model)
