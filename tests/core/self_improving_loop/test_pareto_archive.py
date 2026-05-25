"""P2-revised (2026-05-25) — Pareto archive + Dynamic Reward Weighting invariants.

Plan: ``docs/plans/2026-05-25-p2-pareto-archive-dynamic-reward-weighting.md``.

Tests:
- PareteArchive insert / dominate-prune / sample
- _dominates strict Pareto check
- compute_hypervolume exact 2D + MC ≥3D
- dynamic_reward_weight_step gradient ascent + sum-to-1
- append_archive_entry + load_archive roundtrip
- backward compat (pareto_mode=False legacy 동작)
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from core.self_improving_loop.pareto_archive import (
    ArchiveEntry,
    PareteArchive,
    _dominates,
    append_archive_entry,
    compute_hypervolume,
    dynamic_reward_weight_step,
    load_archive,
)


def _entry(
    mutation_id: str,
    dim_means: dict[str, float],
    *,
    ts: float = 1716638400.0,
) -> ArchiveEntry:
    return ArchiveEntry(
        mutation_id=mutation_id,
        group_id="g-test",
        audit_run_id="a-test",
        ts=ts,
        dim_means=dim_means,
    )


class TestDominates:
    def test_strict_dominance(self) -> None:
        """W-PAR-1: a dominates b if a >= b in all dims AND a > b in one dim."""
        a = {"safety": 0.8, "helpfulness": 0.9}
        b = {"safety": 0.5, "helpfulness": 0.6}
        assert _dominates(a, b) is True
        assert _dominates(b, a) is False

    def test_no_dominance_when_equal(self) -> None:
        """W-PAR-2: a == b → no dominance."""
        a = {"safety": 0.5, "helpfulness": 0.6}
        assert _dominates(a, dict(a)) is False

    def test_trade_off_no_dominance(self) -> None:
        """W-PAR-3: a > b in one dim AND a < b in another → no dominance (Pareto-optimal pair)."""
        a = {"safety": 0.8, "helpfulness": 0.4}
        b = {"safety": 0.4, "helpfulness": 0.8}
        assert _dominates(a, b) is False
        assert _dominates(b, a) is False


class TestPareteArchive:
    def test_insert_non_dominated(self) -> None:
        """W-PAR-4: insert non-dominated entry succeeds, archive grows."""
        archive = PareteArchive()
        e1 = _entry("m1", {"safety": 0.5, "helpfulness": 0.5})
        e2 = _entry("m2", {"safety": 0.8, "helpfulness": 0.3})
        assert archive.insert(e1) is True
        assert archive.insert(e2) is True
        assert len(archive) == 2

    def test_insert_dominated_rejected(self) -> None:
        """W-PAR-5: dominated entry not inserted."""
        archive = PareteArchive()
        archive.insert(_entry("m1", {"safety": 0.8, "helpfulness": 0.8}))
        dominated = _entry("m2", {"safety": 0.5, "helpfulness": 0.5})
        assert archive.insert(dominated) is False
        assert len(archive) == 1

    def test_insert_prunes_dominated(self) -> None:
        """W-PAR-6: new entry dominates existing → existing pruned."""
        archive = PareteArchive()
        archive.insert(_entry("m1", {"safety": 0.5, "helpfulness": 0.5}))
        archive.insert(_entry("m2", {"safety": 0.6, "helpfulness": 0.4}))
        # m3 dominates m1
        assert archive.insert(_entry("m3", {"safety": 0.9, "helpfulness": 0.9})) is True
        ids = {e.mutation_id for e in archive.entries}
        assert "m3" in ids
        assert "m1" not in ids  # pruned

    def test_sample_returns_subset(self) -> None:
        """W-PAR-7: sample 이 archive 의 subset 반환."""
        archive = PareteArchive()
        for i in range(5):
            archive.insert(_entry(f"m{i}", {"safety": 0.1 * i, "helpfulness": 0.1 * (5 - i)}))
        sample = archive.sample(n=3, rng=random.Random(42))
        assert len(sample) == 3
        sample_ids = {e.mutation_id for e in sample}
        archive_ids = {e.mutation_id for e in archive.entries}
        assert sample_ids.issubset(archive_ids)


class TestComputeHypervolume:
    def test_empty_archive_zero(self) -> None:
        """W-HV-1: empty archive → HV = 0."""
        archive = PareteArchive()
        assert compute_hypervolume(archive, {"x": 0.0, "y": 0.0}) == 0.0

    def test_single_entry_2d_exact(self) -> None:
        """W-HV-2: single entry (x, y) above origin → HV = x * y."""
        archive = PareteArchive()
        archive.insert(_entry("m1", {"x": 0.5, "y": 0.4}))
        hv = compute_hypervolume(archive, {"x": 0.0, "y": 0.0})
        assert hv == pytest.approx(0.5 * 0.4, rel=1e-9)

    def test_two_entry_2d_pareto_exact(self) -> None:
        """W-HV-3: two trade-off entries (0.8,0.2) + (0.4,0.6) → exact 2D HV."""
        archive = PareteArchive()
        archive.insert(_entry("m1", {"x": 0.8, "y": 0.2}))
        archive.insert(_entry("m2", {"x": 0.4, "y": 0.6}))
        hv = compute_hypervolume(archive, {"x": 0.0, "y": 0.0})
        # Visual: rectangle (0.8 × 0.2) + extra (0.4 × 0.4) = 0.16 + 0.16 = 0.32
        assert hv == pytest.approx(0.32, rel=1e-9)

    def test_3d_mc_approximation(self) -> None:
        """W-HV-4: dim >= 3 falls back to MC, returns positive value."""
        archive = PareteArchive()
        archive.insert(_entry("m1", {"x": 0.5, "y": 0.5, "z": 0.5}))
        hv = compute_hypervolume(
            archive,
            {"x": 0.0, "y": 0.0, "z": 0.0},
            mc_samples=500,
            rng_seed=42,
        )
        # Volume of (0..0.5)^3 = 0.125, expect MC近似 within 30% (small N)
        assert 0.0 < hv <= 0.5**3 * 1.5


class TestDynamicRewardWeight:
    def test_step_normalizes_to_unity(self) -> None:
        """W-DW-1: weight update 후 sum=1 정규화 invariant."""
        archive = PareteArchive()
        archive.insert(_entry("m1", {"x": 0.5, "y": 0.5}))
        archive.insert(_entry("m2", {"x": 0.8, "y": 0.2}))
        new_w = dynamic_reward_weight_step(
            {"x": 0.5, "y": 0.5},
            archive,
            {"x": 0.0, "y": 0.0},
            lr=0.01,
        )
        assert sum(new_w.values()) == pytest.approx(1.0, rel=1e-6)

    def test_step_empty_archive_returns_unchanged(self) -> None:
        """W-DW-2: empty archive → weight 그대로."""
        archive = PareteArchive()
        initial = {"x": 0.5, "y": 0.5}
        new_w = dynamic_reward_weight_step(initial, archive, {"x": 0.0, "y": 0.0})
        assert new_w == initial


class TestArchiveJsonl:
    def test_append_and_load_roundtrip(self, tmp_path: Path) -> None:
        """W-JL-1: append → load → entries 동일."""
        archive_path = tmp_path / "baseline_archive.jsonl"
        e1 = _entry("m1", {"safety": 0.5, "helpfulness": 0.6})
        e2 = _entry("m2", {"safety": 0.8, "helpfulness": 0.3})
        append_archive_entry(e1, archive_path=archive_path)
        append_archive_entry(e2, archive_path=archive_path)
        loaded = load_archive(archive_path)
        assert len(loaded) == 2
        ids = {e.mutation_id for e in loaded.entries}
        assert ids == {"m1", "m2"}

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """W-JL-2: 파일 없으면 empty archive 반환 (graceful)."""
        loaded = load_archive(tmp_path / "nonexistent.jsonl")
        assert len(loaded) == 0

    def test_load_applies_pareto_filter(self, tmp_path: Path) -> None:
        """W-JL-3: load 시 dominated entry pruned (insert path 재실행)."""
        archive_path = tmp_path / "archive.jsonl"
        # 쓰기: m1 (0.5,0.5), m2 (0.9,0.9, dominates m1)
        e1 = _entry("m1", {"safety": 0.5, "helpfulness": 0.5})
        e2 = _entry("m2", {"safety": 0.9, "helpfulness": 0.9})
        append_archive_entry(e1, archive_path=archive_path)
        append_archive_entry(e2, archive_path=archive_path)
        loaded = load_archive(archive_path)
        # load 가 insert pipeline 재실행 → m1 dominated, m2 만 남음
        ids = {e.mutation_id for e in loaded.entries}
        assert ids == {"m2"}


class TestBackwardCompat:
    def test_pareto_mode_default_false(self) -> None:
        """W-COMPAT-1: AutoresearchConfig.pareto_mode default = False (legacy)."""
        from core.config.self_improving_loop import AutoresearchConfig

        cfg = AutoresearchConfig()
        assert cfg.pareto_mode is False

    def test_hypervolume_reference_point_default_empty(self) -> None:
        """W-COMPAT-2: hypervolume_reference_point default = empty dict."""
        from core.config.self_improving_loop import AutoresearchConfig

        cfg = AutoresearchConfig()
        assert cfg.hypervolume_reference_point == {}
