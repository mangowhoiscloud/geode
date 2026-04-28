"""Slash command dispatch — extracted from CLI REPL.

OpenClaw-inspired Binding Router pattern: static command → handler mapping.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any as _Any

if TYPE_CHECKING:
    from core.cli.session_checkpoint import SessionState

from simple_term_menu import TerminalMenu

from core.auth.profiles import AuthProfile, ProfileStore
from core.cli._helpers import is_glm_key as _is_glm_key
from core.cli._helpers import mask_key as _mask_key
from core.cli._helpers import upsert_env as _upsert_env
from core.config import (
    ANTHROPIC_BUDGET,
    ANTHROPIC_PRIMARY,
    ANTHROPIC_SECONDARY,
    GLM_PRIMARY,
    OPENAI_PRIMARY,
)
from core.ui.console import console

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model Registry (OpenClaw Auth Profile Rotation pattern)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelProfile:
    """A selectable LLM model profile."""

    id: str
    provider: str
    label: str
    cost: str  # relative cost indicator


# v0.53.0 — provider labels are CANONICAL provider IDs (matching
# /login dashboard + auth.toml), not marketing names. Pre-fix:
# "Codex (Plus)" label vs "openai-codex" provider ID mismatch caused
# user confusion. Auth-mode (OAuth vs PAYG) is NOT in the picker —
# the system auto-resolves at LLM call time via resolve_routing()
# based on the user's active /login state.
#
# Label = canonical provider ID + cost ($) tier.
# `gpt-5.5` default routes to `openai-codex` per equivalence-class
# scan when Codex Plus OAuth is registered (v0.52.4 routing policy);
# otherwise to `openai` PAYG. Both paths visible via /login dashboard.
MODEL_PROFILES: list[ModelProfile] = [
    ModelProfile(ANTHROPIC_PRIMARY, "anthropic", "Opus 4.7", "$$$"),
    ModelProfile("claude-opus-4-6", "anthropic", "Opus 4.6", "$$$"),
    ModelProfile(ANTHROPIC_SECONDARY, "anthropic", "Sonnet 4.6", "$$"),
    ModelProfile(ANTHROPIC_BUDGET, "anthropic", "Haiku 4.5", "$"),
    # v0.53.2 — gpt-5.5 is OAuth-only (Codex backend per
    # developers.openai.com/codex/models). _resolve_provider returns
    # "openai-codex" for it via _CODEX_ONLY_MODELS; ModelProfile.provider
    # must match so the /model picker label is honest about which
    # auth-mode the user's pick will actually consume.
    ModelProfile(OPENAI_PRIMARY, "openai-codex", "GPT-5.5", "$$"),
    ModelProfile("gpt-5.4", "openai", "GPT-5.4", "$$"),
    ModelProfile("gpt-5.4-mini", "openai", "GPT-5.4 Mini", "$"),
    ModelProfile("gpt-5.3-codex", "openai-codex", "GPT-5.3 Codex", "$$"),
    ModelProfile(GLM_PRIMARY, "glm", "GLM-5.1", "$"),
    ModelProfile("glm-5-turbo", "glm", "GLM-5 Turbo", "$"),
    ModelProfile("glm-4.7-flash", "glm", "GLM-4.7 Flash", "$"),
]

_MODEL_INDEX: dict[str, ModelProfile] = {m.id: m for m in MODEL_PROFILES}

# ---------------------------------------------------------------------------
# Conversation Context ContextVar (shared with tool handlers)
# ---------------------------------------------------------------------------

_conversation_ctx: ContextVar[_Any] = ContextVar("conversation_ctx", default=None)


def set_conversation_context(ctx: _Any) -> None:
    """Inject the active ConversationContext for command handlers."""
    _conversation_ctx.set(ctx)


def get_conversation_context() -> _Any:
    """Retrieve the active ConversationContext (None if not set)."""
    return _conversation_ctx.get(None)


# ---------------------------------------------------------------------------
# Command Map (OpenClaw Binding pattern: deterministic routing)
# ---------------------------------------------------------------------------

COMMAND_MAP: dict[str, str] = {
    "/quit": "quit",
    "/exit": "quit",
    "/q": "quit",
    "/help": "help",
    "/list": "list",
    "/verbose": "verbose",
    "/analyze": "analyze",
    "/a": "analyze",
    "/run": "run",
    "/r": "run",
    "/search": "search",
    "/s": "search",
    "/key": "key",
    "/model": "model",
    "/auth": "auth",
    "/generate": "generate",
    "/gen": "generate",
    "/report": "report",
    "/rpt": "report",
    "/batch": "batch",
    "/b": "batch",
    "/schedule": "schedule",
    "/sched": "schedule",
    "/trigger": "trigger",
    "/status": "status",
    "/compare": "compare",
    "/mcp": "mcp",
    "/skills": "skills",
    "/skill": "skill_invoke",
    "/cost": "cost",
    "/resume": "resume",
    "/context": "context",
    "/ctx": "context",
    "/apply": "apply",
    "/compact": "compact",
    "/clear": "clear",
    "/login": "login",
    "/tasks": "tasks",
    "/task": "tasks",
    "/t": "tasks",
}


def show_help() -> None:
    """Show interactive mode help."""
    console.print()
    console.print("  [header]Commands[/header]")
    console.print("  [label]/analyze[/label] <IP name>  — Analyze an IP (dry-run)")
    console.print("  [label]/run[/label] <IP name>      — Analyze with real LLM")
    console.print("  [label]/search[/label] <query>     — Search IPs by keyword")
    console.print("  [label]/list[/label]               — Show available IPs")
    console.print("  [label]/verbose[/label]            — Toggle verbose mode")
    console.print("  [label]/login[/label]              — Plans + credentials dashboard (unified)")
    console.print("  [label]/login add[/label]          — Interactive plan/key wizard")
    console.print("  [label]/login oauth openai[/label] — Codex OAuth (Plus quota)")
    console.print("  [label]/key[/label] <value>        — Quick PAYG API key (legacy alias)")
    console.print("  [label]/model[/label]              — Show & switch LLM model")
    console.print("  [label]/auth[/label]               — Auth profile rotator (legacy)")
    console.print("  [label]/generate[/label] [count]   — Generate synthetic demo data")
    console.print("  [label]/report[/label] <IP> [fmt]  — Generate report (md/html/json)")
    console.print("  [label]/batch[/label] <IP1> <IP2>  — Batch analyze multiple IPs")
    console.print("  [label]/schedule[/label]           — Manage scheduled automations")
    console.print("  [label]/trigger[/label]            — Manage event/cron triggers")
    console.print("  [label]/status[/label]             — Show system status")
    console.print("  [label]/cost[/label]               — LLM cost dashboard")
    console.print("  [label]/compare[/label] <A> <B>    — Compare two IPs")
    console.print("  [label]/mcp[/label]                — MCP server status/tools/add")
    console.print("  [label]/skills[/label]             — List/add/reload skills")
    console.print("  [label]/skill[/label] <name> [args] — Invoke a skill")
    console.print("  [label]/resume[/label]             — Resume interrupted session")
    console.print("  [label]/context[/label]            — Show assembled context tiers")
    console.print("  [label]/apply[/label]              — Manage job applications")
    console.print("  [label]/tasks[/label]              — Show task list")
    console.print("  [label]/compact[/label]            — Compact conversation context")
    console.print("  [label]/clear[/label]              — Clear conversation history")
    console.print("  [label]/help[/label]               — Show this help")
    console.print("  [label]/quit[/label]               — Exit GEODE")
    console.print()
    console.print("  [muted]Or just type naturally: 'Berserk', '다크 판타지 게임 찾아줘'[/muted]")
    console.print()


def cmd_list() -> None:
    """List available IP fixtures."""
    from core.domains.game_ip.fixtures import FIXTURE_MAP as _FIXTURE_MAP

    console.print()
    console.print("  [header]Available IPs[/header]")
    for name in _FIXTURE_MAP:
        console.print(f"    [value]{name.title()}[/value]")
    console.print()


def cmd_key(args: str) -> bool:
    """Handle /key command (legacy; prefer /login).

    Returns True if readiness should be rechecked.
    """
    from core.config import settings

    parts = args.split(None, 1) if args else []

    # /key (no args) → defer to the unified /login dashboard
    if not parts:
        console.print("\n  [muted]/key now redirects to the unified /login dashboard.[/muted]")
        cmd_login("")
        return False

    # /key openai <value>
    if parts[0].lower() == "openai":
        if len(parts) < 2:
            console.print("  [warning]Usage: /key openai <API_KEY>[/warning]")
            return False
        value = parts[1].strip()
        settings.openai_api_key = value
        _upsert_env("OPENAI_API_KEY", value)
        try:
            from core.llm.providers.openai import reset_openai_client

            reset_openai_client()
        except ImportError:
            pass
        console.print(f"  [success]OpenAI API key set[/success]  {_mask_key(value)}")
        console.print()
        return True

    # /key glm <value>
    if parts[0].lower() == "glm":
        if len(parts) < 2:
            console.print("  [warning]Usage: /key glm <API_KEY>[/warning]")
            return False
        value = parts[1].strip()
        settings.zai_api_key = value
        _upsert_env("ZAI_API_KEY", value)
        try:
            from core.llm.providers.glm import reset_glm_client

            reset_glm_client()
        except ImportError:
            pass
        console.print(f"  [success]ZhipuAI API key set[/success]  {_mask_key(value)}")
        console.print()
        return True

    # /key <value> → auto-detect provider by prefix
    value = parts[0].strip()
    if value.startswith("sk-ant-"):
        settings.anthropic_api_key = value
        _upsert_env("ANTHROPIC_API_KEY", value)
        _seed_payg_plan_from_key("anthropic", value)
        console.print(f"  [success]Anthropic API key set[/success]  {_mask_key(value)}")
    elif value.startswith("sk-proj-") or value.startswith("sk-"):
        settings.openai_api_key = value
        _upsert_env("OPENAI_API_KEY", value)
        try:
            from core.llm.providers.openai import reset_openai_client

            reset_openai_client()
        except ImportError:
            pass
        _seed_payg_plan_from_key("openai", value)
        console.print(f"  [success]OpenAI API key set[/success]  {_mask_key(value)}")
    elif _is_glm_key(value):
        settings.zai_api_key = value
        _upsert_env("ZAI_API_KEY", value)
        try:
            from core.llm.providers.glm import reset_glm_client

            reset_glm_client()
        except ImportError:
            pass
        _seed_payg_plan_from_key("glm", value)
        console.print(f"  [success]GLM API key set[/success]  {_mask_key(value)}")
    else:
        console.print(
            "  [warning]Unrecognized key prefix. Use:[/warning]\n"
            "  [muted]/key <sk-ant-...>          → Anthropic[/muted]\n"
            "  [muted]/key openai <sk-proj-...>  → OpenAI[/muted]\n"
            "  [muted]/key glm <key>             → GLM[/muted]\n"
            "  [muted]Tip: use /login add for subscription plans (Coding Lite/Pro/Max).[/muted]"
        )
        console.print()
        return False
    console.print(
        "  [muted]Tip: /login add to register a Coding Plan "
        "(cheaper than PAYG for heavy use).[/muted]"
    )
    console.print()
    return True


def _seed_payg_plan_from_key(provider: str, key: str) -> None:
    """Mirror a freshly-set env API key into the Plan registry as PAYG.

    Keeps `/login` dashboard in sync with `/key` writes so users see the
    same credential in both views (Phase 1 single-store + Phase 2 plans).
    """
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
        _persist_auth_state()
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
                console.print(
                    "  [warning]Warning: No Codex OAuth token found. "
                    "Run /login openai to authenticate.[/warning]"
                )
        except Exception:
            console.print(
                "  [warning]Warning: Codex OAuth not configured. Run /login openai first.[/warning]"
            )
        return

    entry = provider_key_map.get(selected.provider)
    if entry is None:
        return
    key_value, env_var = entry
    if not key_value or _is_placeholder(key_value):
        console.print(f"  [warning]Warning: {env_var} not set. Model may not work.[/warning]")


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
    from core.config import settings

    old = settings.model
    old_effort = getattr(settings, "agentic_effort", "high")
    same_model = selected.id == old
    same_effort = effort is None or effort == old_effort

    if same_model and same_effort:
        console.print(f"  [muted]Already using {selected.label}[/muted]")
        console.print()
        return

    _check_provider_key(selected)

    # --- Context Window Guard ---
    ctx = get_conversation_context()
    if ctx is not None and ctx.messages:
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW
        from core.orchestration.context_monitor import estimate_message_tokens

        current_tokens = estimate_message_tokens(ctx.messages)
        target_window = MODEL_CONTEXT_WINDOW.get(selected.id, 200_000)
        threshold = int(target_window * 0.8)

        if current_tokens > threshold:
            console.print()
            console.print(
                f"  [warning]Context guard: {current_tokens:,} tokens "
                f"exceeds {selected.label} limit "
                f"({target_window:,} x 80% = {threshold:,})[/warning]"
            )
            console.print("  [muted]Run /compact or /clear first, then retry /model.[/muted]")
            console.print()
            return

    if not same_model:
        settings.model = selected.id
        _upsert_env("GEODE_MODEL", selected.id)
    if effort is not None and effort != old_effort:
        # Persist effort separately so config.toml + env var stay in sync
        # with the picker's choice. The AgenticLoop's adaptive-compute
        # path reads ``self._effort`` (set at ctor time) — model-hot-swap
        # path picks up the new value on the next round via the same
        # settings.model deferred-apply mechanism.
        try:
            object.__setattr__(settings, "agentic_effort", effort)
        except Exception:
            log.debug("Could not persist agentic_effort to settings", exc_info=True)
        _upsert_env("GEODE_AGENTIC_EFFORT", effort)

    # Model hot-swap is deferred: AgenticLoop._sync_model_from_settings()
    # checks settings.model at the start of each round and applies
    # the change safely between LLM calls. Direct loop.update_model()
    # during tool execution caused adapter swap mid-call → crash.

    if not same_model and effort is not None:
        console.print(
            f"  [success]Model[/success]  {old} → [bold]{selected.label}[/bold]"
            f"  [muted]({selected.id} · effort={effort})[/muted]"
        )
    elif not same_model:
        console.print(
            f"  [success]Model[/success]  {old} → [bold]{selected.label}[/bold]"
            f"  [muted]({selected.id})[/muted]"
        )
    elif effort is not None:
        console.print(
            f"  [success]Effort[/success]  {old_effort} → [bold]{effort}[/bold]"
            f"  [muted](model unchanged: {selected.label})[/muted]"
        )
    console.print()


def _interactive_model_picker() -> None:
    """Two-axis interactive picker — model (↑↓) + effort level (←→).

    v0.59.0 — replaces the legacy single-axis ``TerminalMenu`` with the
    Claude Code ``ModelPicker.tsx`` pattern. Per-provider effort enum
    in ``core/cli/effort_picker.py``. Ctrl+C / q / ESC cancels; Enter
    confirms both the model and its current effort selection.
    """
    from core.cli.effort_picker import pick_model_and_effort
    from core.config import settings

    profiles = [(p.id, p.provider, p.label, p.cost) for p in MODEL_PROFILES]
    current_effort = getattr(settings, "agentic_effort", "high")
    result = pick_model_and_effort(profiles, settings.model, current_effort)
    if result.cancelled:
        console.print("  [muted]Cancelled[/muted]")
        console.print()
        return

    chosen_profile = next(p for p in MODEL_PROFILES if p.id == result.model_id)
    _apply_model(chosen_profile, effort=result.effort)


def cmd_model(args: str) -> None:
    """Handle /model command (OpenClaw Auth Profile Rotation pattern).

    /model         → interactive arrow-key picker
    /model 2       → select by number
    /model gpt-5.4 → select by name
    """
    arg = args.strip()

    # /model (no args) → interactive picker (requires tty)
    if not arg:
        import sys

        if not sys.stdin.isatty():
            # Non-interactive: show model list instead of crashing
            from core.config import settings

            console.print()
            console.print("  [header]Models[/header]")
            for i, p in enumerate(MODEL_PROFILES, 1):
                marker = " ←" if p.id == settings.model else ""
                console.print(f"  {i}. {p.label:<12} {p.provider:<10} {p.cost}{marker}")
            console.print()
            console.print("  [muted]Usage: /model <number> or /model <name>[/muted]")
            console.print()
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
            console.print(f"  [warning]Invalid number: {arg} (1-{len(MODEL_PROFILES)})[/warning]")
            console.print()
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
        console.print(f"  [warning]Unknown model: {arg}[/warning]")
        console.print("  [muted]Available:[/muted]", end="")
        for p in MODEL_PROFILES:
            console.print(f" [muted]{p.id}[/muted]", end="")
        console.print()
        console.print()
        return

    _apply_model(selected)


def _auth_login_status() -> None:
    """Show OAuth status + offer interactive login for missing providers."""
    import shutil
    import subprocess  # nosec B404

    console.print()
    console.print("  [header]OAuth Login Status[/header]")

    # -- Check current status --
    providers: list[dict[str, str | bool]] = []

    # Anthropic — OAuth disabled (ToS violation since 2026-01-09)
    console.print(
        "  [muted]\u2014[/muted] Anthropic  [muted]OAuth disabled (ToS — API key only)[/muted]"
    )
    providers.append({"name": "Anthropic", "cli": "claude", "ok": True})  # skip login prompt

    # OpenAI
    codex_ok = False
    try:
        from core.auth.codex_cli_oauth import (
            read_codex_cli_credentials,
        )

        codex_creds = read_codex_cli_credentials(force_refresh=True)
        if codex_creds:
            acct = codex_creds.get("account_id", "unknown")[:12]
            console.print(
                f"  [success]\u2713[/success] OpenAI     Codex CLI OAuth (account: {acct}...)"
            )
            codex_ok = True
    except Exception:  # noqa: S110
        pass
    if not codex_ok:
        console.print("  [error]\u2717[/error] OpenAI     [muted]not logged in[/muted]")
    providers.append({"name": "OpenAI", "cli": "codex", "ok": codex_ok})

    # -- Offer interactive login for missing providers --
    missing = [p for p in providers if not p["ok"]]
    if not missing:
        console.print()
        console.print("  [success]All providers authenticated via OAuth.[/success]")
        console.print()
        return

    console.print()
    for p in missing:
        cli_name = str(p["cli"])
        cli_path = shutil.which(cli_name)
        if not cli_path:
            console.print(
                f"  [muted]{p['name']}:[/muted]  "
                f"[warning]{cli_name} CLI not installed[/warning]  "
                f"[muted](install then run /auth login)[/muted]"
            )
            continue

        console.print(
            f"  [muted]{p['name']}:[/muted]  "
            f"[bold]{cli_name} login[/bold] — "
            f"opens browser for OAuth"
        )
        try:
            resp = (
                console.input(f"  [header]Run {cli_name} login now? [Y/n][/header] ")
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            console.print()
            continue

        if resp in ("n", "no"):
            continue

        console.print(f"  [muted]Opening browser for {p['name']} login...[/muted]")
        try:
            result = subprocess.run(  # noqa: S603  # nosec B603
                [cli_path, "login"],
                timeout=120,
            )
            if result.returncode == 0:
                console.print(f"  [success]{p['name']} login successful![/success]")
                # Re-read credentials + update ProfileStore
                _sync_oauth_profile_after_login(cli_name)
            else:
                console.print(
                    f"  [warning]{p['name']} login failed (exit code {result.returncode})[/warning]"
                )
        except subprocess.TimeoutExpired:
            console.print(f"  [warning]{p['name']} login timed out (120s)[/warning]")
        except OSError as exc:
            console.print(f"  [warning]{p['name']} login error: {exc}[/warning]")

    console.print()


def _sync_oauth_profile_after_login(cli_name: str) -> None:
    """Re-read OAuth credentials and update ProfileStore after login."""
    from core.auth.profiles import AuthProfile, CredentialType

    store = _get_profile_store()

    if cli_name == "claude":
        # Anthropic OAuth disabled — ToS prohibits third-party use
        return

    if cli_name == "codex":
        from core.auth.codex_cli_oauth import (
            invalidate_cache as codex_invalidate,
        )
        from core.auth.codex_cli_oauth import (
            read_codex_cli_credentials,
        )

        codex_invalidate()
        codex_creds = read_codex_cli_credentials(force_refresh=True)
        if codex_creds:
            profile = AuthProfile(
                name="openai-codex:codex-cli",
                provider="openai-codex",
                credential_type=CredentialType.OAUTH,
                key=codex_creds["access_token"],
                refresh_token=codex_creds.get("refresh_token", ""),
                expires_at=codex_creds.get("expires_at", 0.0),
                managed_by="codex-cli",
            )
            store.add(profile)


def cmd_auth(args: str) -> None:
    """Handle /auth command — manage auth profiles (OpenClaw Auth Profile UI pattern).

    /auth             → show profile status
    /auth add         → interactive add profile
    /auth remove <n>  → remove a profile
    """
    from core.auth.rotation import ProfileRotator

    # Module-level singleton (lazy init)
    store = _get_profile_store()
    rotator = ProfileRotator(store)

    arg = args.strip()

    if not arg:
        # Show status
        statuses = rotator.get_status()
        if not statuses:
            console.print()
            console.print("  [muted]No auth profiles configured.[/muted]")
            console.print(
                "  [muted]Use /auth login to check OAuth status,"
                " or /key <value> for API keys.[/muted]"
            )
            console.print()
            return

        console.print()
        console.print("  [header]Auth Profiles[/header]")
        for s in statuses:
            icon = "✓" if s["status"] == "active" else "●" if "cooldown" in s["status"] else "✗"
            style = "success" if icon == "✓" else "warning" if icon == "●" else "error"
            # Build status suffix with subscription info for OAuth profiles
            status_text = s["status"]
            meta = s.get("metadata", {})
            sub_type = meta.get("subscription_type", "")
            if sub_type:
                sub_label = sub_type.capitalize()
                status_text = f"{status_text} · {sub_label}"
            managed = s.get("managed_by", "")
            if managed:
                status_text = f"{status_text} · managed:{managed}"
            console.print(
                f"  [{style}]{icon}[/{style}] {s['name']:<22} "
                f"{s['type']:<10} {s['display']:<18} "
                f"[{style}]{status_text}[/{style}]"
            )
        console.print()
        console.print("  [muted]Priority: oauth > token > api_key[/muted]")
        # Hint if no OAuth profiles detected
        has_oauth = any(s["type"] == "oauth" for s in statuses)
        if not has_oauth:
            console.print("  [muted]Tip: /auth login to set up OAuth (saves API costs)[/muted]")
        console.print()
        return

    if arg.startswith("login"):
        _auth_login_status()
        return

    if arg.startswith("add"):
        add_args = arg[3:].strip()
        _auth_add_interactive(store, add_args)
        return

    if arg.startswith("remove"):
        name = arg[6:].strip()
        if not name:
            console.print("  [warning]Usage: /auth remove <profile-name>[/warning]")
            return
        if store.remove(name):
            console.print(f"  [success]Removed profile: {name}[/success]")
        else:
            console.print(f"  [warning]Profile not found: {name}[/warning]")
        console.print()
        return

    console.print("  [warning]Usage: /auth [login|add|remove <name>][/warning]")
    console.print()


def _auth_add_interactive(store: ProfileStore, add_args: str) -> None:
    """Interactive auth profile addition."""
    import sys

    if not sys.stdin.isatty():
        console.print("  [warning]/auth add requires an interactive terminal.[/warning]")
        console.print("  [muted]Use /key <provider> <value> to set API keys directly.[/muted]")
        console.print()
        return

    from core.auth.profiles import AuthProfile, CredentialType

    # Level 1: Provider selection
    providers = ["anthropic", "openai", "glm"]
    entries = ["Anthropic", "OpenAI", "GLM"]

    menu = TerminalMenu(
        entries,
        title="\n  Provider  (↑↓ select, Enter confirm, q cancel)\n",
        menu_cursor="  > ",
        menu_cursor_style=("fg_cyan", "bold"),
    )
    idx = menu.show()
    if idx is None:
        console.print("  [muted]Cancelled[/muted]")
        console.print()
        return

    provider = providers[idx]

    # Level 2: Credential type
    type_entries = ["API Key", "Token"]
    menu2 = TerminalMenu(
        type_entries,
        title=f"\n  {provider.capitalize()} — Credential Type\n",
        menu_cursor="  > ",
    )
    idx2 = menu2.show()
    if idx2 is None:
        console.print("  [muted]Cancelled[/muted]")
        console.print()
        return

    cred_type = CredentialType.API_KEY if idx2 == 0 else CredentialType.TOKEN

    # Input: key value
    try:
        key = console.input("  [label]Enter key:[/label] ").strip()
    except (KeyboardInterrupt, EOFError):
        console.print("\n  [muted]Cancelled[/muted]")
        console.print()
        return

    if not key:
        console.print("  [warning]No key provided.[/warning]")
        console.print()
        return

    # Name: provider:identifier
    existing = store.list_by_provider(provider)
    identifier = f"key{len(existing) + 1}"
    name = f"{provider}:{identifier}"

    profile = AuthProfile(
        name=name,
        provider=provider,
        credential_type=cred_type,
        key=key,
    )
    store.add(profile)
    console.print(f"  [success]Added profile: {name}[/success]  {profile.masked_key}")
    console.print()


def _get_profile_store() -> ProfileStore:
    """Return the runtime ProfileStore singleton.

    Pre-v0.50.0 the CLI maintained its own parallel store, so credentials
    added through `/auth add` were invisible to the LLM dispatch layer.
    Both layers now read from `runtime_wiring.infra` directly.
    """
    from core.lifecycle.container import ensure_profile_store

    return ensure_profile_store()


def cmd_generate(args: str) -> None:
    """Handle /generate command — create synthetic demo data.

    /generate         → generate 5 IPs
    /generate 10      → generate 10 IPs
    /generate 3 mecha → generate 3 IPs of specific genre
    """
    from core.domains.game_ip.fixtures.generator import GENRE_PARAMS, generate_batch

    parts = args.strip().split() if args.strip() else []

    count = 5
    genre = None

    if len(parts) >= 1 and parts[0].isdigit():
        count = int(parts[0])
        count = max(1, min(20, count))
    if len(parts) >= 2:
        genre = parts[1].lower()
        if genre not in GENRE_PARAMS:
            console.print(f"  [warning]Unknown genre: {genre}[/warning]")
            console.print(f"  [muted]Available: {', '.join(GENRE_PARAMS.keys())}[/muted]")
            console.print()
            return

    ips = generate_batch(count, genre=genre, seed=42)

    console.print()
    console.print(f"  [header]Generated {len(ips)} Synthetic IPs[/header]")
    for ip in ips:
        tier = ip.data["expected_results"]["tier"]
        score = ip.data["expected_results"]["final_score"]
        tier_style = {"S": "tier_s", "A": "tier_a", "B": "tier_b", "C": "tier_c"}.get(tier, "bold")
        console.print(
            f"    [{tier_style}]{tier}[/{tier_style}] {score:5.1f}  "
            f"[value]{ip.ip_name:<20}[/value] {ip.genre} / {ip.media_type}"
        )
    console.print()


def cmd_batch(
    args: str,
    *,
    run_fn: _Any = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> list[_Any]:
    """Handle /batch command — analyze multiple IPs in sequence.

    /batch Balatro Hades Celeste
    /batch Balatro,Hades,Celeste
    """
    if not args.strip():
        console.print("  [warning]Usage: /batch <IP1> <IP2> ... or <IP1>,<IP2>,...[/warning]")
        return []

    # Parse IP names (comma or space separated)
    raw = args.strip()
    if "," in raw:
        ip_names = [n.strip() for n in raw.split(",") if n.strip()]
    else:
        ip_names = [n.strip() for n in raw.split() if n.strip()]

    if not ip_names:
        console.print("  [warning]No IP names provided.[/warning]")
        return []

    console.print()
    console.print(f"  [header]Batch Analysis — {len(ip_names)} IPs[/header]")
    mode = "[muted]dry-run[/muted]" if dry_run else "[success]live[/success]"
    console.print(f"  Mode: {mode}")
    console.print()

    results: list[_Any] = []
    for i, ip_name in enumerate(ip_names, 1):
        console.print(f"  [{i}/{len(ip_names)}] [value]{ip_name}[/value]")
        if run_fn is not None:
            try:
                with console.status(
                    f"  [cyan]Analyzing {ip_name}...[/cyan]",
                    spinner="dots",
                    spinner_style="cyan",
                ):
                    result = run_fn(ip_name, dry_run=dry_run, verbose=verbose)
                results.append(result)
            except Exception as exc:
                console.show_cursor(True)
                console.print(f"  [error]Failed: {exc}[/error]")
                results.append(None)
        else:
            results.append(None)

    console.print()
    console.print(f"  [success]Batch complete: {len(results)}/{len(ip_names)} processed[/success]")
    console.print()
    return results


from core.cli.cmd_schedule import cmd_schedule as cmd_schedule  # noqa: E402


def cmd_trigger(args: str) -> None:
    """Handle /trigger command — manage event/cron triggers.

    /trigger           → list active triggers
    /trigger list      → list active triggers
    /trigger fire <ev> → manually fire an event
    """
    arg = args.strip().lower()

    if not arg or arg == "list":
        console.print()
        console.print("  [header]Trigger Manager[/header]")
        console.print("  [muted]Triggers are wired to HookSystem at priority 70.[/muted]")
        console.print()
        console.print("  Event-based: CUSUM drift → auto-snapshot, model evaluation")
        console.print("  Cron-based:  Managed via /schedule templates")
        console.print()
        console.print("  [muted]Use /trigger fire <event> to manually dispatch.[/muted]")
        console.print()
        return

    parts = arg.split(None, 1)
    if parts[0] == "fire" and len(parts) > 1:
        event_name = parts[1]
        console.print(f"  [warning]Cannot fire event: {event_name}[/warning]")
        console.print(
            "  [muted]Manual event dispatch requires a running TriggerManager "
            "instance (available in GeodeRuntime, not standalone REPL).[/muted]"
        )
        console.print()
        return

    console.print("  [warning]Usage: /trigger [list|fire <event>][/warning]")
    console.print()


def cmd_mcp(arg: str, *, mcp_manager: _Any | None = None) -> None:
    """Handle /mcp command — list/manage MCP servers.

    /mcp or /mcp status  → server connection status + tool counts
    /mcp tools           → list all MCP tool names
    /mcp reload          → reload config and reconnect
    """
    from core.mcp.manager import MCPServerManager

    mgr: MCPServerManager
    if mcp_manager is not None:
        mgr = mcp_manager
    else:
        mgr = MCPServerManager()
        mgr.load_config()

    sub = arg.strip().lower() if arg else ""

    if not sub or sub in ("status", "list"):
        servers = mgr.list_servers()
        if not servers:
            console.print("  [muted]No MCP servers configured.[/muted]")
            console.print("  [muted]Add servers to .claude/mcp_servers.json[/muted]")
            console.print()
            return

        console.print()
        console.print("  [header]MCP Servers[/header]")
        for s in servers:
            connected = s["connected"]
            status = "[success]connected[/success]" if connected else "[muted]off[/muted]"
            console.print(
                f"  {s['name']:20s} {status}  "
                f"[muted]{s['command']} ({s['tool_count']} tools)[/muted]"
            )
        console.print()
        return

    if sub == "tools":
        all_tools = mgr.get_all_tools()
        if not all_tools:
            console.print("  [muted]No MCP tools available.[/muted]")
            console.print()
            return

        console.print()
        console.print("  [header]MCP Tools[/header]")
        for tool in all_tools:
            server = tool.get("_mcp_server", "unknown")
            name = tool.get("name", "?")
            desc = tool.get("description", "")[:60]
            console.print(f"  [label]{name:30s}[/label] [muted]{server}[/muted]  {desc}")
        console.print()
        return

    if sub == "reload":
        count = mgr.reload_config()
        console.print(f"  [success]MCP config reloaded: {count} server(s)[/success]")
        console.print()
        return

    if sub.startswith("add"):
        _mcp_add(mgr, sub[3:].strip())
        return

    console.print(f"  [muted]MCP subcommand not recognized: {arg}[/muted]")
    console.print("  [muted]Usage: /mcp [status|tools|reload|add][/muted]")
    console.print()


def _mcp_add(mgr: _Any, raw: str) -> None:
    """Handle /mcp add <name> <command> [args...].

    Example: /mcp add brave-search npx -y @anthropic/mcp-server-brave-search
    """
    parts = raw.split() if raw else []
    if len(parts) < 2:
        console.print("  [warning]Usage: /mcp add <name> <command> [args...][/warning]")
        console.print(
            "  [muted]Example: /mcp add brave-search npx"
            " -y @anthropic/mcp-server-brave-search[/muted]"
        )
        console.print()
        return

    name = parts[0]
    command = parts[1]
    cmd_args = parts[2:] if len(parts) > 2 else []

    if mgr.add_server(name, command, args=cmd_args):
        console.print(f"  [success]Added MCP server: {name}[/success]")
        console.print(f"  [muted]Command: {command} {' '.join(cmd_args)}[/muted]")
        console.print("  [muted]Saved to .claude/mcp_servers.json[/muted]")
    else:
        console.print(f"  [warning]Failed to add MCP server: {name}[/warning]")
    console.print()


def cmd_skills(skill_registry: _Any, arg: str) -> None:
    """Handle /skills command — list/inspect loaded skills.

    /skills           → list loaded skills
    /skills reload    → reload from disk
    /skills <name>    → show skill detail
    """
    from core.skills.skills import SkillLoader, SkillRegistry

    reg: SkillRegistry = skill_registry
    sub = arg.strip() if arg else ""

    if not sub:
        names = reg.list_skills()
        if not names:
            console.print("  [muted]No skills loaded.[/muted]")
            console.print("  [muted]Add skills to .geode/skills/<name>/SKILL.md[/muted]")
            console.print()
            return

        console.print()
        console.print(f"  [header]Skills ({len(names)})[/header]")
        for name in names:
            skill = reg.get(name)
            if skill is None:
                continue
            tools_str = f" [muted]({len(skill.tools)} tools)[/muted]" if skill.tools else ""
            desc = skill.description[:70]
            if len(skill.description) > 70:
                desc += "..."
            console.print(f"  [label]{name:25s}[/label]{tools_str}  {desc}")
        console.print()
        return

    if sub == "reload":
        # Clear and reload
        new_reg = SkillRegistry()
        loaded = SkillLoader().load_all(registry=new_reg)
        # Replace contents in existing registry
        reg._skills.clear()
        for skill in loaded:
            reg.register(skill)
        console.print(f"  [success]Reloaded {len(loaded)} skills[/success]")
        console.print()
        return

    if sub.startswith("add"):
        _skills_add(reg, sub[3:].strip())
        return

    # Show specific skill detail
    skill = reg.get(sub)
    if skill is None:
        console.print(f"  [warning]Skill not found: {sub}[/warning]")
        console.print(f"  [muted]Available: {', '.join(reg.list_skills())}[/muted]")
        console.print()
        return

    console.print()
    console.print(f"  [header]{skill.name}[/header]")
    console.print(f"  [label]Description:[/label] {skill.description}")
    if skill.triggers:
        console.print(f"  [label]Triggers:[/label]    {', '.join(skill.triggers)}")
    if skill.tools:
        console.print(f"  [label]Tools:[/label]       {', '.join(skill.tools)}")
    console.print(f"  [label]Risk:[/label]        {skill.risk}")
    console.print(f"  [label]Body:[/label]        {len(skill.body)} chars")
    console.print()


def cmd_skill_invoke(skill_registry: _Any, arg: str, *, agentic_ref: _Any = None) -> None:
    """Handle /skill <name> [args] — invoke a skill with arguments.

    Supports context:fork (subagent execution) and $ARGUMENTS substitution.
    """
    from core.skills.skills import SkillRegistry

    reg: SkillRegistry = skill_registry
    parts = arg.strip().split(None, 1)
    if not parts:
        console.print("  [warning]Usage: /skill <name> [arguments][/warning]")
        console.print()
        return

    name = parts[0]
    arguments = parts[1] if len(parts) > 1 else ""

    skill = reg.get(name)
    if skill is None:
        console.print(f"  [warning]Skill not found: {name}[/warning]")
        console.print(f"  [muted]Available: {', '.join(reg.list_skills())}[/muted]")
        console.print()
        return

    # Render skill body with dynamic context and arguments
    rendered = skill.render(arguments=arguments)
    if not rendered:
        console.print(f"  [warning]Skill '{name}' has no body content[/warning]")
        console.print()
        return

    if skill.context_fork:
        # Fork execution: run in isolated subagent
        console.print(f"  [dim]Skill '{name}' → forked subagent[/dim]")
        from core.cli.bootstrap import _build_agentic_stack_minimal

        try:
            result = _build_agentic_stack_minimal(rendered, quiet=True)
            status = "ok" if result and not getattr(result, "error", False) else "err"
            summary = getattr(result, "text", "")[:200] if result else "(no output)"
            console.print(f"  [dim]skill:{name} → {status}[/dim]")
            if summary:
                console.print(f"\n{summary}\n")
        except Exception as exc:
            console.print(f"  [error]Skill fork failed: {exc}[/error]")
    else:
        # Inline execution: inject rendered body as user message into main loop
        from core.cli.session_state import get_current_loop

        _loop = get_current_loop()
        if _loop is not None:
            prompt = f"[skill:{name}] {rendered}"
            result = _loop.run(prompt)
            from core.ui.agentic_ui import render_status_line

            render_status_line()
        else:
            console.print("  [warning]AgenticLoop not available for skill execution[/warning]")
    console.print()


def _skills_add(reg: _Any, raw: str) -> None:
    """Handle /skills add <path> — register an external SKILL.md file.

    Copies the SKILL.md into .geode/skills/<name>/ and registers it.
    Example: /skills add /path/to/my-skill/SKILL.md
    """
    import shutil

    from core.skills.skills import SkillLoader

    path_str = raw.strip()
    if not path_str:
        console.print("  [warning]Usage: /skills add <path-to-SKILL.md>[/warning]")
        console.print("  [muted]Example: /skills add ./my-skill/SKILL.md[/muted]")
        console.print()
        return

    src = Path(path_str).expanduser().resolve()
    if not src.exists():
        console.print(f"  [warning]File not found: {src}[/warning]")
        console.print()
        return

    if not src.name.upper().startswith("SKILL"):
        console.print(f"  [warning]Expected a SKILL.md file, got: {src.name}[/warning]")
        console.print()
        return

    # Determine skill name from parent directory or filename
    skill_name = src.parent.name
    if skill_name in (".", ""):
        skill_name = src.stem.lower().replace(" ", "-")

    # Copy to .geode/skills/<name>/SKILL.md
    loader = SkillLoader()
    dest_dir = loader.skills_dir / skill_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    shutil.copy2(src, dest)

    # Load and register
    skill = loader.load_file(dest)
    reg.register(skill)

    console.print(f"  [success]Added skill: {skill.name}[/success]")
    console.print(f"  [muted]Copied to {dest}[/muted]")
    if skill.triggers:
        console.print(f"  [muted]Triggers: {', '.join(skill.triggers)}[/muted]")
    console.print()


def cmd_cost(args: str) -> None:
    """Handle /cost command — LLM cost dashboard.

    /cost              → session + monthly summary
    /cost daily        → today's breakdown
    /cost recent       → last 10 LLM calls
    /cost budget <amt> → set monthly budget ceiling (USD)
    """
    from datetime import date

    from core.llm.token_tracker import get_tracker
    from core.llm.usage_store import get_usage_store

    sub = args.strip().lower() if args else ""
    store = get_usage_store()
    tracker = get_tracker()
    acc = tracker.accumulator

    # --- session summary (always shown unless subcommand) ---
    if not sub or sub == "session":
        console.print()
        console.print("  [header]Cost Dashboard[/header]")

        # Session
        if acc.calls:
            console.print()
            console.print("  [label]Session[/label]")
            console.print(f"    Calls: {len(acc.calls)}")
            console.print(
                f"    Tokens: {acc.total_input_tokens:,} in / {acc.total_output_tokens:,} out"
            )
            console.print(f"    Cost: [warning]${acc.total_cost_usd:.4f}[/warning]")
        else:
            console.print()
            console.print("  [label]Session[/label]  [muted]no calls yet[/muted]")

        # Monthly
        summary = store.get_monthly_summary()
        today = date.today()
        console.print()
        console.print(f"  [label]Month ({today.year}-{today.month:02d})[/label]")
        console.print(f"    Calls: {summary['total_calls']}")
        console.print(f"    Cost: [warning]${summary['total_cost']:.2f}[/warning]")

        if summary["by_model"]:
            for model, stats in sorted(summary["by_model"].items(), key=lambda x: -x[1]["cost"]):
                console.print(f"      {model}: ${stats['cost']:.2f} ({int(stats['calls'])} calls)")

        # Budget
        budget = _get_cost_budget()
        if budget > 0:
            pct = summary["total_cost"] / budget * 100
            bar = _budget_bar(pct)
            console.print()
            cost = summary["total_cost"]
            console.print(f"  [label]Budget[/label]  ${cost:.2f} / ${budget:.2f}  {bar}")
        console.print()
        return

    # --- daily ---
    if sub == "daily" or sub == "today":
        daily = store.get_daily_summary()
        console.print()
        console.print(f"  [header]Daily Cost — {daily['date']}[/header]")
        console.print(f"    Calls: {daily['total_calls']}")
        console.print(f"    Cost: [warning]${daily['total_cost']:.4f}[/warning]")
        if daily["by_model"]:
            for model, stats in sorted(daily["by_model"].items(), key=lambda x: -x[1]["cost"]):
                console.print(f"      {model}: ${stats['cost']:.4f} ({int(stats['calls'])} calls)")
        console.print()
        return

    # --- recent ---
    if sub == "recent":
        records = store.get_recent_records(10)
        if not records:
            console.print("  [muted]No recent records.[/muted]")
            console.print()
            return

        from datetime import datetime

        console.print()
        console.print("  [header]Recent LLM Calls (last 10)[/header]")
        for rec in records:
            ts = datetime.fromtimestamp(rec.ts).strftime("%H:%M:%S")
            console.print(
                f"    {ts}  {rec.model:<30s}  "
                f"{rec.input_tokens:>6,}in {rec.output_tokens:>6,}out  "
                f"${rec.cost_usd:.4f}"
            )
        console.print()
        return

    # --- budget ---
    if sub.startswith("budget"):
        rest = sub[6:].strip()
        if not rest:
            budget = _get_cost_budget()
            if budget > 0:
                console.print(f"  [label]Monthly budget:[/label] ${budget:.2f}")
            else:
                console.print("  [muted]No budget set.[/muted]")
            console.print("  [muted]Usage: /cost budget <amount>[/muted]")
            console.print()
            return

        try:
            amount = float(rest)
        except ValueError:
            console.print(f"  [warning]Invalid amount: {rest}[/warning]")
            console.print()
            return

        _set_cost_budget(amount)
        console.print(f"  [success]Monthly budget set: ${amount:.2f}[/success]")
        console.print()
        return

    console.print("  [warning]Usage: /cost [daily|recent|budget <amount>][/warning]")
    console.print()


def _budget_bar(pct: float) -> str:
    """Render a budget progress bar."""
    filled = int(min(pct, 100) / 5)
    empty = 20 - filled
    if pct >= 90:
        style = "error"
    elif pct >= 70:
        style = "warning"
    else:
        style = "success"
    bar = "█" * filled + "░" * empty
    return f"[{style}]{bar}[/{style}] {pct:.0f}%"


def _get_cost_budget() -> float:
    """Read monthly budget from .geode/config.toml or env."""
    import os

    env_val = os.environ.get("GEODE_MONTHLY_BUDGET", "")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass

    config_path = Path(".geode") / "config.toml"
    if config_path.exists():
        import tomllib

        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
            return float(data.get("cost", {}).get("monthly_budget", 0))
        except (OSError, ValueError, KeyError):
            return 0.0
    return 0.0


def _set_cost_budget(amount: float) -> None:
    """Write monthly budget to .geode/config.toml."""
    config_path = Path(".geode") / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    found_section = False
    found_key = False

    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8")
        in_cost_section = False
        for line in raw.splitlines():
            if line.strip() == "[cost]":
                in_cost_section = True
                found_section = True
                lines.append(line)
                continue
            if in_cost_section and line.strip().startswith("monthly_budget"):
                lines.append(f"monthly_budget = {amount}")
                found_key = True
                in_cost_section = False
                continue
            if in_cost_section and line.strip().startswith("["):
                # New section — insert before it
                if not found_key:
                    lines.append(f"monthly_budget = {amount}")
                    found_key = True
                in_cost_section = False
            lines.append(line)

        if found_section and not found_key:
            lines.append(f"monthly_budget = {amount}")
    else:
        lines = []

    if not found_section:
        if lines:
            lines.append("")
        lines.append("[cost]")
        lines.append(f"monthly_budget = {amount}")

    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_resume(args: str) -> SessionState | None:
    """Handle /resume [session_id] — resume an interrupted session.

    Returns the full SessionState (with messages) for the caller to restore
    into ConversationContext, or None if no session was selected.
    """
    from core.cli.session_checkpoint import SessionCheckpoint

    checkpoint = SessionCheckpoint()

    if args.strip():
        # Explicit session ID
        state = checkpoint.load(args.strip())
        if state is None:
            console.print(f"  [warning]Session not found: {args.strip()}[/warning]")
            console.print()
            return None
        if state.status not in ("active", "paused"):
            console.print(
                f"  [warning]Session {args.strip()} is {state.status} (not resumable)[/warning]"
            )
            console.print()
            return None
        console.print(f"  [success]Resuming session: {state.session_id}[/success]")
        if state.user_input:
            console.print(f"  [muted]Original input: {state.user_input[:80]}[/muted]")
        console.print(
            f"  [muted]Round: {state.round_idx} | Messages: {len(state.messages)}[/muted]"
        )
        console.print()
        return state

    # No args: list resumable sessions
    sessions = checkpoint.list_resumable()
    if not sessions:
        console.print("  [muted]No resumable sessions found.[/muted]")
        console.print()
        return None

    import time as _time

    console.print()
    console.print("  [header]Resumable Sessions[/header]")
    for i, s in enumerate(sessions[:10], 1):
        age_min = (_time.time() - s.updated_at) / 60
        age_str = f"{age_min:.0f}m ago" if age_min < 60 else f"{age_min / 60:.1f}h ago"
        label = s.user_input[:50] if s.user_input else "(no input)"
        console.print(f"  {i}. [bold]{s.session_id}[/bold] [{s.status}] {age_str}")
        console.print(f"     [muted]{label}[/muted]")
    console.print()
    console.print("  [muted]Usage: /resume <session_id>[/muted]")
    console.print()
    return None


def cmd_apply(args: str) -> None:
    """Manage job applications via tracker.json.

    /apply                          -> list all applications
    /apply add <company> <position> -> add new application
    /apply status <company> <status> -> update status
    /apply remove <company>         -> remove application
    """
    from core.memory.vault import ApplicationEntry, ApplicationTracker

    tracker = ApplicationTracker()
    parts = args.strip().split() if args.strip() else []

    # /apply (no args) -> list
    if not parts:
        entries = tracker.list()
        if not entries:
            console.print("  [muted]No applications tracked.[/muted]")
            console.print("  [muted]Usage: /apply add <company> <position>[/muted]")
            console.print()
            return
        console.print()
        console.print(f"  [header]Applications ({len(entries)})[/header]")
        for e in entries:
            status_style = {
                "draft": "muted",
                "applied": "label",
                "interview": "warning",
                "offer": "success",
                "rejected": "error",
            }.get(e.status, "muted")
            console.print(
                f"  [{status_style}]{e.status:<12}[/{status_style}] "
                f"[value]{e.company}[/value] — {e.position}"
            )
        console.print()
        return

    sub = parts[0].lower()

    # /apply add <company> <position>
    if sub == "add":
        if len(parts) < 3:
            console.print("  [warning]Usage: /apply add <company> <position>[/warning]")
            console.print()
            return
        company = parts[1]
        position = " ".join(parts[2:])
        tracker.add(ApplicationEntry(company=company, position=position))
        console.print(f"  [success]Added: {company} — {position}[/success]")
        console.print()
        return

    # /apply status <company> <status>
    if sub == "status":
        if len(parts) < 3:
            console.print("  [warning]Usage: /apply status <company> <status>[/warning]")
            console.print(
                f"  [muted]Valid statuses: {', '.join(ApplicationTracker.VALID_STATUSES)}[/muted]"
            )
            console.print()
            return
        company = parts[1]
        status = parts[2].lower()
        if status not in ApplicationTracker.VALID_STATUSES:
            console.print(f"  [warning]Invalid status: {status}[/warning]")
            console.print(f"  [muted]Valid: {', '.join(ApplicationTracker.VALID_STATUSES)}[/muted]")
            console.print()
            return
        if tracker.update_status(company, status):
            console.print(f"  [success]{company}: {status}[/success]")
        else:
            console.print(f"  [warning]Not found: {company}[/warning]")
        console.print()
        return

    # /apply remove <company>
    if sub == "remove":
        if len(parts) < 2:
            console.print("  [warning]Usage: /apply remove <company>[/warning]")
            console.print()
            return
        company = parts[1]
        if tracker.remove(company):
            console.print(f"  [success]Removed: {company}[/success]")
        else:
            console.print(f"  [warning]Not found: {company}[/warning]")
        console.print()
        return

    console.print("  [warning]Usage: /apply [add|status|remove] ...[/warning]")
    console.print()


def cmd_context(args: str) -> None:
    """Show assembled context from all tiers.

    /context           -> show all tier summaries
    /context career    -> show career identity
    /context profile   -> show user profile
    """
    sub = args.strip().lower()

    # Career sub-command
    if sub == "career":
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        career = profile.load_career()
        if not career:
            console.print("  [muted]No career data. Edit ~/.geode/identity/career.toml[/muted]")
            console.print()
            return
        console.print()
        console.print("  [header]Career Identity[/header]")
        identity = career.get("identity", {})
        for k, v in identity.items():
            console.print(f"  [label]{k}:[/label] {v}")
        goals = career.get("goals", {})
        if goals:
            console.print()
            console.print("  [header]Goals[/header]")
            for k, v in goals.items():
                console.print(f"  [label]{k}:[/label] {v}")
        console.print()
        return

    # Profile sub-command
    if sub == "profile":
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        data = profile.load_profile()
        if not data:
            console.print("  [muted]No profile data. Run `geode init`.[/muted]")
            console.print()
            return
        console.print()
        console.print("  [header]User Profile[/header]")
        for k, v in data.items():
            if k == "preferences":
                continue
            if k == "learned_patterns":
                continue
            if v:
                console.print(f"  [label]{k}:[/label] {v}")
        console.print()
        return

    # Default: show all tier summaries
    console.print()
    console.print("  [header]Context Tiers[/header]")

    # Tier 0: SOUL
    try:
        from core.memory.organization import MonoLakeOrganizationMemory

        org = MonoLakeOrganizationMemory()
        soul = org.get_soul()
        if soul:
            preview = soul.split("\n")[0][:80] if soul else "(empty)"
            console.print(f"  [label]T0 SOUL:[/label] {preview}")
        else:
            console.print("  [label]T0 SOUL:[/label] [muted]not found[/muted]")
    except Exception as exc:
        err = type(exc).__name__
        console.print(f"  [label]T0 SOUL:[/label] [muted]unavailable ({err})[/muted]")

    # Tier 0.5: User Profile
    try:
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        summary = profile.get_context_summary()
        console.print(f"  [label]T0.5 Profile:[/label] {summary or '[muted]empty[/muted]'}")
        career_summary = profile.get_career_summary()
        if career_summary:
            console.print(f"  [label]T0.5 Career:[/label] {career_summary}")
    except Exception as exc:
        err = type(exc).__name__
        console.print(f"  [label]T0.5 Profile:[/label] [muted]unavailable ({err})[/muted]")

    # Tier 1: Project Memory
    try:
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if mem.exists():
            rules = mem.list_rules()
            console.print(f"  [label]T1 Project:[/label] {len(rules)} rules")
        else:
            console.print("  [label]T1 Project:[/label] [muted]not initialized[/muted]")
    except Exception as exc:
        err = type(exc).__name__
        console.print(f"  [label]T1 Project:[/label] [muted]unavailable ({err})[/muted]")

    # Vault
    try:
        from core.memory.vault import Vault

        vault = Vault()
        vs = vault.get_context_summary()
        console.print(f"  [label]V0 Vault:[/label] {vs or '[muted]empty[/muted]'}")
    except Exception as exc:
        err = type(exc).__name__
        console.print(f"  [label]V0 Vault:[/label] [muted]unavailable ({err})[/muted]")

    console.print()
    console.print("  [muted]Subcommands: /context career | /context profile[/muted]")
    console.print()


# ---------------------------------------------------------------------------
# /compact — Context Budget compaction (Karpathy P6)
# ---------------------------------------------------------------------------


def cmd_compact(args: str) -> None:
    """Compact conversation context to fit within model budget.

    /compact         -> compact to current model's 70% budget
    /compact --hard  -> keep only last 1 turn
    """
    from core.config import settings
    from core.orchestration.context_monitor import (
        adaptive_prune,
        check_context,
        summarize_tool_results,
    )

    ctx = get_conversation_context()
    if ctx is None or not ctx.messages:
        console.print("  [muted]Nothing to compact.[/muted]")
        console.print()
        return

    before = check_context(ctx.messages, settings.model)
    console.print()
    console.print(
        f"  [label]Before:[/label] {before.estimated_tokens:,} tokens "
        f"({before.usage_pct:.0f}% of {settings.model} "
        f"{before.context_window:,})"
    )

    hard = "--hard" in args
    if hard:
        last_pair = ctx.messages[-2:] if len(ctx.messages) >= 2 else list(ctx.messages)
        ctx.messages.clear()
        ctx.messages.extend(last_pair)
    else:
        summarize_tool_results(ctx.messages, before.context_window)
        compacted = adaptive_prune(ctx.messages, before.context_window)
        ctx.messages.clear()
        ctx.messages.extend(compacted)

    ctx._sanitize_tool_pairs()

    after = check_context(ctx.messages, settings.model)
    console.print(
        f"  [label]After:[/label]  {after.estimated_tokens:,} tokens "
        f"({after.usage_pct:.0f}% of {settings.model} "
        f"{after.context_window:,})"
    )
    console.print(
        f"  [success]Compacted[/success]  "
        f"{before.estimated_tokens:,} → {after.estimated_tokens:,} tokens"
    )
    console.print()


# ---------------------------------------------------------------------------
# /clear — Clear conversation history
# ---------------------------------------------------------------------------


def cmd_clear(args: str) -> None:
    """Clear conversation context entirely.

    /clear         -> confirm prompt before clearing
    /clear --force -> clear without confirmation
    """
    ctx = get_conversation_context()
    if ctx is None or not ctx.messages:
        console.print("  [muted]Conversation already empty.[/muted]")
        console.print()
        return

    msg_count = len(ctx.messages)
    console.print()

    if "--force" not in args:
        # v0.51.1: in IPC mode, native input() blocks the daemon and never
        # reaches the thin client REPL. Detect via the IPC writer thread-local
        # and require an explicit --force flag instead.
        from core.ui.agentic_ui import _ipc_writer_local

        in_ipc_mode = getattr(_ipc_writer_local, "writer", None) is not None
        if in_ipc_mode:
            console.print(
                f"  [warning]Refusing to clear {msg_count} messages without --force.[/warning]"
            )
            console.print(
                "  [muted]Run /clear --force to confirm "
                "(IPC mode disables interactive prompts).[/muted]"
            )
            console.print()
            return
        console.print(f"  Clear all {msg_count} messages? (y/N): ", end="")
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "y":
            console.print("  [muted]Cancelled.[/muted]")
            console.print()
            return

    ctx.clear()

    # Reset token tracker so stale cost/token counts don't persist
    from core.llm.token_tracker import reset_tracker

    reset_tracker()

    console.print(f"  [success]Conversation cleared[/success] ({msg_count} messages removed)")
    console.print()


def cmd_tasks(args: str) -> None:
    """Show user task list.

    Usage:
        /tasks            — show all tasks
        /tasks pending    — show pending only
        /tasks done       — show completed tasks
    """
    from core.cli.session_state import _get_user_task_graph
    from core.orchestration.task_system import TaskStatus

    _STATUS_LABEL: dict[TaskStatus, tuple[str, str]] = {
        TaskStatus.PENDING: ("○", "muted"),
        TaskStatus.READY: ("○", "muted"),
        TaskStatus.RUNNING: ("▶", "value"),
        TaskStatus.COMPLETED: ("✓", "success"),
        TaskStatus.FAILED: ("✗", "error"),
        TaskStatus.SKIPPED: ("–", "muted"),
    }

    filter_arg = args.strip().lower()
    graph = _get_user_task_graph()
    all_tasks = [graph.get_task(tid) for batch in graph.topological_order() for tid in batch]
    all_tasks = [t for t in all_tasks if t is not None]

    # Apply filter
    if filter_arg in ("pending", "todo"):
        all_tasks = [t for t in all_tasks if t.status in (TaskStatus.PENDING, TaskStatus.READY)]
    elif filter_arg in ("done", "completed"):
        all_tasks = [t for t in all_tasks if t.status == TaskStatus.COMPLETED]
    elif filter_arg in ("active", "running"):
        all_tasks = [t for t in all_tasks if t.status == TaskStatus.RUNNING]

    console.print()
    if not all_tasks:
        console.print("  [muted]No tasks.[/muted]")
        console.print()
        return

    # Sort: running first, then pending, then completed/failed
    _order = {
        TaskStatus.RUNNING: 0,
        TaskStatus.READY: 1,
        TaskStatus.PENDING: 1,
        TaskStatus.FAILED: 2,
        TaskStatus.SKIPPED: 2,
        TaskStatus.COMPLETED: 3,
    }
    all_tasks.sort(key=lambda t: _order.get(t.status, 9))

    console.print("  [header]Tasks[/header]")
    for task in all_tasks:
        icon, style = _STATUS_LABEL.get(task.status, ("?", "muted"))
        owner = task.metadata.get("owner", "")
        owner_tag = f"  [muted]{owner}[/muted]" if owner else ""
        elapsed = f"  [muted]{task.elapsed_s:.1f}s[/muted]" if task.elapsed_s else ""
        console.print(
            f"  [{style}]{icon}[/{style}]  [{style}]{task.task_id}[/{style}]"
            f"  {task.name}{owner_tag}{elapsed}"
        )
    console.print()
    running = sum(1 for t in all_tasks if t.status == TaskStatus.RUNNING)
    pending = sum(1 for t in all_tasks if t.status in (TaskStatus.PENDING, TaskStatus.READY))
    done = sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED)
    console.print(
        f"  [muted]{len(all_tasks)} total"
        f"  ▶ {running} active  ○ {pending} pending  ✓ {done} done[/muted]"
    )
    console.print()


def cmd_login(args: str) -> None:
    """Handle /login — unified credentials/plans command (v0.50.0+).

    Subcommands (mirrors Hermes `auth` + Claude Code `/login`/`/status`):

      /login                — show plans, profiles, routing, quota
      /login add            — interactive wizard (kind → provider → key/OAuth)
      /login oauth <prov>   — OAuth device flow (currently: openai/codex)
      /login set-key <plan> <key>
      /login use <plan>     — pin a plan as the active one for its provider
      /login remove <plan>
      /login route <model> <plan> [<plan>...]
      /login quota          — per-plan usage breakdown
      /login status         — legacy alias of bare /login
    """
    raw = args.strip()
    if not raw:
        _login_show_status()
        return

    parts = raw.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if sub in ("status", "list", "ls"):
        _login_show_status()
        return
    if sub in ("add", "new"):
        _login_add_interactive(rest)
        return
    if sub in ("oauth", "openai"):
        # `/login openai` is preserved for backwards compatibility — it always
        # ran the Codex device-code flow even before v0.50.0.
        target = rest.strip().lower() or "openai"
        _login_oauth(target)
        return
    if sub in ("set-key", "setkey", "key"):
        _login_set_key(rest)
        return
    if sub == "use":
        _login_use(rest)
        return
    if sub in ("remove", "rm", "delete"):
        _login_remove(rest)
        return
    if sub == "route":
        _login_route(rest)
        return
    if sub == "quota":
        _login_quota()
        return
    if sub == "refresh":
        # v0.52 phase 3 — daemon-side reload of auth.toml after thin client
        # writes (e.g. /login oauth completed in CLI process). When invoked
        # in CLI process this is a no-op; the actual reload happens when the
        # CLI relays /login refresh to the daemon via IPC.
        #
        # Semantics — ADDITIVE ONLY (v0.52.1 documented invariant):
        #   * Plans/Profiles newly written to auth.toml ARE picked up.
        #   * Plans/Profiles REMOVED from auth.toml are NOT removed from the
        #     daemon's in-memory singletons. Use `/login remove <plan-id>`
        #     for explicit deletion (which goes through the same IPC path
        #     and updates both file + memory atomically).
        #
        # Why additive: lifecycle.container.ensure_profile_store() returns
        # the cached singleton on subsequent calls; load_auth_toml() merges
        # into the existing store rather than rebuilding it. This protects
        # in-flight requests using profiles loaded from .env / managed CLIs
        # (Codex CLI OAuth) which never appear in auth.toml.
        try:
            from core.auth.auth_toml import auth_toml_path, load_auth_toml
            from core.auth.plan_registry import get_plan_registry
            from core.lifecycle.container import ensure_profile_store

            registry = get_plan_registry()
            store = ensure_profile_store()
            plans_before = {p.id for p in registry.list_all()}
            profiles_before = {p.name for p in store.list_all()}
            ok = load_auth_toml()
            plans_after = {p.id for p in registry.list_all()}
            profiles_after = {p.name for p in store.list_all()}
            new_plans = plans_after - plans_before
            new_profiles = profiles_after - profiles_before
            # v0.52.2 — production observability for the B7 thin → daemon
            # refresh signal. Pre-fix this branch was completely silent on
            # success, making it impossible to verify the relay was firing.
            log.info(
                "auth.toml reload: file=%s loaded=%s new_plans=%d "
                "new_profiles=%d total_plans=%d total_profiles=%d",
                auth_toml_path(),
                ok,
                len(new_plans),
                len(new_profiles),
                len(plans_after),
                len(profiles_after),
            )
            for plan_id in sorted(new_plans):
                log.info("auth.toml reload: + plan %s", plan_id)
            for profile_name in sorted(new_profiles):
                log.info("auth.toml reload: + profile %s", profile_name)
        except Exception:
            log.warning("auth.toml reload failed", exc_info=True)
        return
    if sub in ("help", "?"):
        _login_help()
        return

    console.print(
        f"\n  [warning]Unknown /login subcommand:[/warning] {sub}\n"
        "  Run [label]/login help[/label] for the full menu.\n"
    )


# ---------------------------------------------------------------------------
# /login subcommands — implementation
# ---------------------------------------------------------------------------


def _login_help() -> None:
    console.print(
        "\n  [header]/login[/header] — credentials & subscription plans\n"
        "\n"
        "  [label]/login[/label]                       Show all plans, profiles, routing\n"
        "  [label]/login add[/label]                   Interactive wizard\n"
        "  [label]/login oauth openai[/label]          OAuth device flow (Codex Plus)\n"
        "  [label]/login set-key[/label] <plan> <key>  Update a plan's API key\n"
        "  [label]/login use[/label] <plan>            Pin a plan as active for its provider\n"
        "  [label]/login route[/label] <model> <plan>… Bind a model to plan(s) in priority order\n"
        "  [label]/login remove[/label] <plan>         Delete a plan\n"
        "  [label]/login quota[/label]                 Per-plan quota / usage\n"
    )


def _login_show_status() -> None:
    """Render the unified plans + profiles + routing dashboard.

    Combines OpenClaw `/status` (auth-mode badge), Hermes `hermes status`
    (per-provider expiry + subscription line), and Claude Code Settings
    Status tab (plan + token source + provider).
    """
    from core.auth.oauth_login import get_auth_status as get_oauth_status
    from core.auth.plan_registry import get_plan_registry
    from core.auth.profiles import CredentialType
    from core.lifecycle.container import ensure_profile_store

    store = ensure_profile_store()
    registry = get_plan_registry()
    plans = registry.list_all()
    profiles = store.list_all()

    console.print()
    console.print("  [header]Plans[/header]")
    if not plans and not profiles:
        console.print("  [muted]No plans or credentials registered yet.[/muted]")
        console.print("  [muted]Run /login add to register a plan, or paste an API key.[/muted]")
        console.print()
        return

    if plans:
        for plan in plans:
            usage = registry.usage_for(plan.id)
            tier_label = f" · {plan.subscription_tier}" if plan.subscription_tier else ""
            quota_label = ""
            if plan.quota is not None:
                remaining = usage.remaining_in_window(plan)
                quota_label = (
                    f"  [muted]used {int(usage.weighted_calls)}/{plan.quota.max_calls}"
                    f" ({plan.quota.window_s // 3600}h window, {remaining} left)[/muted]"
                )
            bound = [p for p in profiles if p.plan_id == plan.id]
            mark = "[success]✓[/success]" if bound else "[warning]?[/warning]"
            console.print(
                f"  {mark} [bold]{plan.id}[/bold]  "
                f"[muted]{plan.kind.value}[/muted]  {plan.base_url}{tier_label}{quota_label}"
            )
    else:
        console.print("  [muted]No Plans registered. Profiles below run via PAYG defaults.[/muted]")
    console.print()

    # Profiles section — aggregates env-loaded keys + interactively added
    console.print("  [header]Profiles[/header]")
    if not profiles:
        console.print("  [muted]No credentials. Run /login add or set provider env vars.[/muted]")
    else:
        # Group by provider for readability
        by_provider: dict[str, list[AuthProfile]] = {}
        for p in profiles:
            by_provider.setdefault(p.provider, []).append(p)
        # v0.51.0 — pre-compute eligibility per provider so each profile row
        # carries an inline reject badge (cooldown / expired / disabled / etc).
        verdicts_by_name: dict[str, str] = {}
        details_by_name: dict[str, str] = {}
        for prov in by_provider:
            for v in store.evaluate_eligibility(prov):
                verdicts_by_name[v.profile_name] = v.reason_code
                details_by_name[v.profile_name] = v.detail
        for provider in sorted(by_provider.keys()):
            for p in by_provider[provider]:
                badge = {
                    CredentialType.OAUTH: "oauth",
                    CredentialType.TOKEN: "token",
                    CredentialType.API_KEY: "api-key",
                }.get(p.credential_type, "?")
                plan_id = p.plan_id or "[muted](none)[/muted]"
                managed = f" · managed:{p.managed_by}" if p.managed_by else ""
                expiry = ""
                if p.expires_at:
                    import time as _t

                    rem = int(p.expires_at - _t.time())
                    expiry = f" · expires {rem // 60}m" if rem > 0 else " · [error]expired[/error]"
                # Eligibility badge — green ✓ when ok, yellow/red with reason otherwise.
                reason = verdicts_by_name.get(p.name, "ok")
                if reason == "ok":
                    badge_str = "[success]✓[/success]"
                else:
                    detail = details_by_name.get(p.name, "")
                    badge_str = f"[warning]✗ {reason}[/warning]"
                    if detail:
                        badge_str += f" [muted]({detail})[/muted]"
                console.print(
                    f"  {badge_str}  {p.name:<28} "
                    f"[muted]{badge:<7}[/muted] {p.masked_key} "
                    f"plan={plan_id}{managed}{expiry}"
                )
    console.print()

    # Routing section
    routing = registry.all_routing()
    if routing:
        console.print("  [header]Routing[/header]")
        for model, plan_ids in sorted(routing.items()):
            chain = " → ".join(plan_ids) if plan_ids else "[muted](none)[/muted]"
            console.print(f"  {model:<24} → {chain}")
        console.print()

    # OAuth status (shows expiry + email when available)
    try:
        oauth = get_oauth_status()
    except Exception:
        oauth = []
    if oauth:
        console.print("  [header]OAuth (external CLIs)[/header]")
        for s in oauth:
            colour = "success" if s.get("status") == "active" else "warning"
            console.print(
                f"  [{colour}]{s.get('status', '?'):<8}[/{colour}] "
                f"{s.get('provider', ''):<20} "
                f"{s.get('email') or '-':<24} "
                f"{s.get('expires_in', ''):<10} "
                f"[muted]({s.get('source', '')})[/muted]"
            )
        console.print()

    console.print(
        "  [muted]Tip: /login add to register a plan · /login quota for usage detail[/muted]\n"
    )


def _login_add_interactive(_args: str) -> None:
    """Interactive wizard — Plan kind → Provider → endpoint/key/OAuth.

    Mirrors OpenClaw setup wizard (`prompter.select` levels) collapsed
    into a single CLI command so existing users can run it any time.
    """
    import sys

    from core.auth.plan_registry import get_plan_registry
    from core.auth.plans import (
        GLM_CODING_TIERS,
        default_plan_for_payg,
    )
    from core.auth.profiles import AuthProfile, CredentialType
    from core.lifecycle.container import ensure_profile_store

    if not sys.stdin.isatty():
        console.print(
            "  [warning]/login add requires an interactive terminal.[/warning]\n"
            "  [muted]Set keys via env vars (ZAI_API_KEY, OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY) for non-interactive setup.[/muted]"
        )
        return

    kinds = [
        ("subscription", "Subscription (GLM Coding Plan, ChatGPT Plus, Claude Pro)"),
        ("payg", "Pay-as-you-go API key (Anthropic, OpenAI, GLM PAYG)"),
        ("oauth", "OAuth borrowed (Codex CLI / Claude Code)"),
    ]
    menu = TerminalMenu(
        [label for _, label in kinds],
        title="\n  Plan kind?  (↑↓ select, Enter confirm, q cancel)\n",
        menu_cursor="  > ",
        menu_cursor_style=("fg_cyan", "bold"),
    )
    idx = menu.show()
    if idx is None:
        console.print("  [muted]Cancelled[/muted]\n")
        return
    kind_id = kinds[idx][0]

    registry = get_plan_registry()
    store = ensure_profile_store()

    if kind_id == "subscription":
        # Currently only GLM Coding Plan tiers are templated
        tier_entries = [
            "GLM Coding Lite  ($6/mo · 80 calls/5h · 3× weight on glm-5.1)",
            "GLM Coding Pro   ($30/mo · 240 calls/5h)",
            "GLM Coding Max   ($80/mo · 600 calls/5h)",
        ]
        tier_keys = ["lite", "pro", "max"]
        tmenu = TerminalMenu(
            tier_entries,
            title="\n  Subscription tier?\n",
            menu_cursor="  > ",
        )
        tidx = tmenu.show()
        if tidx is None:
            console.print("  [muted]Cancelled[/muted]\n")
            return
        plan = GLM_CODING_TIERS[tier_keys[tidx]]
        try:
            key = console.input(f"  [label]{plan.display_name} API key:[/label] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n  [muted]Cancelled[/muted]\n")
            return
        if not key:
            console.print("  [warning]No key provided.[/warning]\n")
            return
        registry.add(plan)
        registry.set_routing("glm-5.1", [plan.id, *registry.get_routing("glm-5.1")])
        for m in ("glm-5", "glm-5-turbo", "glm-4.7-flash"):
            registry.set_routing(m, [plan.id, *registry.get_routing(m)])
        store.add(
            AuthProfile(
                name=f"{plan.id}:user",
                provider=plan.provider,
                credential_type=CredentialType.API_KEY,
                key=key,
                plan_id=plan.id,
            )
        )
        # Reset the GLM client so the next call picks up the new endpoint+key
        try:
            from core.llm.providers.glm import reset_glm_client

            reset_glm_client()
        except Exception:  # noqa: S110 — best-effort cache invalidation
            pass
        _persist_auth_state()
        console.print(
            f"  [success]Registered[/success] {plan.display_name}  "
            f"[muted]({plan.base_url})[/muted]\n"
        )
        return

    if kind_id == "payg":
        providers = [
            ("anthropic", "Anthropic"),
            ("openai", "OpenAI"),
            ("glm", "GLM (z.ai PAYG)"),
        ]
        pmenu = TerminalMenu(
            [label for _, label in providers],
            title="\n  Provider?\n",
            menu_cursor="  > ",
        )
        pidx = pmenu.show()
        if pidx is None:
            console.print("  [muted]Cancelled[/muted]\n")
            return
        provider = providers[pidx][0]
        try:
            key = console.input(f"  [label]{providers[pidx][1]} API key:[/label] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n  [muted]Cancelled[/muted]\n")
            return
        if not key:
            console.print("  [warning]No key provided.[/warning]\n")
            return
        plan = default_plan_for_payg(provider, key)
        registry.add(plan)
        store.add(
            AuthProfile(
                name=f"{plan.id}:user",
                provider=provider,
                credential_type=CredentialType.API_KEY,
                key=key,
                plan_id=plan.id,
            )
        )
        # Mirror to settings + .env so legacy fallbacks keep working
        from core.config import settings

        env_field_map = {
            "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "openai": ("openai_api_key", "OPENAI_API_KEY"),
            "glm": ("zai_api_key", "ZAI_API_KEY"),
        }
        if provider in env_field_map:
            field_name, env_var = env_field_map[provider]
            object.__setattr__(settings, field_name, key)
            _upsert_env(env_var, key)
        _persist_auth_state()
        console.print(
            f"  [success]Registered[/success] {plan.display_name}  "
            f"[muted](key {_mask_key(key)})[/muted]\n"
        )
        return

    if kind_id == "oauth":
        oauth_entries = [
            "OpenAI Codex CLI (chatgpt.com/backend-api/codex)",
            "Claude Code (currently disabled — Anthropic ToS)",
        ]
        omenu = TerminalMenu(
            oauth_entries,
            title="\n  OAuth source?\n",
            menu_cursor="  > ",
        )
        oidx = omenu.show()
        if oidx is None:
            console.print("  [muted]Cancelled[/muted]\n")
            return
        if oidx == 1:
            console.print(
                "  [warning]Claude Code OAuth is disabled (Anthropic ToS, "
                "see core/runtime_wiring/infra.py).[/warning]\n"
            )
            return
        _login_oauth("openai")
        return


def _login_oauth(target: str) -> None:
    """Run the OAuth device-code flow for an external CLI provider."""
    target = target.lower().strip()
    if target not in ("openai", "codex"):
        console.print(
            f"  [warning]OAuth not implemented for '{target}'.[/warning]\n"
            "  [muted]Available: openai (Codex CLI Plus quota)[/muted]\n"
        )
        return
    console.print()
    try:
        from core.auth.oauth_login import login_openai

        creds = login_openai()
        if creds:
            import contextlib

            with contextlib.suppress(Exception):
                from core.llm.providers.codex import reset_codex_client

                reset_codex_client()
            console.print(
                "  [success]Codex OAuth registered.[/success]  "
                "[muted]Provider: openai-codex[/muted]\n"
            )
    except Exception as exc:
        console.print(f"  [red]Login failed: {exc}[/red]\n")


def _login_set_key(rest: str) -> None:
    parts = rest.split(None, 1)
    if len(parts) < 2:
        console.print("  [warning]Usage: /login set-key <plan-id> <api-key>[/warning]\n")
        return
    plan_id, key = parts[0], parts[1].strip()

    from core.auth.plan_registry import get_plan_registry
    from core.auth.profiles import AuthProfile, CredentialType
    from core.lifecycle.container import ensure_profile_store

    registry = get_plan_registry()
    plan = registry.get(plan_id)
    if plan is None:
        console.print(
            f"  [warning]Unknown plan: {plan_id}[/warning]  [muted](use /login add first)[/muted]\n"
        )
        return
    store = ensure_profile_store()
    name = f"{plan.id}:user"
    existing = store.get(name)
    if existing is not None:
        existing.key = key
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
    if plan.provider == "glm-coding":
        from core.llm.providers.glm import reset_glm_client

        reset_glm_client()
    _persist_auth_state()
    console.print(
        f"  [success]Updated key[/success] for {plan.display_name}  "
        f"[muted]({_mask_key(key)})[/muted]\n"
    )


def _login_use(rest: str) -> None:
    plan_id = rest.strip()
    if not plan_id:
        console.print("  [warning]Usage: /login use <plan-id>[/warning]\n")
        return
    from core.auth.plan_registry import get_plan_registry

    registry = get_plan_registry()
    plan = registry.get(plan_id)
    if plan is None:
        console.print(f"  [warning]Unknown plan: {plan_id}[/warning]\n")
        return
    # Pin this plan ahead of any other for a few common models in its provider
    model_hints = {
        "glm-coding": ["glm-5.1", "glm-5", "glm-5-turbo", "glm-4.7-flash"],
        "glm": ["glm-5.1", "glm-5", "glm-5-turbo"],
        "openai": ["gpt-5.4", "gpt-5.4-mini"],
        "openai-codex": ["gpt-5.3-codex", "gpt-5.4-mini"],
        "anthropic": ["claude-opus-4-7", "claude-sonnet-4-6"],
    }
    for model in model_hints.get(plan.provider, []):
        existing = [pid for pid in registry.get_routing(model) if pid != plan.id]
        registry.set_routing(model, [plan.id, *existing])
    _persist_auth_state()
    console.print(
        f"  [success]Activated[/success] {plan.display_name} for {plan.provider} models.\n"
    )


def _login_remove(rest: str) -> None:
    plan_id = rest.strip()
    if not plan_id:
        console.print("  [warning]Usage: /login remove <plan-id>[/warning]\n")
        return
    from core.auth.plan_registry import get_plan_registry
    from core.lifecycle.container import ensure_profile_store

    registry = get_plan_registry()
    if not registry.remove(plan_id):
        console.print(f"  [warning]Plan not found: {plan_id}[/warning]\n")
        return
    store = ensure_profile_store()
    for p in list(store.list_all()):
        if p.plan_id == plan_id:
            store.remove(p.name)
    _persist_auth_state()
    console.print(f"  [success]Removed plan and its profiles:[/success] {plan_id}\n")


def _login_route(rest: str) -> None:
    parts = rest.split()
    if len(parts) < 2:
        console.print("  [warning]Usage: /login route <model> <plan-id> [<plan-id>...][/warning]\n")
        return
    model, plan_ids = parts[0], parts[1:]
    from core.auth.plan_registry import get_plan_registry

    registry = get_plan_registry()
    unknown = [pid for pid in plan_ids if registry.get(pid) is None]
    if unknown:
        console.print(f"  [warning]Unknown plan(s): {', '.join(unknown)}[/warning]\n")
        return
    registry.set_routing(model, plan_ids)
    _persist_auth_state()
    console.print(f"  [success]Routing[/success] {model} → " + " → ".join(plan_ids) + "\n")


def _login_quota() -> None:
    from core.auth.plan_registry import get_plan_registry

    registry = get_plan_registry()
    plans = registry.list_all()
    quoted = [p for p in plans if p.quota is not None]
    if not quoted:
        console.print("  [muted]No quota-bearing plans registered.[/muted]\n")
        return
    console.print("\n  [header]Plan Quota[/header]")
    for plan in quoted:
        usage = registry.usage_for(plan.id)
        assert plan.quota is not None
        reset_in = usage.seconds_until_reset()
        reset_label = f"{reset_in // 60}m" if reset_in > 0 else "ready"
        console.print(
            f"  {plan.id:<24} "
            f"used {int(usage.weighted_calls):>4}/{plan.quota.max_calls} "
            f"· resets in {reset_label}"
            + (
                "  [muted](weights: "
                + ", ".join(f"{m}×{int(w)}" for m, w in plan.quota.model_weights.items())
                + ")[/muted]"
                if plan.quota.model_weights
                else ""
            )
        )
    console.print()


def resolve_action(cmd: str) -> str | None:
    """Resolve a slash command to its action name. Returns None if unknown."""
    return COMMAND_MAP.get(cmd)
