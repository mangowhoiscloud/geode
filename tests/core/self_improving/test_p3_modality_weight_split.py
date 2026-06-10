"""measurement_modality dispatch + N=1 widening tests.

The per-dim ``measurement_modality`` provenance (PR-1) is read by
``compute_fitness`` / ``_should_promote``. The analytics weight-PENALTY split
(PR-SIL-5THEME C3) was REMOVED with the two post-judge analytics dims
(PR-DROP-ANALYTICS-DIMS, 2026-06-02) — every dim is now ``judge_llm`` so the
multiplier is uniformly 1.0. These tests pin the surviving behaviour: the
dispatch returns the base ``DIM_WEIGHTS`` value for ``judge_llm`` / unknown /
None modalities, the N=1 critical widening fires for ``judge_llm``, and the v1/v2
baseline modality reader still round-trips (including legacy rows that carry the
removed analytics modalities, for backward-compat).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from core.self_improving import ledger
from core.self_improving.fitness import (
    DIM_WEIGHTS,
    JUDGE_LLM_MODALITIES,
    _dim_weight_with_modality,
    compute_fitness,
)
from core.self_improving.gate import N1_FITNESS_MARGIN_FLOOR, _should_promote
from core.self_improving.ledger import _load_baseline_measurement_modality

# ---------------------------------------------------------------------------
# 1. Modality weight constants — schema invariants
# ---------------------------------------------------------------------------


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
    dim_means = {"stuck_in_loops": 5.0, "broken_tool_use": 5.0}
    f_no_modality = compute_fitness(dim_means, measurement_modality=None)
    f_explicit_none = compute_fitness(dim_means)
    assert f_no_modality == f_explicit_none


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


def test_should_promote_n1_widening_conservative_default_for_missing_modality() -> None:
    """baseline_measurement_modality=None (v1 legacy baseline) → guard 가
    conservative default (judge_llm 가정) 로 widening 유지."""
    from core.self_improving.fitness import CRITICAL_DIMS

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

    monkeypatch.setattr(ledger, "BASELINE_PATH", tmp_path / "nonexistent.json")
    assert _load_baseline_measurement_modality() == {}


def test_load_baseline_modality_returns_empty_for_v1_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v1 baseline (no schema_version key) → {}.

    v1 reader 는 modality 미emit — guard 가 conservative default 로
    widening 유지하도록 빈 dict 반환.
    """

    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dim_means": {"x": 1.0}}), encoding="utf-8")
    monkeypatch.setattr(ledger, "BASELINE_PATH", path)
    assert _load_baseline_measurement_modality() == {}


def test_load_baseline_modality_reads_v2_raw_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v2 baseline 의 ``raw.measurement_modality`` 가 그대로 반환."""

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
    monkeypatch.setattr(ledger, "BASELINE_PATH", path)
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
    monkeypatch.setattr(ledger, "BASELINE_PATH", path)
    result = _load_baseline_measurement_modality()
    assert result == {"broken_tool_use": "judge_llm"}
