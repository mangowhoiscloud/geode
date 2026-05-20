"""ADR-012 S0b — `reflection` reader invariants.

`reflection.json` 의 정책이 reflection LLM 호출 직전에 description +
system_prompt 를 override 하는지 검증. S0a 의 패턴 그대로.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from core.agent.reflection_policy import (
    _load_reflection_policy_override,
    apply_reflection_policy,
)

from core.agent import reflection_policy


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Monkeypatch ``_REFLECTION_POLICY_SOT_PATH`` to tmp_path."""
    sot = tmp_path / "reflection.json"
    monkeypatch.setattr(reflection_policy, "_REFLECTION_POLICY_SOT_PATH", sot)
    monkeypatch.delenv("GEODE_REFLECTION_POLICY_OVERRIDE", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, str]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


_BASE_TOOL: dict[str, object] = {
    "name": "record_reflection",
    "description": "base description",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}
_BASE_SYSTEM = "base system prompt"


# ---------------------------------------------------------------------------
# 1. Reader — SoT 파일 존재/부재/손상
# ---------------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert not isolated_sot.exists()
    assert _load_reflection_policy_override() is None


def test_load_returns_none_when_sot_unreadable_json(isolated_sot: Path) -> None:
    isolated_sot.write_text("not json {", encoding="utf-8")
    assert _load_reflection_policy_override() is None


def test_load_returns_none_when_sot_type_violation(isolated_sot: Path) -> None:
    """dict/int 등 string 이 아닌 field → graceful ``None``."""
    isolated_sot.write_text(json.dumps({"description": ["not", "a", "string"]}), encoding="utf-8")
    assert _load_reflection_policy_override() is None


def test_load_returns_dict_when_sot_valid(isolated_sot: Path) -> None:
    payload = {"description": "new desc", "system_prompt": "new sys"}
    _write(isolated_sot, payload)
    assert _load_reflection_policy_override() == payload


def test_load_unknown_fields_ignored(isolated_sot: Path) -> None:
    _write(isolated_sot, {"description": "x", "unknown_field": "ignored"})
    assert _load_reflection_policy_override() == {"description": "x"}


def test_load_empty_string_fields_dropped(isolated_sot: Path) -> None:
    """빈 string 은 None 처럼 취급 — _coerce 가 truthy filter."""
    _write(isolated_sot, {"description": "", "system_prompt": "real"})
    assert _load_reflection_policy_override() == {"system_prompt": "real"}


def test_strict_load_via_env_var_raises_on_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "nope.json"
    monkeypatch.setenv("GEODE_REFLECTION_POLICY_OVERRIDE", str(missing))
    with pytest.raises(RuntimeError, match="GEODE_REFLECTION_POLICY_OVERRIDE"):
        _load_reflection_policy_override()


def test_strict_load_via_env_var_raises_on_type_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"description": ["list", "not", "str"]}), encoding="utf-8")
    monkeypatch.setenv("GEODE_REFLECTION_POLICY_OVERRIDE", str(bad))
    with pytest.raises(RuntimeError, match="description"):
        _load_reflection_policy_override()


# ---------------------------------------------------------------------------
# 2. apply_reflection_policy — 정책의 실제 효과
# ---------------------------------------------------------------------------


def test_apply_none_policy_is_noop() -> None:
    tool, sys_p = apply_reflection_policy(_BASE_TOOL, _BASE_SYSTEM, None)
    assert tool == _BASE_TOOL
    assert sys_p == _BASE_SYSTEM


def test_apply_empty_policy_dict_is_noop() -> None:
    tool, sys_p = apply_reflection_policy(_BASE_TOOL, _BASE_SYSTEM, {})
    assert tool == _BASE_TOOL
    assert sys_p == _BASE_SYSTEM


def test_apply_description_override() -> None:
    tool, sys_p = apply_reflection_policy(
        _BASE_TOOL, _BASE_SYSTEM, {"description": "overridden desc"}
    )
    assert tool["description"] == "overridden desc"
    assert sys_p == _BASE_SYSTEM
    # base tool 은 mutate 되지 않음 (deepcopy)
    assert _BASE_TOOL["description"] == "base description"


def test_apply_system_prompt_override() -> None:
    tool, sys_p = apply_reflection_policy(
        _BASE_TOOL, _BASE_SYSTEM, {"system_prompt": "overridden sys"}
    )
    assert tool == _BASE_TOOL  # description 안 바뀜
    assert sys_p == "overridden sys"


def test_apply_both_fields() -> None:
    tool, sys_p = apply_reflection_policy(
        _BASE_TOOL,
        _BASE_SYSTEM,
        {"description": "new desc", "system_prompt": "new sys"},
    )
    assert tool["description"] == "new desc"
    assert sys_p == "new sys"


def test_apply_preserves_input_schema() -> None:
    """``input_schema`` 는 mutate 대상이 아님 — typed payload contract 보존."""
    tool, _ = apply_reflection_policy(
        _BASE_TOOL,
        _BASE_SYSTEM,
        {"description": "x", "system_prompt": "y"},
    )
    assert tool["input_schema"] == _BASE_TOOL["input_schema"]
    assert tool["name"] == _BASE_TOOL["name"]


# ---------------------------------------------------------------------------
# 3. Wiring — _reflection.py 가 reader 를 호출하는지
# ---------------------------------------------------------------------------


def test_reflection_module_imports_reader() -> None:
    """`_reflection.py` 가 ``_load_reflection_policy_override`` 와
    ``apply_reflection_policy`` 둘 다 호출하는지 source-grep."""
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/agent/loop/_reflection.py").read_text(encoding="utf-8")
    assert "_load_reflection_policy_override" in src
    assert "apply_reflection_policy" in src


def test_reflection_module_uses_overridden_values() -> None:
    """`_reflection.py` 가 `active_tool` / `active_system` (override 적용된
    값) 을 사용하는지 — 단순 import 가 아니라 실제 사용 여부 검증."""
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/agent/loop/_reflection.py").read_text(encoding="utf-8")
    assert "active_tool" in src
    assert "active_system" in src
    assert "system=active_system" in src
    assert "tools=[active_tool]" in src


# ---------------------------------------------------------------------------
# 4. Producer → Reader round trip — write_policy 의 dict[str, str] payload
# ---------------------------------------------------------------------------


def test_producer_reader_round_trip(isolated_sot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``write_policy("reflection", {"description": "..."})`` → reader 가
    그대로 정규화. reflection 의 두 field 가 본질 string 이라 split 불필요."""
    from core.self_improving_loop import policies as policies_mod

    monkeypatch.setattr(policies_mod, "policy_path", lambda kind: isolated_sot)
    policies_mod.write_policy(
        "reflection",
        {"description": "evolved desc", "system_prompt": "evolved sys"},
    )

    result = _load_reflection_policy_override()
    assert result == {"description": "evolved desc", "system_prompt": "evolved sys"}


# ---------------------------------------------------------------------------
# 5. ALIVE slot 신호
# ---------------------------------------------------------------------------


def test_reflection_json_is_now_referenced_in_inference_path() -> None:
    """`reflection.json` 이 `core/agent/` 경로 어딘가에서 grep 가능."""
    repo_root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for path in (repo_root / "core" / "agent").rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "reflection.json" in content:
            hits.append(str(path.relative_to(repo_root)))
    assert any("reflection_policy.py" in h for h in hits), (
        f"reflection.json 이 core/agent/reflection_policy.py 에서 발견되어야 함. hits={hits}"
    )
