"""ADR-013 T4 — Provider routing JSON mutation surface invariants.

5-element 패턴:
- SoT: provider-routing.json (in-repo + operator-local)
- Path: GLOBAL_PROVIDER_ROUTING_PATH + OPERATOR_LOCAL_PROVIDER_ROUTING_PATH
- Reader: core/llm/strategies/provider_routing_policy.py
- Entry: core/llm/strategies/plan_registry.py:resolve_routing (explicit-chain branch)
- Env: GEODE_PROVIDER_ROUTING_OVERRIDE + GEODE_PROVIDER_ROUTING_STRICT
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.llm.strategies import provider_routing_policy
from core.llm.strategies.provider_routing_policy import (
    _load_provider_routing_override,
    apply_provider_routing_policy,
)


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "provider-routing.json"
    operator_local = tmp_path / "operator-local-provider-routing.json"
    monkeypatch.setattr(provider_routing_policy, "_PROVIDER_ROUTING_SOT_PATH", sot)
    monkeypatch.setattr(
        provider_routing_policy,
        "_OPERATOR_LOCAL_PROVIDER_ROUTING_PATH",
        operator_local,
    )
    monkeypatch.delenv("GEODE_PROVIDER_ROUTING_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_PROVIDER_ROUTING_STRICT", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# Reader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_provider_routing_override() is None


def test_load_returns_none_when_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_provider_routing_override() is None


def test_load_returns_none_when_chain_not_list(isolated_sot: Path) -> None:
    _write(isolated_sot, {"gpt-5": "plan-x"})
    assert _load_provider_routing_override() is None


def test_load_returns_none_when_chain_contains_non_str(isolated_sot: Path) -> None:
    _write(isolated_sot, {"gpt-5": ["plan-x", 42]})
    assert _load_provider_routing_override() is None


def test_load_valid_payload(isolated_sot: Path) -> None:
    payload = {
        "claude-opus-4-7": ["plan-anthropic-paid", "plan-anthropic-free"],
        "gpt-5": ["plan-openai-tier4"],
    }
    _write(isolated_sot, payload)
    assert _load_provider_routing_override() == payload


def test_load_drops_empty_chain(isolated_sot: Path) -> None:
    """Empty chain → drop the model entry (no policy effect)."""
    _write(isolated_sot, {"gpt-5": [], "claude": ["plan-a"]})
    assert _load_provider_routing_override() == {"claude": ["plan-a"]}


def test_load_drops_empty_string_entries(isolated_sot: Path) -> None:
    _write(isolated_sot, {"gpt-5": ["plan-a", "", "plan-b"]})
    assert _load_provider_routing_override() == {"gpt-5": ["plan-a", "plan-b"]}


def test_strict_env_var_raises_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_PROVIDER_ROUTING_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GEODE_PROVIDER_ROUTING_STRICT", "1")
    with pytest.raises(RuntimeError, match="GEODE_PROVIDER_ROUTING_OVERRIDE"):
        _load_provider_routing_override()


def test_env_var_without_strict_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_PROVIDER_ROUTING_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GEODE_PROVIDER_ROUTING_STRICT", raising=False)
    assert _load_provider_routing_override() is None


def test_operator_local_layer_priority(isolated_sot: Path) -> None:
    operator_local = isolated_sot.parent / "operator-local-provider-routing.json"
    operator_local.write_text(json.dumps({"gpt-5": ["from-ops"]}), encoding="utf-8")
    _write(isolated_sot, {"gpt-5": ["from-repo"]})
    assert _load_provider_routing_override() == {"gpt-5": ["from-ops"]}


# Apply -----------------------------------------------------------------------


def test_apply_none_returns_default_chain_unchanged() -> None:
    default = ["plan-a", "plan-b"]
    assert apply_provider_routing_policy("gpt-5", default, None) == default


def test_apply_none_with_empty_default_returns_empty(
    # Codex MCP FLAG #3 fix-up (PR #1420) — explicit empty-default identity.
) -> None:
    """`apply(..., [], None)` must return ``[]`` — no spurious chain on
    missing SoT + empty registry routing (the most-common production case)."""
    assert apply_provider_routing_policy("gpt-5", [], None) == []


def test_apply_empty_policy_returns_default() -> None:
    default = ["plan-a"]
    assert apply_provider_routing_policy("gpt-5", default, {}) == default


def test_apply_model_not_in_policy_returns_default() -> None:
    default = ["plan-a"]
    policy = {"claude-opus": ["plan-x"]}
    assert apply_provider_routing_policy("gpt-5", default, policy) == default


def test_apply_model_in_policy_overrides_default() -> None:
    default = ["plan-a"]
    policy = {"gpt-5": ["plan-override-1", "plan-override-2"]}
    assert apply_provider_routing_policy("gpt-5", default, policy) == [
        "plan-override-1",
        "plan-override-2",
    ]


def test_apply_empty_chain_in_policy_falls_through_to_default() -> None:
    """Empty list in policy → no override (registry chain authoritative)."""
    default = ["plan-default"]
    policy = {"gpt-5": []}
    assert apply_provider_routing_policy("gpt-5", default, policy) == default


def test_apply_returns_new_list_not_alias() -> None:
    """Returned list is a fresh copy — caller mutation must not affect policy."""
    policy = {"gpt-5": ["plan-x"]}
    out = apply_provider_routing_policy("gpt-5", [], policy)
    out.append("plan-injected")
    assert policy["gpt-5"] == ["plan-x"]


# Wiring ----------------------------------------------------------------------


def test_plan_registry_module_imports_reader_and_apply() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "core/llm/strategies/plan_registry.py").read_text(encoding="utf-8")
    assert "_load_provider_routing_override" in src
    assert "apply_provider_routing_policy" in src


def test_plan_registry_uses_apply_before_iterating_chain() -> None:
    """resolve_routing 의 explicit-chain branch 가 registry.get_routing 대신
    apply_provider_routing_policy() 의 결과를 iterate 해야 함."""
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "core/llm/strategies/plan_registry.py").read_text(encoding="utf-8")
    assert "apply_provider_routing_policy(" in src
    # The output of apply is what gets iterated for plan lookup.
    apply_idx = src.find("apply_provider_routing_policy(")
    iter_idx = src.find("for plan_id in routed_plan_ids:")
    assert 0 < apply_idx < iter_idx


# Path constants --------------------------------------------------------------


def test_path_constants_present() -> None:
    from core.paths import GLOBAL_PROVIDER_ROUTING_PATH, OPERATOR_LOCAL_PROVIDER_ROUTING_PATH

    assert GLOBAL_PROVIDER_ROUTING_PATH.name == "provider-routing.json"
    assert OPERATOR_LOCAL_PROVIDER_ROUTING_PATH.name == "provider-routing.json"
    assert "policies" in str(GLOBAL_PROVIDER_ROUTING_PATH)
    assert "autoresearch/handoff" in str(OPERATOR_LOCAL_PROVIDER_ROUTING_PATH)


# Env wiring in train.py ------------------------------------------------------


def test_train_py_sets_provider_routing_env_pair() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "core/self_improving/measure.py").read_text(encoding="utf-8")
    assert "GEODE_PROVIDER_ROUTING_OVERRIDE" in src
    assert "GEODE_PROVIDER_ROUTING_STRICT" in src
    assert "GLOBAL_PROVIDER_ROUTING_PATH" in src


# ALIVE marker ----------------------------------------------------------------


def test_provider_routing_json_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    hits: list[str] = []
    for path in (repo_root / "core").rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "provider-routing.json" in content:
            hits.append(str(path.relative_to(repo_root)))
    assert any("provider_routing_policy.py" in h for h in hits), (
        f"provider-routing.json must appear in core/llm/strategies/provider_routing_policy.py. hits={hits}"
    )
