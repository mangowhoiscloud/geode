"""MCP adapter wiring — notification, calendar, gateway.

Extracted from core.runtime as standalone functions (formerly GeodeRuntime staticmethods).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.mcp.manager import MCPServerManager

from core.wiring.bootstrap import _plugin_status

log = logging.getLogger(__name__)


def build_slack_transport() -> Any:
    """Construct the direct Slack transport at the outer wiring boundary."""
    from core.messaging.slack_transport import SlackTransport

    return SlackTransport()


async def open_slack_socket_mode_url(app_token: str) -> str:
    """Open one temporary Slack Socket Mode URL through outer wiring."""
    from core.messaging.slack_transport import open_socket_mode_url

    return await open_socket_mode_url(app_token)


def get_gateway_manager() -> Any:
    """Return the active messaging gateway from outer composition."""
    from core.messaging.binding import get_gateway

    return get_gateway()


def start_gateway_webhook(processor: Any, *, port: int) -> Any:
    """Start the supervised webhook server at the wiring boundary."""
    from core.server.supervised.webhook_handler import start_webhook_server

    return start_webhook_server(processor, port=port)


def build_cli_poller(
    services: Any,
    *,
    scheduler_service: Any,
    command_handler: Any,
    context_initializer: Any,
) -> Any:
    """Build the daemon IPC poller with CLI capabilities injected."""
    from core.server.ipc_server.poller import CLIPoller

    return CLIPoller(
        services,
        scheduler_service=scheduler_service,
        command_handler=command_handler,
        context_initializer=context_initializer,
    )


def build_notification_adapter(*, mcp_manager: MCPServerManager) -> Any:
    """Build a CompositeNotificationAdapter with MCP-backed channels.

    Chains Slack + Discord + Telegram adapters. If no messaging MCP servers
    are available, notification tools report that the message was not sent.
    """
    from core.mcp.composite_notification import CompositeNotificationAdapter
    from core.mcp.discord_adapter import DiscordNotificationAdapter
    from core.mcp.slack_adapter import SlackNotificationAdapter
    from core.mcp.telegram_adapter import TelegramNotificationAdapter

    adapters = [
        # Slack posts directly to the Web API (PR-SLACK-TRANSPORT);
        # Discord/Telegram remain MCP-backed.
        SlackNotificationAdapter(),
        DiscordNotificationAdapter(manager=mcp_manager),
        TelegramNotificationAdapter(manager=mcp_manager),
    ]
    composite = CompositeNotificationAdapter(adapters)  # type: ignore[arg-type]
    log.info("Notification adapter wired: channels=%s", composite.list_channels())
    return composite


def build_calendar_adapter(*, mcp_manager: MCPServerManager) -> Any:
    """Build direct Google OAuth plus MCP-backed calendar sources.

    The direct Google adapter is always present and discovers credentials at
    call time, so /login google takes effect without restarting the daemon.
    Google/Apple MCP adapters remain available as compatibility fallbacks.
    """
    from core.mcp.apple_calendar_adapter import AppleCalendarAdapter
    from core.mcp.composite_calendar import CompositeCalendarAdapter
    from core.mcp.google_calendar_adapter import GoogleCalendarAdapter
    from core.mcp.google_workspace_calendar import GoogleWorkspaceCalendarAdapter

    adapters: list[Any] = [GoogleWorkspaceCalendarAdapter()]
    adapters.extend(
        [
            GoogleCalendarAdapter(manager=mcp_manager),
            AppleCalendarAdapter(manager=mcp_manager),
        ]
    )
    composite = CompositeCalendarAdapter(adapters)
    log.info("Calendar adapter wired; availability will be checked at call time")
    return composite


_POLLER_REGISTRY: dict[str, str] = {
    "slack": "core.server.supervised.slack_poller:SlackPoller",
    "discord": "core.server.supervised.discord_poller:DiscordPoller",
    "telegram": "core.server.supervised.telegram_poller:TelegramPoller",
    # CLI poller is registered separately in serve() (not config-driven)
}

_DEFAULT_POLLERS: list[str] = ["slack", "discord", "telegram"]


def _load_poller_class(dotted_path: str) -> type:
    """Dynamically import a poller class from 'module.path:ClassName'."""
    import importlib

    module_path, class_name = dotted_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    cls: type = getattr(module, class_name)
    return cls


def _resolve_slack_bot_user_id() -> str:
    """Resolve GEODE's Slack bot user ID via auth.test API (best-effort)."""
    import asyncio

    from core.messaging.slack_transport import get_slack_transport

    transport = get_slack_transport()
    if not transport.configured:
        return ""
    try:
        data = asyncio.run(transport.auth_test())
        uid: str = data.get("user_id", "")
        if uid:
            log.info("Resolved Slack bot user ID: %s", uid)
        return uid
    except Exception as exc:
        log.debug("Failed to resolve Slack bot user ID: %s", exc)
    return ""


def _load_gateway_config() -> tuple[dict[str, Any], list[str]]:
    """Merge the [gateway] config: global SoT + project overlay.

    Returns ``(merged_config, source_labels)``. Scalar keys: project
    overrides global. ``bindings.rules``: global rules first, project
    rules appended (both active). Either file may be absent.
    """
    import tomllib

    from core.config.toml_edit import resolve_config_toml_path
    from core.paths import PROJECT_CONFIG_TOML

    merged_gateway: dict[str, Any] = {}
    # (channel, channel_id) -> rule; a project rule REPLACES the global
    # rule for the same key (override, not duplicate — a duplicate would
    # double-poll the channel and shadow the project's settings behind
    # first-match routing).
    merged_rules: dict[tuple[str, str], dict[str, Any]] = {}
    sources: list[str] = []
    for label, path in (("global", resolve_config_toml_path()), ("project", PROJECT_CONFIG_TOML)):
        if not path.exists():
            continue
        try:
            with open(path, "rb") as fh:
                raw = tomllib.load(fh)
        except Exception:
            log.warning("Gateway config unreadable: %s", path, exc_info=True)
            continue
        gw = raw.get("gateway")
        if not isinstance(gw, dict):
            continue
        sources.append(f"{label}:{path}")
        for key, value in gw.items():
            if key == "bindings":
                rules = value.get("rules", []) if isinstance(value, dict) else []
                if isinstance(rules, list):
                    for rule in rules:
                        if isinstance(rule, dict):
                            rule_key = (
                                str(rule.get("channel", "")),
                                str(rule.get("channel_id", "")),
                            )
                            merged_rules[rule_key] = rule
            else:
                merged_gateway[key] = value  # later (project) wins on scalars
    if merged_rules:
        merged_gateway["bindings"] = {"rules": list(merged_rules.values())}
    return ({"gateway": merged_gateway} if merged_gateway else {}), sources


def build_gateway(*, notification: Any = None, mcp_manager: MCPServerManager | None = None) -> None:
    """Build the channel manager and optional external-channel pollers.

    Reads ``[gateway] pollers`` from ``.geode/config.toml`` to determine
    which pollers to register. Defaults to all three (slack, discord,
    telegram) when the config key is absent. When the external gateway is
    disabled, an empty manager still backs the local CLI IPC daemon.
    """
    from core.config import settings
    from core.messaging.binding import ChannelManager, set_gateway

    if not settings.gateway_enabled:
        set_gateway(ChannelManager())
        log.debug("External gateway disabled; local CLI channel remains available")
        return

    # Use the unified LaneQueue from runtime (gateway lane already registered)
    from core.wiring.container import build_default_lanes

    try:
        lane_queue = build_default_lanes()
    except Exception as exc:
        _plugin_status["gateway_lane_queue"] = "unavailable"
        log.warning("Plugin gateway_lane_queue: %s", exc)
        lane_queue = None

    # Resolve GEODE's Slack bot user ID for accurate mention detection.
    # Prefers SLACK_BOT_USER_ID env var; falls back to auth.test API call.
    import os

    from core.messaging.slack_transport import resolve_bot_token

    bot_user_id = os.environ.get("SLACK_BOT_USER_ID", "")
    if not bot_user_id and resolve_bot_token():
        bot_user_id = _resolve_slack_bot_user_id()

    manager = ChannelManager(lane_queue=lane_queue, bot_user_id=bot_user_id)
    poll_interval = settings.gateway_poll_interval_s

    # Load config from TOML — root-level SoT (PR-SLACK-TRANSPORT).
    # The user-level ~/.geode/config.toml [gateway] is authoritative; the
    # project .geode/config.toml may OVERLAY it (scalar keys win, binding
    # rules append). Previously only the project file was read, so the
    # daemon's entire Slack surface silently depended on its launchd
    # WorkingDirectory.
    toml_config: dict[str, Any] = {}
    try:
        toml_config, config_sources = _load_gateway_config()
        if toml_config.get("gateway"):
            manager.load_bindings_from_config(toml_config)
            log.info("Gateway config sources: %s", ", ".join(config_sources) or "none")
    except Exception as exc:
        _plugin_status["gateway_bindings"] = "skipped"
        log.warning("Plugin gateway_bindings: config load failed (%s)", exc)

    try:
        from core.mcp.manager import get_mcp_manager

        if mcp_manager is None:
            mcp = get_mcp_manager(auto_startup=True)
        else:
            mcp = mcp_manager
            mcp.startup()
        log.info(
            "Gateway MCP: %d/%d servers connected",
            mcp.connected_count,
            mcp.server_count,
        )
    except Exception as exc:
        _plugin_status["gateway_mcp"] = "unavailable"
        log.warning("Plugin gateway_mcp: MCP manager failed (%s)", exc)
        set_gateway(None)
        return

    # Config-driven poller registration
    enabled_pollers: list[str] = toml_config.get("gateway", {}).get("pollers", _DEFAULT_POLLERS)

    for poller_name in enabled_pollers:
        dotted = _POLLER_REGISTRY.get(poller_name)
        if dotted is None:
            log.warning("Unknown poller '%s' in config — skipped", poller_name)
            continue
        try:
            poller_cls = _load_poller_class(dotted)
            manager.register_poller(
                poller_cls(
                    manager,
                    mcp_manager=mcp,
                    notification=notification,
                    poll_interval_s=poll_interval,
                )
            )
        except Exception as exc:
            log.warning("Poller '%s' init failed: %s", poller_name, exc)

    # Hot-reload bindings on config.toml change
    try:
        from core.orchestration.hot_reload import ConfigWatcher

        def _reload_bindings(path: Any, mtime: float) -> None:
            try:
                reload_config, reload_sources = _load_gateway_config()
                manager.load_bindings_from_config(reload_config)
                log.info(
                    "Gateway bindings reloaded (trigger=%s, sources=%s)",
                    path,
                    ", ".join(reload_sources) or "none",
                )
            except Exception as reload_exc:
                log.warning("Gateway binding reload failed: %s", reload_exc)

        from core.config.toml_edit import resolve_config_toml_path
        from core.paths import PROJECT_CONFIG_TOML as _PROJECT_TOML

        _watcher = ConfigWatcher()
        # Watch BOTH paths even when absent at boot — an overlay created
        # (or removed) later must re-merge without a daemon restart.
        for _cfg in (resolve_config_toml_path(), _PROJECT_TOML):
            _watcher.watch(_cfg, _reload_bindings, name=f"gateway-bindings:{_cfg}")
        _watcher.start()
        # Attach to manager to prevent GC (daemon thread lifetime)
        manager._binding_watcher = _watcher  # type: ignore[attr-defined]
    except Exception as exc:
        _plugin_status["gateway_hot_reload"] = "unavailable"
        log.debug("Gateway binding hot-reload not available: %s", exc)

    set_gateway(manager)
    log.info(
        "Gateway built with %d pollers (configured: %s)", len(manager._pollers), enabled_pollers
    )


def build_plugins(*, mcp_manager: MCPServerManager) -> tuple[Any | None, Any]:
    """Build plugin adapters and return the owned notification/calendar pair."""
    notification = build_notification_adapter(mcp_manager=mcp_manager)
    calendar = build_calendar_adapter(mcp_manager=mcp_manager)
    build_gateway(notification=notification, mcp_manager=mcp_manager)
    return notification, calendar
