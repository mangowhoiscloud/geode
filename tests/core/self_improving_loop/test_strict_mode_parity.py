"""C.8 (2026-05-25) — silent fallback STRICT mode parity invariants (PR-28).

Memory ``project_autoresearch_fragmentation_audit.md`` F5 — silent fallback
은 ``autoresearch/train.py:838-873`` 의 ``_STRICT=1`` 강제 + ``sot_resolution.
resolve_sot`` 의 strict flag 분기로 이미 해소 (ADR-012 S0a/S0b). 본 file
은 그 fix 의 **drift invariant pin** — 12 kind 의 STRICT env naming 이
지속적으로 sot_resolution 의 derivation (``<X>_OVERRIDE → <X>_STRICT``)
과 일치하는지 fail-fast.

drift 사례 (예방):
- train.py 가 ``GEODE_TOOL_POLICY_OVERRIDE`` set 하는데 STRICT 누락 → audit 의
  silent fallback 복귀
- sot_resolution 가 다른 STRICT suffix (예: ``_FAIL_FAST``) 로 rename →
  train.py 와 desync

12 kind 의 invariant:
- 모든 GEODE_<X>_OVERRIDE env 가 set 됐을 때 STRICT 도 함께 set
- STRICT suffix 가 sot_resolution 의 _OVERRIDE → _STRICT derivation 과
  일치
"""

from __future__ import annotations

import inspect
import re

# 12 kind enumerated in autoresearch/train.py:838-873 — must stay in sync
# with that file's env-emit block.
_TRAIN_PY_STRICT_ENV_PATTERN = re.compile(r'env\["GEODE_([A-Z_]+)_STRICT"\]\s*=\s*"1"')
_TRAIN_PY_OVERRIDE_ENV_PATTERN = re.compile(
    r'env\["GEODE_([A-Z_]+)_OVERRIDE"\]\s*=\s*str\(GLOBAL_\1_PATH\)'
)


def _read_train_py_env_block() -> str:
    from autoresearch import train

    return inspect.getsource(train)


def test_train_py_overrides_paired_with_strict() -> None:
    """Every ``GEODE_<X>_OVERRIDE`` env set in train.py must be paired
    with a ``GEODE_<X>_STRICT=1`` set on the same kind."""
    source = _read_train_py_env_block()
    overrides = set(_TRAIN_PY_OVERRIDE_ENV_PATTERN.findall(source))
    stricts = set(_TRAIN_PY_STRICT_ENV_PATTERN.findall(source))
    missing_strict = overrides - stricts
    assert not missing_strict, (
        f"Override-without-STRICT drift: {missing_strict} — audit subprocess "
        "would silent-fallback. Add GEODE_<X>_STRICT=1 alongside the override."
    )


def test_train_py_strict_count_at_least_12_kinds() -> None:
    """ADR-012 S0a/S0b — 12 kind 의 STRICT 강제. drift 시 count 감소."""
    source = _read_train_py_env_block()
    strict_kinds = set(_TRAIN_PY_STRICT_ENV_PATTERN.findall(source))
    assert len(strict_kinds) >= 12, (
        f"Expected >=12 STRICT kinds (ADR-012 S0a/S0b), found {len(strict_kinds)}: "
        f"{sorted(strict_kinds)}"
    )


def test_sot_resolution_strict_derivation_pattern() -> None:
    """sot_resolution 의 derivation 이 ``<X>_OVERRIDE → <X>_STRICT`` 패턴
    유지 — train.py 의 env naming 과 일치."""
    from core.self_improving_loop import sot_resolution

    source = inspect.getsource(sot_resolution)
    assert "_OVERRIDE_SUFFIX" in source
    assert "_STRICT_SUFFIX" in source
    assert "removesuffix(_OVERRIDE_SUFFIX) + _STRICT_SUFFIX" in source


def test_resolve_sot_returns_strict_true_with_env_strict(tmp_path, monkeypatch) -> None:
    """End-to-end — env override + STRICT=1 → SoTSelection(strict=True)."""
    from core.self_improving_loop.sot_resolution import resolve_sot

    fake_sot = tmp_path / "fake_policy.json"
    fake_sot.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GEODE_TEST_KIND_OVERRIDE", str(fake_sot))
    monkeypatch.setenv("GEODE_TEST_KIND_STRICT", "1")
    selection = resolve_sot(
        env_var="GEODE_TEST_KIND_OVERRIDE",
        operator_local=tmp_path / "nonexistent",
        in_repo=tmp_path / "also_nonexistent",
    )
    assert selection is not None
    assert selection.strict is True
    assert selection.path == fake_sot


def test_resolve_sot_returns_strict_false_without_env_strict(tmp_path, monkeypatch) -> None:
    """env override 만 set + STRICT 없음 → strict=False (operator override)."""
    from core.self_improving_loop.sot_resolution import resolve_sot

    fake_sot = tmp_path / "fake_policy.json"
    fake_sot.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GEODE_TEST_KIND_OVERRIDE", str(fake_sot))
    monkeypatch.delenv("GEODE_TEST_KIND_STRICT", raising=False)
    selection = resolve_sot(
        env_var="GEODE_TEST_KIND_OVERRIDE",
        operator_local=tmp_path / "nonexistent",
        in_repo=tmp_path / "also_nonexistent",
    )
    assert selection is not None
    assert selection.strict is False


def test_resolve_sot_returns_none_when_no_layer_present(tmp_path, monkeypatch) -> None:
    """env 미set / operator_local 부재 / in_repo 부재 → None."""
    from core.self_improving_loop.sot_resolution import resolve_sot

    monkeypatch.delenv("GEODE_UNUSED_KIND_OVERRIDE", raising=False)
    selection = resolve_sot(
        env_var="GEODE_UNUSED_KIND_OVERRIDE",
        operator_local=tmp_path / "nonexistent",
        in_repo=tmp_path / "also_nonexistent",
    )
    assert selection is None


def test_resolve_sot_operator_local_strict_false(tmp_path, monkeypatch) -> None:
    """env 미set + operator_local 존재 → strict=False (daily-use graceful)."""
    from core.self_improving_loop.sot_resolution import resolve_sot

    monkeypatch.delenv("GEODE_UNUSED_KIND_OVERRIDE", raising=False)
    operator = tmp_path / "operator.json"
    operator.write_text("{}", encoding="utf-8")
    selection = resolve_sot(
        env_var="GEODE_UNUSED_KIND_OVERRIDE",
        operator_local=operator,
        in_repo=tmp_path / "nonexistent",
    )
    assert selection is not None
    assert selection.strict is False
    assert selection.path == operator


def test_resolve_sot_in_repo_strict_false(tmp_path, monkeypatch) -> None:
    """env 미set + operator 부재 + in_repo 존재 → in_repo, strict=False."""
    from core.self_improving_loop.sot_resolution import resolve_sot

    monkeypatch.delenv("GEODE_UNUSED_KIND_OVERRIDE", raising=False)
    in_repo = tmp_path / "repo.json"
    in_repo.write_text("{}", encoding="utf-8")
    selection = resolve_sot(
        env_var="GEODE_UNUSED_KIND_OVERRIDE",
        operator_local=tmp_path / "nonexistent",
        in_repo=in_repo,
    )
    assert selection is not None
    assert selection.strict is False
    assert selection.path == in_repo
