"""Runtime wiring sub-modules — OpenClaw-style decomposition of GeodeRuntime.create().

Modules:
    bootstrap  — hooks, memory, session, config_watcher, task, prompt, plugin_registry
    infra      — policies, tools, LLM, auth, lanes
    scheduling — TriggerManager + SchedulerService + auto-trigger
    adapters   — MCP signal/notification/calendar/gateway
"""

from core.wiring.bootstrap import get_plugin_status

__all__ = ["get_plugin_status"]
