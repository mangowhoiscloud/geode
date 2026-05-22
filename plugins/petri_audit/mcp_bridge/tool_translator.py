"""inspect_ai ``ToolInfo`` → MCP ``Tool`` schema translation (CSA-2).

Pure functions, no I/O, no subprocess. The parent process (the
:mod:`plugins.petri_audit.claude_cli_provider` ``generate(tools=[...])``
path) calls :func:`serialise_tool_infos_for_bridge` and writes the
result to a temp file; the bridge subprocess (:mod:`bridge_server`)
calls :func:`deserialise_tool_specs` to re-hydrate as plain dicts.

The split is deliberate — the bridge subprocess does NOT import
``inspect_ai`` so it can start fast (claude CLI waits on the MCP
``initialize`` handshake before sending the prompt).

Schema-translation rules
========================

Input — :class:`inspect_ai.tool.ToolInfo`
    Pydantic shape ``{name: str, description: str, parameters: ToolParams,
    options: dict | None}`` where ``ToolParams`` itself is
    ``{type: "object", properties: dict[str, JSONSchema], required:
    list[str], additionalProperties: bool | JSONSchema | None}``.

Output — :class:`mcp.types.Tool`
    ``{name: str, description: str, inputSchema: dict[str, Any]}``.
    ``inputSchema`` IS JSON Schema (object-shaped) so the conversion
    is largely ``ToolParams.model_dump(exclude_none=True, by_alias=True)``.

Notes
-----

* We do NOT strip ``additionalProperties=False`` — inspect_ai's auditor
  tools (e.g. ``set_system_message``, ``send_message``) declare it
  explicitly to constrain the LLM's output shape. Stripping it would
  silently widen the contract.

* Empty ``description`` is normalised to a single space — MCP rejects
  the empty string but accepts whitespace. inspect_ai tools always
  carry a description, but defensive coding here costs nothing.

* The translator is recursive: nested ``properties`` (e.g. arrays of
  objects) and ``anyOf`` / ``items`` are preserved by ``model_dump``'s
  native recursion — we never hand-walk the schema.

* Unicode tool names pass through unchanged (MCP tool names are
  arbitrary strings).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from inspect_ai.tool import ToolInfo

    from mcp import types as mcp_types

__all__ = [
    "deserialise_tool_specs",
    "serialise_tool_infos_for_bridge",
    "tool_info_to_mcp_tool",
    "tool_info_to_spec_dict",
    "tool_infos_to_mcp_tools",
]


def tool_info_to_spec_dict(info: ToolInfo) -> dict[str, Any]:
    """Convert one ``ToolInfo`` to a plain ``{name, description, inputSchema}`` dict.

    The dict shape mirrors :class:`mcp.types.Tool` but stays free of any
    pydantic / MCP import so the bridge subprocess can re-hydrate it
    without importing inspect_ai or mcp at module load.

    The ``inputSchema`` field is a fully JSON-serialisable JSON Schema
    object — no Pydantic model instances, no ellipsis defaults, no
    ``Any`` types leak through.
    """
    params = info.parameters
    if hasattr(params, "model_dump"):
        input_schema = params.model_dump(exclude_none=True, by_alias=True)
    else:
        input_schema = dict(params) if params else {}

    if "type" not in input_schema:
        input_schema = {"type": "object", **input_schema}

    description = (info.description or "").strip()
    if not description:
        description = " "

    return {
        "name": info.name,
        "description": description,
        "inputSchema": input_schema,
    }


def tool_info_to_mcp_tool(info: ToolInfo) -> mcp_types.Tool:
    """``ToolInfo`` → :class:`mcp.types.Tool`.

    Convenience wrapper for parent-process use. The bridge subprocess
    should NOT call this — it uses :func:`deserialise_tool_specs`
    instead so it does not need to import inspect_ai.
    """
    from mcp import types as mcp_types

    spec = tool_info_to_spec_dict(info)
    return mcp_types.Tool(
        name=spec["name"],
        description=spec["description"],
        inputSchema=spec["inputSchema"],
    )


def tool_infos_to_mcp_tools(infos: list[ToolInfo]) -> list[mcp_types.Tool]:
    """Bulk conversion preserving input order."""
    return [tool_info_to_mcp_tool(info) for info in infos]


def serialise_tool_infos_for_bridge(infos: list[ToolInfo]) -> str:
    """Serialise ``ToolInfo[]`` → JSON string for the bridge subprocess.

    The bridge reads this via the ``GEODE_AUDIT_BRIDGE_TOOLS_JSON``
    env-var-pointed file. JSON is the wire format because:

    * the bridge subprocess does not import inspect_ai
      (cold-start cost would dominate the MCP initialize handshake);
    * a tempfile (vs env-inline JSON) sidesteps the ~8KB ENV-line limit
      on some shells — auditor tool schemas can run 12-16 KB combined.
    """
    return json.dumps(
        [tool_info_to_spec_dict(info) for info in infos],
        ensure_ascii=False,
        sort_keys=True,
    )


def deserialise_tool_specs(payload: str) -> list[dict[str, Any]]:
    """Inverse of :func:`serialise_tool_infos_for_bridge`.

    Returns plain dicts with ``{name, description, inputSchema}`` —
    one per tool. The bridge subprocess feeds these directly into
    :class:`mcp.types.Tool` constructors at ``list_tools`` time.

    Raises :class:`ValueError` (via ``json.loads``) on malformed input.
    The bridge surfaces parse errors via stderr + non-zero exit so the
    parent process knows the lifecycle prep was corrupt.
    """
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError(f"expected JSON array, got {type(data).__name__}")
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"item {idx} not a dict: {type(item).__name__}")
        for required in ("name", "description", "inputSchema"):
            if required not in item:
                raise ValueError(f"item {idx} missing {required!r}")
        out.append(item)
    return out
