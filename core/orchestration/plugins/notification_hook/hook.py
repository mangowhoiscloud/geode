"""Notification Hook Plugin — routes pipeline events to external messaging.

Registers hook handlers for key lifecycle events and sends notifications
via the NotificationPort adapter (Slack, Discord, Telegram).

Event → Notification mapping:
  PIPELINE_END      → info     "Pipeline completed: {ip_name} — {tier} ({score})"
  PIPELINE_ERROR    → critical "Pipeline error: {ip_name} — {error}"
  DRIFT_DETECTED    → warning  "Drift detected: {metric}"
  SUBAGENT_FAILED   → warning  "Sub-agent failed: {task_id}"
"""

from __future__ import annotations

import logging
from typing import Any

from core.orchestration.hooks import HookEvent, HookSystem

log = logging.getLogger(__name__)

# Event → severity mapping
_SEVERITY_MAP: dict[HookEvent, str] = {
    HookEvent.PIPELINE_END: "info",
    HookEvent.PIPELINE_ERROR: "critical",
    HookEvent.DRIFT_DETECTED: "warning",
    HookEvent.SUBAGENT_FAILED: "warning",
}


def _format_message(event: HookEvent, data: dict[str, Any]) -> str:
    """Format a notification message from hook event data."""
    ip_name = data.get("ip_name", "unknown")

    if event == HookEvent.PIPELINE_END:
        tier = data.get("tier", "?")
        score = data.get("final_score", data.get("score", 0))
        return f"Pipeline completed: {ip_name} — {tier} ({score:.1f})"

    if event == HookEvent.PIPELINE_ERROR:
        error = data.get("error", data.get("message", "unknown error"))
        return f"Pipeline error: {ip_name} — {error}"

    if event == HookEvent.DRIFT_DETECTED:
        metric = data.get("metric", data.get("field", "unknown"))
        return f"Drift detected: {metric}"

    if event == HookEvent.SUBAGENT_FAILED:
        task_id = data.get("task_id", "unknown")
        error = data.get("error", "")
        msg = f"Sub-agent failed: {task_id}"
        if error:
            msg += f" — {error}"
        return msg

    return f"[{event.value}] {data}"


def _make_notification_handler(
    channel: str,
    recipient: str,
) -> Any:
    """Create a hook handler that sends notifications for mapped events."""

    def handler(event: HookEvent, data: dict[str, Any]) -> None:
        from core.mcp.notification_port import get_notification

        adapter = get_notification()
        if adapter is None or not adapter.is_available(channel):
            log.debug(
                "Notification skipped for %s: no adapter for channel '%s'",
                event.value,
                channel,
            )
            return

        severity = _SEVERITY_MAP.get(event, "info")
        message = _format_message(event, data)

        result = adapter.send_message(channel, recipient, message, severity=severity)
        if not result.success:
            log.warning(
                "Notification send failed for %s → %s: %s",
                event.value,
                channel,
                result.error,
            )

    return handler


def handle(event: HookEvent, data: dict[str, Any]) -> None:
    """Entry point for hook_discovery YAML plugin loader.

    Uses default channel/recipient from config. For custom channels,
    use register_notification_hooks() directly.
    """
    from core.mcp.notification_port import get_notification

    adapter = get_notification()
    if adapter is None:
        return

    # Determine channel/recipient from config settings
    try:
        from core.config import settings

        channel = settings.notification_channel
        recipient = settings.notification_recipient
    except Exception:
        channel = "slack"
        recipient = "#geode-alerts"

    if not adapter.is_available(channel):
        return

    severity = _SEVERITY_MAP.get(event, "info")
    message = _format_message(event, data)
    adapter.send_message(channel, recipient, message, severity=severity)


def register_notification_hooks(
    hooks: HookSystem,
    *,
    channel: str = "slack",
    recipient: str = "#geode-alerts",
) -> None:
    """Register notification handlers for lifecycle events.

    Args:
        hooks: HookSystem instance to register with.
        channel: Default notification channel ("slack", "discord", "telegram").
        recipient: Default recipient (channel name, chat ID, etc.).
    """
    handler = _make_notification_handler(channel, recipient)

    for event in _SEVERITY_MAP:
        hooks.register(
            event,
            handler,
            name=f"notification_{event.value}",
            priority=200,  # Run after core handlers
        )

    log.info(
        "Notification hooks registered: events=%d, channel=%s, recipient=%s",
        len(_SEVERITY_MAP),
        channel,
        recipient,
    )
