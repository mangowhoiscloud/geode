"""Output/Export Tools — LLM-callable tools for results export.

Layer 5 tools for output generation:
- GenerateReportTool: Render a markdown/json/html report artifact with a save receipt
- ExportJsonTool: Export analysis result as JSON file
- SendNotificationTool: Deliver through the injected NotificationPort, or report not sent

All artifact-producing tools auto-save to Vault (.geode/vault/).
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import time
from collections.abc import Callable
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


_REPORT_FORMATS = {"markdown": ".md", "json": ".json", "html": ".html"}
_REPORT_KNOWN_KEYS = ("summary", "tier", "final_score", "subscores", "recommendation", "findings")


def _report_sections(subject: str, data: dict[str, Any]) -> dict[str, Any]:
    """Project caller data into report sections; absent values stay None."""
    score = data.get("final_score")
    tier = data.get("tier")
    if data.get("summary"):
        summary = str(data["summary"])
    elif score is not None:
        tier_text = f" as Tier {tier}" if tier is not None else ""
        summary = f"Subject '{subject}' evaluated{tier_text} with final score {score:.1f}/100."
    else:
        summary = None
    findings = data.get("findings")
    return {
        "executive_summary": summary,
        "scores": data.get("subscores") if data.get("subscores") is not None else {},
        "tier": tier,
        "final_score": score,
        "findings": findings if isinstance(findings, list) or findings is None else [findings],
        "recommendations": data.get("recommendation"),
        "details": {k: v for k, v in data.items() if k not in _REPORT_KNOWN_KEYS},
    }


def _items(value: Any, text: Callable[[Any], str]) -> list[str]:
    """One display line per entry of a caller value of any JSON shape."""
    if isinstance(value, dict):
        return [f"{k}: {text(v)}" for k, v in value.items()]
    if isinstance(value, list):
        return [text(v) for v in value]
    return [] if value in (None, "") else [text(value)]


def _render_report(report: dict[str, Any], fmt: str) -> str:
    """Serialize the report in the requested format (values escaped for HTML)."""
    if fmt == "json":
        return json.dumps(report, indent=2, ensure_ascii=False, default=str)
    sections = report["sections"]
    unknown = "not provided"

    def text(value: Any) -> str:
        if value is None:
            return unknown
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    blocks: list[tuple[str, list[str]]] = [
        ("Summary", [text(sections["executive_summary"])]),
        ("Tier", [text(sections["tier"])]),
        ("Final score", [text(sections["final_score"])]),
        ("Scores", _items(sections["scores"], text) or [unknown]),
        ("Findings", _items(sections["findings"] or [], text) or [unknown]),
        ("Recommendations", [text(sections["recommendations"])]),
    ]
    if sections["details"]:
        blocks.append(("Details", [f"{k}: {text(v)}" for k, v in sections["details"].items()]))
    if fmt == "markdown":
        lines = [f"# {report['title']}", "", f"_Generated {report['generated_at']}_", ""]
        for heading, items in blocks:
            lines += [f"## {heading}", "", *(f"- {item}" for item in items), ""]
        return "\n".join(lines)
    esc = html.escape
    body = "".join(
        f"<h2>{esc(heading)}</h2><ul>{''.join(f'<li>{esc(i)}</li>' for i in items)}</ul>"
        for heading, items in blocks
    )
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>{esc(report['title'])}</title></head><body>"
        f"<h1>{esc(report['title'])}</h1><p><em>Generated {esc(report['generated_at'])}"
        f"</em></p>{body}</body></html>\n"
    )


class GenerateReportTool:
    """Tool for generating structured reports.

    Renders caller-provided analysis data in the requested format, saves the
    exact bytes to the Vault, and returns the saved path as the receipt.
    Specialized report generators belong in external packages.
    """

    def __init__(self, vault: Any = None) -> None:
        self._vault = vault

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
            "required": [],
        }

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        from core.memory.vault import Vault, _slugify
        from core.tools.base import tool_error

        subject = str(kwargs.get("subject") or kwargs.get("subject_id") or "Untitled")
        analysis_data = kwargs.get("analysis_data") or {}
        fmt = str(kwargs.get("format") or "markdown")
        if fmt not in _REPORT_FORMATS:
            return tool_error(
                f"Unsupported report format '{fmt}'; use one of {sorted(_REPORT_FORMATS)}",
                error_type="validation",
            )
        if not isinstance(analysis_data, dict):
            return tool_error("analysis_data must be an object", error_type="validation")
        score = analysis_data.get("final_score")
        if score is not None and (isinstance(score, bool) or not isinstance(score, int | float)):
            return tool_error("final_score must be a number when provided", error_type="validation")

        report: dict[str, Any] = {
            "title": f"GEODE Analysis Report: {subject}",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "format": fmt,
            "sections": _report_sections(subject, analysis_data),
        }
        content = _render_report(report, fmt)
        vault = self._vault or Vault()
        try:
            path = vault.save(
                f"analysis-{_slugify(subject)}{_REPORT_FORMATS[fmt]}",
                content,
                category="research",
            )
        except OSError as exc:
            return tool_error(f"Report was rendered but not saved: {exc}", error_type="internal")
        encoded = content.encode("utf-8")
        report["artifact"] = {
            "path": str(path),
            "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
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

    Routes to the NotificationPort adapter (Slack, Discord, Telegram) when
    available. Without one the result says ``sent: false``; a failed send is
    a top-level error.
    """

    def __init__(self, notification: Any = None) -> None:
        self._notification = notification

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
        channel: str = kwargs["channel"]
        message: str = kwargs["message"]
        severity: str = kwargs.get("severity", "info")
        recipient: str = kwargs.get("recipient", "default")

        adapter = self._notification
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
    body: dict[str, Any] = {
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
    if not result.success:
        body["error"] = f"Notification not delivered: {result.error or 'unknown error'}"
        body["error_type"] = "connection"
    return body


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
