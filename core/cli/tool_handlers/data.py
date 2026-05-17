"""Data tool handlers — generate_data."""

from __future__ import annotations

from typing import Any


def _build_data_handlers() -> dict[str, Any]:
    """Build synthetic data tool handlers."""
    from core.tools.data_tools import GenerateDataTool

    generate_data_tool = GenerateDataTool()

    async def handle_generate_data(**kwargs: Any) -> dict[str, Any]:
        return await generate_data_tool.aexecute(**kwargs)

    return {
        "generate_data": handle_generate_data,
    }
