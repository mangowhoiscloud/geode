"""Output tool handlers — generate_report, export_json."""

from __future__ import annotations

from typing import Any


def _build_output_handlers() -> dict[str, Any]:
    """Build artifact/output tool handlers."""
    from core.tools.output_tools import ExportJsonTool, GenerateReportTool

    report_tool = GenerateReportTool()
    export_tool = ExportJsonTool()

    async def handle_generate_report(**kwargs: Any) -> dict[str, Any]:
        return await report_tool.aexecute(**kwargs)

    async def handle_export_json(**kwargs: Any) -> dict[str, Any]:
        return await export_tool.aexecute(**kwargs)

    return {
        "generate_report": handle_generate_report,
        "export_json": handle_export_json,
    }
