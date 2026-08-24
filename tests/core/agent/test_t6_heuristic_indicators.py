"""ADR-013 T6 — Heuristic indicators JSON mutation surface invariants.

5-element 패턴:
- SoT: heuristics.json
- Sources: explicit override + operator-local + packaged candidates
- Reader: core/agent/heuristics_policy.py
- Entry: core/agent/system_prompt.py:build_system_prompt
- Env: GEODE_HEURISTICS_OVERRIDE + GEODE_HEURISTICS_STRICT
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.agent.heuristics_policy import (
    _load_heuristics_override,
    apply_heuristics_policy,
)
from core.config.policy_source import PolicySourcePaths


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "heuristics.json"
    monkeypatch.delenv("GEODE_HEURISTICS_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_HEURISTICS_STRICT", raising=False)
    yield sot


def _sources(sot: Path) -> PolicySourcePaths:
    return PolicySourcePaths(
        "GEODE_HEURISTICS_OVERRIDE",
        sot.parent / "operator-local-heuristics.json",
        sot,
    )


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# Reader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_heuristics_override(sources=_sources(isolated_sot)) is None


def test_load_returns_none_when_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_heuristics_override(sources=_sources(isolated_sot)) is None


def test_load_returns_none_when_value_not_list(isolated_sot: Path) -> None:
    _write(isolated_sot, {"complexity_indicators": "single string"})
    assert _load_heuristics_override(sources=_sources(isolated_sot)) is None


def test_load_returns_none_when_value_contains_non_str(isolated_sot: Path) -> None:
    _write(isolated_sot, {"complexity_indicators": ["x", 42]})
    assert _load_heuristics_override(sources=_sources(isolated_sot)) is None


def test_load_valid_payload_all_groups(isolated_sot: Path) -> None:
    payload = {
        "complexity_indicators": ["multi-step", "if and only if"],
        "high_risk_indicators": ["delete all", "drop table"],
        "time_pressure_indicators": ["asap", "urgent"],
    }
    _write(isolated_sot, payload)
    assert _load_heuristics_override(sources=_sources(isolated_sot)) == payload


def test_load_partial_groups(isolated_sot: Path) -> None:
    _write(isolated_sot, {"complexity_indicators": ["x"]})
    assert _load_heuristics_override(sources=_sources(isolated_sot)) == {
        "complexity_indicators": ["x"]
    }


def test_load_dedupes_phrases_preserving_order(isolated_sot: Path) -> None:
    _write(
        isolated_sot,
        {"complexity_indicators": ["a", "b", "a", "c", "b"]},
    )
    assert _load_heuristics_override(sources=_sources(isolated_sot)) == {
        "complexity_indicators": ["a", "b", "c"]
    }


def test_load_drops_empty_strings(isolated_sot: Path) -> None:
    _write(isolated_sot, {"complexity_indicators": ["a", "", "b"]})
    assert _load_heuristics_override(sources=_sources(isolated_sot)) == {
        "complexity_indicators": ["a", "b"]
    }


def test_load_drops_empty_group(isolated_sot: Path) -> None:
    _write(isolated_sot, {"complexity_indicators": [], "high_risk_indicators": ["x"]})
    assert _load_heuristics_override(sources=_sources(isolated_sot)) == {
        "high_risk_indicators": ["x"]
    }


def test_load_unknown_group_dropped(isolated_sot: Path) -> None:
    """Forward-compat — unknown group 자동 drop."""
    _write(
        isolated_sot,
        {"complexity_indicators": ["x"], "unknown_indicators": ["y"]},
    )
    assert _load_heuristics_override(sources=_sources(isolated_sot)) == {
        "complexity_indicators": ["x"]
    }


def test_strict_env_var_raises_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_HEURISTICS_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GEODE_HEURISTICS_STRICT", "1")
    with pytest.raises(RuntimeError, match="GEODE_HEURISTICS_OVERRIDE"):
        _load_heuristics_override(sources=_sources(tmp_path / "heuristics.json"))


def test_env_var_without_strict_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_HEURISTICS_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GEODE_HEURISTICS_STRICT", raising=False)
    assert _load_heuristics_override(sources=_sources(tmp_path / "heuristics.json")) is None


def test_operator_local_layer_priority(isolated_sot: Path) -> None:
    operator_local = isolated_sot.parent / "operator-local-heuristics.json"
    operator_local.write_text(json.dumps({"complexity_indicators": ["from-ops"]}), encoding="utf-8")
    _write(isolated_sot, {"complexity_indicators": ["from-repo"]})
    assert _load_heuristics_override(sources=_sources(isolated_sot)) == {
        "complexity_indicators": ["from-ops"]
    }


# Apply -----------------------------------------------------------------------


_BASE = "BASE PROMPT TEXT"


def test_apply_none_is_noop() -> None:
    assert apply_heuristics_policy(_BASE, None) == _BASE


def test_apply_empty_dict_is_noop() -> None:
    assert apply_heuristics_policy(_BASE, {}) == _BASE


def test_apply_all_empty_groups_is_noop() -> None:
    """policy 가 있어도 모든 group 이 비어있으면 base 그대로."""
    assert apply_heuristics_policy(_BASE, {"complexity_indicators": []}) == _BASE


def test_apply_single_group_renders_block() -> None:
    out = apply_heuristics_policy(_BASE, {"complexity_indicators": ["multi-step"]})
    assert out.startswith(_BASE)
    assert "<heuristic_indicators>" in out
    assert 'label="complexity"' in out
    assert "multi-step" in out
    assert "</heuristic_indicators>" in out


def test_apply_all_groups_renders_each() -> None:
    out = apply_heuristics_policy(
        _BASE,
        {
            "complexity_indicators": ["multi-step"],
            "high_risk_indicators": ["delete all"],
            "time_pressure_indicators": ["asap"],
        },
    )
    assert 'label="complexity"' in out
    assert 'label="high_risk"' in out
    assert 'label="time_pressure"' in out
    assert "multi-step" in out
    assert "delete all" in out
    assert "asap" in out


def test_apply_xml_escapes_special_chars() -> None:
    out = apply_heuristics_policy(_BASE, {"complexity_indicators": ["foo & bar", "<html>"]})
    assert "foo &amp; bar" in out
    assert "&lt;html&gt;" in out
    assert "<html>" not in out.replace("&lt;html&gt;", "")


def test_apply_with_empty_base_prompt() -> None:
    out = apply_heuristics_policy("", {"complexity_indicators": ["x"]})
    assert out.startswith("<heuristic_indicators>")


# Wiring ----------------------------------------------------------------------


def test_system_prompt_imports_reader_and_apply() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "core/agent/system_prompt.py").read_text(encoding="utf-8")
    assert "_load_heuristics_override" in src
    assert "apply_heuristics_policy" in src


def test_system_prompt_wires_apply_into_static() -> None:
    """`static = apply_heuristics_policy(static, _load_heuristics_override())`
    must appear AFTER the T3 style-guide apply, both in the static path."""
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "core/agent/system_prompt.py").read_text(encoding="utf-8")
    style_idx = src.find("static = apply_style_guide_policy(")
    heur_idx = src.find("static = apply_heuristics_policy(")
    assert style_idx > 0
    assert heur_idx > 0
    # Heuristics applied AFTER style-guide (so its block renders below).
    assert style_idx < heur_idx


# Path constants --------------------------------------------------------------


def test_product_source_candidates_present() -> None:
    from core.config.runtime_policy_sources import build_policy_source_bundle

    sources = build_policy_source_bundle()["heuristics"]
    assert sources.packaged_default is not None
    assert sources.operator_local is not None
    assert sources.packaged_default.name == "heuristics.json"
    assert sources.operator_local.name == "heuristics.json"
    assert "policies" in str(sources.packaged_default)
    assert "autoresearch/handoff" in str(sources.operator_local)


# Env wiring in train.py ------------------------------------------------------


def test_train_py_sets_heuristics_env_pair() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "evolve/scaffold_search/measure.py").read_text(encoding="utf-8")
    assert "GEODE_HEURISTICS_OVERRIDE" in src
    assert "GEODE_HEURISTICS_STRICT" in src
    assert "AUTORESEARCH_HEURISTICS_PATH" in src


# ALIVE marker ----------------------------------------------------------------


def test_heuristics_json_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    composition = (repo_root / "core/config/runtime_policy_sources.py").read_text(encoding="utf-8")
    assert '"heuristics"' in composition
    assert "AUTORESEARCH_HEURISTICS_PATH" in composition
