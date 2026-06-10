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
    AGENT_ROLES,
    MODEL_PROFILES,
    AgentRole,
    ModelProfile,
    forced_login_method_for,
    model_available,
    role_by_name,
)

log = logging.getLogger(__name__)


def _current_model_for_role(role: AgentRole) -> str:
    """Read the current model id for ``role`` from ``settings`` (or the
    role-specific toml section when the role has no Settings attr).

    Centralised reader so the picker, non-tty fallback, and post-apply
    confirmation all consult the same source. Falls back to an empty
    string if the field is unset.

    PR-G2 (2026-05-21) — roles with ``settings_field=""`` (e.g.
    mutator) don't live on Settings; their durable SoT is the toml
    section + key. Read it lazily so the picker shows what the
    runner will actually invoke at dispatch time. Returns ``""`` when
    the toml key is absent — caller renders this as "(inherits
    Settings.model)".
    """
    from core.config import settings

    if not role.settings_field:
        return _read_toml_value(role.toml_section, role.toml_key)
    return getattr(settings, role.settings_field, "") or ""


def _read_toml_value(section: str, key: str) -> str:
    """Read ``[<section>] <key>`` from ``~/.geode/config.toml``.

    Returns ``""`` when the file is missing, the section is missing,
    the key is missing, or any parse error occurs — the picker
    renders empty as "(inherits Settings.model)" so a silent miss
    falls back to the global model rather than crashing the slash.
    Used by the PR-G2 mutator role (and any future role with
    ``settings_field=""``)."""
    import tomllib

    from core.paths import GLOBAL_CONFIG_TOML

    if not GLOBAL_CONFIG_TOML.is_file():
        return ""
    try:
        data = tomllib.loads(GLOBAL_CONFIG_TOML.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    cursor: object = data
    for part in section.split("."):
        if not isinstance(cursor, dict):
            return ""
        cursor = cursor.get(part)
        if cursor is None:
            return ""
    if not isinstance(cursor, dict):
        return ""
    value = cursor.get(key)
    return str(value) if value else ""


def _apply_model(
    selected: ModelProfile,
    *,
    effort: str | None = None,
    role: str = "primary",
    scope: str = "project",
) -> None:
    """Apply a model selection — update settings + .env + config.toml.

    v0.59.0 — accepts an optional ``effort`` parameter coming from the
    two-axis picker (``effort_picker.pick_model_and_effort``). When
    set, persists to ``settings.agentic_effort`` + ``GEODE_AGENTIC_EFFORT``
    env var so the next AgenticLoop turn picks it up via
    ``_sync_model_from_settings`` (same hot-swap pathway as the model
    field). ``None`` means "no effort knob applies for this model" —
    leave the existing setting untouched.

    PR-A (2026-05-21) — ``role`` selects which agent's model knob is
    updated. ``"primary"`` (default) writes ``settings.model`` + ``[llm]
    primary_model``; ``"reflection"`` writes the PR-3 C-2 knob
    (``settings.cognitive_reflection_model`` + ``[cognitive]
    reflection_model``). Effort is *only* applied when the role declares
    ``has_effort=True`` — the reflection node has no effort axis.

    ``scope`` picks the durable config target (precedence: CLI > env >
    project ``.geode/config.toml`` > global ``~/.geode/config.toml`` >
    routing default). ``"project"`` (default) persists the *primary*
    switch to the session's project config **only** — the global
    ``GEODE_MODEL`` env is intentionally NOT written, since env outranks
    the project TOML and would leak a per-workspace choice to every
    project + shadow the project ``primary_model`` on reload. ``"global"``
    writes ``~/.geode/config.toml`` + ``GEODE_MODEL`` env. Non-primary
    roles (reflection / mutator) are daemon-global and always write env.

    Includes context window guard: blocks downgrade when current context
    exceeds 80% of the target model's window (primary role only —
    reflection runs on a separate cheap model and doesn't share the
    main loop's context).
    """
    from core.cli import commands as _pkg
    from core.config import settings
    from core.config.env_io import upsert_config_toml

    role_def = role_by_name(role)
    old = _current_model_for_role(role_def)
    old_effort = getattr(settings, "agentic_effort", "high")
    same_model = selected.id == old
    same_effort = not role_def.has_effort or effort is None or effort == old_effort

    if same_model and same_effort:
        _pkg.console.print(
            f"  [muted]Already using {selected.label} for {role_def.label.lower()}[/muted]"
        )
        _pkg.console.print()
        return

    _pkg._check_provider_key(selected)

    # --- Context Window Guard --- (primary only — reflection runs in
    # a clean-context sandbox per PR-3 C-2 design, so the main loop's
    # context size doesn't constrain its model choice).
    if role_def.name == "primary":
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
                _pkg.console.print(
                    "  [muted]Run /compact or /clear first, then retry /model.[/muted]"
                )
                _pkg.console.print()
                return

    # v0.61.0 — picker choices now persist to BOTH .env (session) and
    # .geode/config.toml (durable). 3-codebase consensus (Hermes/Codex/
    # Claude Code all persist picker choices to durable config).
    if not same_model:
        # Pydantic v2 ``Settings`` is frozen on instance attribute
        # writes via __setattr__; the legacy primary-model path used
        # direct attribute assignment which works for the ``model``
        # field but not for arbitrary new fields. ``object.__setattr__``
        # bypasses validation so the picker's choice lands regardless
        # of the field's pydantic descriptor type.
        #
        # PR-G2 (2026-05-21) — roles with ``settings_field=""`` (e.g.
        # mutator) don't live on Settings; skip the attribute write
        # and persist via env + toml only. The runner's lazy
        # ``load_self_improving_loop_config()`` will pick up the new
        # toml value on the next dispatch.
        if role_def.settings_field:
            try:
                object.__setattr__(settings, role_def.settings_field, selected.id)
            except Exception:
                log.debug(
                    "Could not persist %s to settings",
                    role_def.settings_field,
                    exc_info=True,
                )
        # Durable persistence honours the requested scope. The global
        # ``~/.geode/.env`` (GEODE_MODEL) write is skipped for a *primary*
        # **project** switch: writing it leaked the choice to every project
        # (env outranks the project TOML in the precedence chain) and made
        # ``_apply_toml_overlay`` skip the project ``primary_model`` on the
        # next session reload. Non-primary roles (reflection / mutator) are
        # daemon-global knobs, so they keep their env write; global scope
        # writes env for every role.
        if scope == "global" or role_def.name != "primary":
            _pkg._upsert_env(role_def.env_var, selected.id)
        upsert_config_toml(role_def.toml_section, role_def.toml_key, selected.id, scope=scope)
    if role_def.has_effort and effort is not None and effort != old_effort:
        try:
            object.__setattr__(settings, "agentic_effort", effort)
        except Exception:
            log.debug("Could not persist agentic_effort to settings", exc_info=True)
        if scope == "global":
            _pkg._upsert_env("GEODE_AGENTIC_EFFORT", effort)
        upsert_config_toml("agentic", "effort", effort, scope=scope)

    # Model hot-swap is deferred: AgenticLoop._sync_model_from_settings_async()
    # checks settings.model at the start of each round and applies
    # the change safely between LLM calls. Direct loop.update_model_async()
    # during tool execution caused adapter swap mid-call → crash.
    # Reflection model is read lazily inside ``_maybe_reflect`` so no
    # hot-swap plumbing is needed there.

    role_tag = "" if role_def.name == "primary" else f"  [muted]({role_def.label})[/muted]"
    from core.paths import GLOBAL_CONFIG_TOML, PROJECT_CONFIG_TOML

    scope_path = str(GLOBAL_CONFIG_TOML) if scope == "global" else str(PROJECT_CONFIG_TOML)
    scope_tag = f"  [muted]· {scope} ({scope_path})[/muted]"
    if not same_model and role_def.has_effort and effort is not None:
        _pkg.console.print(
            f"  [success]Model[/success]  {old} → [bold]{selected.label}[/bold]"
            f"  [muted]({selected.id} · effort={effort})[/muted]{role_tag}{scope_tag}"
        )
    elif not same_model:
        _pkg.console.print(
            f"  [success]Model[/success]  {old} → [bold]{selected.label}[/bold]"
            f"  [muted]({selected.id})[/muted]{role_tag}{scope_tag}"
        )
    elif role_def.has_effort and effort is not None:
        _pkg.console.print(
            f"  [success]Effort[/success]  {old_effort} → [bold]{effort}[/bold]"
            f"  [muted](model unchanged: {selected.label})[/muted]"
        )
    if not same_model:
        where = "this project" if scope == "project" else "all projects"
        _pkg.console.print(
            f"  [muted]Scope: {where}. Applies to new sessions — "
            "restart `geode` to pick it up.[/muted]"
        )
    _pkg.console.print()


def _interactive_model_picker() -> None:
    """Two-axis interactive picker — model (↑↓) + effort level (←→).

    v0.59.0 — replaces the legacy single-axis ``TerminalMenu`` with the
    Claude Code ``ModelPicker.tsx`` pattern. Per-provider effort enum
    in ``core/cli/effort_picker.py``. Ctrl+C / q / ESC cancels; Enter
    confirms both the model and its current effort selection.

    PR-A (2026-05-21) — adds a role-tab axis. Tab cycles between
    ``primary`` (default — main agentic loop) and ``reflection``
    (PR-3 C-2 belief-update node), with future roles (mutator /
    judge) registerable in :data:`core.cli.commands._state.AGENT_ROLES`.
    Enter persists the focused-tab role's selection via
    :func:`_apply_model` ``role=`` kwarg.
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
    role_tabs = [(r.name, r.label, r.description) for r in AGENT_ROLES]
    role_initial_models = {r.name: _current_model_for_role(r) for r in AGENT_ROLES}
    role_has_effort = {r.name: r.has_effort for r in AGENT_ROLES}
    current_effort = getattr(settings, "agentic_effort", "high")
    result = pick_model_and_effort(
        profiles,
        settings.model,
        current_effort,
        roles=role_tabs,
        initial_role="primary",
        role_initial_models=role_initial_models,
        role_has_effort=role_has_effort,
    )
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
    _apply_model(chosen_profile, effort=result.effort, role=result.role)


def _interactive_model_picker_for_role(role_def: AgentRole) -> None:
    """PR-A — picker entered with ``initial_role=role_def.name``.

    Same UI as :func:`_interactive_model_picker` but the tab strip is
    anchored on the requested role so e.g. ``/model reflection``
    drops the user straight into the reflection picker. Tab still
    cycles to other roles so the operator can switch within the same
    invocation.
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
    role_tabs = [(r.name, r.label, r.description) for r in AGENT_ROLES]
    role_initial_models = {r.name: _current_model_for_role(r) for r in AGENT_ROLES}
    role_has_effort = {r.name: r.has_effort for r in AGENT_ROLES}
    current_for_focus = role_initial_models.get(role_def.name) or settings.model
    current_effort = getattr(settings, "agentic_effort", "high")
    result = pick_model_and_effort(
        profiles,
        current_for_focus,
        current_effort,
        roles=role_tabs,
        initial_role=role_def.name,
        role_initial_models=role_initial_models,
        role_has_effort=role_has_effort,
    )
    if result.cancelled:
        _pkg.console.print("  [muted]Cancelled[/muted]")
        _pkg.console.print()
        return
    chosen_profile = next(p for p in MODEL_PROFILES if p.id == result.model_id)
    _apply_model(chosen_profile, effort=result.effort, role=result.role)


def cmd_model(args: str) -> None:
    """Handle /model command (OpenClaw Auth Profile Rotation pattern).

    /model                       → interactive picker (this project)
    /model 2                     → select by number (this project)
    /model gpt-5.4               → select by name (this project)
    /model global gpt-5.4        → switch the user-global default (all projects)
    /model reflection            → interactive picker for reflection role
    /model reflection haiku-4.5  → set reflection model by name
    /model reflection 4          → set reflection model by number

    Scope (config precedence: CLI > env > project ``.geode/config.toml`` >
    global ``~/.geode/config.toml`` > routing default):
      * default (no ``global`` token) → writes the *project* config, so the
        switch is scoped to the current workspace.
      * ``/model global <name>`` → writes ``~/.geode/config.toml``, inherited
        by every project without its own override.
    Either way the change applies to *new* sessions (restart ``geode``).
    """
    from core.cli import commands as _pkg

    arg = args.strip()

    # ``/model global <…>`` — switch the user-global default instead of the
    # session's project config. Parsed before the role token (order:
    # ``/model global <role> <name>``). Default scope is "project" so a bare
    # ``/model <name>`` no longer leaks the choice to every workspace via the
    # global env (the pre-fix behaviour that made project switches stick
    # globally and shadowed the project TOML).
    scope = "project"
    if arg:
        first, _, rest = arg.partition(" ")
        if first == "global":
            scope = "global"
            arg = rest.strip()

    # PR-A — explicit role prefix: ``/model <role>`` or
    # ``/model <role> <picker-arg>``. The role token must match a
    # registered :class:`AgentRole` name; otherwise fall through to
    # the legacy number/name resolver (primary role).
    role_name = "primary"
    if arg:
        first, _, rest = arg.partition(" ")
        if first in {r.name for r in AGENT_ROLES}:
            role_name = first
            arg = rest.strip()
    role_def = role_by_name(role_name)

    # ``/model global`` with no model — the interactive picker applies to the
    # project scope, so global needs an explicit model id/number.
    if scope == "global" and not arg:
        _pkg.console.print("  [warning]Global scope needs an explicit model.[/warning]")
        _pkg.console.print("  [muted]Usage: /model global <number> | /model global <name>[/muted]")
        _pkg.console.print()
        return

    # /model (no args, primary role) → interactive picker (requires tty)
    # /model reflection → interactive picker focused on reflection tab
    if not arg:
        import sys

        if not sys.stdin.isatty():
            # Non-interactive: show model list with per-role markers
            _pkg.console.print()
            _pkg.console.print("  [header]Models[/header]")
            # Track each registered role's current pick so the list
            # marks all of them in one render — matches the
            # multi-tab picker's "Primary / Reflection" semantics.
            role_currents = {r.name: _current_model_for_role(r) for r in AGENT_ROLES}
            for i, p in enumerate(MODEL_PROFILES, 1):
                role_marks = " ".join(
                    f"{r.label[0]}←" for r in AGENT_ROLES if role_currents[r.name] == p.id
                )
                marker = f"  [muted]{role_marks}[/muted]" if role_marks else ""
                avail = "" if model_available(p.id) else "  [muted](login required)[/muted]"
                forced = forced_login_method_for(p.provider)
                forced_suffix = f"  [muted](forced: {forced})[/muted]" if forced else ""
                _pkg.console.print(
                    f"  {i}. {p.label:<12} {p.provider:<10} {p.cost}{marker}{avail}{forced_suffix}"
                )
            _pkg.console.print()
            _pkg.console.print(
                "  [muted]Usage: /model <number> | /model <name> | /model <role> <name>[/muted]"
            )
            _pkg.console.print("  [muted]Role markers: P← = Primary, R← = Reflection[/muted]")
            _pkg.console.print()
            return
        if role_name == "primary":
            _interactive_model_picker()
        else:
            # Single-role picker invocation — render the picker with
            # the role-tab axis but anchored on the requested role.
            _interactive_model_picker_for_role(role_def)
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

    _apply_model(selected, role=role_def.name, scope=scope)
