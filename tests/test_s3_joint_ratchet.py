"""ADR-012 S3 — 공동 ratchet (seed/policy + 4-묶음 baseline.json) invariants.

Pins the 4-axis baseline schema and load/write round-trip:
- baseline.json grows from `{dim_means, dim_stderr}` (pre-S3) to
  `{dim_means, dim_stderr, ux_means, admire_means, bench_means}` (S3).
- Pre-S3 baselines without the 3 newer axes still parse (graceful, empty dicts).
- Per-axis corruption (e.g. non-numeric in `ux_means`) doesn't invalidate
  the load-bearing `dim_means` part — the 3 newer axes are isolated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def isolated_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``BASELINE_PATH`` to ``tmp_path`` so the test never touches
    the operator's real baseline."""
    from autoresearch import train

    target = tmp_path / "baseline.json"
    monkeypatch.setattr(train, "BASELINE_PATH", target)
    return target


# Loader ----------------------------------------------------------------------


def test_load_returns_tuple_of_five(isolated_baseline: Path) -> None:
    """S3 schema: ``_load_baseline`` returns 5-tuple (dim_means, dim_stderr,
    ux_means, admire_means, bench_means)."""
    from autoresearch.train import _load_baseline

    result = _load_baseline()
    assert isinstance(result, tuple)
    assert len(result) == 5


def test_load_missing_file_returns_none_and_empty_axes(isolated_baseline: Path) -> None:
    from autoresearch.train import _load_baseline

    dim_means, dim_stderr, ux, admire, bench = _load_baseline()
    assert dim_means is None
    assert dim_stderr is None
    assert ux == {}
    assert admire == {}
    assert bench == {}


def test_load_pre_s3_baseline_is_backward_compatible(isolated_baseline: Path) -> None:
    """A pre-S3 baseline.json (only ``dim_*``) must still parse — the 3
    newer axes default to ``{}``."""
    isolated_baseline.write_text(
        json.dumps(
            {
                "dim_means": {"role_realism": 7.5},
                "dim_stderr": {"role_realism": 0.2},
            }
        ),
        encoding="utf-8",
    )
    from autoresearch.train import _load_baseline

    dim_means, dim_stderr, ux, admire, bench = _load_baseline()
    assert dim_means == {"role_realism": 7.5}
    assert dim_stderr == {"role_realism": 0.2}
    assert ux == {} and admire == {} and bench == {}


def test_load_full_s3_baseline_returns_all_axes(isolated_baseline: Path) -> None:
    isolated_baseline.write_text(
        json.dumps(
            {
                "dim_means": {"role_realism": 7.5},
                "dim_stderr": {"role_realism": 0.2},
                "ux_means": {"success_rate": 0.9, "token_cost_norm": 0.7},
                "admire_means": {"pairwise_win_rate": 0.6},
                "bench_means": {"swe_bench_pro_pass": 0.35},
            }
        ),
        encoding="utf-8",
    )
    from autoresearch.train import _load_baseline

    dim_means, _, ux, admire, bench = _load_baseline()
    assert dim_means == {"role_realism": 7.5}
    assert ux == {"success_rate": 0.9, "token_cost_norm": 0.7}
    assert admire == {"pairwise_win_rate": 0.6}
    assert bench == {"swe_bench_pro_pass": 0.35}


def test_load_corrupted_ux_axis_isolated_from_dim(isolated_baseline: Path) -> None:
    """A non-dict / non-numeric value in `ux_means` must drop to `{}`
    without invalidating the load-bearing `dim_*` part (per-axis graceful)."""
    isolated_baseline.write_text(
        json.dumps(
            {
                "dim_means": {"role_realism": 7.5},
                "dim_stderr": {},
                "ux_means": "not a dict",
                "admire_means": {"pairwise_win_rate": "non-numeric"},
                "bench_means": {"swe_bench_pro_pass": 0.35},
            }
        ),
        encoding="utf-8",
    )
    from autoresearch.train import _load_baseline

    dim_means, _, ux, admire, bench = _load_baseline()
    assert dim_means == {"role_realism": 7.5}
    assert ux == {}
    assert admire == {}
    assert bench == {"swe_bench_pro_pass": 0.35}


def test_load_missing_dim_means_returns_none(isolated_baseline: Path) -> None:
    """No ``dim_means`` → entire baseline treated as gate-dormant
    (returns None for dim_means/dim_stderr, even if the newer axes are present)."""
    isolated_baseline.write_text(
        json.dumps({"ux_means": {"success_rate": 0.9}}),
        encoding="utf-8",
    )
    from autoresearch.train import _load_baseline

    dim_means, dim_stderr, *_ = _load_baseline()
    assert dim_means is None
    assert dim_stderr is None


# Writer ----------------------------------------------------------------------


def test_write_default_omits_3_newer_axes(isolated_baseline: Path) -> None:
    """Backwards compat — callers that don't pass the 3 newer axes
    serialize a payload that's identical to the pre-S3 shape."""
    from autoresearch.train import _write_baseline

    _write_baseline({"role_realism": 7.5}, {"role_realism": 0.2})
    payload = json.loads(isolated_baseline.read_text(encoding="utf-8"))
    assert payload == {
        "dim_means": {"role_realism": 7.5},
        "dim_stderr": {"role_realism": 0.2},
    }


def test_write_full_4axis_serializes_all(isolated_baseline: Path) -> None:
    from autoresearch.train import _write_baseline

    _write_baseline(
        {"role_realism": 7.5},
        {"role_realism": 0.2},
        ux_means={"success_rate": 0.9},
        admire_means={"pairwise_win_rate": 0.6},
        bench_means={"swe_bench_pro_pass": 0.35},
    )
    payload = json.loads(isolated_baseline.read_text(encoding="utf-8"))
    assert payload == {
        "dim_means": {"role_realism": 7.5},
        "dim_stderr": {"role_realism": 0.2},
        "ux_means": {"success_rate": 0.9},
        "admire_means": {"pairwise_win_rate": 0.6},
        "bench_means": {"swe_bench_pro_pass": 0.35},
    }


def test_write_empty_axis_dict_is_omitted(isolated_baseline: Path) -> None:
    """``ux_means={}`` is treated as 'no signal' and omitted (same as None)."""
    from autoresearch.train import _write_baseline

    _write_baseline(
        {"role_realism": 7.5},
        {"role_realism": 0.2},
        ux_means={},
        admire_means={"pairwise_win_rate": 0.6},
    )
    payload = json.loads(isolated_baseline.read_text(encoding="utf-8"))
    assert "ux_means" not in payload
    assert payload["admire_means"] == {"pairwise_win_rate": 0.6}


# Round-trip ------------------------------------------------------------------


def test_write_then_load_roundtrips_4_axes(isolated_baseline: Path) -> None:
    from autoresearch.train import _load_baseline, _write_baseline

    _write_baseline(
        {"role_realism": 7.5},
        {"role_realism": 0.2},
        ux_means={"success_rate": 0.9},
        admire_means={"pairwise_win_rate": 0.6},
        bench_means={"swe_bench_pro_pass": 0.35},
    )
    dim_means, dim_stderr, ux, admire, bench = _load_baseline()
    assert dim_means == {"role_realism": 7.5}
    assert dim_stderr == {"role_realism": 0.2}
    assert ux == {"success_rate": 0.9}
    assert admire == {"pairwise_win_rate": 0.6}
    assert bench == {"swe_bench_pro_pass": 0.35}


# Seed-generation BaselineSnapshot --------------------------------------------


def test_snapshot_has_3_new_axis_fields() -> None:
    """``BaselineSnapshot`` exposes ux/admire/bench fields (S3 schema)."""
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

    snap = BaselineSnapshot()
    assert snap.ux_means == {}
    assert snap.admire_means == {}
    assert snap.bench_means == {}


def test_snapshot_loader_populates_4_axes(tmp_path: Path) -> None:
    from plugins.seed_generation.baseline_reader import load_baseline

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "dim_means": {"role_realism": 7.5},
                "dim_stderr": {"role_realism": 0.2},
                "ux_means": {"success_rate": 0.9},
                "admire_means": {"pairwise_win_rate": 0.6},
                "bench_means": {"swe_bench_pro_pass": 0.35},
            }
        ),
        encoding="utf-8",
    )
    snap = load_baseline(baseline_path)
    assert snap is not None
    assert snap.ux_means == {"success_rate": 0.9}
    assert snap.admire_means == {"pairwise_win_rate": 0.6}
    assert snap.bench_means == {"swe_bench_pro_pass": 0.35}


def test_snapshot_loader_pre_s3_baseline_empty_new_axes(tmp_path: Path) -> None:
    """Pre-S3 baseline → 3 newer axes default to empty dicts."""
    from plugins.seed_generation.baseline_reader import load_baseline

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {"dim_means": {"role_realism": 7.5}, "dim_stderr": {}},
        ),
        encoding="utf-8",
    )
    snap = load_baseline(baseline_path)
    assert snap is not None
    assert snap.ux_means == {}
    assert snap.admire_means == {}
    assert snap.bench_means == {}


# main() consumer wiring ------------------------------------------------------


def test_train_main_passes_baseline_bench_means_to_compute_fitness() -> None:
    """``compute_fitness`` call site in ``main()`` must pass
    ``baseline_bench_means`` so the cross-validation gate (S6) actually
    fires when both current + baseline bench_means are present."""
    repo_root = Path(__file__).resolve().parent.parent
    src = (repo_root / "autoresearch/train.py").read_text(encoding="utf-8")
    # Locate the main() call site, not the function definition.
    assert "baseline_bench_means=baseline_bench_means" in src
