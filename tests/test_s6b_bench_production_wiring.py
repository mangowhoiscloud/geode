"""PR-SIL-5THEME C2 — S6b bench production wiring tests.

Covers the silent-disconnect closure: schema/math/gate existed (S6) but
production wiring path (collector → main → compute_fitness →
_write_baseline → _should_promote → results.jsonl → OL-C1 emit) was
0 in production. This test file pins each wiring point.

Symmetric with the dim-side PR-1/PR-3/PR-4/PR-5 of petri-schema-v2.
"""

from __future__ import annotations

from typing import Any

from core.self_improving.bench_means import (
    BENCH_DIM_WEIGHTS,
    BENCH_PORT_MAP,
    BENCH_REQUIRES_DOCKER,
    BENCH_REQUIRES_VISION,
    BENCH_RUBRIC_VERSION,
    BenchProvenance,
    collect_bench_means_from_inspect_ai,
    compute_missing_benches,
)

# ---------------------------------------------------------------------------
# 1. Schema invariants — production wiring 의 ground-truth 형태
# ---------------------------------------------------------------------------


def test_bench_port_map_covers_all_bench_dim_weights() -> None:
    """``BENCH_PORT_MAP`` 의 key 가 ``BENCH_DIM_WEIGHTS`` 의 key 와 정확히 일치.

    drift 시 dispatch 가 silent skip 됨 (port 없는 bench 가 collector 의
    ``BENCH_PORT_MAP`` 에 안 들어가 → eligible 빠지고 missing 에도 안
    들어가는 dead-key). 둘 다 7 field 단일 SoT 보장.
    """
    assert set(BENCH_PORT_MAP) == set(BENCH_DIM_WEIGHTS)


def test_bench_port_map_packages_are_inspect_evals_or_harbor() -> None:
    """``BENCH_PORT_MAP`` 의 package 컬럼은 두 PyPI 패키지 중 하나.

    [audit] extra 에 의존성 추가된 두 패키지 (`inspect-evals`,
    `inspect-harbor`) 외 다른 import path 가 silently 끼면 collector 가
    runtime 에서 ImportError 로 graceful-skip 못 함.
    """
    for _field, (package, _task) in BENCH_PORT_MAP.items():
        assert package in {"inspect_evals", "inspect_harbor"}


def test_bench_requires_docker_subset_of_port_map() -> None:
    """Docker 게이트가 적용되는 bench 는 BENCH_PORT_MAP 의 7 중 일부."""
    assert BENCH_REQUIRES_DOCKER.issubset(set(BENCH_PORT_MAP))


def test_bench_requires_vision_subset_of_port_map() -> None:
    """Vision 게이트가 적용되는 bench 도 BENCH_PORT_MAP 의 7 중 일부."""
    assert BENCH_REQUIRES_VISION.issubset(set(BENCH_PORT_MAP))


def test_bench_rubric_version_is_non_empty_string() -> None:
    """``BENCH_RUBRIC_VERSION`` 은 baseline.json 의 cohort tag — 빈 문자열은
    cohort 식별 불가능 (apples-to-oranges 차단 깨짐)."""
    assert BENCH_RUBRIC_VERSION
    assert isinstance(BENCH_RUBRIC_VERSION, str)


# ---------------------------------------------------------------------------
# 2. BenchProvenance dataclass
# ---------------------------------------------------------------------------


def test_bench_provenance_default_init_has_empty_dicts_and_default_version() -> None:
    """``BenchProvenance()`` (인자 없이) 는 모든 dict 가 비고 rubric_version
    은 default cohort tag.

    dry-run path 에서 ``BenchProvenance()`` 호출 → format_results_jsonl_row
    가 anyway 7-field default 채우므로 schema 일관성 유지.
    """
    prov = BenchProvenance()
    assert prov.bench_means == {}
    assert prov.bench_stderr == {}
    assert prov.bench_sample_count == {}
    assert prov.missing_benches == []
    assert prov.rubric_version == BENCH_RUBRIC_VERSION


# ---------------------------------------------------------------------------
# 3. compute_missing_benches — Goodhart suppression surface
# ---------------------------------------------------------------------------


def test_compute_missing_benches_empty_when_all_present() -> None:
    full = dict.fromkeys(BENCH_DIM_WEIGHTS, 0.5)
    assert compute_missing_benches(full) == []


def test_compute_missing_benches_lists_absent_sorted() -> None:
    partial = {"swe_bench_pro_pass": 0.5, "gpqa_diamond": 0.7}
    missing = compute_missing_benches(partial)
    assert missing == sorted(set(BENCH_DIM_WEIGHTS) - {"swe_bench_pro_pass", "gpqa_diamond"})


def test_compute_missing_benches_handles_none_input() -> None:
    """``None`` 은 "측정 0건" — 7 field 전부 missing."""
    assert compute_missing_benches(None) == sorted(BENCH_DIM_WEIGHTS)


# ---------------------------------------------------------------------------
# 4. collect_bench_means_from_inspect_ai — nominal smoke (env off)
# ---------------------------------------------------------------------------


def test_collect_returns_bench_provenance_dataclass() -> None:
    """Nominal smoke (``GEODE_BENCH_S6B_LIVE`` env off 가정 + 패키지 부재)
    — collector 가 BenchProvenance 반환, all-missing 또는 부분 missing."""
    result = collect_bench_means_from_inspect_ai(target_model="gpt-5")
    assert isinstance(result, BenchProvenance)
    accounted = set(result.bench_means) | set(result.missing_benches)
    assert accounted == set(BENCH_DIM_WEIGHTS), (
        f"7-field universe 가 means+missing 합에 빠짐: {accounted}"
    )


def test_collect_target_model_text_only_skips_vision_bench() -> None:
    """Vision 미지원 모델 (e.g. text-only base) 호출 시 ``hle_accuracy`` 가
    missing_benches 에 들어감. A1 graceful-skip 의 vision 게이트 검증."""
    result = collect_bench_means_from_inspect_ai(target_model="text-bison-3")
    assert "hle_accuracy" in result.missing_benches


def test_collect_rubric_version_propagates() -> None:
    """반환된 ``BenchProvenance.rubric_version`` 이 ``BENCH_RUBRIC_VERSION``
    상수와 일치 — baseline.json 의 cohort tag 가 grep-provable."""
    result = collect_bench_means_from_inspect_ai(target_model="gpt-5")
    assert result.rubric_version == BENCH_RUBRIC_VERSION


# ---------------------------------------------------------------------------
# 5. format_results_jsonl_row — 4-axis breakdown columns
# ---------------------------------------------------------------------------


def test_results_jsonl_row_emits_bench_columns_when_provenance_passed() -> None:
    """PR-SIL-5THEME C2 — ``format_results_jsonl_row`` 가 bench 컬럼 4종
    (``bench_means`` / ``bench_stderr`` / ``bench_sample_count`` /
    ``missing_benches`` / ``bench_rubric_version``) emit."""
    import json

    from core.self_improving.train import format_results_jsonl_row

    prov = BenchProvenance(
        bench_means={"swe_bench_pro_pass": 0.42, "gpqa_diamond": 0.71},
        bench_stderr={"swe_bench_pro_pass": 0.05},
        bench_sample_count={"swe_bench_pro_pass": 100, "gpqa_diamond": 200},
        missing_benches=["tau2_bench_success", "hle_accuracy"],
        rubric_version=BENCH_RUBRIC_VERSION,
    )
    row_str = format_results_jsonl_row(
        session_id="s1",
        gen_tag="g1",
        commit="abc",
        fitness=0.5,
        dim_means={},
        dim_stderr={},
        dim_scores={},
        verdict="keep",
        description="test",
        baseline_active=False,
        bench_provenance=prov,
    )
    row = json.loads(row_str)
    # 4-axis 컬럼 4종 모두 present (no silent drop)
    assert "bench_means" in row
    assert "bench_stderr" in row
    assert "bench_sample_count" in row
    assert "missing_benches" in row
    assert "bench_rubric_version" in row
    # 7-field universe (caller 가 2 field 만 채워도 row 는 7-field 보존)
    assert set(row["bench_means"]) == set(BENCH_DIM_WEIGHTS)
    # caller 의 값이 그대로 보존
    assert row["bench_means"]["swe_bench_pro_pass"] == 0.42
    # rubric_version cohort tag
    assert row["bench_rubric_version"] == BENCH_RUBRIC_VERSION
    # missing_benches sorted contract
    assert row["missing_benches"] == ["hle_accuracy", "tau2_bench_success"]


def test_results_jsonl_row_default_empty_when_no_provenance() -> None:
    """``bench_provenance=None`` (legacy caller) → 7-field 0.0 default 채워서
    schema 일관성 유지. legacy reader backward-compat."""
    import json

    from core.self_improving.train import format_results_jsonl_row

    row = json.loads(
        format_results_jsonl_row(
            session_id="s1",
            gen_tag="g1",
            commit="abc",
            fitness=0.5,
            dim_means={},
            dim_stderr={},
            dim_scores={},
            verdict="keep",
            description="",
            baseline_active=False,
            # bench_provenance 미전달
        )
    )
    assert set(row["bench_means"]) == set(BENCH_DIM_WEIGHTS)
    assert all(v == 0.0 for v in row["bench_means"].values())
    assert row["missing_benches"] == []


# ---------------------------------------------------------------------------
# 6. _write_baseline — bench provenance 영속화
# ---------------------------------------------------------------------------


def test_write_baseline_persists_bench_provenance(monkeypatch: Any, tmp_path: Any) -> None:
    """PR-SIL-5THEME C2 — ``_write_baseline`` 가 ``bench_stderr`` /
    ``bench_sample_count`` / ``bench_rubric_version`` 슬롯에 영속화. dim 측
    PR-1 패턴과 symmetric."""
    import json
    from pathlib import Path

    from core.self_improving import train as train_module

    target = tmp_path / "baseline.json"
    monkeypatch.setattr(train_module, "BASELINE_PATH", Path(target))

    train_module._write_baseline(
        dim_means={"broken_tool_use": 3.0},
        dim_stderr={"broken_tool_use": 0.1},
        bench_means={"gpqa_diamond": 0.6, "swe_bench_pro_pass": 0.4},
        bench_stderr={"gpqa_diamond": 0.04, "swe_bench_pro_pass": 0.05},
        bench_sample_count={"gpqa_diamond": 200, "swe_bench_pro_pass": 100},
        bench_rubric_version=BENCH_RUBRIC_VERSION,
        session_id="sX",
        commit="abc1234",
    )

    payload = json.loads(target.read_text())
    raw = payload["raw"]
    assert raw["bench_stderr"] == {"gpqa_diamond": 0.04, "swe_bench_pro_pass": 0.05}
    assert raw["bench_sample_count"] == {"gpqa_diamond": 200, "swe_bench_pro_pass": 100}
    assert raw["bench_rubric_version"] == BENCH_RUBRIC_VERSION
    assert payload["axes"]["bench_means"] == {"gpqa_diamond": 0.6, "swe_bench_pro_pass": 0.4}


# ---------------------------------------------------------------------------
# 7. _should_promote — cross-validation gate 활성
# ---------------------------------------------------------------------------


def test_should_promote_passes_bench_to_compute_fitness() -> None:
    """``_should_promote`` 가 bench_means + baseline_bench_means 를
    internal ``compute_fitness`` 호출에 forward. 이전엔 미전달 → Goodhart
    cross-validation gate 가 promote 결정에 0 영향. 이제 forward → fire 가능."""
    from core.self_improving.train import _should_promote

    # alignment_only_fooling scenario: dim 개선 (lower) + bench regress (lower)
    dim_means = {"broken_tool_use": 2.0}  # promote (lower than baseline 3.0)
    baseline_means = {"broken_tool_use": 3.0}
    bench_means_now = dict.fromkeys(BENCH_DIM_WEIGHTS, 0.3)  # regress (lower)
    bench_means_base = dict.fromkeys(BENCH_DIM_WEIGHTS, 0.6)

    ok, reason = _should_promote(
        current_means=dim_means,
        current_stderr={"broken_tool_use": 0.0},
        baseline_means=baseline_means,
        baseline_stderr={"broken_tool_use": 0.0},
        bench_means=bench_means_now,
        baseline_bench_means=bench_means_base,
    )
    assert not ok, "alignment_only_fooling 시나리오에서 promote 차단 실패"
    assert "cross-validation conflict" in reason
    assert "alignment_only_fooling" in reason
