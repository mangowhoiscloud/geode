"""CSA-2 — ToolInfo → MCP Tool schema translation."""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("inspect_ai", reason="audit extra required for translator tests")


# ---------------------------------------------------------------------------
# spec-dict shape (no MCP import)
# ---------------------------------------------------------------------------


def _make_tool_info(
    *,
    name: str = "send_message",
    description: str = "Send a message to the target",
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> Any:
    from inspect_ai.tool import ToolInfo, ToolParams
    from inspect_ai.util._json import JSONSchema

    props_in = properties or {"message": {"type": "string", "description": "the body"}}
    props = {k: JSONSchema(**v) for k, v in props_in.items()}
    return ToolInfo(
        name=name,
        description=description,
        parameters=ToolParams(properties=props, required=required or list(props.keys())),
    )


def test_spec_dict_shape_basic() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import tool_info_to_spec_dict

    info = _make_tool_info()
    spec = tool_info_to_spec_dict(info)
    assert set(spec.keys()) == {"name", "description", "inputSchema"}
    assert spec["name"] == "send_message"
    assert spec["description"] == "Send a message to the target"
    assert spec["inputSchema"]["type"] == "object"
    assert "message" in spec["inputSchema"]["properties"]


def test_spec_dict_empty_description_normalised() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import tool_info_to_spec_dict

    info = _make_tool_info(description="")
    spec = tool_info_to_spec_dict(info)
    # MCP rejects empty description; we substitute a single space.
    assert spec["description"] == " "


def test_spec_dict_preserves_required_list() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import tool_info_to_spec_dict

    info = _make_tool_info(
        properties={
            "a": {"type": "string"},
            "b": {"type": "integer"},
        },
        required=["a"],
    )
    spec = tool_info_to_spec_dict(info)
    assert spec["inputSchema"]["required"] == ["a"]


def test_spec_dict_nested_object_preserved() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import tool_info_to_spec_dict

    info = _make_tool_info(
        properties={
            "ctx": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "n": {"type": "integer"}},
            }
        },
        required=["ctx"],
    )
    spec = tool_info_to_spec_dict(info)
    nested = spec["inputSchema"]["properties"]["ctx"]
    assert nested["type"] == "object"
    # JSONSchema preserves nested properties through model_dump's native recursion
    assert "properties" in nested


def test_spec_dict_unicode_tool_name() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import tool_info_to_spec_dict

    info = _make_tool_info(name="시작_메시지")
    spec = tool_info_to_spec_dict(info)
    assert spec["name"] == "시작_메시지"


# ---------------------------------------------------------------------------
# bulk + MCP Tool conversion
# ---------------------------------------------------------------------------


def test_tool_info_to_mcp_tool_constructs_valid_type() -> None:
    pytest.importorskip("mcp")
    from plugins.petri_audit.mcp_bridge.tool_translator import tool_info_to_mcp_tool

    from mcp import types as mcp_types

    info = _make_tool_info()
    tool = tool_info_to_mcp_tool(info)
    assert isinstance(tool, mcp_types.Tool)
    assert tool.name == "send_message"
    # MCP's Tool.model_validate-shaped round trip
    dumped = tool.model_dump()
    assert dumped["name"] == "send_message"
    assert dumped["inputSchema"]["type"] == "object"


def test_tool_infos_to_mcp_tools_preserves_order() -> None:
    pytest.importorskip("mcp")
    from plugins.petri_audit.mcp_bridge.tool_translator import tool_infos_to_mcp_tools

    infos = [_make_tool_info(name=f"tool_{i}") for i in range(3)]
    tools = tool_infos_to_mcp_tools(infos)
    assert [t.name for t in tools] == ["tool_0", "tool_1", "tool_2"]


# ---------------------------------------------------------------------------
# serialise / deserialise round-trip
# ---------------------------------------------------------------------------


def test_serialise_round_trips_through_deserialise() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import (
        deserialise_tool_specs,
        serialise_tool_infos_for_bridge,
    )

    infos = [_make_tool_info(name=f"tool_{i}") for i in range(3)]
    payload = serialise_tool_infos_for_bridge(infos)
    specs = deserialise_tool_specs(payload)
    assert len(specs) == 3
    assert [s["name"] for s in specs] == ["tool_0", "tool_1", "tool_2"]


def test_serialise_emits_deterministic_json() -> None:
    """sort_keys=True so test snapshots and content-hash-based caching work."""
    from plugins.petri_audit.mcp_bridge.tool_translator import serialise_tool_infos_for_bridge

    info = _make_tool_info()
    out1 = serialise_tool_infos_for_bridge([info])
    out2 = serialise_tool_infos_for_bridge([info])
    assert out1 == out2


def test_serialise_handles_unicode_without_escaping() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import serialise_tool_infos_for_bridge

    info = _make_tool_info(name="시작", description="한국어 설명")
    payload = serialise_tool_infos_for_bridge([info])
    # ensure_ascii=False → raw codepoints, not \uXXXX escapes
    assert "시작" in payload
    assert "한국어 설명" in payload


def test_deserialise_rejects_non_array() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import deserialise_tool_specs

    with pytest.raises(ValueError, match="expected JSON array"):
        deserialise_tool_specs(json.dumps({"not": "an array"}))


def test_deserialise_rejects_non_dict_item() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import deserialise_tool_specs

    with pytest.raises(ValueError, match="not a dict"):
        deserialise_tool_specs(json.dumps(["string instead of dict"]))


def test_deserialise_rejects_missing_required_field() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import deserialise_tool_specs

    with pytest.raises(ValueError, match="missing 'description'"):
        deserialise_tool_specs(json.dumps([{"name": "x", "inputSchema": {}}]))


def test_deserialise_rejects_malformed_json() -> None:
    from plugins.petri_audit.mcp_bridge.tool_translator import deserialise_tool_specs

    with pytest.raises(json.JSONDecodeError):
        deserialise_tool_specs("{not json")


# ---------------------------------------------------------------------------
# Conformance — real inspect_petri auditor tools
# ---------------------------------------------------------------------------


def test_auditor_tools_translate_without_error() -> None:
    """Real auditor tools (synthetic mode) all translate cleanly to MCP Tools.

    Catches drift between inspect_ai's ToolParams shape and MCP's Tool
    inputSchema expectations. If a future inspect_petri release adds a
    ToolParam feature MCP doesn't support, this test fails early."""
    pytest.importorskip("inspect_petri")
    pytest.importorskip("mcp")
    from inspect_ai.tool import ToolDef, ToolInfo
    from inspect_petri._auditor.tools import auditor_tools
    from plugins.petri_audit.mcp_bridge.tool_translator import tool_info_to_mcp_tool

    from mcp import types as mcp_types

    raw_tools = auditor_tools(target_tools="synthetic")
    assert len(raw_tools) == 9, f"synthetic mode should yield 9 tools, got {len(raw_tools)}"
    for tool in raw_tools:
        td = ToolDef(tool)
        info = ToolInfo(name=td.name, description=td.description, parameters=td.parameters)
        mcp_tool = tool_info_to_mcp_tool(info)
        assert isinstance(mcp_tool, mcp_types.Tool)
        assert mcp_tool.name == td.name
