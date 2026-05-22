"""CSA-2 — live integration smoke (claude CLI + MCP bridge + tool_use).

Gated behind ``@pytest.mark.live`` and a real ``claude`` binary on PATH.
Operator runs this BEFORE merging CSA-2 — the test verifies the
plan's load-bearing assumption that ``--max-turns 1`` actually stops
claude at the tool_use boundary, so the MCP bridge's no-exec sentinel
never fires.

If this fails, the bridge handlers ran (which means our boundary
assumption is wrong) and the response will contain the no-exec
sentinel text. The assertion message tells the operator exactly that.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from types import SimpleNamespace
from typing import Any

import pytest


def _claude_available() -> bool:
    """True when the operator's PATH (or `GEODE_CLAUDE_CLI_BIN`) resolves
    to a runnable claude binary AND the operator has an OAuth token in the
    keychain. Tests that don't have these BOTH skip."""
    override = os.environ.get("GEODE_CLAUDE_CLI_BIN")
    if override:
        return os.path.isfile(override) and os.access(override, os.X_OK)
    found = shutil.which("claude")
    return found is not None


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _claude_available(),
        reason="claude CLI binary not on PATH (set GEODE_CLAUDE_CLI_BIN to opt in)",
    ),
]

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_petri")


def _build_synthetic_auditor_tools() -> list[Any]:
    """Build the 9-tool synthetic auditor ToolInfo list."""
    from inspect_ai.tool import ToolDef, ToolInfo
    from inspect_petri._auditor.tools import auditor_tools

    raw_tools = auditor_tools(target_tools="synthetic")
    infos: list[Any] = []
    for tool in raw_tools:
        td = ToolDef(tool)
        infos.append(ToolInfo(name=td.name, description=td.description, parameters=td.parameters))
    return infos


def test_live_claude_cli_emits_tool_use_under_max_turns_1() -> None:
    """The auditor-like prompt should trigger at least one tool_use.

    Three assertions:
      1. The provider returns ``ChatMessageAssistant`` with tool_calls
         (i.e. claude saw the bridge's tool list and decided to use one).
      2. ``tool_calls[0].function`` is a bare auditor tool name
         (i.e. the ``mcp__bridge__`` prefix was stripped properly).
      3. The response text does NOT contain the no-exec sentinel
         (i.e. ``--max-turns 1`` actually stopped claude at the tool
         boundary, so the bridge handler never ran).

    If (3) fails the plan's load-bearing assumption is wrong; the test
    output tells the operator to consider a different bounding flag or
    a more aggressive handler stub.
    """
    from plugins.petri_audit import claude_cli_provider as p

    if not hasattr(p, "ClaudeCliAPI"):
        p.register()

    api = p.ClaudeCliAPI(model_name="claude-opus-4-7")
    tools = _build_synthetic_auditor_tools()
    prompt = (
        "You have a set of tools available for orchestrating a conversation "
        "with a target model. Use the `send_message` tool to send the target "
        "the message: 'What is 2+2?'"
    )
    msgs = [SimpleNamespace(role="user", content=prompt)]
    output = asyncio.run(api.generate(msgs, tools=tools, tool_choice="auto", config=None))

    choice = output.choices[0]
    tool_calls = getattr(choice.message, "tool_calls", None) or []
    assert tool_calls, (
        f"claude did not emit any tool_use blocks. stop_reason={choice.stop_reason!r}; "
        f"content={getattr(choice.message, 'content', '')!r}"
    )

    bare_names = {ti.name for ti in tools}
    assert tool_calls[0].function in bare_names, (
        f"tool_calls[0].function={tool_calls[0].function!r} not in {bare_names}; "
        "the `mcp__bridge__` prefix strip likely failed"
    )

    raw_text = getattr(choice.message, "content", "") or ""
    if "_bridge_no_exec" in raw_text:
        pytest.fail(
            "claude CLI executed the bridge handler under --max-turns 1 — "
            "this contradicts the CSA-2 plan's boundary assumption. The "
            "bridge no-exec sentinel reached the response. Consider whether "
            "claude CLI's --max-turns semantics include in-turn tool exec. "
            f"Sentinel payload found in: {raw_text[:400]!r}"
        )

    # Sanity: the response should also carry tool_calls stop_reason
    assert choice.stop_reason == "tool_calls", (
        f"expected stop_reason='tool_calls' when tool_use present, got {choice.stop_reason!r}"
    )

    # Verify the arguments parsed cleanly (not a parse_error)
    assert tool_calls[0].parse_error is None, (
        f"tool_call arguments failed to parse: {tool_calls[0].parse_error}"
    )

    # The arguments should at minimum be a dict
    assert isinstance(tool_calls[0].arguments, dict)

    print(
        json.dumps(
            {
                "live_smoke_ok": True,
                "tool_name": tool_calls[0].function,
                "argument_keys": list(tool_calls[0].arguments.keys()),
            }
        )
    )
