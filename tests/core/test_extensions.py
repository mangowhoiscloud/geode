from __future__ import annotations

from types import MappingProxyType
from typing import Any, cast

import pytest
from core.config.policy_source import PolicySourcePaths
from core.extensions import (
    ExtensionDescriptor,
    ExtensionExecution,
    ExtensionPolicy,
    ExtensionState,
    ExtensionSurface,
    decide_extension,
    extension_context,
    load_extension_policy,
)


def _descriptor(**changes: object) -> ExtensionDescriptor:
    values = {
        "name": "audit",
        "surface": ExtensionSurface.HOOK,
        "origin": "/project/.geode/hooks/audit/hook.yaml",
        "execution": ExtensionExecution.TRUSTED,
        "capabilities": ("events",),
        "resource_keys": ("audit-log",),
    }
    values.update(changes)
    return ExtensionDescriptor(**cast(Any, values))


def _policy(**entry: object) -> ExtensionPolicy:
    value = {
        "enabled": True,
        "trusted": True,
        "execution": "trusted",
        "capabilities": ["events"],
    }
    value.update(entry)
    return ExtensionPolicy.from_mapping({"version": 1, "extensions": {"hook:audit": value}})


def test_decision_is_fail_closed_until_trust_and_grants_match() -> None:
    descriptor = _descriptor()

    missing = decide_extension(descriptor, ExtensionPolicy.empty())
    assert (missing.state, missing.enabled, missing.trusted) == (
        ExtensionState.REJECTED,
        False,
        False,
    )
    assert decide_extension(descriptor, _policy(trusted=False)).state is ExtensionState.REJECTED
    assert decide_extension(descriptor, _policy(capabilities=[])).state is ExtensionState.REJECTED

    granted = decide_extension(descriptor, _policy())
    assert granted.state is ExtensionState.GRANTED
    assert granted.may_load_in_process is True
    assert granted.granted_capabilities == ("events",)


def test_context_exposes_only_granted_immutable_ports() -> None:
    decision = decide_extension(_descriptor(), _policy())
    sink = object()
    context = extension_context(decision, {"events": sink})

    assert context.require("events") is sink
    assert isinstance(context.ports, type(MappingProxyType({})))
    with pytest.raises(PermissionError, match="lacks port"):
        context.require("runtime")
    with pytest.raises(ValueError, match="lack grants"):
        extension_context(decision, {"runtime": object()})


def test_brokered_execution_does_not_claim_in_process_trust() -> None:
    descriptor = _descriptor(
        surface=ExtensionSurface.MCP,
        execution=ExtensionExecution.BROKERED,
        capabilities=("network",),
    )
    policy = ExtensionPolicy.from_mapping(
        {
            "version": 1,
            "extensions": {
                "mcp:audit": {
                    "enabled": True,
                    "trusted": False,
                    "execution": "brokered",
                    "capabilities": ["network"],
                }
            },
        }
    )

    decision = decide_extension(descriptor, policy)
    assert decision.state is ExtensionState.GRANTED
    assert decision.trusted is False
    assert decision.may_launch_brokered is True
    assert decision.may_load_in_process is False


def test_policy_snapshot_is_deterministic_and_defensive() -> None:
    raw = {
        "version": 1,
        "extensions": {
            "hook:audit": {
                "enabled": True,
                "trusted": True,
                "execution": "trusted",
                "capabilities": ["events"],
            }
        },
    }
    first = ExtensionPolicy.from_mapping(raw)
    second = ExtensionPolicy.from_mapping(raw)
    raw["extensions"]["hook:audit"]["enabled"] = False

    assert first.content_hash == second.content_hash
    assert first.grants["hook:audit"].enabled is True
    mutable_view = cast(dict[str, object], first.grants)
    with pytest.raises(TypeError):
        mutable_view["new"] = first.grants["hook:audit"]


def test_status_separates_installed_enabled_trusted_and_granted() -> None:
    decision = decide_extension(_descriptor(), _policy())

    assert decision.status() == {
        "id": "hook:audit",
        "origin": "/project/.geode/hooks/audit/hook.yaml",
        "state": "granted",
        "installed": True,
        "manifest_enabled": True,
        "enabled": True,
        "trusted": True,
        "capabilities": ["events"],
        "resource_keys": ["audit-log"],
        "reason": "operator policy",
    }


def test_descriptor_rejects_string_as_capability_collection() -> None:
    with pytest.raises(TypeError, match="collection of strings"):
        _descriptor(capabilities="events")


def test_policy_rejects_unknown_fields_instead_of_ignoring_typos() -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        ExtensionPolicy.from_mapping(
            {
                "version": 1,
                "extensions": {
                    "hook:audit": {
                        "trusted": True,
                        "execution": "trusted",
                        "enabledd": False,
                    }
                },
            }
        )


def test_policy_file_schema_is_graceful_by_default_and_strict_for_override(
    tmp_path: Any,
) -> None:
    invalid = tmp_path / "policy.json"
    invalid.write_text('{"version": 2, "extensions": {}}', encoding="utf-8")

    graceful = load_extension_policy(PolicySourcePaths("UNUSED", operator_local=invalid))
    assert graceful == ExtensionPolicy.empty()

    with pytest.raises(RuntimeError, match="version=1"):
        load_extension_policy(
            PolicySourcePaths(
                "UNUSED",
                explicit_override=invalid,
                explicit_override_strict=True,
            )
        )
