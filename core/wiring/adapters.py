"""MCP adapter wiring — notification, calendar, gateway.

Extracted from core.runtime as standalone functions (formerly GeodeRuntime staticmethods).
"""

from __future__ import annotations

import logging
from typing import Any

from core.wiring.bootstrap import _plugin_status

log = logging.getLogger(__name__)


def _load_mcp_manager_for_plugin(
    plugin_name: str,
    setter_fn: Any,
) -> Any | None:
    """Load MCP manager config, or mark plugin unavailable and return None."""
    from core.mcp.manager import get_mcp_manager

    try:
        manager = get_mcp_manager()
        manager.load_config()
        return manager
    except Exception as exc:
        _plugin_status[plugin_name] = "unavailable"
        log.warning("Plugin %s: MCP manager failed (%s)", plugin_name, exc)
        setter_fn(None)
        return None


def build_notification_adapter() -> None:
    """Build and inject CompositeNotificationAdapter with MCP-backed channels.

    Chains Slack + Discord + Telegram adapters. If no messaging MCP servers
    are available, notification tools fall back to stub responses.
    """
    from core.mcp.composite_notification import CompositeNotificationAdapter
    from core.mcp.discord_adapter import DiscordNotificationAdapter
    from core.mcp.notification_port import set_notification
    from core.mcp.slack_adapter import SlackNotificationAdapter
    from core.mcp.telegram_adapter import TelegramNotificationAdapter

    manager = _load_mcp_manager_for_plugin("notification_adapter", set_notification)
    if manager is None:
        return

    adapters = [
        # Slack posts directly to the Web API (PR-SLACK-TRANSPORT);
        # Discord/Telegram remain MCP-backed.
        SlackNotificationAdapter(),
        DiscordNotificationAdapter(manager=manager),
        TelegramNotificationAdapter(manager=manager),
    ]
    composite = CompositeNotificationAdapter(adapters)  # type: ignore[arg-type]
    log.info("Notification adapter wired: channels=%s", composite.list_channels())
    set_notification(composite)


def build_calendar_adapter() -> None:
    """Build and inject CompositeCalendarAdapter with MCP-backed sources.

    Chains Google Calendar + CalDAV (Apple Calendar) adapters.
    If no calendar MCP servers are available, calendar tools return empty.
    """
    from core.mcp.apple_calendar_adapter import AppleCalendarAdapter
    from core.mcp.calendar_port import set_calendar
    from core.mcp.composite_calendar import CompositeCalendarAdapter
    from core.mcp.google_calendar_adapter import GoogleCalendarAdapter

    manager = _load_mcp_manager_for_plugin("calendar_adapter", set_calendar)
    if manager is None:
        return

    adapters = [
        GoogleCalendarAdapter(manager=manager),
        AppleCalendarAdapter(manager=manager),
    ]
    composite = CompositeCalendarAdapter(adapters)  # type: ignore[arg-type]
    log.info("Calendar adapter wired; availability will be checked at call time")
    set_calendar(composite)


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
    from core.messaging.slack_transport import resolve_bot_token

    token = resolve_bot_token()
    if not token:
        return ""
    try:
        import httpx

        resp = httpx.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
        data = resp.json()
        if data.get("ok"):
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

    from core.paths import GLOBAL_CONFIG_TOML, PROJECT_CONFIG_TOML

    merged_gateway: dict[str, Any] = {}
    merged_rules: list[dict[str, Any]] = []
    sources: list[str] = []
    for label, path in (("global", GLOBAL_CONFIG_TOML), ("project", PROJECT_CONFIG_TOML)):
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
                    merged_rules.extend(r for r in rules if isinstance(r, dict))
            else:
                merged_gateway[key] = value  # later (project) wins on scalars
    if merged_rules:
        merged_gateway["bindings"] = {"rules": merged_rules}
    return ({"gateway": merged_gateway} if merged_gateway else {}), sources


def build_gateway() -> None:
    """Build and inject Gateway with config-driven channel pollers.

    Reads ``[gateway] pollers`` from ``.geode/config.toml`` to determine
    which pollers to register. Defaults to all three (slack, discord,
    telegram) when the config key is absent.
    """
    from core.config import settings
    from core.mcp.notification_port import get_notification
    from core.messaging.binding import ChannelManager, set_gateway

    if not settings.gateway_enabled:
        log.debug("Gateway disabled (GEODE_GATEWAY_ENABLED=false)")
        set_gateway(None)
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
    notification = get_notification()
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

        mcp = get_mcp_manager(auto_startup=True)
        log.info("Gateway MCP: %d/%d servers connected", len(mcp._clients), len(mcp._servers))
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

        from core.paths import GLOBAL_CONFIG_TOML as _GLOBAL_TOML
        from core.paths import PROJECT_CONFIG_TOML as _PROJECT_TOML

        _watcher = ConfigWatcher()
        _watched_any = False
        for _cfg in (_GLOBAL_TOML, _PROJECT_TOML):
            if _cfg.exists():
                _watcher.watch(_cfg, _reload_bindings, name=f"gateway-bindings:{_cfg}")
                _watched_any = True
        if _watched_any:
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


def build_plugins() -> None:
    """Wire all MCP plugin adapters: notification, calendar, gateway."""
    build_notification_adapter()
    build_calendar_adapter()
    build_gateway()
    try:
        from core.mcp.calendar_port import get_calendar
        from core.scheduler.calendar_bridge import set_calendar_bridge

        cal = get_calendar()
        if cal is None:
            set_calendar_bridge(None)
        else:
            log.debug("Calendar adapter available — bridge will wire in REPL")
    except Exception as exc:
        _plugin_status["calendar_bridge"] = "error"
        log.warning("Plugin calendar_bridge: setup failed (%s)", exc)
