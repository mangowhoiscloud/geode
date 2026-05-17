"""Reusable MCP-fallback helpers for signal-tier tools.

Public utilities shared by any plugin's signal layer that wants to try an
MCP server first and fall back to fixture/stub data on failure. Extracted
from ``core/tools/signal_tools.py`` during the v0.66.2 step-5 split so
external plugins can adopt the same MCP-first / fixture-fallback shape
without copying the helpers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def parse_mcp_content(result: dict[str, Any]) -> dict[str, Any]:
    """Extract structured data from an MCP tool result.

    MCP tools return ``content`` array with text/image blocks. Tries to
    parse text content as JSON first; falls back to a raw text dict.
    Some non-standard servers may return data keys directly — those pass
    through unchanged.
    """
    content = result.get("content")
    if not isinstance(content, list) or not content:
        # Direct dict with data keys (non-standard) — return as-is
        return result

    texts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            # Try parsing as JSON first
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
            texts.append(text)

    if texts:
        return {"text": "\n".join(texts)}
    return result


async def try_mcp_signal_async(
    server_name: str,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any] | None:
    """Async MCP signal helper using ``MCPServerManager.acall_tool``."""
    try:
        from core.mcp.manager import get_mcp_manager

        manager = get_mcp_manager()
        health = await asyncio.to_thread(manager.check_health)
        if not health.get(server_name, False):
            return None

        result = await manager.acall_tool(server_name, tool_name, args)
        if "error" in result:
            log.debug(
                "MCP signal %s/%s error: %s",
                server_name,
                tool_name,
                result["error"],
            )
            return None

        return parse_mcp_content(result)
    except Exception as exc:
        log.debug("MCP signal %s/%s failed: %s", server_name, tool_name, exc)
        return None
