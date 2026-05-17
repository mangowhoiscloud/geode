"""Output/Export Tools — LLM-callable tools for results export.

Layer 5 tools for output generation:
- GenerateReportTool: Generate a lightweight report artifact
- ExportJsonTool: Export analysis result as JSON file
- SendNotificationTool: Stub notification sender

All artifact-producing tools auto-save to Vault (.geode/vault/).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _save_to_vault(
    filename: str,
    content: str,
    *,
    category: str | None = None,
) -> None:
    """Best-effort save artifact to vault. Never raises."""
    try:
        from core.memory.vault import Vault

        vault = Vault()
        vault.ensure_structure()
        path = vault.save(filename, content, category=category)
        if path:
            log.info("Vault: saved %s", path)
    except Exception:
        log.debug("Vault save failed (best-effort)", exc_info=True)


class GenerateReportTool:
    """Tool for generating structured reports.

    Produces a lightweight artifact from caller-provided structured data.
    Domain-specific report generators belong in external plugins.
    """

    @property
    def name(self) -> str:
        return "generate_report"

    @property
    def description(self) -> str:
        return (
            "Generate a structured analysis report for a subject evaluation. "
            "Includes executive summary, scores, and recommendations."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Subject or title for the report.",
                },
                "analysis_data": {
                    "type": "object",
                    "description": "Analysis results to include in the report.",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json", "html"],
                    "description": "Output format for the report.",
                    "default": "markdown",
                },
            },
            "required": ["subject"],
        }

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        subject: str = kwargs.get("subject") or kwargs.get("subject_id") or "Untitled"
        analysis_data: dict[str, Any] = kwargs.get("analysis_data", {})
        fmt: str = kwargs.get("format", "markdown")

        tier = analysis_data.get("tier", "N/A")
        score = analysis_data.get("final_score", 0.0)

        report = {
            "title": f"GEODE Analysis Report: {subject}",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "format": fmt,
            "sections": {
                "executive_summary": (
                    f"Subject '{subject}' evaluated as Tier {tier} "
                    f"with final score {score:.1f}/100."
                ),
                "scores": analysis_data.get("subscores", {}),
                "tier": tier,
                "final_score": score,
                "recommendations": analysis_data.get("recommendation", "See full analysis."),
            },
        }

        # Auto-save to vault
        _save_to_vault(
            f"analysis-{subject.lower().replace(' ', '-')}.json",
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            category="research",
        )

        return {"result": report}

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Run report generation and vault writes off the event loop."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)


class ExportJsonTool:
    """Tool for exporting analysis results as JSON files."""

    @property
    def name(self) -> str:
        return "export_json"

    @property
    def description(self) -> str:
        return (
            "Export analysis result data as a JSON file to disk. "
            "Returns the file path of the exported file."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "description": "Data to export as JSON.",
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename (without path). Defaults to timestamped name.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory path. Defaults to current directory.",
                },
            },
            "required": ["data"],
        }

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        data: dict[str, Any] = kwargs["data"]
        filename: str = kwargs.get(
            "filename",
            f"geode_export_{int(time.time())}.json",
        )
        output_dir: str = kwargs.get("output_dir", ".")

        output_path = Path(output_dir) / filename

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            content_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
            output_path.write_text(content_str, encoding="utf-8")

            # Auto-save to vault
            _save_to_vault(filename, content_str)

            return {
                "result": {
                    "exported": True,
                    "path": str(output_path),
                    "size_bytes": output_path.stat().st_size,
                }
            }
        except OSError as e:
            return {
                "error": f"Failed to export JSON: {e}",
                "exported": False,
            }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Run JSON export and vault writes off the event loop."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)


class SendNotificationTool:
    """Send notifications via external messaging services.

    Routes to NotificationPort adapter (Slack, Discord, Telegram) when
    available; falls back to stub response in demo mode.
    """

    @property
    def name(self) -> str:
        return "send_notification"

    @property
    def description(self) -> str:
        return (
            "Send a notification about pipeline events (completion, alerts, drift). "
            "Supports channels: slack, discord, telegram, email, webhook."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "enum": ["slack", "discord", "telegram", "email", "webhook"],
                    "description": "Notification channel.",
                },
                "message": {
                    "type": "string",
                    "description": "Notification message body.",
                },
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "critical"],
                    "description": "Notification severity level.",
                    "default": "info",
                },
                "recipient": {
                    "type": "string",
                    "description": "Target recipient (channel name, chat ID, or URL).",
                },
            },
            "required": ["channel", "message"],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        from core.mcp.notification_port import get_notification

        channel: str = kwargs["channel"]
        message: str = kwargs["message"]
        severity: str = kwargs.get("severity", "info")
        recipient: str = kwargs.get("recipient", "default")

        adapter = get_notification()
        if adapter is not None and await adapter.ais_available(channel):
            result = await adapter.asend_message(channel, recipient, message, severity=severity)
            return _notification_result(result, severity, recipient, message)

        return _notification_unavailable_result(channel, severity, recipient, message)


def _notification_result(
    result: Any,
    severity: str,
    recipient: str,
    message: str,
) -> dict[str, Any]:
    return {
        "result": {
            "sent": result.success,
            "channel": result.channel,
            "severity": severity,
            "recipient": recipient,
            "message_id": result.message_id,
            "message_preview": message[:100],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error": result.error,
        }
    }


def _notification_unavailable_result(
    channel: str,
    severity: str,
    recipient: str,
    message: str,
) -> dict[str, Any]:
    return {
        "result": {
            "sent": False,
            "channel": channel,
            "severity": severity,
            "recipient": recipient,
            "message_preview": message[:100],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": f"No {channel} adapter available — notification not delivered.",
        }
    }
