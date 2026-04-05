"""Slash command dispatch — extracted from CLI REPL.

OpenClaw-inspired Binding Router pattern: static command → handler mapping.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any as _Any

if TYPE_CHECKING:
    from core.cli.session_checkpoint import SessionState

from simple_term_menu import TerminalMenu

from core.cli._helpers import is_glm_key as _is_glm_key
from core.cli._helpers import mask_key as _mask_key
from core.cli._helpers import upsert_env as _upsert_env
from core.cli.ui.console import console
from core.config import (
    ANTHROPIC_BUDGET,
    ANTHROPIC_PRIMARY,
    ANTHROPIC_SECONDARY,
    GLM_PRIMARY,
    OPENAI_PRIMARY,
)
from core.gateway.auth.profiles import ProfileStore

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


MODEL_PROFILES: list[ModelProfile] = [
    ModelProfile(ANTHROPIC_PRIMARY, "Anthropic", "Opus 4.6", "$$$"),
    ModelProfile(ANTHROPIC_SECONDARY, "Anthropic", "Sonnet 4.6", "$$"),
    ModelProfile(ANTHROPIC_BUDGET, "Anthropic", "Haiku 4.5", "$"),
    ModelProfile(OPENAI_PRIMARY, "OpenAI", "GPT-5.4", "$$"),
    ModelProfile(GLM_PRIMARY, "ZhipuAI", "GLM-5", "$"),
    ModelProfile("glm-5-turbo", "ZhipuAI", "GLM-5 Turbo", "$"),
    ModelProfile("glm-4.7-flash", "ZhipuAI", "GLM-4.7 Flash", "$"),
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
    console.print("  [label]/key[/label] <value>        — Set API key (auto-detect provider)")
    console.print("  [label]/key openai[/label] <value> — Set OpenAI API key")
    console.print("  [label]/key glm[/label] <value>    — Set ZhipuAI API key")
    console.print("  [label]/model[/label]              — Show & switch LLM model")
    console.print("  [label]/auth[/label]               — Manage auth profiles")
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
    """Handle /key command. Returns True if readiness should be rechecked."""
    from core.config import settings

    parts = args.split(None, 1) if args else []

    # /key (no args) → show current status
    if not parts:
        anthro = (
            _mask_key(settings.anthropic_api_key)
            if settings.anthropic_api_key
            else "[muted]not set[/muted]"
        )
        openai = (
            _mask_key(settings.openai_api_key)
            if settings.openai_api_key
            else "[muted]not set[/muted]"
        )
        zhipu = (
            _mask_key(settings.zai_api_key) if settings.zai_api_key else "[muted]not set[/muted]"
        )
        console.print()
        console.print(f"  [label]Anthropic[/label]  {anthro}")
        console.print(f"  [label]OpenAI[/label]    {openai}")
        console.print(f"  [label]ZhipuAI[/label]   {zhipu}")
        console.print()
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
        console.print(f"  [success]Anthropic API key set[/success]  {_mask_key(value)}")
    elif value.startswith("sk-proj-") or value.startswith("sk-"):
        settings.openai_api_key = value
        _upsert_env("OPENAI_API_KEY", value)
        try:
            from core.llm.providers.openai import reset_openai_client

            reset_openai_client()
        except ImportError:
            pass
        console.print(f"  [success]OpenAI API key set[/success]  {_mask_key(value)}")
    elif _is_glm_key(value):
        settings.zai_api_key = value
        _upsert_env("ZAI_API_KEY", value)
        try:
            from core.llm.providers.glm import reset_glm_client

            reset_glm_client()
        except ImportError:
            pass
        console.print(f"  [success]ZhipuAI API key set[/success]  {_mask_key(value)}")
    else:
        console.print(
            "  [warning]Unrecognized key prefix. Use:[/warning]\n"
            "  [muted]/key <sk-ant-...>          → Anthropic[/muted]\n"
            "  [muted]/key openai <sk-proj-...>  → OpenAI[/muted]\n"
            "  [muted]/key glm <key>             → ZhipuAI[/muted]"
        )
        console.print()
        return False
    console.print()
    return True


def _check_provider_key(selected: ModelProfile) -> None:
    """Warn if the provider's API key is not set for the selected model."""
    from core.cli.startup import _is_placeholder
    from core.config import settings

    provider_key_map: dict[str, tuple[str, str]] = {
        "Anthropic": (settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
        "OpenAI": (settings.openai_api_key, "OPENAI_API_KEY"),
        "ZhipuAI": (settings.zai_api_key, "ZAI_API_KEY"),
    }
    entry = provider_key_map.get(selected.provider)
    if entry is None:
        return
    key_value, env_var = entry
    if not key_value or _is_placeholder(key_value):
        console.print(f"  [warning]Warning: {env_var} not set. Model may not work.[/warning]")


def _apply_model(selected: ModelProfile) -> None:
    """Apply a model selection — update settings + .env.

    Includes context window guard: blocks downgrade when current context
    exceeds 80% of the target model's window.
    """
    from core.config import settings

    old = settings.model
    if selected.id == old:
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

    settings.model = selected.id
    _upsert_env("GEODE_MODEL", selected.id)

    # Model hot-swap is deferred: AgenticLoop._sync_model_from_settings()
    # checks settings.model at the start of each round and applies
    # the change safely between LLM calls. Direct loop.update_model()
    # during tool execution caused adapter swap mid-call → crash.

    console.print(
        f"  [success]Model[/success]  {old} → [bold]{selected.label}[/bold]"
        f"  [muted]({selected.id})[/muted]"
    )
    console.print()


def _interactive_model_picker() -> None:
    """Arrow-key interactive model picker (OpenClaw Auth Profile Rotation)."""
    from core.config import settings

    # Build menu entries
    entries: list[str] = []
    current_idx = 0
    for i, p in enumerate(MODEL_PROFILES):
        if p.id == settings.model:
            current_idx = i
        entries.append(f"{p.label:<12} {p.provider:<10} {p.cost}")

    menu = TerminalMenu(
        entries,
        title="\n  Models  (↑↓ select, Enter confirm, q cancel)\n",
        cursor_index=current_idx,
        menu_cursor="  > ",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("fg_cyan", "bold"),
    )
    idx = menu.show()
    if idx is None:
        console.print("  [muted]Cancelled[/muted]")
        console.print()
        return

    _apply_model(MODEL_PROFILES[idx])


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

    # Anthropic
    claude_ok = False
    try:
        from core.gateway.auth.claude_code_oauth import (
            read_claude_code_credentials,
        )

        creds = read_claude_code_credentials(force_refresh=True)
        if creds:
            sub = creds.get("subscription_type", "unknown")
            console.print(
                f"  [success]\u2713[/success] Anthropic  Claude Code OAuth ({sub.capitalize()})"
            )
            claude_ok = True
    except Exception:  # noqa: S110
        pass
    if not claude_ok:
        console.print("  [error]\u2717[/error] Anthropic  [muted]not logged in[/muted]")
    providers.append({"name": "Anthropic", "cli": "claude", "ok": claude_ok})

    # OpenAI
    codex_ok = False
    try:
        from core.gateway.auth.codex_cli_oauth import (
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
    from core.gateway.auth.profiles import AuthProfile, CredentialType

    store = _get_profile_store()

    if cli_name == "claude":
        from core.gateway.auth.claude_code_oauth import (
            invalidate_cache,
            read_claude_code_credentials,
        )

        invalidate_cache()
        creds = read_claude_code_credentials(force_refresh=True)
        if creds:
            profile = AuthProfile(
                name="anthropic:claude-code",
                provider="anthropic",
                credential_type=CredentialType.OAUTH,
                key=creds["access_token"],
                refresh_token=creds.get("refresh_token", ""),
                expires_at=creds.get("expires_at", 0.0),
                managed_by="claude-code",
                metadata={
                    **(
                        {"subscription_type": creds["subscription_type"]}
                        if "subscription_type" in creds
                        else {}
                    ),
                    **(
                        {"rate_limit_tier": creds["rate_limit_tier"]}
                        if "rate_limit_tier" in creds
                        else {}
                    ),
                },
            )
            store.add(profile)

    elif cli_name == "codex":
        from core.gateway.auth.codex_cli_oauth import (
            invalidate_cache as codex_invalidate,
        )
        from core.gateway.auth.codex_cli_oauth import (
            read_codex_cli_credentials,
        )

        codex_invalidate()
        codex_creds = read_codex_cli_credentials(force_refresh=True)
        if codex_creds:
            profile = AuthProfile(
                name="openai:codex-cli",
                provider="openai",
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
    from core.gateway.auth.rotation import ProfileRotator

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

    from core.gateway.auth.profiles import AuthProfile, CredentialType

    # Level 1: Provider selection
    providers = ["anthropic", "openai", "zhipuai"]
    entries = ["Anthropic", "OpenAI", "ZhipuAI"]

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


# Module-level profile store singleton
_profile_store: ProfileStore | None = None


def _get_profile_store() -> ProfileStore:
    """Get or create the module-level profile store, seeded from settings."""
    global _profile_store
    from core.gateway.auth.profiles import AuthProfile, CredentialType

    if _profile_store is not None:
        return _profile_store

    store = ProfileStore()

    # Seed from existing settings
    from core.config import settings

    if settings.anthropic_api_key:
        store.add(
            AuthProfile(
                name="anthropic:default",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key=settings.anthropic_api_key,
            )
        )
    if settings.openai_api_key:
        store.add(
            AuthProfile(
                name="openai:default",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key=settings.openai_api_key,
            )
        )
    if settings.zai_api_key:
        store.add(
            AuthProfile(
                name="zhipuai:default",
                provider="zhipuai",
                credential_type=CredentialType.API_KEY,
                key=settings.zai_api_key,
            )
        )
    _profile_store = store
    return store


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
            from core.cli.ui.agentic_ui import render_status_line

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
        except Exception:
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
    except Exception:
        console.print("  [label]T0 SOUL:[/label] [muted]unavailable[/muted]")

    # Tier 0.5: User Profile
    try:
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        summary = profile.get_context_summary()
        console.print(f"  [label]T0.5 Profile:[/label] {summary or '[muted]empty[/muted]'}")
        career_summary = profile.get_career_summary()
        if career_summary:
            console.print(f"  [label]T0.5 Career:[/label] {career_summary}")
    except Exception:
        console.print("  [label]T0.5 Profile:[/label] [muted]unavailable[/muted]")

    # Tier 1: Project Memory
    try:
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if mem.exists():
            rules = mem.list_rules()
            console.print(f"  [label]T1 Project:[/label] {len(rules)} rules")
        else:
            console.print("  [label]T1 Project:[/label] [muted]not initialized[/muted]")
    except Exception:
        console.print("  [label]T1 Project:[/label] [muted]unavailable[/muted]")

    # Vault
    try:
        from core.memory.vault import Vault

        vault = Vault()
        vs = vault.get_context_summary()
        console.print(f"  [label]V0 Vault:[/label] {vs or '[muted]empty[/muted]'}")
    except Exception:
        console.print("  [label]V0 Vault:[/label] [muted]unavailable[/muted]")

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


def resolve_action(cmd: str) -> str | None:
    """Resolve a slash command to its action name. Returns None if unknown."""
    return COMMAND_MAP.get(cmd)
