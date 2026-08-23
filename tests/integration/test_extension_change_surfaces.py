"""Black-box extension change-surface contracts from roadmap §8.

Every extension artifact is created outside the repository.  The scenarios use
the supported discovery or composition seam without editing kernel registries,
CLI dispatch, provider switches, policy name lists, or OAuth storage.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

from core.agent.tool_executor import ToolExecutor
from core.extensions import ExtensionPolicy, ExtensionState
from core.hooks import HookEvent, HookSystem
from core.hooks.discovery import HookPluginLoader
from core.llm.adapters import reload_adapters
from core.llm.adapters.base import AdapterCallRequest, Message
from core.llm.adapters.registry import _reset_for_test
from core.mcp.manager import MCPServerManager
from core.skills.skills import SkillLoader, SkillRegistry
from core.tools.google_capabilities import GoogleServiceDescriptor, GoogleToolBinding
from core.tools.plan import (
    ApprovalPolicy,
    CapabilityRequirement,
    DataClassification,
    ExecutionBinding,
    PersistenceRule,
    SafetyPolicy,
    ToolSpec,
    bind_tool_plan,
    compile_tool_plan,
)


def _trusted_policy(surface: str, name: str) -> ExtensionPolicy:
    return ExtensionPolicy.from_mapping(
        {
            "version": 1,
            "extensions": {
                f"{surface}:{name}": {
                    "enabled": True,
                    "trusted": True,
                    "execution": "trusted",
                    "capabilities": [],
                }
            },
        }
    )


def _bind_one_tool(
    name: str,
    handler: Any,
    *,
    schema: dict[str, Any],
    safety: SafetyPolicy | None = None,
    capability: CapabilityRequirement | None = None,
):
    plan = compile_tool_plan(
        ((ToolSpec(name, f"Scenario tool {name}", schema), "scenario registration"),),
        (ExecutionBinding(name, "scenario registration"),),
        safety={name: safety or SafetyPolicy()},
        capabilities={name: capability or CapabilityRequirement()},
    )
    return bind_tool_plan(plan, {name: handler})


def test_project_skill_is_added_from_only_a_project_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    skill_dir = tmp_path / ".geode" / "skills" / "scenario-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        dedent(
            """
            ---
            name: scenario-skill
            description: Loaded from a project directory
            triggers: [scenario]
            ---
            # Scenario Skill
            Return the project-local result.
            """
        ).lstrip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    registry = SkillRegistry()
    loaded = SkillLoader(extension_policy=_trusted_policy("skill", "scenario-skill")).load_all(
        registry
    )

    scenario = registry.get("scenario-skill")
    assert scenario is next(skill for skill in loaded if skill.name == "scenario-skill")
    assert scenario.load_body() == "# Scenario Skill\nReturn the project-local result."
    decision = next(
        item
        for item in registry.extension_decisions
        if item.descriptor.extension_id == "skill:scenario-skill"
    )
    assert decision.state is ExtensionState.GRANTED


def test_filesystem_hook_is_added_from_only_a_manifest_and_handler(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    hook_dir = hooks_dir / "scenario-hook"
    hook_dir.mkdir(parents=True)
    (hook_dir / "hook.yaml").write_text(
        dedent(
            """
            name: scenario-hook
            events: [session_start]
            handler: handler.py
            enabled: true
            """
        ).lstrip(),
        encoding="utf-8",
    )
    (hook_dir / "handler.py").write_text(
        "def handle(event, data):\n    return {'event': event.value, 'subject': data['subject']}\n",
        encoding="utf-8",
    )

    loader = HookPluginLoader(policy=_trusted_policy("hook", "scenario-hook"))
    hooks = HookSystem()
    try:
        assert len(loader.load_from_dirs([hooks_dir])) == 1
        loader.register_all(hooks)

        result = hooks.trigger_with_result(HookEvent.SESSION_STARTED, {"subject": "black-box"})

        assert result[0].success is True
        assert result[0].data == {"event": "session_started", "subject": "black-box"}
    finally:
        loader.unregister_all(hooks)


def test_mcp_server_is_added_from_only_project_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    server = tmp_path / "scenario_mcp.py"
    server.write_text(
        dedent(
            """
            import json
            import sys

            for line in sys.stdin:
                request = json.loads(line)
                if "id" not in request:
                    continue
                method = request.get("method")
                if method == "initialize":
                    result = {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "scenario", "version": "1"},
                    }
                elif method == "tools/list":
                    result = {
                        "tools": [{
                            "name": "scenario_echo",
                            "description": "Echo a value",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"value": {"type": "string"}},
                                "required": ["value"],
                            },
                        }]
                    }
                elif method == "tools/call":
                    value = request["params"]["arguments"]["value"]
                    result = {"content": [{"type": "text", "text": value}]}
                else:
                    result = {}
                response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
                print(json.dumps(response), flush=True)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    config = tmp_path / "mcp_servers.json"
    config.write_text(
        json.dumps(
            {
                "scenario": {
                    "command": sys.executable,
                    "args": [str(server)],
                    "execution": "trusted",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.mcp.config_catalog.GLOBAL_CONFIG_TOML", tmp_path / "global.toml")
    monkeypatch.setattr("core.mcp.manager.get_project_root", lambda: tmp_path)

    manager = MCPServerManager(
        config_path=config,
        extension_policy=_trusted_policy("mcp", "scenario"),
    )
    try:
        assert manager.load_config() == 1
        assert manager.startup() == 1
        assert [tool["name"] for tool in manager.get_all_tools()] == ["scenario_echo"]
        result = asyncio.run(manager.acall_tool("scenario", "scenario_echo", {"value": "ok"}))
        assert result == {"content": [{"type": "text", "text": "ok"}]}
    finally:
        manager.shutdown()


def test_third_party_adapter_is_added_from_only_a_package_entry_point(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "scenario_adapter.py").write_text(
        dedent(
            """
            from core.llm.adapters import AdapterBillingType
            from core.llm.adapters.base import AdapterCallResult, UsageSummary

            class ScenarioAdapter:
                name = "scenario-adapter"
                provider = "scenario"
                source = "adapter"
                billing_type = AdapterBillingType.UNKNOWN

                async def acomplete(self, request):
                    return AdapterCallResult(
                        text=request.messages[0].content,
                        usage=UsageSummary(),
                        stop_reason="end_turn",
                    )

            def create():
                return ScenarioAdapter()
            """
        ).lstrip(),
        encoding="utf-8",
    )
    metadata = tmp_path / "scenario_adapter-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: scenario-adapter\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "entry_points.txt").write_text(
        "[geode.llm_adapters]\nscenario-adapter = scenario_adapter:create\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    _reset_for_test()
    try:
        snapshot = reload_adapters(
            extension_policy=_trusted_policy("llm-adapter", "scenario-adapter")
        )
        adapter = snapshot.resolve_for("scenario", "adapter")
        request = AdapterCallRequest(
            model="scenario-model",
            messages=(Message(role="user", content="hello"),),
        )

        assert adapter.name == "scenario-adapter"
        assert snapshot.report.origins[-1] == (
            "scenario-adapter",
            "entrypoint:scenario-adapter:scenario-adapter",
        )
        assert asyncio.run(adapter.acomplete(request)).stop_reason == "end_turn"
    finally:
        _reset_for_test()


def test_native_tool_is_added_with_one_registration() -> None:
    bound = _bind_one_tool(
        "scenario_echo",
        lambda value: {"echo": value},
        schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )

    result = asyncio.run(
        ToolExecutor(bound_tool_plan=bound).aexecute("scenario_echo", {"value": "ok"})
    )

    assert bound.tool_names == ("scenario_echo",)
    assert bound.registration_for("scenario_echo") is not None
    assert result == {"echo": "ok"}


def test_google_workspace_service_is_added_from_one_descriptor_registration() -> None:
    descriptor = GoogleServiceDescriptor(
        name="people-labels-read",
        scopes=("https://www.googleapis.com/auth/contacts.readonly",),
        description="Read contact labels",
        risk="sensitive",
        required_api_services=("people.googleapis.com",),
    )
    tool = GoogleToolBinding(
        name="google_people_labels",
        read_services=(descriptor.name,),
        handler_class="PeopleLabelsTool",
    )
    approvals: list[str] = []

    def list_labels(account: str) -> dict[str, Any]:
        return {"account": account, "scopes": descriptor.scopes, "labels": ["team"]}

    safety = SafetyPolicy(
        data_class=DataClassification.PERSONAL,
        persistence=PersistenceRule.REDACT,
        approval=ApprovalPolicy.PER_INVOCATION,
        allow_headless=False,
        allow_subagents=False,
    )
    capability = CapabilityRequirement(
        services=tool.read_services,
        auth=("google-oauth",),
    )
    bound = _bind_one_tool(
        tool.name,
        list_labels,
        schema={
            "type": "object",
            "properties": {"account": {"type": "string"}},
            "required": ["account"],
            "additionalProperties": False,
        },
        safety=safety,
        capability=capability,
    )

    result = asyncio.run(
        ToolExecutor(
            bound_tool_plan=bound,
            approval_callback=lambda name, *_args: approvals.append(name) or "y",
        ).aexecute(tool.name, {"account": "work"})
    )
    registration = bound.registration_for(tool.name)

    assert registration is not None
    assert registration.capability.services == (descriptor.name,)
    assert registration.safety == safety
    assert approvals == [tool.name]
    assert result == {
        "account": "work",
        "scopes": descriptor.scopes,
        "labels": ["team"],
    }
