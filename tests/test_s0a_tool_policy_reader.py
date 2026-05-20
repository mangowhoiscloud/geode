"""ADR-012 S0a — `tool_policy` reader invariants.

`tool-policy.json` 의 정책이 인퍼런스 경로에서 실제로 도구 후보를
필터/재정렬하는지 검증한다. 이 test 가 통과한 시점부터 5축의
`tool_policy` slot 은 ALIVE 이며, PR-AUDIT-5SLOT 의 dead anchor
회귀 marker 가 함께 갱신되어야 한다 (의도된 회귀).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.agent.loop._helpers import get_agentic_tools
from core.agent.tool_policy import _load_tool_policy_override, apply_tool_policy

from core.agent import tool_policy

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Monkeypatch ``_TOOL_POLICY_SOT_PATH`` to tmp_path so tests don't read
    or pollute the operator's real SoT at ``~/.geode/self-improving-loop/``."""
    sot = tmp_path / "tool-policy.json"
    monkeypatch.setattr(tool_policy, "_TOOL_POLICY_SOT_PATH", sot)
    monkeypatch.delenv("GEODE_TOOL_POLICY_OVERRIDE", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Reader — SoT 파일 존재/부재/손상 시 동작
# ---------------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    """SoT 파일 부재 → ``None`` (no-op)."""
    assert not isolated_sot.exists()
    assert _load_tool_policy_override() is None


def test_load_returns_none_when_sot_unreadable_json(isolated_sot: Path) -> None:
    """Malformed JSON → WARNING + ``None`` (graceful)."""
    isolated_sot.write_text("not json {", encoding="utf-8")
    assert _load_tool_policy_override() is None


def test_load_returns_none_when_sot_schema_violation(isolated_sot: Path) -> None:
    """``allowed_tools`` 가 list[str] 가 아니면 ``None`` (graceful)."""
    _write(isolated_sot, {"allowed_tools": "not-a-list"})
    assert _load_tool_policy_override() is None


def test_load_returns_dict_when_sot_valid(isolated_sot: Path) -> None:
    """유효한 SoT → 정책 dict 반환."""
    payload = {
        "allowed_tools": ["bash", "read"],
        "forbidden_tools": ["write"],
        "priority_order": ["read", "bash"],
    }
    _write(isolated_sot, payload)
    result = _load_tool_policy_override()
    assert result == payload


def test_load_unknown_fields_ignored(isolated_sot: Path) -> None:
    """Forward-compat — 알려지지 않은 field 는 무시."""
    _write(isolated_sot, {"allowed_tools": ["bash"], "unknown_field": "ignored"})
    result = _load_tool_policy_override()
    assert result == {"allowed_tools": ["bash"]}


def test_strict_load_via_env_var_raises_on_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GEODE_TOOL_POLICY_OVERRIDE`` 가 가리키는 파일이 없으면 RuntimeError."""
    missing = tmp_path / "nope.json"
    monkeypatch.setenv("GEODE_TOOL_POLICY_OVERRIDE", str(missing))
    with pytest.raises(RuntimeError, match="GEODE_TOOL_POLICY_OVERRIDE"):
        _load_tool_policy_override()


def test_strict_load_via_env_var_raises_on_schema_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """audit subprocess 는 schema 위반 시 RuntimeError (fail-fast)."""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"forbidden_tools": "not-a-list"}), encoding="utf-8")
    monkeypatch.setenv("GEODE_TOOL_POLICY_OVERRIDE", str(bad))
    with pytest.raises(RuntimeError, match="forbidden_tools"):
        _load_tool_policy_override()


# ---------------------------------------------------------------------------
# 2. apply_tool_policy — 정책의 실제 효과
# ---------------------------------------------------------------------------


def _tools(*names: str) -> list[dict[str, Any]]:
    return [{"name": n} for n in names]


def test_apply_none_policy_is_noop() -> None:
    """``policy is None`` → 입력 그대로 반환."""
    tools = _tools("a", "b", "c")
    assert apply_tool_policy(tools, None) == tools


def test_apply_empty_policy_dict_is_noop() -> None:
    """빈 dict 정책 → 입력 그대로."""
    tools = _tools("a", "b", "c")
    assert apply_tool_policy(tools, {}) == tools


def test_apply_forbidden_tools_excludes_named() -> None:
    """forbidden 에 등장한 도구는 결과에서 제외."""
    tools = _tools("a", "b", "c")
    result = apply_tool_policy(tools, {"forbidden_tools": ["b"]})
    assert [t["name"] for t in result] == ["a", "c"]


def test_apply_allowed_tools_whitelist() -> None:
    """allowed 가 선언되면 그 안에 있는 도구만 유지."""
    tools = _tools("a", "b", "c")
    result = apply_tool_policy(tools, {"allowed_tools": ["a", "c"]})
    assert [t["name"] for t in result] == ["a", "c"]


def test_apply_priority_order_reorders() -> None:
    """priority 가 선언되면 그 순서대로 재정렬, 정책에 없는 도구는 뒤로."""
    tools = _tools("a", "b", "c", "d")
    result = apply_tool_policy(tools, {"priority_order": ["c", "a"]})
    # c, a 가 앞으로 + b, d 는 원래 상대 순서 유지
    assert [t["name"] for t in result] == ["c", "a", "b", "d"]


def test_apply_forbidden_and_allowed_combined() -> None:
    """forbidden 먼저, allowed 다음."""
    tools = _tools("a", "b", "c", "d")
    result = apply_tool_policy(
        tools,
        {"allowed_tools": ["a", "b", "c"], "forbidden_tools": ["b"]},
    )
    assert [t["name"] for t in result] == ["a", "c"]


def test_apply_full_policy_filter_and_reorder() -> None:
    """3 field 모두 적용."""
    tools = _tools("a", "b", "c", "d")
    result = apply_tool_policy(
        tools,
        {
            "allowed_tools": ["a", "b", "d"],
            "forbidden_tools": ["b"],
            "priority_order": ["d", "a"],
        },
    )
    # b 제외, a/d 만 살아남고 d 가 앞
    assert [t["name"] for t in result] == ["d", "a"]


def test_apply_unnamed_tool_passes_through() -> None:
    """``name`` 이 없는 도구는 정책 영향 없이 통과."""
    tools: list[dict[str, Any]] = [{"name": "a"}, {"description": "unnamed"}]
    result = apply_tool_policy(tools, {"forbidden_tools": ["a"]})
    # a 제외, unnamed 는 통과
    assert len(result) == 1
    assert "name" not in result[0]


# ---------------------------------------------------------------------------
# 3. get_agentic_tools — 도구 호출 경로의 단일 진입점 통합
# ---------------------------------------------------------------------------


def test_get_agentic_tools_applies_policy(
    isolated_sot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``get_agentic_tools`` 가 ``tool-policy.json`` 정책을 실제로 적용해야 함.
    `tool_policy` slot 이 ALIVE 임을 증명하는 핵심 test."""
    # 정책: 모든 도구 제거 (whitelist = []).
    _write(isolated_sot, {"allowed_tools": []})
    result = get_agentic_tools()
    assert result == [], (
        "tool-policy.json 의 allowed_tools=[] 정책이 적용되어야 하는데 도구가 살아있음 — "
        f"reader wiring 깨졌을 가능성. count={len(result)}"
    )


def test_get_agentic_tools_noop_without_policy(
    isolated_sot: Path,
) -> None:
    """정책 부재 시 기존 동작 유지 — base + registry + mcp tools 그대로."""
    assert not isolated_sot.exists()
    result = get_agentic_tools()
    # 정책 없을 때는 base tools 최소 1개 이상 (load_all_tool_definitions 가 비어있지 않음).
    assert len(result) > 0


def test_get_agentic_tools_forbidden_filter_round_trip(
    isolated_sot: Path,
) -> None:
    """base tools 중 하나를 forbidden 으로 지정하면 결과에서 제외."""
    base_result = get_agentic_tools()
    assert base_result, "base tools should be non-empty for this test"
    target = base_result[0]["name"]
    _write(isolated_sot, {"forbidden_tools": [target]})
    filtered = get_agentic_tools()
    names = [t["name"] for t in filtered]
    assert target not in names, (
        f"forbidden_tools=[{target}] 정책이 적용되어야 하는데 {target} 가 살아있음."
    )


# ---------------------------------------------------------------------------
# 4. ALIVE slot 신호 — `tool-policy.json` 이 인퍼런스 경로에서 참조됨
# ---------------------------------------------------------------------------


def test_tool_policy_json_is_now_referenced_in_inference_path() -> None:
    """ADR-012 S0a 의 핵심 결과 — `tool-policy.json` 이 `core/agent/` 경로
    어딘가에서 grep 가능. PR-AUDIT-5SLOT 의 dead anchor 회귀 marker 의
    의도된 발화 (DEAD → ALIVE)."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for path in (repo_root / "core" / "agent").rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "tool-policy.json" in content:
            hits.append(str(path.relative_to(repo_root)))
    # 적어도 tool_policy.py 의 path constant alias 위치에서 발견되어야 함
    assert any("tool_policy.py" in h for h in hits), (
        f"tool-policy.json 이 core/agent/tool_policy.py 에서 발견되어야 함. hits={hits}"
    )
