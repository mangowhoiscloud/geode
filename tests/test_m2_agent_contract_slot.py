"""ADR-012 M2 — Agent contract mutation slot invariants.

Pins:
- TARGET_KINDS 5 → 6 (skill_catalog 후 agent_contract 추가).
- AgentDefinition.role / system_prompt / tools mutate 가능;
  ``model`` field 는 Tier 2 guardrail 로 mutation surface 에서 제외.
- skill_catalog 와 동일 flat ↔ nested 변환 (tools 는 list[str] / comma-split).
- apply_agent_contracts_policy(agent_def, policy) 가 model_copy(update=...)
  로 새 instance 반환 (원본 immutable).
- T2 reader 와 동일한 BACKFILL-SOT 3-layer chain.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.agent.agent_contracts_policy import (
    _load_agent_contracts_override,
    apply_agent_contracts_policy,
)

from core.agent import agent_contracts_policy
from core.self_improving_loop import policies as pol


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "agent-contracts.json"
    operator_local = tmp_path / "operator-local-agent-contracts.json"
    monkeypatch.setattr(agent_contracts_policy, "_AGENT_CONTRACTS_SOT_PATH", sot)
    monkeypatch.setattr(
        agent_contracts_policy, "_OPERATOR_LOCAL_AGENT_CONTRACTS_PATH", operator_local
    )
    monkeypatch.delenv("GEODE_AGENT_CONTRACTS_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_AGENT_CONTRACTS_STRICT", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# Dispatcher integration -----------------------------------------------------


def test_target_kinds_includes_agent_contract() -> None:
    assert "agent_contract" in pol.TARGET_KINDS


def test_target_kinds_count_is_7_behaviour_kinds() -> None:
    """PR-HYPERPARAM-FOUNDATION (2026-05-28) graduated ``hyperparam`` (count 8),
    then PR-DROP-HYPERPARAM-MUTATION (2026-05-31) REMOVED it again — the mutable
    surface is now exactly the 7 *behaviour* kinds. Order matters because the
    type-hint enum derives from the tuple."""
    assert len(pol.TARGET_KINDS) == 7
    assert pol.TARGET_KINDS == (
        "prompt",
        "tool_policy",
        "decomposition",
        "reflection",
        "skill_catalog",
        "agent_contract",
        "tool_descriptions",
    )


def test_policy_path_agent_contract_maps_to_in_repo() -> None:
    from core.paths import GLOBAL_AGENT_CONTRACTS_PATH

    assert pol.policy_path("agent_contract") == GLOBAL_AGENT_CONTRACTS_PATH


def test_is_valid_target_kind_accepts_agent_contract() -> None:
    assert pol.is_valid_target_kind("agent_contract") is True


# Reader --------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_agent_contracts_override() is None


def test_load_returns_none_when_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_agent_contracts_override() is None


def test_load_rejects_role_not_str(isolated_sot: Path) -> None:
    _write(isolated_sot, {"agent": {"role": 42}})
    assert _load_agent_contracts_override() is None


def test_load_rejects_tools_not_list(isolated_sot: Path) -> None:
    _write(isolated_sot, {"agent": {"tools": "web_search"}})
    assert _load_agent_contracts_override() is None


def test_load_rejects_tools_with_non_str_entry(isolated_sot: Path) -> None:
    _write(isolated_sot, {"agent": {"tools": ["web_search", 42]}})
    assert _load_agent_contracts_override() is None


def test_load_valid_payload(isolated_sot: Path) -> None:
    payload = {
        "research_assistant": {
            "role": "Research Specialist (v2)",
            "system_prompt": "Evolved.",
            "tools": ["web_search", "read_document"],
        },
        "data_analyst": {"system_prompt": "Evolved analyst."},
    }
    _write(isolated_sot, payload)
    assert _load_agent_contracts_override() == payload


def test_load_drops_model_field(isolated_sot: Path) -> None:
    """``model`` is Tier 2 — must be stripped on coerce even if present."""
    _write(
        isolated_sot,
        {"research_assistant": {"system_prompt": "x", "model": "evil-model"}},
    )
    result = _load_agent_contracts_override()
    assert result == {"research_assistant": {"system_prompt": "x"}}
    assert "model" not in result["research_assistant"]


def test_load_unknown_field_dropped(isolated_sot: Path) -> None:
    _write(
        isolated_sot,
        {"research_assistant": {"system_prompt": "x", "future_field": "y"}},
    )
    result = _load_agent_contracts_override()
    assert result == {"research_assistant": {"system_prompt": "x"}}


def test_strict_env_var_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_AGENT_CONTRACTS_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GEODE_AGENT_CONTRACTS_STRICT", "1")
    with pytest.raises(RuntimeError, match="GEODE_AGENT_CONTRACTS_OVERRIDE"):
        _load_agent_contracts_override()


def test_env_var_without_strict_graceful(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_AGENT_CONTRACTS_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GEODE_AGENT_CONTRACTS_STRICT", raising=False)
    assert _load_agent_contracts_override() is None


# Apply ---------------------------------------------------------------------


def _make_agent_def() -> Any:
    from core.skills.agents import AgentDefinition

    return AgentDefinition(
        name="research_assistant",
        role="Research Specialist",
        system_prompt="Original prompt.",
        tools=["web_search"],
        model="claude-sonnet-4-6",
    )


def test_apply_none_returns_original() -> None:
    agent_def = _make_agent_def()
    assert apply_agent_contracts_policy(agent_def, None) is agent_def


def test_apply_empty_dict_returns_original() -> None:
    agent_def = _make_agent_def()
    assert apply_agent_contracts_policy(agent_def, {}) is agent_def


def test_apply_unknown_agent_returns_original() -> None:
    agent_def = _make_agent_def()
    out = apply_agent_contracts_policy(agent_def, {"other_agent": {"role": "evil"}})
    assert out is agent_def


def test_apply_overrides_role_system_prompt_tools() -> None:
    agent_def = _make_agent_def()
    out = apply_agent_contracts_policy(
        agent_def,
        {
            "research_assistant": {
                "role": "Research Specialist v2",
                "system_prompt": "Evolved prompt.",
                "tools": ["web_search", "read_document"],
            }
        },
    )
    assert out is not agent_def  # new instance
    assert out.role == "Research Specialist v2"
    assert out.system_prompt == "Evolved prompt."
    assert out.tools == ["web_search", "read_document"]
    # original unchanged
    assert agent_def.role == "Research Specialist"


def test_apply_never_touches_model_field() -> None:
    """``model`` Tier 2 guardrail — apply must NEVER change it,
    even if policy somehow contains the key."""
    agent_def = _make_agent_def()
    out = apply_agent_contracts_policy(
        agent_def,
        {"research_assistant": {"model": "compromised-model"}},
    )
    # No mutable field overrides → original returned (early-out branch).
    assert out is agent_def
    # Critical invariant — model is preserved
    assert out.model == "claude-sonnet-4-6"


# nested ↔ flat via policies.py dispatcher -----------------------------------


def test_policies_write_agent_contract_then_load_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: write_policy(flat dotted) → disk nested → load_policy
    returns the same flat dotted dict."""
    target = tmp_path / "agent-contracts.json"
    monkeypatch.setitem(pol._KIND_TO_PATH, "agent_contract", target)

    original = {
        "research_assistant.role": "RS v2",
        "research_assistant.system_prompt": "Evolved.",
        "research_assistant.tools": "web_search, read_document",
        "data_analyst.system_prompt": "Evolved DA.",
    }
    pol.write_policy("agent_contract", original)

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    # disk shape = nested, tools is list[str]
    assert on_disk == {
        "research_assistant": {
            "role": "RS v2",
            "system_prompt": "Evolved.",
            "tools": ["web_search", "read_document"],
        },
        "data_analyst": {"system_prompt": "Evolved DA."},
    }
    # load returns same flat dotted
    loaded = pol.load_policy("agent_contract")
    assert loaded == original


def test_policies_write_uses_list_split_for_tools_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tools field: comma-separated flat string → list[str] on disk."""
    target = tmp_path / "agent-contracts.json"
    monkeypatch.setitem(pol._KIND_TO_PATH, "agent_contract", target)
    pol.write_policy(
        "agent_contract",
        {"agent.tools": "a, b , , c "},
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    # Empty tokens dropped + whitespace stripped
    assert on_disk == {"agent": {"tools": ["a", "b", "c"]}}


# Tier 2 untouched ------------------------------------------------------------


def test_m1_skill_catalog_dispatch_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2 가 M1 dispatcher 를 break 하지 않음 — skill_catalog 유지."""
    target = tmp_path / "skill-catalog.json"
    monkeypatch.setitem(pol._KIND_TO_PATH, "skill_catalog", target)
    pol.write_policy(
        "skill_catalog",
        {"sk.description": "x", "sk.user_invocable": "true"},
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"sk": {"description": "x", "user_invocable": True}}
