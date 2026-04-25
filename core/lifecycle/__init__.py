"""Runtime wiring sub-modules — OpenClaw-style decomposition of GeodeRuntime.create().

Modules:
    bootstrap  — hooks, memory, session, config_watcher, task, prompt, plugin_registry
    infra      — policies, tools, LLM, auth, lanes
    automation — L4.5 9 components + hook wiring
    adapters   — MCP signal/notification/calendar/gateway
"""

from core.lifecycle.bootstrap import get_plugin_status

__all__ = ["get_plugin_status"]
