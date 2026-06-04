"""Regression pin — a sub-agent toolkit grant survives a hostile tool_policy.

PR-PILOT-PETRI-AUDIT-WIRING (2026-06-01).

Root cause: ``get_agentic_tools`` applies the global ADR-012 ``tool_policy``
SoT (``tool-policy.json``) — a *self-improving-loop mutation surface* — to
the model-visible tool list. A named sub-agent resolves its toolkit grant
into ``AgenticLoop.allowed_tool_names``. The toolkit filter ran *after*
``get_agentic_tools``, so a ``tool-policy.json`` whose ``allowed_tools``
whitelist omitted a granted tool stripped it BEFORE the toolkit filter could
honour it. The worker then advertised a narrower toolset to the model, the
model reported the tool "isn't in my available tool set", and skipped the
work — silently. (The originating case was the seed_pilot worker losing
``petri_audit``; PR-PILOT-UNIFY-DIM-EXTRACT 2026-06-04 later removed that
worker — the Pilot now audits directly — but the guard still protects every
other toolkit-granted sub-agent, so this pin stays. ``petri_audit`` remains
a real tool: the REPL's ``petri_audit`` tool still funnels through
``get_agentic_tools``.)

Fix: ``get_agentic_tools(..., force_include=...)`` keeps toolkit-granted
tools authoritative over the global tool_policy (policy may reorder but not
strip them). The CLI / serve path (no ``force_include``) is unchanged — the
policy whitelist is still fully honoured there.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from core.agent.loop._tool_factory import get_agentic_tools
from core.agent.worker import filter_handlers
from core.tools.toolkit_registry import ToolkitRegistry

from core.agent import tool_policy


@pytest.fixture
def hostile_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Install a ``tool-policy.json`` whose ``allowed_tools`` omits petri_audit.

    Mimics a self-improving-loop tool_policy mutation that re-shapes the
    global tool surface toward read/write/web tools and (accidentally or
    by drift) drops the expensive ``petri_audit``. Isolated to ``tmp_path``
    via the strict ``GEODE_TOOL_POLICY_OVERRIDE`` env path so the operator's
    real artefacts are neither read nor polluted.
    """
    policy_path = tmp_path / "tool-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "allowed_tools": [
                    "read_document",
                    "grep_files",
                    "glob_files",
                    "write_file",
                    "edit_file",
                    "general_web_search",
                ]
            }
        ),
        encoding="utf-8",
    )
    # Point the in-repo SoT layer at the tmp file (graceful path) and make
    # sure no env/operator-local layer shadows it.
    monkeypatch.setattr(tool_policy, "_TOOL_POLICY_SOT_PATH", policy_path)
    monkeypatch.setattr(tool_policy, "_OPERATOR_LOCAL_TOOL_POLICY_PATH", tmp_path / "absent.json")
    monkeypatch.delenv("GEODE_TOOL_POLICY_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_TOOL_POLICY_STRICT", raising=False)
    yield policy_path


# A representative toolkit grant: one expensive tool the hostile policy
# strips (``petri_audit``) + one already in the whitelist (``read_document``).
_GRANTED_TOOLKIT = {"petri_audit", "read_document"}


def test_hostile_policy_strips_petri_audit_without_force_include(hostile_policy: Path) -> None:
    """Baseline: the hostile policy DOES strip petri_audit on the default path.

    This is the pre-fix behaviour for the CLI / serve surface and must stay
    intact — the policy whitelist is authoritative when no sub-agent toolkit
    declares otherwise.
    """
    names = {t.get("name") for t in get_agentic_tools(None)}
    assert "petri_audit" not in names
    assert "read_document" in names


def test_force_include_keeps_toolkit_grant_against_hostile_policy(
    hostile_policy: Path,
) -> None:
    """The fix: a toolkit-granted tool survives the hostile policy."""
    names = {t.get("name") for t in get_agentic_tools(None, force_include=_GRANTED_TOOLKIT)}
    assert "petri_audit" in names, (
        "petri_audit was stripped by the global tool_policy despite being a "
        "force_include (toolkit) grant — the regression is back"
    )
    # read_document was already in the whitelist; still present.
    assert "read_document" in names


def test_force_include_does_not_resurrect_non_toolkit_tools(hostile_policy: Path) -> None:
    """force_include only protects the named tools — others stay policy-governed."""
    names = {t.get("name") for t in get_agentic_tools(None, force_include=_GRANTED_TOOLKIT)}
    # memory_save is neither in the whitelist nor force_include → stays stripped.
    assert "memory_save" not in names


def test_granted_worker_effective_toolset_keeps_granted_tool(hostile_policy: Path) -> None:
    """End-to-end: a toolkit-granted worker's model-visible toolset keeps its tool.

    Reproduces the worker's two-stage resolution:
      1. ``filter_handlers`` resolves the granted toolkit →
         ``allowed_tool_names`` (executor side).
      2. ``get_agentic_tools(force_include=allowed_tool_names)`` then the
         ``allowed_tool_names`` membership filter (model-advertising side).
    Both ends must keep the granted tool for the worker to actually use it.
    """
    registry = ToolkitRegistry.from_dict(
        {
            "_default": {"tools": ["read_document"]},
            "granted_kit": {"tools": ["petri_audit", "read_document"]},
        }
    )
    handlers = {name: object() for name in ("petri_audit", "read_document", "write_file")}
    filtered_handlers = filter_handlers(
        handlers=handlers,
        denied_tools=["delegate_task"],
        agent_allowed_tools=[],
        toolkit="granted_kit",
        toolkit_registry=registry,
    )
    allowed_tool_names = set(filtered_handlers)
    # Executor side already correct (handlers were never tool_policy-filtered).
    assert "petri_audit" in allowed_tool_names

    # Model-advertising side — the path the bug lived on.
    tools = get_agentic_tools(None, force_include=allowed_tool_names)
    advertised = {t.get("name") for t in tools if t.get("name") in allowed_tool_names}
    assert advertised == {"petri_audit", "read_document"}, (
        f"granted worker model-visible toolset {advertised} is missing "
        "petri_audit — the global tool_policy stripped a toolkit grant"
    )
