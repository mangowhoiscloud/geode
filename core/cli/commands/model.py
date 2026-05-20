"""``/model`` slash command + interactive model picker.

Hosts ``cmd_model``, ``_apply_model``, and ``_interactive_model_picker``.
Extracted from the monolithic ``core/cli/commands.py`` (Tier 3 #9) — every
function body is preserved byte-identical from the legacy module.

Tests that monkeypatch ``core.cli.commands.console`` /
``core.cli.commands._upsert_env`` / ``core.cli.commands._check_provider_key``
reach the call sites here through the deferred ``import core.cli.commands
as _pkg`` lookup, mirroring the pattern used by ``core/ui/agentic_ui``.
"""

from __future__ import annotations

import logging

from core.cli.commands._state import (
    _MODEL_INDEX,
    MODEL_PROFILES,
    ModelProfile,
    forced_login_method_for,
    model_available,
)

log = logging.getLogger(__name__)


def _apply_model(selected: ModelProfile, *, effort: str | None = None) -> None:
    """Apply a model selection — update settings + .env.

    v0.59.0 — accepts an optional ``effort`` parameter coming from the
    two-axis picker (``effort_picker.pick_model_and_effort``). When
    set, persists to ``settings.agentic_effort`` + ``GEODE_AGENTIC_EFFORT``
    env var so the next AgenticLoop turn picks it up via
    ``_sync_model_from_settings`` (same hot-swap pathway as the model
    field). ``None`` means "no effort knob applies for this model" —
    leave the existing setting untouched.

    Includes context window guard: blocks downgrade when current context
    exceeds 80% of the target model's window.
    """
    from core.cli import commands as _pkg
    from core.config import settings

    old = settings.model
    old_effort = getattr(settings, "agentic_effort", "high")
    same_model = selected.id == old
    same_effort = effort is None or effort == old_effort

    if same_model and same_effort:
        _pkg.console.print(f"  [muted]Already using {selected.label}[/muted]")
        _pkg.console.print()
        return

    _pkg._check_provider_key(selected)

    # --- Context Window Guard ---
    ctx = _pkg.get_conversation_context()
    if ctx is not None and ctx.messages:
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW
        from core.orchestration.context_monitor import estimate_message_tokens

        current_tokens = estimate_message_tokens(ctx.messages)
        target_window = MODEL_CONTEXT_WINDOW.get(selected.id, 200_000)
        threshold = int(target_window * 0.8)

        if current_tokens > threshold:
            _pkg.console.print()
            _pkg.console.print(
                f"  [warning]Context guard: {current_tokens:,} tokens "
                f"exceeds {selected.label} limit "
                f"({target_window:,} x 80% = {threshold:,})[/warning]"
            )
            _pkg.console.print("  [muted]Run /compact or /clear first, then retry /model.[/muted]")
            _pkg.console.print()
            return

    # v0.61.0 — picker choices now persist to BOTH .env (session) and
    # .geode/config.toml (durable). Previously the comment claimed
    # config.toml sync but only .env was actually written; on next
    # session the user got the env-loaded value, but only because .env
    # happens to survive — wiping .env would lose the choice silently.
    # 3-codebase consensus (Hermes/Codex/Claude Code all persist picker
    # choices to durable config).
    from core.utils.env_io import upsert_config_toml

    if not same_model:
        settings.model = selected.id
        _pkg._upsert_env("GEODE_MODEL", selected.id)
        upsert_config_toml("llm", "primary_model", selected.id)
    if effort is not None and effort != old_effort:
        try:
            object.__setattr__(settings, "agentic_effort", effort)
        except Exception:
            log.debug("Could not persist agentic_effort to settings", exc_info=True)
        _pkg._upsert_env("GEODE_AGENTIC_EFFORT", effort)
        upsert_config_toml("agentic", "effort", effort)

    # Model hot-swap is deferred: AgenticLoop._sync_model_from_settings_async()
    # checks settings.model at the start of each round and applies
    # the change safely between LLM calls. Direct loop.update_model_async()
    # during tool execution caused adapter swap mid-call → crash.

    if not same_model and effort is not None:
        _pkg.console.print(
            f"  [success]Model[/success]  {old} → [bold]{selected.label}[/bold]"
            f"  [muted]({selected.id} · effort={effort})[/muted]"
        )
    elif not same_model:
        _pkg.console.print(
            f"  [success]Model[/success]  {old} → [bold]{selected.label}[/bold]"
            f"  [muted]({selected.id})[/muted]"
        )
    elif effort is not None:
        _pkg.console.print(
            f"  [success]Effort[/success]  {old_effort} → [bold]{effort}[/bold]"
            f"  [muted](model unchanged: {selected.label})[/muted]"
        )
    _pkg.console.print()


def _interactive_model_picker() -> None:
    """Two-axis interactive picker — model (↑↓) + effort level (←→).

    v0.59.0 — replaces the legacy single-axis ``TerminalMenu`` with the
    Claude Code ``ModelPicker.tsx`` pattern. Per-provider effort enum
    in ``core/cli/effort_picker.py``. Ctrl+C / q / ESC cancels; Enter
    confirms both the model and its current effort selection.
    """
    from core.cli import commands as _pkg
    from core.cli.effort_picker import pick_model_and_effort
    from core.config import settings

    profiles = [
        (
            p.id,
            p.provider,
            p.label,
            p.cost,
            model_available(p.id),
            forced_login_method_for(p.provider),
        )
        for p in MODEL_PROFILES
    ]
    current_effort = getattr(settings, "agentic_effort", "high")
    result = pick_model_and_effort(profiles, settings.model, current_effort)
    if result.cancelled:
        # M5 — surface the "login first" path explicitly when the user
        # tried to pick an unavailable model. ``pick_model_and_effort``
        # returns ``cancelled=True`` for both q/ESC and the blocked-Enter
        # case; if the cursor still points at an unavailable entry we
        # assume the latter.
        _pkg.console.print("  [muted]Cancelled[/muted]")
        _pkg.console.print(
            "  [muted]Tip: run `/login` to add credentials for any model "
            "marked (login required).[/muted]"
        )
        _pkg.console.print()
        return

    chosen_profile = next(p for p in MODEL_PROFILES if p.id == result.model_id)
    _apply_model(chosen_profile, effort=result.effort)


def cmd_model(args: str) -> None:
    """Handle /model command (OpenClaw Auth Profile Rotation pattern).

    /model         → interactive arrow-key picker
    /model 2       → select by number
    /model gpt-5.4 → select by name
    """
    from core.cli import commands as _pkg

    arg = args.strip()

    # /model (no args) → interactive picker (requires tty)
    if not arg:
        import sys

        if not sys.stdin.isatty():
            # Non-interactive: show model list instead of crashing
            from core.config import settings

            _pkg.console.print()
            _pkg.console.print("  [header]Models[/header]")
            for i, p in enumerate(MODEL_PROFILES, 1):
                marker = " ←" if p.id == settings.model else ""
                # M5 — surface login-state so a curl-driven caller (or a
                # user who pipes /model into stdin) sees which entries
                # would 401 before they hit them.
                avail = "" if model_available(p.id) else "  [muted](login required)[/muted]"
                # M2 — same row also surfaces a per-provider
                # ``forced_login_method`` override (Codex CLI parity).
                forced = forced_login_method_for(p.provider)
                forced_suffix = f"  [muted](forced: {forced})[/muted]" if forced else ""
                _pkg.console.print(
                    f"  {i}. {p.label:<12} {p.provider:<10} {p.cost}{marker}{avail}{forced_suffix}"
                )
            _pkg.console.print()
            _pkg.console.print("  [muted]Usage: /model <number> or /model <name>[/muted]")
            _pkg.console.print()
            return
        _interactive_model_picker()
        return

    # Resolve by number or name
    selected: ModelProfile | None = None

    if arg.isdigit():
        idx = int(arg) - 1
        if 0 <= idx < len(MODEL_PROFILES):
            selected = MODEL_PROFILES[idx]
        else:
            _pkg.console.print(
                f"  [warning]Invalid number: {arg} (1-{len(MODEL_PROFILES)})[/warning]"
            )
            _pkg.console.print()
            return
    else:
        selected = _MODEL_INDEX.get(arg)
        if not selected:
            arg_norm = arg.lower().replace("-", "").replace(" ", "").replace("_", "")
            for p in MODEL_PROFILES:
                id_norm = p.id.lower().replace("-", "").replace(" ", "").replace("_", "")
                label_norm = p.label.lower().replace("-", "").replace(" ", "").replace("_", "")
                if arg_norm in id_norm or arg_norm in label_norm:
                    selected = p
                    break

    if not selected:
        _pkg.console.print(f"  [warning]Unknown model: {arg}[/warning]")
        _pkg.console.print("  [muted]Available:[/muted]", end="")
        for p in MODEL_PROFILES:
            _pkg.console.print(f" [muted]{p.id}[/muted]", end="")
        _pkg.console.print()
        _pkg.console.print()
        return

    if not model_available(selected.id):
        # M5 — explicit /model <name> can still trip the credential
        # path. Surface the "login required" hint *before* applying so
        # the user doesn't see settings flip then immediately get the
        # _check_provider_key warning on next call.
        _pkg.console.print(
            f"  [warning]{selected.label} ({selected.provider}) "
            "has no authenticated profile.[/warning]"
        )
        _pkg.console.print(
            f"  [muted]Run `/login {selected.provider}` (OAuth) or "
            f"`/login add` (API key) first, then retry "
            f"`/model {selected.id}`.[/muted]"
        )
        _pkg.console.print()
        return

    _apply_model(selected)
