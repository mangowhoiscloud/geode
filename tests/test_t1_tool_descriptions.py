"""ADR-013 T1 — `tool_descriptions` JSON mutation surface invariants.

S0a 검증된 5-element 패턴 (SoT + path + reader + entry + env) 의 T1 적용:
- SoT: tool-descriptions.json
- Path: GLOBAL_TOOL_DESCRIPTIONS_PATH
- Reader: core/agent/tool_descriptions_policy.py
- Entry: core/agent/loop/_helpers.py:get_agentic_tools
- Env: GEODE_TOOL_DESCRIPTIONS_OVERRIDE
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.agent.tool_descriptions_policy import (
    _load_tool_descriptions_override,
    apply_tool_descriptions_policy,
)

from core.agent import tool_descriptions_policy


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "tool-descriptions.json"
    monkeypatch.setattr(tool_descriptions_policy, "_TOOL_DESCRIPTIONS_SOT_PATH", sot)
    monkeypatch.delenv("GEODE_TOOL_DESCRIPTIONS_OVERRIDE", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# Reader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_tool_descriptions_override() is None


def test_load_returns_none_when_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_tool_descriptions_override() is None


def test_load_returns_none_when_type_violation(isolated_sot: Path) -> None:
    _write(isolated_sot, {"bash": {"description": ["not", "str"]}})
    assert _load_tool_descriptions_override() is None


def test_load_valid_payload(isolated_sot: Path) -> None:
    payload = {"bash": {"description": "overridden", "hints": ["hint1", "hint2"]}}
    _write(isolated_sot, payload)
    result = _load_tool_descriptions_override()
    assert result == payload


def test_load_unknown_field_in_entry_ignored(isolated_sot: Path) -> None:
    """Forward-compat — entry 내 알려지지 않은 field 는 무시."""
    _write(isolated_sot, {"bash": {"description": "x", "unknown_field": "ignored"}})
    result = _load_tool_descriptions_override()
    assert result == {"bash": {"description": "x"}}


def test_strict_load_raises_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_TOOL_DESCRIPTIONS_OVERRIDE", str(tmp_path / "nope.json"))
    with pytest.raises(RuntimeError, match="GEODE_TOOL_DESCRIPTIONS_OVERRIDE"):
        _load_tool_descriptions_override()


def test_strict_load_raises_on_hints_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"bash": {"hints": "not-a-list"}}), encoding="utf-8")
    monkeypatch.setenv("GEODE_TOOL_DESCRIPTIONS_OVERRIDE", str(bad))
    with pytest.raises(RuntimeError, match="hints"):
        _load_tool_descriptions_override()


# Apply -----------------------------------------------------------------------


def _tools(*specs: tuple[str, str]) -> list[dict[str, Any]]:
    return [{"name": n, "description": d} for n, d in specs]


def test_apply_none_is_noop() -> None:
    tools = _tools(("bash", "default bash"))
    assert apply_tool_descriptions_policy(tools, None) == tools


def test_apply_empty_dict_is_noop() -> None:
    tools = _tools(("bash", "default bash"))
    assert apply_tool_descriptions_policy(tools, {}) == tools


def test_apply_description_override() -> None:
    tools = _tools(("bash", "default"), ("read", "default read"))
    out = apply_tool_descriptions_policy(tools, {"bash": {"description": "EVOLVED"}})
    by_name = {t["name"]: t["description"] for t in out}
    assert by_name["bash"] == "EVOLVED"
    assert by_name["read"] == "default read"  # 무관 tool 영향 없음


def test_apply_hints_append_to_default_description() -> None:
    tools = _tools(("bash", "default bash"))
    out = apply_tool_descriptions_policy(tools, {"bash": {"hints": ["Quote paths", "Avoid -i"]}})
    desc = out[0]["description"]
    assert "default bash" in desc
    assert "Hints:" in desc
    assert "- Quote paths" in desc
    assert "- Avoid -i" in desc


def test_apply_description_and_hints_combined() -> None:
    tools = _tools(("bash", "default"))
    out = apply_tool_descriptions_policy(
        tools, {"bash": {"description": "NEW DESC", "hints": ["h1"]}}
    )
    desc = out[0]["description"]
    assert desc.startswith("NEW DESC")
    assert "- h1" in desc


def test_apply_unknown_tool_in_policy_ignored() -> None:
    """policy 에 등록된 tool 이 input list 에 없으면 영향 없음."""
    tools = _tools(("bash", "default"))
    out = apply_tool_descriptions_policy(tools, {"unknown_tool": {"description": "X"}})
    assert out == tools


def test_apply_deepcopies_so_input_not_mutated() -> None:
    """원본 tool dict 오염 방지 (S0b deep-copy 패턴)."""
    tools = _tools(("bash", "default"))
    original_desc = tools[0]["description"]
    apply_tool_descriptions_policy(tools, {"bash": {"description": "EVOLVED"}})
    assert tools[0]["description"] == original_desc


# Wiring ----------------------------------------------------------------------


def test_helpers_imports_tool_descriptions_reader() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/agent/loop/_helpers.py").read_text(encoding="utf-8")
    assert "_load_tool_descriptions_override" in src
    assert "apply_tool_descriptions_policy" in src


def test_helpers_applies_descriptions_before_tool_policy() -> None:
    """tool_descriptions 가 tool_policy 보다 먼저 적용돼야 함 — policy 의
    forbidden/priority 가 갱신된 description 기반으로 판단 가능."""
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/agent/loop/_helpers.py").read_text(encoding="utf-8")
    desc_pos = src.find("apply_tool_descriptions_policy(tools,")
    policy_pos = src.find("apply_tool_policy(tools,")
    assert desc_pos > 0 and policy_pos > 0
    assert desc_pos < policy_pos


# Path constant ---------------------------------------------------------------


def test_path_constant_in_core_paths() -> None:
    from core.paths import GLOBAL_TOOL_DESCRIPTIONS_PATH

    assert GLOBAL_TOOL_DESCRIPTIONS_PATH.name == "tool-descriptions.json"


# Env wiring in train.py ------------------------------------------------------


def test_train_py_sets_descriptions_override_env() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "autoresearch/train.py").read_text(encoding="utf-8")
    assert "GEODE_TOOL_DESCRIPTIONS_OVERRIDE" in src
    assert "GLOBAL_TOOL_DESCRIPTIONS_PATH" in src


# ALIVE marker ----------------------------------------------------------------


def test_tool_descriptions_json_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for path in (repo_root / "core" / "agent").rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "tool-descriptions.json" in content:
            hits.append(str(path.relative_to(repo_root)))
    assert any("tool_descriptions_policy.py" in h for h in hits), (
        f"tool-descriptions.json 이 core/agent/tool_descriptions_policy.py 에서 발견되어야 함. hits={hits}"
    )
