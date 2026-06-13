"""ADR-013 T2 — Skill catalog JSON mutation surface invariants.

5-element 패턴 (S0a-checked):
- SoT: skill-catalog.json
- Path: AUTORESEARCH_SKILL_CATALOG_PATH + OPERATOR_LOCAL_SKILL_CATALOG_PATH
- Reader: core/skills/skill_catalog_policy.py
- Entry: core/agent/loop/_context.py:_build_system_prompt
- Env: GEODE_SKILL_CATALOG_OVERRIDE (+ _STRICT=1 opt-in)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.skills import skill_catalog_policy
from core.skills.skill_catalog_policy import (
    _load_skill_catalog_override,
    apply_skill_catalog_policy,
)
from core.skills.skills import SkillDefinition, SkillRegistry


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "skill-catalog.json"
    operator_local = tmp_path / "operator-local-skill-catalog.json"
    monkeypatch.setattr(skill_catalog_policy, "_SKILL_CATALOG_SOT_PATH", sot)
    monkeypatch.setattr(skill_catalog_policy, "_OPERATOR_LOCAL_SKILL_CATALOG_PATH", operator_local)
    monkeypatch.delenv("GEODE_SKILL_CATALOG_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_SKILL_CATALOG_STRICT", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


def _make_registry(*skills: tuple[str, str, bool]) -> SkillRegistry:
    reg = SkillRegistry()
    for name, desc, user_invocable in skills:
        reg.register(SkillDefinition(name=name, description=desc, user_invocable=user_invocable))
    return reg


# Reader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_skill_catalog_override() is None


def test_load_returns_none_when_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_skill_catalog_override() is None


def test_load_returns_none_when_description_not_str(isolated_sot: Path) -> None:
    _write(isolated_sot, {"sk": {"description": ["list", "not", "str"]}})
    assert _load_skill_catalog_override() is None


def test_load_returns_none_when_user_invocable_not_bool(isolated_sot: Path) -> None:
    _write(isolated_sot, {"sk": {"user_invocable": "true"}})
    assert _load_skill_catalog_override() is None


def test_load_valid_payload(isolated_sot: Path) -> None:
    payload = {"sk": {"description": "x", "user_invocable": False}}
    _write(isolated_sot, payload)
    assert _load_skill_catalog_override() == payload


def test_load_unknown_field_ignored(isolated_sot: Path) -> None:
    _write(isolated_sot, {"sk": {"description": "x", "extra": "ignored"}})
    assert _load_skill_catalog_override() == {"sk": {"description": "x"}}


def test_strict_env_var_raises_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_SKILL_CATALOG_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GEODE_SKILL_CATALOG_STRICT", "1")
    with pytest.raises(RuntimeError, match="GEODE_SKILL_CATALOG_OVERRIDE"):
        _load_skill_catalog_override()


def test_env_var_without_strict_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_SKILL_CATALOG_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GEODE_SKILL_CATALOG_STRICT", raising=False)
    assert _load_skill_catalog_override() is None


def test_operator_local_layer_priority(isolated_sot: Path) -> None:
    operator_local = isolated_sot.parent / "operator-local-skill-catalog.json"
    operator_local.write_text(json.dumps({"sk": {"description": "from-ops"}}), encoding="utf-8")
    _write(isolated_sot, {"sk": {"description": "from-repo"}})
    assert _load_skill_catalog_override() == {"sk": {"description": "from-ops"}}


# Apply -----------------------------------------------------------------------


def test_apply_none_delegates_to_registry() -> None:
    """No behavior change contract — exact XML equality vs registry's own renderer."""
    reg = _make_registry(
        ("sk1", "default desc", True),
        ("sk2", "another desc", False),
    )
    out = apply_skill_catalog_policy(reg, None)
    assert out == reg.get_context_block()


def test_apply_empty_dict_delegates_to_registry() -> None:
    """Empty dict same as None — exact XML equality (Codex MCP catch, PR #1418)."""
    reg = _make_registry(
        ("sk1", "default desc", True),
        ("sk2", "another desc", False),
    )
    out = apply_skill_catalog_policy(reg, {})
    assert out == reg.get_context_block()


def test_apply_description_override() -> None:
    reg = _make_registry(("sk1", "default desc", True))
    out = apply_skill_catalog_policy(reg, {"sk1": {"description": "EVOLVED desc"}})
    assert "EVOLVED desc" in out
    assert "default desc" not in out


def test_apply_user_invocable_false_overrides_to_false() -> None:
    reg = _make_registry(("sk1", "desc", True))
    out = apply_skill_catalog_policy(reg, {"sk1": {"user_invocable": False}})
    assert 'user_invocable="false"' in out


def test_apply_user_invocable_true_overrides_to_true() -> None:
    reg = _make_registry(("sk1", "desc", False))
    out = apply_skill_catalog_policy(reg, {"sk1": {"user_invocable": True}})
    assert 'user_invocable="true"' in out


def test_apply_unknown_skill_in_policy_ignored() -> None:
    """Base registry is authoritative for which skills exist."""
    reg = _make_registry(("sk1", "default desc", True))
    out = apply_skill_catalog_policy(reg, {"nonexistent": {"description": "X"}})
    assert "X" not in out
    assert "default desc" in out
    assert "sk1" in out


def test_apply_empty_registry_returns_empty_string() -> None:
    """No skills + any policy → empty block (consistent with `get_context_block`)."""
    reg = SkillRegistry()
    assert apply_skill_catalog_policy(reg, {"sk1": {"description": "x"}}) == ""


def test_apply_respects_max_chars_truncation() -> None:
    reg = _make_registry(
        ("sk1", "d1" * 100, True),
        ("sk2", "d2" * 100, True),
        ("sk3", "d3" * 100, True),
    )
    out = apply_skill_catalog_policy(reg, {"sk1": {"description": "ovr"}}, max_chars=120)
    assert "<truncated" in out


def test_apply_xml_escapes_special_chars() -> None:
    """XML escape (S0b deep-copy 식 안전성) — `<` 등이 raw 로 새지 않음."""
    reg = _make_registry(("sk1", "default", True))
    out = apply_skill_catalog_policy(reg, {"sk1": {"description": 'has <html> & quotes "'}})
    assert "&lt;html&gt;" in out
    assert "&amp;" in out


# Wiring ----------------------------------------------------------------------


def test_context_module_imports_reader_and_apply() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "core/agent/loop/_context.py").read_text(encoding="utf-8")
    assert "_load_skill_catalog_override" in src
    assert "apply_skill_catalog_policy" in src


def test_context_module_calls_apply_instead_of_get_context_block_direct() -> None:
    """T2 wires the override into the inference path — apply_*_policy must be
    invoked where the previous direct ``get_context_block()`` lived (skill_ctx)."""
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "core/agent/loop/_context.py").read_text(encoding="utf-8")
    # The earlier-built skill_ctx line must now reach through apply_*_policy.
    assert "skill_ctx = apply_skill_catalog_policy(" in src


# Path constants --------------------------------------------------------------


def test_path_constants_present() -> None:
    from core.paths import AUTORESEARCH_SKILL_CATALOG_PATH, OPERATOR_LOCAL_SKILL_CATALOG_PATH

    assert AUTORESEARCH_SKILL_CATALOG_PATH.name == "skill-catalog.json"
    assert OPERATOR_LOCAL_SKILL_CATALOG_PATH.name == "skill-catalog.json"
    assert "policies" in str(AUTORESEARCH_SKILL_CATALOG_PATH)
    assert "autoresearch/handoff" in str(OPERATOR_LOCAL_SKILL_CATALOG_PATH)


# Env wiring in train.py ------------------------------------------------------


def test_train_py_sets_skill_catalog_env() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "core/self_improving/measure.py").read_text(encoding="utf-8")
    assert "GEODE_SKILL_CATALOG_OVERRIDE" in src
    assert "GEODE_SKILL_CATALOG_STRICT" in src
    assert "AUTORESEARCH_SKILL_CATALOG_PATH" in src


# ALIVE marker ----------------------------------------------------------------


def test_skill_catalog_json_referenced_in_inference_path() -> None:
    """grep `skill-catalog.json` lands in `core/skills/skill_catalog_policy.py`."""
    repo_root = Path(__file__).resolve().parents[3]
    hits: list[str] = []
    for path in (repo_root / "core").rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "skill-catalog.json" in content:
            hits.append(str(path.relative_to(repo_root)))
    assert any("skill_catalog_policy.py" in h for h in hits), (
        f"skill-catalog.json must appear in core/skills/skill_catalog_policy.py. hits={hits}"
    )
