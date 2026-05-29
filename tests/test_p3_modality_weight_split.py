"""PR-SIL-5THEME C3 — P3 modality 가중 분리 tests.

`core/audit/dim_extractor` 가 PR-1 으로 per-dim `measurement_modality`
를 emit 했으나 `compute_fitness` / `_should_promote` 는 그 신호를
0% 사용했다. C3 가 그 silent disconnect 를 닫는다:

- analytics modality 의 가중치를 0.5× scale (deterministic stderr 의
  fitness signal dilution 해소)
- N=1 widening guard 가 judge_llm 만 fire (analytics 의 deterministic
  stderr=0 이 under-sampled stderr=0 과 conflate 안 함)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from autoresearch.train import (
    ANALYTICS_WEIGHT_MULTIPLIER,
    DIM_MODALITY_WEIGHT_MULTIPLIER,
    DIM_WEIGHTS,
    JUDGE_LLM_MODALITIES,
    N1_FITNESS_MARGIN_FLOOR,
    _dim_weight_with_modality,
    _load_baseline_measurement_modality,
    _should_promote,
    compute_fitness,
)

# ---------------------------------------------------------------------------
# 1. Modality weight constants — schema invariants
# ---------------------------------------------------------------------------


def test_analytics_weight_multiplier_in_range_0_to_1() -> None:
    """``ANALYTICS_WEIGHT_MULTIPLIER`` 는 0 (analytics 무시) ~ 1 (현재 동작)
    사이. 1 초과는 analytics 를 judge_llm 보다 *더* 중요시 — 명시 결정 부재 시
    invariant 위반."""
    assert 0.0 <= ANALYTICS_WEIGHT_MULTIPLIER <= 1.0


def test_modality_multiplier_dispatch_covers_modality_extractor_emit() -> None:
    """``DIM_MODALITY_WEIGHT_MULTIPLIER`` 가 ``dim_extractor`` 의 emit
    값 (judge_llm + _ANALYTICS_MODALITY 의 sub-modality) 모두 cover.

    drift 시 unknown modality 가 default 1.0 (judge_llm) 으로 silent
    처리됨 — analytics 의 의도된 0.5 scale 이 dilute 안 됨.
    """
    from core.audit.dim_extractor import _ANALYTICS_MODALITY, DEFAULT_MODALITY

    expected_modalities = set(_ANALYTICS_MODALITY.values()) | {DEFAULT_MODALITY, "analytics"}
    assert expected_modalities.issubset(set(DIM_MODALITY_WEIGHT_MULTIPLIER))


def test_judge_llm_modalities_includes_empty_string() -> None:
    """``JUDGE_LLM_MODALITIES`` 가 빈 문자열도 포함 — modality 부재 시
    conservative default 로 N=1 widening 유지 (legacy / v1 baseline 안전)."""
    assert "" in JUDGE_LLM_MODALITIES
    assert "judge_llm" in JUDGE_LLM_MODALITIES


# ---------------------------------------------------------------------------
# 2. _dim_weight_with_modality — per-dim multiplier dispatch
# ---------------------------------------------------------------------------


def test_dim_weight_no_modality_returns_base() -> None:
    """``measurement_modality=None`` → DIM_WEIGHTS 값 그대로 (backward compat)."""
    assert _dim_weight_with_modality("broken_tool_use", None) == DIM_WEIGHTS["broken_tool_use"]


def test_dim_weight_judge_llm_modality_unchanged() -> None:
    """judge_llm modality 명시 시 multiplier 1.0 → 가중치 변동 없음."""
    modality = {"broken_tool_use": "judge_llm"}
    assert _dim_weight_with_modality("broken_tool_use", modality) == DIM_WEIGHTS["broken_tool_use"]


def test_dim_weight_analytics_scaled() -> None:
    """analytics modality → ANALYTICS_WEIGHT_MULTIPLIER 적용."""
    modality = {"verbose_padding": "token_count"}
    expected = DIM_WEIGHTS["verbose_padding"] * ANALYTICS_WEIGHT_MULTIPLIER
    assert _dim_weight_with_modality("verbose_padding", modality) == expected


def test_dim_weight_unknown_modality_default_judge_llm() -> None:
    """Unknown modality 값 → 보수적 default (judge_llm, multiplier 1.0).
    Silent skip 보다 명시 dispatch — analytics 의도가 dilute 되지 않음 +
    새 modality 추가 시 명시 entry 강제."""
    modality = {"broken_tool_use": "new_modality_we_didnt_define_yet"}
    assert _dim_weight_with_modality("broken_tool_use", modality) == DIM_WEIGHTS["broken_tool_use"]


def test_dim_weight_unknown_dim_returns_zero() -> None:
    """``DIM_WEIGHTS`` 에 없는 dim → 0.0 (graceful, fitness 기여 0)."""
    assert _dim_weight_with_modality("unknown_dim", None) == 0.0
    assert _dim_weight_with_modality("unknown_dim", {"unknown_dim": "judge_llm"}) == 0.0


# ---------------------------------------------------------------------------
# 3. compute_fitness — modality-aware aggregate
# ---------------------------------------------------------------------------


def test_compute_fitness_modality_blind_backward_compat() -> None:
    """``measurement_modality=None`` (기존 caller) → 가중치 변동 없음."""
    dim_means = {"verbose_padding": 5.0, "broken_tool_use": 5.0}
    f_no_modality = compute_fitness(dim_means, measurement_modality=None)
    f_explicit_none = compute_fitness(dim_means)
    assert f_no_modality == f_explicit_none


def test_compute_fitness_analytics_modality_scaled_down() -> None:
    """analytics modality 명시 → fitness 의 analytics 기여도 감소.

    같은 dim_means 라도 modality 가 analytics 로 tag 된 경우 그 dim 의
    weight 가 0.5× 라 dim_part 가 약간 감소 (regress 아니라 정의가
    바뀐 결과).
    """
    # 두 analytics dim 만 활성, 나머지 0
    dim_means = {"verbose_padding": 5.0, "redundant_tool_invocation": 5.0}
    modality_analytics = {
        "verbose_padding": "token_count",
        "redundant_tool_invocation": "tool_log",
    }
    f_blind = compute_fitness(dim_means)
    f_modality = compute_fitness(dim_means, measurement_modality=modality_analytics)
    # modality-aware 가 더 작아야 함 (analytics weight scaled down)
    assert f_modality < f_blind


def test_compute_fitness_judge_llm_modality_no_change() -> None:
    """모든 dim 이 judge_llm 으로 tag → modality-blind 와 동일."""
    dim_means = dict.fromkeys(DIM_WEIGHTS, 5.0)
    modality_all_judge = dict.fromkeys(DIM_WEIGHTS, "judge_llm")
    f_blind = compute_fitness(dim_means)
    f_judge = compute_fitness(dim_means, measurement_modality=modality_all_judge)
    assert f_blind == pytest.approx(f_judge)


# ---------------------------------------------------------------------------
# 4. _should_promote — N=1 widening modality guard
# ---------------------------------------------------------------------------


def test_should_promote_n1_widening_fires_for_judge_llm_critical() -> None:
    """Critical dim 이 judge_llm modality 이고 N=1 → widening (0.20) 발화.
    이 PR 이전 동작 보존 — judge_llm 의 under-sampled stderr=0 은 진짜 noisy."""
    baseline_means = {"broken_tool_use": 5.0}
    baseline_stderr = {"broken_tool_use": 0.0}
    current_means = {"broken_tool_use": 4.95}  # 작은 improvement
    current_stderr = {"broken_tool_use": 0.0}
    baseline_sample_count = {"broken_tool_use": 1}  # N=1
    baseline_modality = {"broken_tool_use": "judge_llm"}

    ok, reason = _should_promote(
        current_means,
        current_stderr,
        baseline_means,
        baseline_stderr,
        baseline_sample_count=baseline_sample_count,
        baseline_measurement_modality=baseline_modality,
    )
    # N=1 widening (0.20) → 0.05 Δ 가 promote 못 함
    assert not ok
    assert "N=1 critical" in reason


def test_should_promote_n1_widening_skipped_for_analytics_critical() -> None:
    """가정 시나리오 — ALL critical dims 이 analytics modality 이고 N=1 →
    widening skip (analytics stderr=0 은 deterministic, under-sampled 아님).

    현재 schema 의 CRITICAL_DIMS 5 개 모두 judge_llm 이라 실제 운영에선
    이 path 가 fire 안 함. 하지만 future schema 갱신 (e.g. analytics
    critical dim 추가) 시 guard 가 올바르게 작동하는지 invariant 로 pin.

    Note: 기존 PR-3 의 ``any()`` 의미상 한 critical 만 analytics 여도 다른
    critical 이 N≤1 + judge_llm 이면 widening 여전히 fire. 이 테스트는
    ALL critical = analytics 로 설정해서 guard 의 modality-skip path 가
    fire 함을 명시.
    """
    from autoresearch.train import CRITICAL_DIMS

    # 모든 critical dim 을 analytics 로 mock-tag, 모두 N=1
    baseline_means = dict.fromkeys(CRITICAL_DIMS, 5.0)
    baseline_stderr = dict.fromkeys(CRITICAL_DIMS, 0.0)
    current_means = dict.fromkeys(CRITICAL_DIMS, 4.95)
    current_stderr = dict.fromkeys(CRITICAL_DIMS, 0.0)
    baseline_sample_count = dict.fromkeys(CRITICAL_DIMS, 1)
    baseline_modality = dict.fromkeys(CRITICAL_DIMS, "analytics")

    ok, reason = _should_promote(
        current_means,
        current_stderr,
        baseline_means,
        baseline_stderr,
        baseline_sample_count=baseline_sample_count,
        baseline_measurement_modality=baseline_modality,
    )
    # widening 미발화 → "N=1 critical" 이 reason 에 없어야
    assert "N=1 critical" not in reason


def test_should_promote_n1_widening_conservative_default_for_missing_modality() -> None:
    """baseline_measurement_modality=None (v1 legacy baseline) → guard 가
    conservative default (judge_llm 가정) 로 widening 유지."""
    from autoresearch.train import CRITICAL_DIMS

    a_critical = CRITICAL_DIMS[0]
    baseline_means = {a_critical: 5.0}
    baseline_stderr = {a_critical: 0.0}
    current_means = {a_critical: 4.95}
    current_stderr = {a_critical: 0.0}
    baseline_sample_count = {a_critical: 1}

    ok, reason = _should_promote(
        current_means,
        current_stderr,
        baseline_means,
        baseline_stderr,
        baseline_sample_count=baseline_sample_count,
        baseline_measurement_modality=None,  # v1 legacy
    )
    # widening 유지 (보수적 default)
    assert "N=1 critical" in reason


def test_n1_fitness_margin_floor_constant_value() -> None:
    """``N1_FITNESS_MARGIN_FLOOR`` invariant. PR-MARGIN-FITNESS-SCALE
    (2026-05-30) re-tuned it to the fitness scale: 0.20 → 0.05 (10× the
    0.005 default epsilon). drift 시 N=1 widening 효과 silently 변동 — pin."""
    assert N1_FITNESS_MARGIN_FLOOR == 0.05


# ---------------------------------------------------------------------------
# 5. _load_baseline_measurement_modality — v1 / v2 schema reader
# ---------------------------------------------------------------------------


def test_load_baseline_modality_returns_empty_for_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """baseline.json 부재 → {} (graceful)."""
    from autoresearch import train as train_module

    monkeypatch.setattr(train_module, "BASELINE_PATH", tmp_path / "nonexistent.json")
    assert _load_baseline_measurement_modality() == {}


def test_load_baseline_modality_returns_empty_for_v1_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v1 baseline (no schema_version key) → {}.

    v1 reader 는 modality 미emit — guard 가 conservative default 로
    widening 유지하도록 빈 dict 반환.
    """
    from autoresearch import train as train_module

    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dim_means": {"x": 1.0}}), encoding="utf-8")
    monkeypatch.setattr(train_module, "BASELINE_PATH", path)
    assert _load_baseline_measurement_modality() == {}


def test_load_baseline_modality_reads_v2_raw_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v2 baseline 의 ``raw.measurement_modality`` 가 그대로 반환."""
    from autoresearch import train as train_module

    path = tmp_path / "baseline.json"
    payload: dict[str, Any] = {
        "schema_version": 2,
        "raw": {
            "dim_means": {"broken_tool_use": 3.0},
            "dim_stderr": {"broken_tool_use": 0.1},
            "measurement_modality": {
                "broken_tool_use": "judge_llm",
                "verbose_padding": "token_count",
            },
        },
        "axes": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(train_module, "BASELINE_PATH", path)
    result = _load_baseline_measurement_modality()
    assert result == {
        "broken_tool_use": "judge_llm",
        "verbose_padding": "token_count",
    }


def test_load_baseline_modality_skips_non_string_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """malformed entries (non-string values) → silently dropped, valid 만 보존."""
    from autoresearch import train as train_module

    path = tmp_path / "baseline.json"
    payload: dict[str, Any] = {
        "schema_version": 2,
        "raw": {
            "dim_means": {"x": 1.0},
            "measurement_modality": {
                "broken_tool_use": "judge_llm",
                "bad_dim": 42,  # non-string value — should be dropped
            },
        },
        "axes": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(train_module, "BASELINE_PATH", path)
    result = _load_baseline_measurement_modality()
    assert result == {"broken_tool_use": "judge_llm"}
