"""ADR-012 S0c — `decomposition` reader invariants.

`decomposition.json` 의 정책이 ``core/agent/plan.py:decompose_async`` 의
LLM 호출 직전에 system prompt 를 override / prefix / suffix 하는지 검증.

PR-CL-A1-followup (2026-05-23): host 가 ``core/orchestration/goal_decomposer.py``
→ ``core/agent/plan.py:decompose_async`` 로 이전됨 (모듈 삭제). wiring
자체는 동일 — ``load_prompt("decomposer", "system")`` 직후 ``apply_decomposition_policy``
가 적용됨.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from core.agent.decomposition_policy import (
    _load_decomposition_policy_override,
    apply_decomposition_policy,
)

from core.agent import decomposition_policy


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolate all 3 SoT layers to tmp_path."""
    sot = tmp_path / "decomposition.json"
    operator_local = tmp_path / "operator-local-decomposition.json"
    monkeypatch.setattr(decomposition_policy, "_DECOMPOSITION_POLICY_SOT_PATH", sot)
    monkeypatch.setattr(
        decomposition_policy, "_OPERATOR_LOCAL_DECOMPOSITION_POLICY_PATH", operator_local
    )
    monkeypatch.delenv("GEODE_DECOMPOSITION_POLICY_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_DECOMPOSITION_POLICY_STRICT", raising=False)
    yield sot


def _write(sot: Path, payload: dict[str, str]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# Reader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_decomposition_policy_override() is None


def test_load_returns_none_when_sot_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_decomposition_policy_override() is None


def test_load_returns_none_when_sot_type_violation(isolated_sot: Path) -> None:
    isolated_sot.write_text(json.dumps({"system_prompt": ["not", "str"]}), encoding="utf-8")
    assert _load_decomposition_policy_override() is None


def test_load_valid_payload(isolated_sot: Path) -> None:
    _write(isolated_sot, {"system_prompt": "new", "prefix": "p", "suffix": "s"})
    assert _load_decomposition_policy_override() == {
        "system_prompt": "new",
        "prefix": "p",
        "suffix": "s",
    }


def test_load_unknown_fields_ignored(isolated_sot: Path) -> None:
    _write(isolated_sot, {"prefix": "p", "unknown": "x"})
    assert _load_decomposition_policy_override() == {"prefix": "p"}


def test_load_empty_string_dropped(isolated_sot: Path) -> None:
    _write(isolated_sot, {"system_prompt": "", "prefix": "p"})
    assert _load_decomposition_policy_override() == {"prefix": "p"}


def test_strict_load_raises_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """audit subprocess (``_OVERRIDE`` + ``_STRICT=1``) — missing → RuntimeError."""
    monkeypatch.setenv("GEODE_DECOMPOSITION_POLICY_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GEODE_DECOMPOSITION_POLICY_STRICT", "1")
    with pytest.raises(RuntimeError, match="GEODE_DECOMPOSITION_POLICY_OVERRIDE"):
        _load_decomposition_policy_override()


def test_strict_load_raises_on_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"prefix": ["list"]}), encoding="utf-8")
    monkeypatch.setenv("GEODE_DECOMPOSITION_POLICY_OVERRIDE", str(bad))
    monkeypatch.setenv("GEODE_DECOMPOSITION_POLICY_STRICT", "1")
    with pytest.raises(RuntimeError, match="prefix"):
        _load_decomposition_policy_override()


def test_env_var_without_strict_flag_is_graceful_on_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR-BACKFILL-SOT (2026-05-21) — env var alone treats env path graceful."""
    monkeypatch.setenv("GEODE_DECOMPOSITION_POLICY_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GEODE_DECOMPOSITION_POLICY_STRICT", raising=False)
    assert _load_decomposition_policy_override() is None


def test_operator_local_layer_takes_priority_over_in_repo(isolated_sot: Path) -> None:
    """3-layer chain — operator-local > in-repo when both present."""
    operator_local = isolated_sot.parent / "operator-local-decomposition.json"
    operator_local.write_text(json.dumps({"prefix": "from-ops"}), encoding="utf-8")
    _write(isolated_sot, {"prefix": "from-repo"})
    assert _load_decomposition_policy_override() == {"prefix": "from-ops"}


# Apply -----------------------------------------------------------------------


_BASE = "base decomposer system prompt"


def test_apply_none_is_noop() -> None:
    assert apply_decomposition_policy(_BASE, None) == _BASE


def test_apply_empty_is_noop() -> None:
    assert apply_decomposition_policy(_BASE, {}) == _BASE


def test_apply_system_prompt_full_override() -> None:
    """system_prompt 가 있으면 전체 override (prefix/suffix 무시)."""
    out = apply_decomposition_policy(
        _BASE,
        {"system_prompt": "override", "prefix": "ignored", "suffix": "ignored"},
    )
    assert out == "override"


def test_apply_prefix_only() -> None:
    out = apply_decomposition_policy(_BASE, {"prefix": "P"})
    assert out == f"P\n\n{_BASE}"


def test_apply_suffix_only() -> None:
    out = apply_decomposition_policy(_BASE, {"suffix": "S"})
    assert out == f"{_BASE}\n\nS"


def test_apply_prefix_and_suffix() -> None:
    out = apply_decomposition_policy(_BASE, {"prefix": "P", "suffix": "S"})
    assert out == f"P\n\n{_BASE}\n\nS"


# Wiring ----------------------------------------------------------------------


def test_decompose_async_imports_reader() -> None:
    """PR-CL-A1-followup (2026-05-23) — reader host moved from
    ``goal_decomposer.py`` (deleted) to ``plan.py:decompose_async``."""
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/agent/plan.py").read_text(encoding="utf-8")
    assert "_load_decomposition_policy_override" in src
    assert "apply_decomposition_policy" in src


def test_decompose_async_applies_policy_after_load_prompt() -> None:
    """``load_prompt("decomposer", "system")`` 호출 직후에 정책이 적용되는지
    source-order 검증. PR-CL-A1-followup (2026-05-23) — host 가
    ``plan.py:decompose_async`` 로 이전됨."""
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "core/agent/plan.py").read_text(encoding="utf-8")
    load_pos = src.find('load_prompt("decomposer", "system")')
    # apply_decomposition_policy 의 첫 호출 위치 — 들여쓰기 무관
    apply_pos = src.find("apply_decomposition_policy(")
    # 호출 (괄호 있는 패턴) 만 검색 — import 의 식별자 위치보다 뒤에 있어야 함
    while apply_pos != -1 and src.count("import", 0, apply_pos) > src.count("def ", 0, apply_pos):
        next_pos = src.find("apply_decomposition_policy(", apply_pos + 1)
        if next_pos == -1:
            break
        apply_pos = next_pos
    assert load_pos > 0
    assert apply_pos > load_pos, (
        f"apply_decomposition_policy 호출이 load_prompt 호출 후에 와야 함. "
        f"load_pos={load_pos} apply_pos={apply_pos}"
    )


# Producer → Reader -----------------------------------------------------------


def test_producer_reader_round_trip(isolated_sot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.self_improving.loop import policies as policies_mod

    monkeypatch.setattr(policies_mod, "policy_path", lambda kind: isolated_sot)
    policies_mod.write_policy(
        "decomposition",
        {"system_prompt": "evolved", "suffix": "extra rules"},
    )
    result = _load_decomposition_policy_override()
    assert result == {"system_prompt": "evolved", "suffix": "extra rules"}


# ALIVE marker ----------------------------------------------------------------


def test_decomposition_json_is_now_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    hits: list[str] = []
    for path in (repo_root / "core").rglob("*.py"):
        if "test_" in path.name or "self_improving" in str(path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "decomposition.json" in content:
            hits.append(str(path.relative_to(repo_root)))
    assert any("decomposition_policy.py" in h for h in hits), (
        f"decomposition.json 이 core/agent/decomposition_policy.py 에서 발견되어야 함. hits={hits}"
    )
