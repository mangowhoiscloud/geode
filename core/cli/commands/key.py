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
from typing import TYPE_CHECKING

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

    # /key (no args) → defer to the unified /login dashboard
    if not parts:
        _pkg.console.print("\n  [muted]/key now redirects to the unified /login dashboard.[/muted]")
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
        try:
            from core.llm.providers.openai import reset_openai_client

            reset_openai_client()
        except ImportError:
            pass
        _pkg.console.print(f"  [success]OpenAI API key set[/success]  {_pkg._mask_key(value)}")
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
        try:
            from core.llm.providers.glm import reset_glm_client

            reset_glm_client()
        except ImportError:
            pass
        _pkg.console.print(f"  [success]ZhipuAI API key set[/success]  {_pkg._mask_key(value)}")
        _pkg.console.print()
        return True

    # /key <value> → auto-detect provider by prefix
    value = parts[0].strip()
    if value.startswith("sk-ant-"):
        settings.anthropic_api_key = value
        _pkg._upsert_env("ANTHROPIC_API_KEY", value)
        _pkg._seed_payg_plan_from_key("anthropic", value)
        _pkg.console.print(f"  [success]Anthropic API key set[/success]  {_pkg._mask_key(value)}")
    elif value.startswith("sk-proj-") or value.startswith("sk-"):
        settings.openai_api_key = value
        _pkg._upsert_env("OPENAI_API_KEY", value)
        try:
            from core.llm.providers.openai import reset_openai_client

            reset_openai_client()
        except ImportError:
            pass
        _pkg._seed_payg_plan_from_key("openai", value)
        _pkg.console.print(f"  [success]OpenAI API key set[/success]  {_pkg._mask_key(value)}")
    elif _pkg._is_glm_key(value):
        settings.zai_api_key = value
        _pkg._upsert_env("ZAI_API_KEY", value)
        try:
            from core.llm.providers.glm import reset_glm_client

            reset_glm_client()
        except ImportError:
            pass
        _pkg._seed_payg_plan_from_key("glm", value)
        _pkg.console.print(f"  [success]GLM API key set[/success]  {_pkg._mask_key(value)}")
    else:
        _pkg.console.print(
            "  [warning]Unrecognized key prefix. Use:[/warning]\n"
            "  [muted]/key <sk-ant-...>          → Anthropic[/muted]\n"
            "  [muted]/key openai <sk-proj-...>  → OpenAI[/muted]\n"
            "  [muted]/key glm <key>             → GLM[/muted]\n"
            "  [muted]Tip: use /login add for subscription plans (Coding Lite/Pro/Max).[/muted]"
        )
        _pkg.console.print()
        return False
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
    from core.cli import commands as _pkg

    try:
        from core.auth.plan_registry import get_plan_registry
        from core.auth.plans import default_plan_for_payg
        from core.auth.profiles import AuthProfile, CredentialType
        from core.lifecycle.container import ensure_profile_store

        registry = get_plan_registry()
        plan = registry.get(f"{provider}-payg") or default_plan_for_payg(provider, key)
        registry.add(plan)
        store = ensure_profile_store()
        name = f"{plan.id}:env"
        existing = store.get(name)
        if existing is not None:
            existing.key = key
            existing.plan_id = plan.id
            existing.error_count = 0
            existing.cooldown_until = 0.0
        else:
            store.add(
                AuthProfile(
                    name=name,
                    provider=plan.provider,
                    credential_type=CredentialType.API_KEY,
                    key=key,
                    plan_id=plan.id,
                )
            )
        _pkg._persist_auth_state()
    except Exception:
        # The legacy /key path must not fail because of plan-seeding.
        log.debug("Plan seed from /key failed", exc_info=True)


def _persist_auth_state() -> None:
    """Persist Plan + Profile state to ~/.geode/auth.toml (best-effort)."""
    try:
        from core.auth.auth_toml import save_auth_toml

        save_auth_toml()
    except Exception:
        log.debug("auth.toml save failed", exc_info=True)


def _check_provider_key(selected: ModelProfile) -> None:
    """Warn if the provider's API key is not set for the selected model."""
    from core.cli import commands as _pkg
    from core.cli.startup import _is_placeholder
    from core.config import settings

    provider_key_map: dict[str, tuple[str, str]] = {
        "Anthropic": (settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
        "OpenAI": (settings.openai_api_key, "OPENAI_API_KEY"),
        "GLM": (settings.zai_api_key, "ZAI_API_KEY"),
    }

    # Codex (Plus) requires OAuth — check token availability
    if "Codex" in selected.provider:
        try:
            from core.auth.codex_cli_oauth import read_codex_cli_credentials
            from core.auth.oauth_login import read_geode_openai_credentials

            geode_creds = read_geode_openai_credentials()
            codex_creds = read_codex_cli_credentials()
            if not geode_creds and not codex_creds:
                _pkg.console.print(
                    "  [warning]Warning: No Codex OAuth token found. "
                    "Run /login openai to authenticate.[/warning]"
                )
        except Exception:
            _pkg.console.print(
                "  [warning]Warning: Codex OAuth not configured. Run /login openai first.[/warning]"
            )
        return

    entry = provider_key_map.get(selected.provider)
    if entry is None:
        return
    key_value, env_var = entry
    if not key_value or _is_placeholder(key_value):
        _pkg.console.print(f"  [warning]Warning: {env_var} not set. Model may not work.[/warning]")
