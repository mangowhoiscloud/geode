"""Slash-command handler for ``/petri`` — role × model × source picker.

Wires the manifest → adapter registry → credential_source → user_overrides
stack to a user-facing slash command. Mirrors GEODE's existing
``/model`` + ``/login`` patterns:

- ``/petri``                         → status table (3 roles × current binding)
- ``/petri <role>``                  → multi-step picker (model → source)
- ``/petri model <role> <name>``     → set model only
- ``/petri source <role> <source>``  → set source only
- ``/petri reset [<role>]``          → restore manifest default (all / one)

Persistence (SoT-flip 2026-05-22): writes flow through
:func:`plugins.petri_audit.user_overrides.save_role_override_to_config_toml`
into ``~/.geode/config.toml`` under
``[self_improving_loop.petri.<role>]`` — the operator-config SoT for
every audit role. The legacy ``~/.geode/petri.toml`` is still read as
a fallback layer (so existing operator setups keep working) but new
writes no longer land there. Read precedence (config.toml → legacy)
is owned by :func:`plugins.petri_audit.registry.get_binding`, the
single binding resolver for downstream consumers (/petri picker
itself, P1-G's ``to_inspect_model`` router, the audit runner).
"""

from __future__ import annotations

import sys
from typing import Any

from plugins.petri_audit.credential_source import (
    CredentialResolutionError,
    list_credential_sources,
    resolve_credential_source,
)
from plugins.petri_audit.manifest import AUTO_SOURCE, load_manifest
from plugins.petri_audit.registry import (
    FamilyInferenceError,
    PetriBinding,
    get_binding,
    infer_provider,
)
from plugins.petri_audit.user_overrides import (
    clear_overrides,
    read_role_override,
    save_role_override_to_config_toml,
)

__all__ = ["cmd_petri"]


# ── Entry point ─────────────────────────────────────────────────────────────


def cmd_petri(args: str) -> None:
    """Handle the ``/petri`` slash command — dispatches on sub-command."""
    from core.cli import commands as _pkg

    raw = args.strip()
    if not raw:
        _print_status()
        return

    tokens = raw.split()
    head = tokens[0].lower()

    if head == "reset":
        role_arg = tokens[1] if len(tokens) > 1 else None
        _cmd_reset(role_arg)
        return

    if head == "model":
        if len(tokens) < 3:
            _pkg.console.print("  [warning]Usage: /petri model <role> <name>[/warning]\n")
            return
        _cmd_set_model(role=tokens[1], model_arg=" ".join(tokens[2:]))
        return

    if head == "source":
        if len(tokens) < 3:
            _pkg.console.print(
                "  [warning]Usage: /petri source <role> "
                "<auto|api_key|claude-cli|openai-codex>[/warning]\n"
            )
            return
        _cmd_set_source(role=tokens[1], source_arg=tokens[2])
        return

    # /petri <role> — interactive picker for that role
    role = head
    if role not in _enabled_roles():
        _pkg.console.print(
            f"  [warning]Unknown petri role: {role}[/warning]   "
            f"[muted](roles: {', '.join(_enabled_roles())})[/muted]\n"
        )
        return

    if not sys.stdin.isatty():
        # Non-TTY: status + usage hint (matches /model behaviour).
        _print_status()
        _pkg.console.print(
            f"  [muted]Usage: /petri model {role} <name>  |  "
            f"/petri source {role} <source>[/muted]\n"
        )
        return

    _picker_for_role(role)


# ── Sub-commands ────────────────────────────────────────────────────────────


def _cmd_set_model(role: str, model_arg: str) -> None:
    from core.cli import commands as _pkg

    if role not in _enabled_roles():
        _pkg.console.print(f"  [warning]Unknown petri role: {role}[/warning]\n")
        return

    manifest = load_manifest()
    role_spec = manifest.get_role(role)
    allowed = role_spec.allowed_models

    chosen = _resolve_model_name(model_arg, allowed)
    if chosen is None:
        _pkg.console.print(f"  [warning]Model {model_arg!r} not in allowed for {role}[/warning]")
        _pkg.console.print(f"  [muted]Allowed: {', '.join(allowed)}[/muted]\n")
        return

    # Family change resets source to 'auto' (manifest default) — old
    # source may be incompatible with new provider (e.g. claude-cli on
    # gpt-* makes no sense).
    existing = read_role_override(role)
    extra: dict[str, str | None] = {}
    if "source" in existing:
        old_provider = _safe_provider(existing.get("model") or role_spec.default_model)
        new_provider = _safe_provider(chosen)
        if old_provider != new_provider:
            extra["source"] = ""  # erase

    save_role_override_to_config_toml(role, model=chosen, **extra)
    _print_role_after_change(role)


def _cmd_set_source(role: str, source_arg: str) -> None:
    from core.cli import commands as _pkg

    if role not in _enabled_roles():
        _pkg.console.print(f"  [warning]Unknown petri role: {role}[/warning]\n")
        return

    manifest = load_manifest()
    role_spec = manifest.get_role(role)
    # Family from the role's currently-chosen model (user override or default).
    current_model = read_role_override(role).get("model") or role_spec.default_model
    provider = _safe_provider(current_model)
    if provider is None:
        _pkg.console.print(
            f"  [warning]Cannot infer provider for current model {current_model!r}[/warning]\n"
        )
        return

    source_spec = manifest.get_source(provider)
    if source_arg not in source_spec.allowed:
        _pkg.console.print(
            f"  [warning]Source {source_arg!r} not allowed for provider {provider}[/warning]"
        )
        _pkg.console.print(f"  [muted]Allowed: {', '.join(source_spec.allowed)}[/muted]\n")
        return

    save_role_override_to_config_toml(role, source=source_arg)
    _print_role_after_change(role)


def _cmd_reset(role_arg: str | None) -> None:
    from core.cli import commands as _pkg

    if role_arg is None:
        try:
            confirm = (
                _pkg.console.input(
                    "  [warning]Reset all role overrides to manifest defaults? [y/N][/warning] "
                )
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            _pkg.console.print("\n  [muted]Cancelled[/muted]\n")
            return
        if confirm not in ("y", "yes"):
            _pkg.console.print("  [muted]Cancelled[/muted]\n")
            return
        clear_overrides()
        _pkg.console.print("  [success]All petri overrides cleared.[/success]\n")
        _print_status()
        return

    role = role_arg.lower()
    if role not in _enabled_roles():
        _pkg.console.print(f"  [warning]Unknown petri role: {role}[/warning]\n")
        return
    clear_overrides(role)
    _pkg.console.print(f"  [success]Reset {role} to manifest defaults.[/success]\n")
    _print_role_after_change(role)


# ── Status table ────────────────────────────────────────────────────────────


def _print_status() -> None:
    """Render the 3-row status table + missing-env warning + edit hint."""
    from core.cli import commands as _pkg

    rows = []
    missing_envs: set[str] = set()
    for role in _enabled_roles():
        try:
            binding = get_binding(role)
            source_label = _format_source_label(binding)
            rows.append((role, binding.model, source_label, binding.inspect_id))
        except CredentialResolutionError as e:
            # No credential for this provider — show the row with a marker.
            user_model = (
                read_role_override(role).get("model")
                or load_manifest().get_role(role).default_model
            )
            rows.append((role, user_model, f"[warning]unresolved[/warning] ({e.provider})", "—"))
            missing_envs.update(_env_vars_for_provider(e.provider))
        except Exception as e:
            rows.append((role, "?", f"[warning]error: {type(e).__name__}[/warning]", "—"))

    _pkg.console.print()
    _pkg.console.print("  [header]Petri bindings[/header]")
    _pkg.console.print()
    _pkg.console.print(f"  [muted]{'Role':<9} {'Model':<20} {'Source':<22} Inspect ID[/muted]")
    _pkg.console.print("  " + "─" * 80)
    for role, model, source, inspect_id in rows:
        _pkg.console.print(f"  {role:<9} {model:<20} {source:<22} {inspect_id}")
    _pkg.console.print()
    _pkg.console.print("  [muted]Edit: /petri <role>     Reset: /petri reset[/muted]")
    if missing_envs:
        _pkg.console.print(f"  [warning]Missing env: {', '.join(sorted(missing_envs))}[/warning]")
    _pkg.console.print()


def _print_role_after_change(role: str) -> None:
    from core.cli import commands as _pkg

    try:
        binding = get_binding(role)
    except CredentialResolutionError as e:
        _pkg.console.print(
            f"  [warning]{role}: saved, but no credential resolves[/warning] [muted]({e})[/muted]\n"
        )
        return
    except Exception as e:
        _pkg.console.print(f"  [warning]{role}: {type(e).__name__}: {e}[/warning]\n")
        return

    _pkg.console.print(
        f"  [success]{role}[/success]: "
        f"{binding.model} / {_format_source_label(binding)} "
        f"[muted]→ {binding.inspect_id}[/muted]\n"
    )


# ── Picker (multi-step) ─────────────────────────────────────────────────────


def _picker_for_role(role: str) -> None:
    """Interactive 2-step picker — Step 1 model, Step 2 source."""
    from core.cli import commands as _pkg

    try:
        from simple_term_menu import TerminalMenu
    except ImportError:
        _pkg.console.print(
            "  [warning]simple_term_menu not installed — install it or use "
            "/petri model / /petri source directly[/warning]\n"
        )
        return

    manifest = load_manifest()
    role_spec = manifest.get_role(role)
    current = read_role_override(role)
    current_model = current.get("model") or role_spec.default_model

    # ── Step 1: model picker ─────────────────────────────────────
    entries: list[str] = []
    for model in role_spec.allowed_models:
        marker = "  ← current" if model == current_model else ""
        entries.append(f"{model}{marker}")
    default_idx = role_spec.allowed_models.index(current_model)

    model_menu = TerminalMenu(
        entries,
        title=f"\n  /petri {role}  ·  Step 1/2 — model  (↑↓ select, Enter confirm, q cancel)\n",
        menu_cursor="  > ",
        menu_cursor_style=("fg_cyan", "bold"),
        cursor_index=default_idx,
    )
    midx = model_menu.show()
    if midx is None:
        _pkg.console.print("  [muted]Cancelled[/muted]\n")
        return
    chosen_model = role_spec.allowed_models[midx]

    # ── Step 2: source picker (filtered by provider of chosen model) ────────
    try:
        provider = infer_provider(chosen_model)
    except FamilyInferenceError as e:
        _pkg.console.print(f"  [warning]{e}[/warning]\n")
        return

    sources_info = list_credential_sources(provider)
    if not sources_info:
        _pkg.console.print(f"  [warning]No sources declared for provider={provider}[/warning]\n")
        return

    current_source = current.get("source") or AUTO_SOURCE
    src_entries: list[str] = []
    for info in sources_info:
        avail_marker = "✓" if info["available"] else "✗"
        current_marker = "  ← current" if info["source"] == current_source else ""
        suppressed_marker = " [suppressed]" if info["is_suppressed"] else ""
        env_label = f"  ({', '.join(info['auth_env_vars'])})" if info["auth_env_vars"] else ""
        src_entries.append(
            f"[{avail_marker}] {info['source']:<14}{env_label}{suppressed_marker}{current_marker}"
        )

    default_src_idx = next(
        (i for i, info in enumerate(sources_info) if info["source"] == current_source),
        0,
    )

    source_menu = TerminalMenu(
        src_entries,
        title=f"\n  /petri {role}  ·  Step 2/2 — source for "
        f"provider={provider}, model={chosen_model}\n",
        menu_cursor="  > ",
        menu_cursor_style=("fg_cyan", "bold"),
        cursor_index=default_src_idx,
    )
    sidx = source_menu.show()
    if sidx is None:
        _pkg.console.print("  [muted]Cancelled[/muted]\n")
        return
    chosen_source = sources_info[sidx]["source"]

    # ── Persist + confirm ────────────────────────────────────────────
    save_role_override_to_config_toml(role, model=chosen_model, source=chosen_source)
    _print_role_after_change(role)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _enabled_roles() -> list[str]:
    return load_manifest().enabled_roles


def _resolve_model_name(arg: str, allowed: list[str]) -> str | None:
    """Match arg against allowed model ids by exact or normalised compare."""
    if arg in allowed:
        return arg
    norm = arg.lower().replace("-", "").replace("_", "").replace(" ", "")
    for model in allowed:
        if model.lower().replace("-", "").replace("_", "").replace(" ", "") == norm:
            return model
    return None


def _safe_provider(model: str) -> str | None:
    try:
        return infer_provider(model)
    except FamilyInferenceError:
        return None


def _format_source_label(binding: PetriBinding) -> str:
    """Format the source column — 'auto → <resolved>' when override is auto."""
    override = read_role_override(binding.role)
    declared = override.get("source") or AUTO_SOURCE
    if declared == AUTO_SOURCE and binding.source != AUTO_SOURCE:
        return f"auto → {binding.source}"
    return binding.source


def _env_vars_for_provider(provider: str) -> list[str]:
    """Return all auth env vars declared by adapters for a provider."""
    manifest = load_manifest()
    out: list[str] = []
    for source, adapter in manifest.adapters.get(provider, {}).items():
        del source
        out.extend(adapter.auth_env_vars)
    return out


# Keep this compatibility symbol importable for existing slash-dispatch wiring.
_ = (resolve_credential_source,)


def _smoke() -> dict[str, Any]:  # pragma: no cover — manual REPL aid
    """Manual smoke helper — emits the picker's status payload as a dict."""
    out: dict[str, Any] = {}
    for role in _enabled_roles():
        try:
            out[role] = get_binding(role)
        except Exception as e:
            out[role] = {"error": f"{type(e).__name__}: {e}"}
    return out
