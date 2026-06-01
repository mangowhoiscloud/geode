"""Regression pin — a sub-agent toolkit grant survives a hostile tool_policy.

PR-PILOT-PETRI-AUDIT-WIRING (2026-06-01).

Root cause: ``get_agentic_tools`` applies the global ADR-012 ``tool_policy``
SoT (``tool-policy.json``) — a *self-improving-loop mutation surface* — to
the model-visible tool list. The seed_pilot sub-agent resolves its toolkit
(``seed_pilot`` → ``petri_audit`` + ``read_document``) into
``AgenticLoop.allowed_tool_names``. The toolkit filter ran *after*
``get_agentic_tools``, so a ``tool-policy.json`` whose ``allowed_tools``
whitelist omitted ``petri_audit`` stripped it BEFORE the toolkit filter could
honour it. The pilot worker then advertised only ``read_document`` to the
model, the model reported "petri_audit isn't in my available tool set",
skipped the audit, and emitted all-zero ``dim_means`` — silently neutering
the difficulty-selection lever. The pilot is the agent that *measures* the
loop, so the loop's own mutation disabled its own measurement.

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


_PILOT_TOOLKIT = {"petri_audit", "read_document"}


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
    names = {t.get("name") for t in get_agentic_tools(None, force_include=_PILOT_TOOLKIT)}
    assert "petri_audit" in names, (
        "petri_audit was stripped by the global tool_policy despite being a "
        "force_include (toolkit) grant — the regression is back"
    )
    # read_document was already in the whitelist; still present.
    assert "read_document" in names


def test_force_include_does_not_resurrect_non_toolkit_tools(hostile_policy: Path) -> None:
    """force_include only protects the named tools — others stay policy-governed."""
    names = {t.get("name") for t in get_agentic_tools(None, force_include=_PILOT_TOOLKIT)}
    # memory_save is neither in the whitelist nor force_include → stays stripped.
    assert "memory_save" not in names


def test_pilot_worker_effective_toolset_contains_petri_audit(hostile_policy: Path) -> None:
    """End-to-end: the seed_pilot worker's model-visible toolset has petri_audit.

    Reproduces the worker's two-stage resolution:
      1. ``filter_handlers`` resolves the ``seed_pilot`` toolkit →
         ``allowed_tool_names`` (executor side).
      2. ``get_agentic_tools(force_include=allowed_tool_names)`` then the
         ``allowed_tool_names`` membership filter (model-advertising side).
    Both ends must contain ``petri_audit`` for the pilot to actually audit.
    """
    registry = ToolkitRegistry.from_dict(
        {
            "_default": {"tools": ["read_document"]},
            "seed_pilot": {"tools": ["petri_audit", "read_document"]},
        }
    )
    handlers = {name: object() for name in ("petri_audit", "read_document", "write_file")}
    filtered_handlers = filter_handlers(
        handlers=handlers,
        denied_tools=["delegate_task"],
        agent_allowed_tools=[],
        toolkit="seed_pilot",
        toolkit_registry=registry,
    )
    allowed_tool_names = set(filtered_handlers)
    # Executor side already correct (handlers were never tool_policy-filtered).
    assert "petri_audit" in allowed_tool_names

    # Model-advertising side — the path the bug lived on.
    tools = get_agentic_tools(None, force_include=allowed_tool_names)
    advertised = {t.get("name") for t in tools if t.get("name") in allowed_tool_names}
    assert advertised == {"petri_audit", "read_document"}, (
        f"pilot model-visible toolset {advertised} is missing petri_audit — "
        "the pilot would skip the audit and emit all-zero dim_means"
    )
