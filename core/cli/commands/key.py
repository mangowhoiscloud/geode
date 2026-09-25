"""``/key`` slash command + auth-state mirroring helpers.

Hosts the legacy ``/key`` PAYG entry point plus the ``_seed_payg_plan_from_key``
mirror that keeps the new ``/login`` dashboard in sync with env-style key
writes. Extracted from the monolithic ``core/cli/commands.py`` (Tier 3 #9)
— every function body is preserved byte-identical from the legacy module.

The module-level ``log`` channel is shared with sibling submodules; tests
that monkeypatch ``core.cli.commands.console``/``_upsert_env``/``_mask_key``
reach the call sites here through the deferred ``import core.cli.commands
as _pkg`` lookup, mirroring the pattern used by ``core/ui/agentic_ui``.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from core.cli.onboarding import clear_dry_run_opt_in


def _invalidate(provider: str) -> None:
    """Drop cached adapter clients so a key change takes effect immediately.

    2026-07-29: these call sites used to reset the ``providers/`` SYNC
    singletons, which the live path no longer used — a rotated key kept
    flowing through a stale adapter client until restart.
    """
    from core.llm.adapters.registry import invalidate_provider_clients

    invalidate_provider_clients(provider)


if TYPE_CHECKING:
    from core.cli.commands._state import ModelProfile

log = logging.getLogger(__name__)


def cmd_key(args: str) -> bool:
    """Handle /key command (legacy; prefer /login).

    Returns True if readiness should be rechecked.
    """
    from core.cli import commands as _pkg
    from core.config import settings

    parts = args.split(None, 1) if args else []

    # /key (no args) → defer to the unified /login dashboard.
    # L4 — pre-fix the redirect printed a single muted line with no
    # migration guide; an operator who'd just typed ``/key`` had no
    # way to learn the new command surface short of running ``/login``
    # and inferring it. Surface the migration table inline so the
    # legacy command becomes self-documenting.
    if not parts:
        _pkg.console.print("\n  [muted]/key now redirects to the unified /login dashboard.[/muted]")
        _pkg.console.print("\n  [header]Migration guide[/header]")
        _pkg.console.print(
            "  [muted]Legacy[/muted]                      → [muted]Replacement[/muted]\n"
            "  [label]/key <sk-...>[/label]               → [label]/login add[/label]  "
            "[muted](interactive — picks provider by prefix)[/muted]\n"
            "  [label]/key <provider> <key>[/label]       → [label]/login add[/label], or "
            "[label]/login set-key <plan-id> <key>[/label] for a registered plan\n"
            "\n"
            "  [muted]The legacy forms above still work — they shim into the unified\n"
            "  Plan/Profile model, but `/login add` registers richer metadata\n"
            "  (subscription tier, expiry, quota) that `/key` cannot express.\n"
            "  Run `/login providers` to see every provider variant the dashboard\n"
            "  supports; `/login` (bare) to see plans + profiles + routing.[/muted]"
        )
        _pkg.console.print()
        _pkg.cmd_login("")
        return False

    # /key openai <value>
    if parts[0].lower() == "openai":
        if len(parts) < 2:
            _pkg.console.print("  [warning]Usage: /key openai <API_KEY>[/warning]")
            return False
        value = parts[1].strip()
        settings.openai_api_key = value
        _pkg._upsert_env("OPENAI_API_KEY", value)
        _pkg._seed_payg_plan_from_key("openai", value)
        _invalidate("openai")
        clear_dry_run_opt_in()
        _pkg.console.print(f"  [success]OpenAI API key set[/success]  {_pkg._mask_key(value)}")
        _pkg.console.print()
        return True

    if parts[0].lower() == "openrouter":
        if len(parts) < 2:
            _pkg.console.print("  [warning]Usage: /key openrouter <API_KEY>[/warning]")
            return False
        value = parts[1].strip()
        settings.openrouter_api_key = value
        _pkg._upsert_env("OPENROUTER_API_KEY", value)
        _pkg._seed_payg_plan_from_key("openrouter", value)
        _invalidate("openrouter")
        clear_dry_run_opt_in()
        _pkg.console.print(f"  [success]OpenRouter API key set[/success]  {_pkg._mask_key(value)}")
        _pkg.console.print()
        return True

    # /key glm <value>
    if parts[0].lower() == "glm":
        if len(parts) < 2:
            _pkg.console.print("  [warning]Usage: /key glm <API_KEY>[/warning]")
            return False
        value = parts[1].strip()
        settings.zai_api_key = value
        _pkg._upsert_env("ZAI_API_KEY", value)
        _pkg._seed_payg_plan_from_key("glm", value)
        _invalidate("glm")
        clear_dry_run_opt_in()
        _pkg.console.print(f"  [success]ZhipuAI API key set[/success]  {_pkg._mask_key(value)}")
        _pkg.console.print()
        return True

    # /key <value> → auto-detect provider by prefix
    value = parts[0].strip()
    if value.startswith("sk-ant-"):
        settings.anthropic_api_key = value
        _pkg._upsert_env("ANTHROPIC_API_KEY", value)
        _pkg._seed_payg_plan_from_key("anthropic", value)
        _invalidate("anthropic")
        _pkg.console.print(f"  [success]Anthropic API key set[/success]  {_pkg._mask_key(value)}")
    elif value.startswith("sk-or-v1-"):
        settings.openrouter_api_key = value
        _pkg._upsert_env("OPENROUTER_API_KEY", value)
        _invalidate("openrouter")
        _pkg._seed_payg_plan_from_key("openrouter", value)
        _pkg.console.print(f"  [success]OpenRouter API key set[/success]  {_pkg._mask_key(value)}")
    elif value.startswith("sk-proj-") or value.startswith("sk-"):
        settings.openai_api_key = value
        _pkg._upsert_env("OPENAI_API_KEY", value)
        _invalidate("openai")
        _pkg._seed_payg_plan_from_key("openai", value)
        _pkg.console.print(f"  [success]OpenAI API key set[/success]  {_pkg._mask_key(value)}")
    elif _pkg._is_glm_key(value):
        settings.zai_api_key = value
        _pkg._upsert_env("ZAI_API_KEY", value)
        _invalidate("glm")
        _pkg._seed_payg_plan_from_key("glm", value)
        _pkg.console.print(f"  [success]GLM API key set[/success]  {_pkg._mask_key(value)}")
    else:
        _pkg.console.print(
            "  [warning]Unrecognized key prefix. Use:[/warning]\n"
            "  [muted]/key <sk-ant-...>          → Anthropic[/muted]\n"
            "  [muted]/key <sk-or-v1-...>        → OpenRouter[/muted]\n"
            "  [muted]/key openai <sk-proj-...>  → OpenAI[/muted]\n"
            "  [muted]/key glm <key>             → GLM[/muted]\n"
            "  [muted]Tip: use /login add for subscription plans (Coding Lite/Pro/Max).[/muted]"
        )
        _pkg.console.print()
        return False
    clear_dry_run_opt_in()
    _pkg.console.print(
        "  [muted]Tip: /login add to register a Coding Plan "
        "(cheaper than PAYG for heavy use).[/muted]"
    )
    _pkg.console.print()
    return True


def _seed_payg_plan_from_key(provider: str, key: str) -> None:
    """Mirror a freshly-set env API key into the Plan registry as PAYG.

    Keeps `/login` dashboard in sync with `/key` writes so users see the
    same credential in both views (Phase 1 single-store + Phase 2 plans).
    """
    from core.auth.auth_toml import auth_file_transaction
    from core.auth.profiles import AuthProfile, CredentialType
    from core.cli import commands as _pkg
    from core.llm.strategies.plans import default_plan_for_payg

    try:
        with auth_file_transaction() as (registry, store):
            plan = registry.get(f"{provider}-payg") or default_plan_for_payg(provider, key)
            registry.add(plan)
            name = f"{plan.id}:env"
            existing = store.get(name)
            profile = (
                replace(existing, key=key, plan_id=plan.id, error_count=0, cooldown_until=0.0)
                if existing is not None
                else AuthProfile(
                    name=name,
                    provider=plan.provider,
                    credential_type=CredentialType.API_KEY,
                    key=key,
                    plan_id=plan.id,
                )
            )
            store.add(profile, activate=True)
    except (ValueError, OSError) as exc:
        # The key already reached ~/.geode/.env; report the stale dashboard entry.
        _pkg.console.print(f"  [warning]auth.toml not updated: {exc}[/warning]")


def _check_provider_key(selected: ModelProfile) -> None:
    """Warn if the provider's API key is not set for the selected model."""
    from core.cli import commands as _pkg
    from core.config import settings
    from core.wiring.startup import _is_placeholder

    provider_key_map: dict[str, tuple[str, str]] = {
        "anthropic": (settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
        "openai": (settings.openai_api_key, "OPENAI_API_KEY"),
        "openrouter": (settings.openrouter_api_key, "OPENROUTER_API_KEY"),
        "glm": (settings.zai_api_key, "ZAI_API_KEY"),
    }

    # openai-codex (ChatGPT subscription) requires OAuth — check token availability
    if "openai-codex" in selected.provider:
        try:
            from core.auth.codex_cli_oauth import read_codex_cli_credentials
            from core.auth.oauth_login import read_geode_openai_credentials

            geode_creds = read_geode_openai_credentials()
            codex_creds = read_codex_cli_credentials()
            if not geode_creds and not codex_creds:
                _pkg.console.print(
                    "  [warning]Warning: No ChatGPT subscription OAuth token found. "
                    "Run /login openai to authenticate.[/warning]"
                )
        except Exception:
            _pkg.console.print(
                "  [warning]Warning: ChatGPT subscription OAuth not configured. "
                "Run /login openai first.[/warning]"
            )
        return

    entry = provider_key_map.get(selected.provider)
    if entry is None:
        return
    key_value, env_var = entry
    if not key_value or _is_placeholder(key_value):
        _pkg.console.print(f"  [warning]Warning: {env_var} not set. Model may not work.[/warning]")
