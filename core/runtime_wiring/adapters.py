"""MCP adapter wiring — signal, notification, calendar, gateway.

Extracted from core.runtime as standalone functions (formerly GeodeRuntime staticmethods).
"""

from __future__ import annotations

import logging
from typing import Any

from core.runtime_wiring.bootstrap import _plugin_status

log = logging.getLogger(__name__)


def build_signal_adapter() -> None:
    """Build and inject CompositeSignalAdapter with MCP-backed signal sources.

    Chains MCP signal adapters into CompositeSignalAdapter,
    then injects into signals_node via contextvars. If no MCP servers
    are configured or available, the adapter will report is_available()=False
    and signals_node falls back to fixtures.
    """
    from core.domains.game_ip.nodes.signals import set_signal_adapter
    from core.mcp.composite_signal import CompositeSignalAdapter
    from core.mcp.manager import get_mcp_manager
    from core.mcp.steam_adapter import SteamMCPSignalAdapter

    manager = get_mcp_manager()
    server_count = manager.load_config()

    if server_count == 0:
        log.debug("No MCP servers configured — signal adapter skipped (fixture fallback)")
        set_signal_adapter(None)
        return

    # Build individual MCP signal adapters
    adapters: list[SteamMCPSignalAdapter] = []

    steam_adapter = SteamMCPSignalAdapter(manager=manager, server_name="steam")
    adapters.append(steam_adapter)

    composite = CompositeSignalAdapter(adapters)  # type: ignore[arg-type]

    if composite.is_available():
        log.info(
            "Signal liveification enabled: %d MCP adapters wired",
            len(adapters),
        )
    else:
        log.debug("MCP servers configured but none available — fixture fallback active")

    set_signal_adapter(composite)


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
        SlackNotificationAdapter(manager=manager),
        DiscordNotificationAdapter(manager=manager),
        TelegramNotificationAdapter(manager=manager),
    ]
    composite = CompositeNotificationAdapter(adapters)  # type: ignore[arg-type]
    if composite.is_available():
        log.info("Notification adapter enabled: channels=%s", composite.list_channels())
    else:
        log.debug("No messaging MCP servers available — stub notification mode")
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
    if composite.is_available():
        log.info("Calendar adapter enabled: sources=%s", composite.list_sources())
    else:
        log.debug("No calendar MCP servers available — calendar tools disabled")
    set_calendar(composite)


_POLLER_REGISTRY: dict[str, str] = {
    "slack": "core.gateway.pollers.slack_poller:SlackPoller",
    "discord": "core.gateway.pollers.discord_poller:DiscordPoller",
    "telegram": "core.gateway.pollers.telegram_poller:TelegramPoller",
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


def build_gateway() -> None:
    """Build and inject Gateway with config-driven channel pollers.

    Reads ``[gateway] pollers`` from ``.geode/config.toml`` to determine
    which pollers to register. Defaults to all three (slack, discord,
    telegram) when the config key is absent.
    """
    from core.config import settings
    from core.gateway.channel_manager import ChannelManager, set_gateway
    from core.mcp.notification_port import get_notification

    if not settings.gateway_enabled:
        log.debug("Gateway disabled (GEODE_GATEWAY_ENABLED=false)")
        set_gateway(None)
        return

    # Wire Lane Queue for gateway concurrency control
    lane_queue = None
    try:
        from core.orchestration.lane_queue import LaneQueue

        lane_queue = LaneQueue()
        lane_queue.add_lane("gateway", max_concurrent=2, timeout_s=120.0)
    except Exception as exc:
        _plugin_status["gateway_lane_queue"] = "unavailable"
        log.warning("Plugin gateway_lane_queue: %s", exc)

    manager = ChannelManager(lane_queue=lane_queue)
    notification = get_notification()
    poll_interval = settings.gateway_poll_interval_s

    # Load config from TOML
    toml_config: dict[str, Any] = {}
    config_path = None
    try:
        import tomllib
        from pathlib import Path

        config_path = Path(".geode") / "config.toml"
        if config_path.exists():
            with open(config_path, "rb") as f:
                toml_config = tomllib.load(f)
            manager.load_bindings_from_config(toml_config)
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
        import tomllib
        from pathlib import Path

        from core.orchestration.hot_reload import ConfigWatcher

        def _reload_bindings(path: Any, mtime: float) -> None:
            try:
                reload_config: dict[str, Any] = {}
                if Path(path).exists():
                    with open(path, "rb") as fh:
                        reload_config = tomllib.load(fh)
                manager.load_bindings_from_config(reload_config)
                log.info("Gateway bindings reloaded from %s", path)
            except Exception as reload_exc:
                log.warning("Gateway binding reload failed: %s", reload_exc)

        if config_path and config_path.exists():
            _watcher = ConfigWatcher()
            _watcher.watch(config_path, _reload_bindings, name="gateway-bindings")
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
    """Wire all MCP plugin adapters: signal, notification, calendar, gateway."""
    build_signal_adapter()
    build_notification_adapter()
    build_calendar_adapter()
    build_gateway()
    try:
        from core.automation.calendar_bridge import set_calendar_bridge
        from core.mcp.calendar_port import get_calendar

        cal = get_calendar()
        if cal is None or not cal.is_available():
            set_calendar_bridge(None)
        else:
            log.debug("Calendar adapter available — bridge will wire in REPL")
    except Exception as exc:
        _plugin_status["calendar_bridge"] = "error"
        log.warning("Plugin calendar_bridge: setup failed (%s)", exc)
