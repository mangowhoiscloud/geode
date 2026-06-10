"""Unit tests for the self-improving campaign driver (``core/self_improving/campaign.py``).

PR-CAMPAIGN-DRIVER (2026-05-31); relocated under the ``core.self_improving``
umbrella by PR-SELF-IMPROVING-UMBRELLA (2026-05-31). NO live audits — every
boundary is mocked:
the mutator ``propose()``, the ``train.py`` subprocess, ``read_eval_log``, and
the SoT files (via monkeypatched module-level path constants). The tests cover:

* propose-guard: re-proposes on ``RepetitiveMutationError`` + measurement-
  hyperparam ``ValueError``, accepts a clean proposal, gives up after M.
* arm loop: correct ``GEODE_PROMOTE_POLICY`` (+ seed for random) +
  ``commit_enabled`` per arm; gate runs last.
* SoT snapshot/restore round-trips the policy files + baseline.json.
* degeneracy guard: HALTs on a fake 0-sample eval, passes on a healthy one.
* gen-0 K-repeat collects K held-out values + computes the noise band.
* ``--dry-run`` end-to-end smoke runs without touching PAYG/network.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import core.self_improving.campaign as rc
import pytest
from core.self_improving.loop.mutator_feedback import RepetitionFinding, RepetitiveMutationError
from core.self_improving.loop.runner import Mutation, Proposal

# tests/core/self_improving/test_run_campaign.py → parents[3] = repo root (where ``core/`` is importable
# so ``python -m core.self_improving.campaign`` / ``…train`` resolve their package).
_REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Fixtures — redirect the module-level SoT paths into tmp dirs
# ---------------------------------------------------------------------------


@pytest.fixture
def campaign_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect every SoT path the driver touches into ``tmp_path``."""
    state_dir = tmp_path / "autoresearch"
    policies_dir = state_dir / "policies"
    policies_dir.mkdir(parents=True)
    baseline = state_dir / "baseline.json"
    mutations = state_dir / "mutations.jsonl"
    progress = state_dir / "campaign-progress.log"
    snapshot = tmp_path / "state" / "campaign" / "gen-0-snapshot"
    petri_logs = tmp_path / "petri-logs"
    petri_logs.mkdir(parents=True)

    monkeypatch.setattr(rc, "STATE_DIR", state_dir)
    monkeypatch.setattr(rc, "POLICIES_DIR", policies_dir)
    monkeypatch.setattr(rc, "BASELINE_JSON", baseline)
    monkeypatch.setattr(rc, "MUTATIONS_JSONL", mutations)
    monkeypatch.setattr(rc, "PROGRESS_LOG", progress)
    monkeypatch.setattr(rc, "GEN0_SNAPSHOT_DIR", snapshot)
    monkeypatch.setattr(rc, "PETRI_LOGS_DIR", petri_logs)
    # The snapshot-source tuple is recomputed from the patched POLICIES_DIR so
    # snapshot_sot reads the tmp policies dir, not the repo one.
    monkeypatch.setattr(
        rc,
        "_SNAPSHOT_SOURCES",
        ((policies_dir, "*.json"), (policies_dir, "*.jsonl")),
    )
    return {
        "state_dir": state_dir,
        "policies_dir": policies_dir,
        "baseline": baseline,
        "mutations": mutations,
        "progress": progress,
        "snapshot": snapshot,
        "petri_logs": petri_logs,
    }


def _clean_mutation() -> Mutation:
    return Mutation(
        target_section="some_section",
        new_value="a clean new value",
        rationale="grounded",
        target_kind="prompt",
    )


def _clean_proposal() -> Proposal:
    return Proposal(mutation=_clean_mutation())


def _repetitive_error() -> RepetitiveMutationError:
    finding = RepetitionFinding(
        is_repetitive=True,
        max_similarity=0.99,
        matched_mutation_id="m1",
        matched_target_section="some_section",
    )
    return RepetitiveMutationError(finding, threshold=0.85)


def _write_attribution(
    path: Path,
    *,
    held_out: float | None,
    fitness: float | None,
    delta: float | None = None,
    promote_policy: str | None = None,
    source: str = "manual",
    between_seed_stderr: float | None = 0.05,
) -> None:
    row: dict[str, Any] = {"ts": 1.0, "kind": "attribution", "mutation_id": "x", "source": source}
    if held_out is not None:
        row["held_out_fitness"] = held_out
    if fitness is not None:
        row["fitness_after"] = fitness
    if delta is not None:
        row["fitness_delta"] = delta
    if promote_policy is not None:
        row["promote_policy"] = promote_policy
    if between_seed_stderr is not None:
        row["between_seed_stderr"] = between_seed_stderr
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# propose-guard
# ---------------------------------------------------------------------------


def test_propose_guard_accepts_clean_proposal() -> None:
    clean = _clean_proposal()
    runner = SimpleNamespace(propose=lambda: clean)
    result = rc.propose_with_guard(runner, max_attempts=3)
    assert result is clean


def test_propose_guard_reproposes_on_repetitive_then_accepts() -> None:
    clean = _clean_proposal()
    calls = {"n": 0}

    def propose() -> Proposal:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _repetitive_error()
        return clean

    runner = SimpleNamespace(propose=propose)
    result = rc.propose_with_guard(runner, max_attempts=5)
    assert result is clean
    assert calls["n"] == 2


def test_propose_guard_reproposes_on_measurement_hyperparam_valueerror() -> None:
    clean = _clean_proposal()
    calls = {"n": 0}

    def propose() -> Proposal:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError(
                "hyperparam target_section 'seed_limit' is a FIXED audit-measurement parameter"
            )
        return clean

    runner = SimpleNamespace(propose=propose)
    result = rc.propose_with_guard(runner, max_attempts=5)
    assert result is clean
    assert calls["n"] == 2


def test_propose_guard_gives_up_after_m_attempts() -> None:
    calls = {"n": 0}

    def propose() -> Proposal:
        calls["n"] += 1
        raise _repetitive_error()

    runner = SimpleNamespace(propose=propose)
    result = rc.propose_with_guard(runner, max_attempts=4)
    assert result is None
    assert calls["n"] == 4  # exactly M attempts, no more


# ---------------------------------------------------------------------------
# SoT snapshot / restore round-trip
# ---------------------------------------------------------------------------


def test_snapshot_restore_round_trips_policies_and_baseline(
    campaign_state: dict[str, Path],
) -> None:
    policies_dir = campaign_state["policies_dir"]
    baseline = campaign_state["baseline"]
    (policies_dir / "hyperparam.json").write_text('{"reflection_depth": 3}', encoding="utf-8")
    (policies_dir / "tool-policy.json").write_text('{"a": "b"}', encoding="utf-8")
    (policies_dir / "few-shot-pool.jsonl").write_text('{"row": 1}\n', encoding="utf-8")
    baseline.write_text('{"fitness": 0.5}', encoding="utf-8")

    written = rc.snapshot_sot(campaign_state["snapshot"])
    assert len(written) == 4  # 3 policy files + baseline.json

    # Mutate the live SoT, then restore.
    (policies_dir / "hyperparam.json").write_text('{"reflection_depth": 5}', encoding="utf-8")
    baseline.write_text('{"fitness": 0.9}', encoding="utf-8")
    (policies_dir / "injected.json").write_text("{}", encoding="utf-8")

    restored = rc.restore_sot(campaign_state["snapshot"])
    assert (policies_dir / "hyperparam.json").read_text(
        encoding="utf-8"
    ) == '{"reflection_depth": 3}'
    assert baseline.read_text(encoding="utf-8") == '{"fitness": 0.5}'
    # The snapshot is the canonical set; restored covers exactly the 4 captured files.
    assert {p.name for p in restored} == {
        "hyperparam.json",
        "tool-policy.json",
        "few-shot-pool.jsonl",
        "baseline.json",
    }
    # Mirror semantics — the orphan file injected after the snapshot is DELETED,
    # so the next arm starts from an exact matched gen-0 state (Codex MCP #1).
    assert not (policies_dir / "injected.json").exists()


def test_restore_mirror_deletes_orphan_policy_files(
    campaign_state: dict[str, Path],
) -> None:
    policies_dir = campaign_state["policies_dir"]
    (policies_dir / "hyperparam.json").write_text("{}", encoding="utf-8")
    rc.snapshot_sot(campaign_state["snapshot"])
    # An earlier arm inserts a new policy file that gen-0 never had.
    (policies_dir / "wrapper-sections.json").write_text('{"x": "y"}', encoding="utf-8")
    rc.restore_sot(campaign_state["snapshot"])
    assert (policies_dir / "hyperparam.json").exists()
    assert not (policies_dir / "wrapper-sections.json").exists()


def test_restore_missing_snapshot_raises(campaign_state: dict[str, Path]) -> None:
    with pytest.raises(FileNotFoundError):
        rc.restore_sot(campaign_state["snapshot"] / "does-not-exist")


# ---------------------------------------------------------------------------
# degeneracy guard
# ---------------------------------------------------------------------------


def _fake_eval(*, status: str, samples: list[Any]) -> SimpleNamespace:
    return SimpleNamespace(status=status, samples=samples)


def _healthy_sample() -> SimpleNamespace:
    judge = SimpleNamespace(value={"safety": 3.0, "helpfulness": 2.0})
    return SimpleNamespace(scores={"audit_judge": judge})


@pytest.fixture
def fake_read_eval_log(monkeypatch: pytest.MonkeyPatch):
    """Install a fake ``inspect_ai.log.read_eval_log`` into ``sys.modules``.

    The degeneracy guard does ``from inspect_ai.log import read_eval_log`` lazily;
    ``inspect_ai`` lives behind the ``[audit]`` extra and may be absent in the
    base test env, so we inject a stub module that returns a caller-supplied eval
    object. Returns a setter the test calls with the eval to serve.
    """
    import sys
    import types

    served: dict[str, Any] = {}

    def _reader(_path: str) -> Any:
        return served["eval"]

    inspect_ai_mod = sys.modules.get("inspect_ai") or types.ModuleType("inspect_ai")
    log_mod = types.ModuleType("inspect_ai.log")
    log_mod.read_eval_log = _reader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "inspect_ai", inspect_ai_mod)
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log_mod)

    def _set(eval_obj: Any) -> None:
        served["eval"] = eval_obj

    return _set


def test_degeneracy_guard_passes_on_healthy_eval(
    campaign_state: dict[str, Path], fake_read_eval_log: Any
) -> None:
    (campaign_state["petri_logs"] / "run.eval").write_bytes(b"")
    fake_read_eval_log(_fake_eval(status="success", samples=[_healthy_sample()]))
    result = rc.degeneracy_guard(logs_dir=campaign_state["petri_logs"])
    assert result.ok
    assert "samples=1" in result.reason


def test_degeneracy_guard_halts_on_zero_sample_eval(
    campaign_state: dict[str, Path], fake_read_eval_log: Any
) -> None:
    (campaign_state["petri_logs"] / "run.eval").write_bytes(b"")
    fake_read_eval_log(_fake_eval(status="success", samples=[]))
    result = rc.degeneracy_guard(logs_dir=campaign_state["petri_logs"])
    assert not result.ok
    assert "0 samples" in result.reason


def test_degeneracy_guard_halts_on_zero_scored_dims(
    campaign_state: dict[str, Path], fake_read_eval_log: Any
) -> None:
    (campaign_state["petri_logs"] / "run.eval").write_bytes(b"")
    # A sample with no audit_judge score = 0 scored dims.
    blank = SimpleNamespace(scores={})
    fake_read_eval_log(_fake_eval(status="success", samples=[blank]))
    result = rc.degeneracy_guard(logs_dir=campaign_state["petri_logs"])
    assert not result.ok
    assert "0 scored dims" in result.reason


def test_degeneracy_guard_fallback_on_collapsed_stderr() -> None:
    # No eval log path + a collapsed between_seed_stderr → degenerate.
    signal = rc.CycleSignal(
        held_out_fitness=0.5,
        fitness=0.5,
        fitness_delta=0.0,
        promote_policy="gate",
        source="mutator",
        between_seed_stderr=0.001,
    )
    result = rc._degeneracy_guard_fallback(signal)
    assert not result.ok
    assert "degenerate" in result.reason


def test_degeneracy_guard_fallback_ok_with_healthy_stderr() -> None:
    signal = rc.CycleSignal(
        held_out_fitness=0.5,
        fitness=0.5,
        fitness_delta=0.0,
        promote_policy="gate",
        source="mutator",
        between_seed_stderr=0.08,
    )
    result = rc._degeneracy_guard_fallback(signal)
    assert result.ok


# ---------------------------------------------------------------------------
# gen-0 K-repeat baseline + noise band
# ---------------------------------------------------------------------------


def test_gen0_baseline_collects_k_held_out_and_computes_band(
    campaign_state: dict[str, Path],
) -> None:
    mutations = campaign_state["mutations"]
    synthetic_held = [0.50, 0.54, 0.52, 0.55, 0.51]
    calls = {"n": 0}

    def fake_train(*, env: dict[str, str], dry_run: bool) -> SimpleNamespace:
        # Each "subprocess" appends one synthetic manual attribution row.
        h = synthetic_held[calls["n"]]
        _write_attribution(mutations, held_out=h, fitness=h + 0.1, source="manual")
        calls["n"] += 1
        return SimpleNamespace(returncode=0)

    with rc.ProgressLog(campaign_state["progress"]) as progress:
        band = rc.run_gen0_baseline(
            k=5,
            dry_run=False,
            audit_max_samples=3,
            audit_max_connections=8,
            progress=progress,
            train_runner=fake_train,
        )

    assert calls["n"] == 5
    assert len(band.held_out_values) == 5
    assert band.held_out_values == tuple(synthetic_held)
    assert band.mean == pytest.approx(sum(synthetic_held) / 5)
    assert band.stderr is not None and band.stderr > 0.0


def test_compute_noise_band_single_value_zero_stderr() -> None:
    band = rc.compute_noise_band([0.5], [0.6], k=1)
    assert band.mean == pytest.approx(0.5)
    assert band.stderr == 0.0


def test_compute_noise_band_empty_is_none() -> None:
    band = rc.compute_noise_band([], [], k=3)
    assert band.mean is None
    assert band.stderr is None


# ---------------------------------------------------------------------------
# FITNESS_RESULT stdout parse + K-mean baseline (the core fix)
# ---------------------------------------------------------------------------


def _fitness_result_line(dim_means: dict[str, float], *, fitness: float = 0.7) -> str:
    return "FITNESS_RESULT: " + json.dumps(
        {"fitness": fitness, "audit_run_id": "abc", "dim_means": dim_means, "dim_stderr": {}}
    )


def test_parse_fitness_result_dims_extracts_dim_means() -> None:
    stdout = "noise\n" + _fitness_result_line({"safety": 2.0, "scenario_realism": 8.0}) + "\nmore\n"
    parsed = rc.parse_fitness_result_dims(stdout)
    assert parsed == {"safety": 2.0, "scenario_realism": 8.0}


def test_parse_fitness_result_dims_none_when_absent() -> None:
    assert rc.parse_fitness_result_dims("just logs, no sentinel\n") is None
    assert rc.parse_fitness_result_dims(None) is None
    # Non-numeric dim values are dropped; an all-bad payload yields None.
    bad = "FITNESS_RESULT: " + json.dumps({"dim_means": {"safety": "oops"}})
    assert rc.parse_fitness_result_dims(bad) is None


def test_parse_fitness_result_dims_drops_non_finite() -> None:
    # NaN / Infinity are not valid measurements; json emits them as bare tokens.
    bad = 'FITNESS_RESULT: {"dim_means": {"safety": NaN, "realism": Infinity, "ok": 3.0}}'
    assert rc.parse_fitness_result_dims(bad) == {"ok": 3.0}


def test_parse_fitness_result_dims_last_sentinel_wins_even_if_malformed() -> None:
    # An earlier VALID sentinel must NOT mask a later malformed one — the last
    # FITNESS_RESULT line is authoritative, so a trailing broken sentinel → None.
    stdout = _fitness_result_line({"safety": 2.0}) + "\nFITNESS_RESULT: {not json\n"
    assert rc.parse_fitness_result_dims(stdout) is None
    # And a later VALID sentinel overrides an earlier one.
    stdout2 = _fitness_result_line({"safety": 2.0}) + "\n" + _fitness_result_line({"safety": 9.0})
    assert rc.parse_fitness_result_dims(stdout2) == {"safety": 9.0}


def test_aggregate_dim_means_mean_and_stderr() -> None:
    measures = [
        {"safety": 2.0, "realism": 8.0},
        {"safety": 4.0, "realism": 8.0},
    ]
    mean_dims, stderr_dims, present = rc.aggregate_dim_means(measures)
    assert mean_dims["safety"] == pytest.approx(3.0)  # (2+4)/2
    assert mean_dims["realism"] == pytest.approx(8.0)
    # stderr = stdev([2,4]) / sqrt(2) = sqrt(2) / sqrt(2) = 1.0
    assert stderr_dims["safety"] == pytest.approx(1.0)
    assert stderr_dims["realism"] == pytest.approx(0.0)  # identical values
    assert present == {"safety": 2, "realism": 2}


def test_aggregate_dim_means_partial_coverage_averages_present_only() -> None:
    # 'extra' appears in only one of two measures → averaged over the present one.
    measures = [{"a": 1.0, "extra": 5.0}, {"a": 3.0}]
    mean_dims, stderr_dims, present = rc.aggregate_dim_means(measures)
    assert mean_dims["a"] == pytest.approx(2.0)
    assert mean_dims["extra"] == pytest.approx(5.0)  # only the one present value
    assert present == {"a": 2, "extra": 1}
    assert stderr_dims["extra"] == 0.0  # single observation → no band


def test_aggregate_dim_means_trims_high_low_outlier() -> None:
    # PR-GATE-RECIPE (2026-06-01) — K=5 ≥ 4 → drop the single highest (20) and
    # single lowest (0) repeats; average the middle three (4,5,6) → 5.0, NOT the
    # plain mean 7.0. present_count stays the ORIGINAL 5 (not the post-trim 3) so
    # the caller's partial-coverage check still compares against K.
    measures = [{"d": v} for v in (0.0, 4.0, 5.0, 6.0, 20.0)]
    mean_dims, stderr_dims, present = rc.aggregate_dim_means(measures)
    assert mean_dims["d"] == pytest.approx(5.0)  # trimmed mean of [4,5,6]
    assert mean_dims["d"] != pytest.approx(7.0)  # the plain (untrimmed) mean
    assert stderr_dims["d"] == pytest.approx(1.0 / 3**0.5)  # stdev([4,5,6])/sqrt(3)
    assert present == {"d": 5}


def test_aggregate_dim_means_no_trim_below_four() -> None:
    # K=3 < 4 → trimming would leave < 2 points; fall back to the plain mean.
    measures = [{"d": v} for v in (0.0, 5.0, 10.0)]
    mean_dims, _stderr, present = rc.aggregate_dim_means(measures)
    assert mean_dims["d"] == pytest.approx(5.0)  # plain mean of all three
    assert present == {"d": 3}


def test_write_kmean_baseline_overwrites_dims_preserving_schema(
    campaign_state: dict[str, Path],
) -> None:
    baseline = campaign_state["baseline"]
    # The bootstrap train.py run wrote baseline.json from a SINGLE lucky measure.
    baseline.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "session_id": "boot-1",
                "commit": "deadbeef",
                "ts_utc": "2026-05-31T00:00:00Z",
                "raw": {
                    "dim_means": {"safety": 8.0, "realism": 1.0},  # the lucky outlier
                    "dim_stderr": {"safety": 0.0, "realism": 0.0},
                    "sample_count": {"safety": 3},
                    "measurement_modality": {"safety": "transcript"},
                    "eval_archive": "boot.eval",
                    "rubric_version": "v3-22dim-PR0",
                    "fitness_stderr": 0.02,
                },
                "axes": {"admire_means": None, "bench_means": {"x": 1.0}},
            }
        ),
        encoding="utf-8",
    )
    wrote = rc.write_kmean_baseline(
        {"safety": 3.0, "realism": 7.0},
        {"safety": 1.0, "realism": 0.5},
        baseline_path=baseline,
    )
    assert wrote is True
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    # Only raw.dim_means + raw.dim_stderr overwritten with the K-aggregate.
    assert payload["raw"]["dim_means"] == {"safety": 3.0, "realism": 7.0}
    assert payload["raw"]["dim_stderr"] == {"safety": 1.0, "realism": 0.5}
    # Everything else preserved byte-for-byte (schema, provenance, axes).
    assert payload["schema_version"] == 2
    assert payload["session_id"] == "boot-1"
    assert payload["commit"] == "deadbeef"
    assert payload["raw"]["sample_count"] == {"safety": 3}
    assert payload["raw"]["measurement_modality"] == {"safety": "transcript"}
    assert payload["raw"]["eval_archive"] == "boot.eval"
    assert payload["raw"]["fitness_stderr"] == 0.02
    assert payload["axes"] == {"admire_means": None, "bench_means": {"x": 1.0}}


def test_write_kmean_baseline_no_file_returns_false(campaign_state: dict[str, Path]) -> None:
    # No bootstrap baseline.json on disk → nothing to patch.
    assert not campaign_state["baseline"].exists()
    assert rc.write_kmean_baseline({"safety": 3.0}, {"safety": 1.0}) is False


def test_write_kmean_baseline_empty_dims_returns_false(campaign_state: dict[str, Path]) -> None:
    campaign_state["baseline"].write_text('{"raw": {"dim_means": {}}}', encoding="utf-8")
    assert rc.write_kmean_baseline({}, {}) is False


def test_write_kmean_baseline_malformed_raw_returns_false(
    campaign_state: dict[str, Path],
) -> None:
    # A bootstrap baseline.json with no (or a non-dict) raw block is malformed —
    # the writer refuses to fabricate a raw block (preserve-only contract).
    baseline = campaign_state["baseline"]
    baseline.write_text('{"schema_version": 2, "raw": "not-a-dict"}', encoding="utf-8")
    assert (
        rc.write_kmean_baseline({"safety": 3.0}, {"safety": 1.0}, baseline_path=baseline) is False
    )
    # The malformed file is left untouched (no fabricated raw.dim_means).
    assert json.loads(baseline.read_text(encoding="utf-8")) == {
        "schema_version": 2,
        "raw": "not-a-dict",
    }
    # Missing raw block entirely → also False.
    baseline.write_text('{"schema_version": 2}', encoding="utf-8")
    assert (
        rc.write_kmean_baseline({"safety": 3.0}, {"safety": 1.0}, baseline_path=baseline) is False
    )


def test_gen0_baseline_sets_baseline_to_k_mean_dims(
    campaign_state: dict[str, Path],
) -> None:
    """The CORE fix: after the K-repeat, baseline.json's raw.dim_means equals the
    per-dim mean across the K measures' FITNESS_RESULT dims, and raw.dim_stderr
    the across-K per-dim sample stderr; the rest of the schema is preserved."""
    mutations = campaign_state["mutations"]
    baseline = campaign_state["baseline"]
    # The 1st (bootstrap) measure wrote baseline.json with its lucky-high dims +
    # the full schema. The K-mean must overwrite ONLY the two dim sub-fields.
    baseline.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "session_id": "boot",
                "raw": {
                    "dim_means": {"safety": 8.0, "realism": 2.0},
                    "dim_stderr": {},
                    "rubric_version": "v3-22dim-PR0",
                },
                "axes": {"bench_means": None},
            }
        ),
        encoding="utf-8",
    )
    # Three identical-scaffold measures with KNOWN, varying dims (the stochastic
    # Petri re-measure spread) → the gen-0 noise the fix is meant to capture.
    measure_dims = [
        {"safety": 2.0, "realism": 6.0},
        {"safety": 3.0, "realism": 7.0},
        {"safety": 4.0, "realism": 8.0},
    ]
    calls = {"n": 0}

    def fake_train(*, env: dict[str, str], dry_run: bool) -> SimpleNamespace:
        dims = measure_dims[calls["n"]]
        _write_attribution(mutations, held_out=0.5, fitness=0.6, source="manual")
        calls["n"] += 1
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line(dims))

    with rc.ProgressLog(campaign_state["progress"]) as progress:
        rc.run_gen0_baseline(
            k=3,
            dry_run=False,
            audit_max_samples=3,
            audit_max_connections=8,
            progress=progress,
            train_runner=fake_train,
        )

    payload = json.loads(baseline.read_text(encoding="utf-8"))
    # raw.dim_means = per-dim mean across the 3 measures.
    assert payload["raw"]["dim_means"]["safety"] == pytest.approx(3.0)  # (2+3+4)/3
    assert payload["raw"]["dim_means"]["realism"] == pytest.approx(7.0)  # (6+7+8)/3
    # raw.dim_stderr = across-K per-dim sample stderr (stdev/sqrt(3)).
    import statistics as _stats

    assert payload["raw"]["dim_stderr"]["safety"] == pytest.approx(
        _stats.stdev([2.0, 3.0, 4.0]) / (3**0.5)
    )
    # The rest of the schema is preserved (not the lucky bootstrap dims).
    assert payload["schema_version"] == 2
    assert payload["session_id"] == "boot"
    assert payload["raw"]["rubric_version"] == "v3-22dim-PR0"
    assert payload["axes"] == {"bench_means": None}


# ---------------------------------------------------------------------------
# arm loop — env + commit_enabled per arm; gate last
# ---------------------------------------------------------------------------


class _RecordingRunner:
    """A fake runner that records the env / commit_enabled it was built with and
    succeeds on propose + apply without any network."""

    def __init__(self, *, arm: str, env: dict[str, str], commit_enabled: bool) -> None:
        self.arm = arm
        self.env = env
        self.commit_enabled = commit_enabled
        self.applied: list[Proposal] = []

    def propose(self) -> Proposal:
        return _clean_proposal()

    def apply_proposal(self, proposal: Proposal) -> Mutation:
        self.applied.append(proposal)
        return proposal.mutation


def test_arm_loop_sets_promote_policy_and_seed_and_commit(
    campaign_state: dict[str, Path],
) -> None:
    # Prime a gen-0 snapshot so restore_sot succeeds.
    (campaign_state["policies_dir"] / "hyperparam.json").write_text("{}", encoding="utf-8")
    rc.snapshot_sot(campaign_state["snapshot"])

    built: list[_RecordingRunner] = []

    def factory(*, arm: str, env: dict[str, str], dry_run: bool) -> _RecordingRunner:
        runner = _RecordingRunner(arm=arm, env=dict(env), commit_enabled=(arm == "gate"))
        built.append(runner)
        return runner

    # A healthy signal so the guard never HALTs.
    _write_attribution(
        campaign_state["mutations"],
        held_out=0.5,
        fitness=0.5,
        delta=0.01,
        promote_policy="gate",
        source="mutator",
        between_seed_stderr=0.05,
    )

    def healthy_guard(_signal: rc.CycleSignal | None) -> rc.GuardResult:
        return rc.GuardResult(ok=True, reason="test ok")

    summaries: list[rc.ArmSummary] = []
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        for arm_index, arm in enumerate(("never", "random", "gate")):
            summaries.append(
                rc.run_arm(
                    arm=arm,
                    arm_index=arm_index,
                    n=2,
                    max_propose_attempts=8,
                    audit_max_samples=3,
                    audit_max_connections=8,
                    dry_run=False,
                    progress=progress,
                    snapshot_dir=campaign_state["snapshot"],
                    runner_factory=factory,
                    guard_fn=healthy_guard,
                )
            )

    # never arm: no seed, commit off.
    never_runner = built[0]
    assert never_runner.env["GEODE_PROMOTE_POLICY"] == "never"
    assert "GEODE_PROMOTE_POLICY_SEED" not in never_runner.env
    assert never_runner.commit_enabled is False

    # random arm (index 1): deterministic seed = base + 1, commit off.
    random_runner = built[2]  # built has 2 per arm (n=2); arm boundaries at 0/2/4
    assert random_runner.env["GEODE_PROMOTE_POLICY"] == "random"
    assert random_runner.env["GEODE_PROMOTE_POLICY_SEED"] == str(rc.DEFAULT_RANDOM_SEED_BASE + 1)
    assert random_runner.commit_enabled is False

    # gate arm (index 2, LAST): commit ON.
    gate_runner = built[4]
    assert gate_runner.env["GEODE_PROMOTE_POLICY"] == "gate"
    assert gate_runner.commit_enabled is True

    # gate ran last.
    assert [s.arm for s in summaries] == ["never", "random", "gate"]


def test_arm_loop_halts_on_degenerate_guard(campaign_state: dict[str, Path]) -> None:
    (campaign_state["policies_dir"] / "hyperparam.json").write_text("{}", encoding="utf-8")
    rc.snapshot_sot(campaign_state["snapshot"])
    _write_attribution(
        campaign_state["mutations"], held_out=0.5, fitness=0.5, delta=0.0, source="mutator"
    )

    def factory(*, arm: str, env: dict[str, str], dry_run: bool) -> _RecordingRunner:
        return _RecordingRunner(arm=arm, env=dict(env), commit_enabled=(arm == "gate"))

    def degenerate_guard(_signal: rc.CycleSignal | None) -> rc.GuardResult:
        return rc.GuardResult(ok=False, reason="fake degenerate")

    with rc.ProgressLog(campaign_state["progress"]) as progress:
        summary = rc.run_arm(
            arm="never",
            arm_index=0,
            n=10,
            max_propose_attempts=8,
            audit_max_samples=3,
            audit_max_connections=8,
            dry_run=False,
            progress=progress,
            snapshot_dir=campaign_state["snapshot"],
            runner_factory=factory,
            guard_fn=degenerate_guard,
        )
    assert summary.halted is True
    assert summary.cycles_run == 1  # halted after the first cycle


def test_arm_loop_skips_cycle_when_propose_exhausted(
    campaign_state: dict[str, Path],
) -> None:
    (campaign_state["policies_dir"] / "hyperparam.json").write_text("{}", encoding="utf-8")
    rc.snapshot_sot(campaign_state["snapshot"])

    class _AlwaysRepetitiveRunner:
        def __init__(self) -> None:
            self.applied = 0

        def propose(self) -> Proposal:
            raise _repetitive_error()

        def apply_proposal(self, proposal: Proposal) -> Mutation:  # pragma: no cover
            self.applied += 1
            return proposal.mutation

    def factory(*, arm: str, env: dict[str, str], dry_run: bool) -> _AlwaysRepetitiveRunner:
        return _AlwaysRepetitiveRunner()

    with rc.ProgressLog(campaign_state["progress"]) as progress:
        summary = rc.run_arm(
            arm="never",
            arm_index=0,
            n=2,
            max_propose_attempts=3,
            audit_max_samples=3,
            audit_max_connections=8,
            dry_run=False,
            progress=progress,
            snapshot_dir=campaign_state["snapshot"],
            runner_factory=factory,
            guard_fn=lambda _s: rc.GuardResult(ok=True, reason="ok"),
        )
    assert summary.cycles_run == 0
    assert summary.cycles_skipped == 2


# ---------------------------------------------------------------------------
# env setup
# ---------------------------------------------------------------------------


def test_build_campaign_env_sets_fixed_vars() -> None:
    env = rc.build_campaign_env(
        promote_policy="random",
        promote_policy_seed=424201,
        audit_max_samples=3,
        audit_max_connections=8,
        base_env={"ANTHROPIC_API_KEY": "from-operator-shell"},
    )
    assert env["ANTHROPIC_API_KEY"] == "from-operator-shell"
    assert env["GEODE_CODEX_OAUTH_POLL_DISABLED"] == "1"
    assert env["AUTORESEARCH_SEED_SELECT"] == str(rc.CYCLE_INPUT_POOL)
    assert env["GEODE_HELD_OUT_BENCH"] == str(rc.HELD_OUT_BENCH)
    assert env["GEODE_AUDIT_MAX_SAMPLES"] == "3"
    assert env["GEODE_AUDIT_MAX_CONNECTIONS"] == "8"
    assert env["GEODE_PROMOTE_POLICY"] == "random"
    assert env["GEODE_PROMOTE_POLICY_SEED"] == "424201"


def test_build_campaign_env_omits_arm_when_none() -> None:
    env = rc.build_campaign_env(base_env={})
    assert "GEODE_PROMOTE_POLICY" not in env
    assert "GEODE_PROMOTE_POLICY_SEED" not in env


def test_build_campaign_env_clears_stale_arm_env(campaign_state: dict[str, Path]) -> None:
    # A stale arm policy + seed (+ AUTORESEARCH_* aliases) in the base env must be
    # REMOVED when the caller passes None — gen-0 / gate / never inherit no arm.
    stale = {
        "GEODE_PROMOTE_POLICY": "random",
        "GEODE_PROMOTE_POLICY_SEED": "999",
        "AUTORESEARCH_PROMOTE_POLICY": "random",
        "AUTORESEARCH_PROMOTE_POLICY_SEED": "999",
    }
    env = rc.build_campaign_env(base_env=stale)
    assert "GEODE_PROMOTE_POLICY" not in env
    assert "GEODE_PROMOTE_POLICY_SEED" not in env
    assert "AUTORESEARCH_PROMOTE_POLICY" not in env
    assert "AUTORESEARCH_PROMOTE_POLICY_SEED" not in env
    # gate arm must not inherit the stale seed.
    env_gate = rc.build_campaign_env(promote_policy="gate", base_env=stale)
    assert env_gate["GEODE_PROMOTE_POLICY"] == "gate"
    assert "GEODE_PROMOTE_POLICY_SEED" not in env_gate


# ---------------------------------------------------------------------------
# build_campaign_env — targeted-dim auto-resolution (PR-CAMPAIGN-TARGET-DIM)
# ---------------------------------------------------------------------------


def _write_seed_with_target_dims(pool_dir: Path, name: str, target_dims: list[str]) -> None:
    """Write a minimal seed ``.md`` with a ``target_dims`` YAML frontmatter block."""
    dims_yaml = "\n".join(f"  - {d}" for d in target_dims)
    pool_dir.mkdir(parents=True, exist_ok=True)
    (pool_dir / name).write_text(
        f"---\ntarget_dims:\n{dims_yaml}\n---\n\nseed body\n",
        encoding="utf-8",
    )


def test_build_campaign_env_auto_resolves_target_dim_from_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A CYCLE_INPUT_POOL whose seeds declare ``target_dims: [broken_tool_use]``
    # auto-resolves GEODE_SIL_EXPECTED_DIM by default — gate parity with the
    # inner-loop runner. The dim is POOL-DERIVED (the seed's frontmatter), never
    # a hardcoded constant.
    pool = tmp_path / "cycle-input"
    _write_seed_with_target_dims(pool, "s1.md", ["broken_tool_use"])
    _write_seed_with_target_dims(pool, "s2.md", ["broken_tool_use"])
    monkeypatch.setattr(rc, "CYCLE_INPUT_POOL", pool)

    env = rc.build_campaign_env(base_env={})

    assert json.loads(env["GEODE_SIL_EXPECTED_DIM"]) == {"broken_tool_use": 1.0}


def test_build_campaign_env_unions_multiple_target_dims_from_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Distinct dims across seeds are unioned (value is the nominal 1.0 hint; only
    # the KEYS feed train.py::_resolve_targeted_dims).
    pool = tmp_path / "cycle-input"
    _write_seed_with_target_dims(pool, "s1.md", ["broken_tool_use"])
    _write_seed_with_target_dims(pool, "s2.md", ["sycophancy"])
    monkeypatch.setattr(rc, "CYCLE_INPUT_POOL", pool)

    env = rc.build_campaign_env(base_env={})

    assert json.loads(env["GEODE_SIL_EXPECTED_DIM"]) == {
        "broken_tool_use": 1.0,
        "sycophancy": 1.0,
    }


def test_build_campaign_env_respects_explicit_expected_dim_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An operator-set GEODE_SIL_EXPECTED_DIM in base_env is RESPECTED, never
    # overwritten by the pool-derived value.
    pool = tmp_path / "cycle-input"
    _write_seed_with_target_dims(pool, "s1.md", ["broken_tool_use"])
    monkeypatch.setattr(rc, "CYCLE_INPUT_POOL", pool)

    override = json.dumps({"sycophancy": 0.3})
    env = rc.build_campaign_env(base_env={"GEODE_SIL_EXPECTED_DIM": override})

    assert env["GEODE_SIL_EXPECTED_DIM"] == override


def test_build_campaign_env_empty_pool_leaves_expected_dim_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty pool (no seeds) yields no target dims → GEODE_SIL_EXPECTED_DIM is
    # left UNSET → train.py falls back to the v1 full-aggregate gate.
    pool = tmp_path / "cycle-input"
    pool.mkdir(parents=True)
    monkeypatch.setattr(rc, "CYCLE_INPUT_POOL", pool)

    env = rc.build_campaign_env(base_env={})

    assert "GEODE_SIL_EXPECTED_DIM" not in env


def test_build_campaign_env_no_target_dims_pool_leaves_expected_dim_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seeds present but none declaring target_dims (or malformed frontmatter) →
    # no dims → GEODE_SIL_EXPECTED_DIM absent (graceful full-aggregate fallback).
    pool = tmp_path / "cycle-input"
    pool.mkdir(parents=True)
    (pool / "no_front.md").write_text("just a body, no frontmatter\n", encoding="utf-8")
    (pool / "empty_dims.md").write_text("---\nname: x\n---\nbody\n", encoding="utf-8")
    monkeypatch.setattr(rc, "CYCLE_INPUT_POOL", pool)

    env = rc.build_campaign_env(base_env={})

    assert "GEODE_SIL_EXPECTED_DIM" not in env


def test_build_campaign_env_missing_pool_dir_leaves_expected_dim_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A missing pool dir is graceful — no raise, GEODE_SIL_EXPECTED_DIM unset.
    monkeypatch.setattr(rc, "CYCLE_INPUT_POOL", tmp_path / "does-not-exist")

    env = rc.build_campaign_env(base_env={})

    assert "GEODE_SIL_EXPECTED_DIM" not in env


def test_build_campaign_env_respects_blank_explicit_expected_dim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A deliberately BLANK GEODE_SIL_EXPECTED_DIM in base_env is a valid operator
    # override (train.py::_resolve_targeted_dims reads "".strip() as "no targeting
    # → full aggregate"). The mere PRESENCE of the key means the operator set it,
    # so the pool-derived value must NOT overwrite it.
    pool = tmp_path / "cycle-input"
    _write_seed_with_target_dims(pool, "s1.md", ["broken_tool_use"])
    monkeypatch.setattr(rc, "CYCLE_INPUT_POOL", pool)

    env = rc.build_campaign_env(base_env={"GEODE_SIL_EXPECTED_DIM": ""})

    assert env["GEODE_SIL_EXPECTED_DIM"] == ""


def test_read_latest_attribution_min_rows_blocks_stale(campaign_state: dict[str, Path]) -> None:
    mutations = campaign_state["mutations"]
    _write_attribution(mutations, held_out=0.5, fitness=0.5, source="manual")
    before = rc.count_attribution_rows(mutations)
    assert before == 1
    # No new row appended → min_rows guard returns None (no stale-row reuse).
    assert rc.read_latest_attribution(mutations, min_rows=before) is None
    # A new row appended → the guard lets it through.
    _write_attribution(mutations, held_out=0.6, fitness=0.6, source="manual")
    signal = rc.read_latest_attribution(mutations, min_rows=before)
    assert signal is not None
    assert signal.held_out_fitness == pytest.approx(0.6)


def test_campaign_halt_stops_remaining_arms(campaign_state: dict[str, Path]) -> None:
    (campaign_state["policies_dir"] / "hyperparam.json").write_text("{}", encoding="utf-8")
    _write_attribution(
        campaign_state["mutations"], held_out=0.5, fitness=0.5, delta=0.0, source="mutator"
    )

    def factory(*, arm: str, env: dict[str, str], dry_run: bool) -> _RecordingRunner:
        return _RecordingRunner(arm=arm, env=dict(env), commit_enabled=(arm == "gate"))

    def degenerate_guard(_signal: rc.CycleSignal | None) -> rc.GuardResult:
        return rc.GuardResult(ok=False, reason="fake degenerate")

    result = rc.run_campaign(
        n=3,
        k=0,
        arms=("never", "random", "gate"),
        dry_run=False,
        progress_path=campaign_state["progress"],
        snapshot_dir=campaign_state["snapshot"],
        train_runner=lambda **_kw: SimpleNamespace(returncode=0),
        runner_factory=factory,
        guard_fn=degenerate_guard,
    )
    # The first arm halts → the campaign stops; only ONE arm summary exists.
    assert result["halted"] is True
    assert len(result["arm_summaries"]) == 1
    assert result["arm_summaries"][0].arm == "never"


# ---------------------------------------------------------------------------
# end-to-end dry-run smoke (no PAYG / no network)
# ---------------------------------------------------------------------------


def test_dry_run_end_to_end_smoke(
    campaign_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole campaign runs under --dry-run with synthetic boundaries: the
    train.py subprocess is stubbed (no network) and the offline runner factory
    is stubbed so no mutator LLM call fires."""
    (campaign_state["policies_dir"] / "hyperparam.json").write_text(
        '{"reflection_depth": 3}', encoding="utf-8"
    )
    mutations = campaign_state["mutations"]

    def fake_train(*, env: dict[str, str], dry_run: bool) -> SimpleNamespace:
        assert dry_run is True  # smoke must pass dry_run through
        _write_attribution(mutations, held_out=0.5, fitness=0.6, source="manual")
        return SimpleNamespace(returncode=0)

    # Offline runner factory — never touches the network.
    def factory(*, arm: str, env: dict[str, str], dry_run: bool) -> _RecordingRunner:
        assert dry_run is True
        return _RecordingRunner(arm=arm, env=dict(env), commit_enabled=False)

    result = rc.run_campaign(
        n=1,
        k=1,
        arms=("never", "random", "gate"),
        dry_run=True,
        progress_path=campaign_state["progress"],
        snapshot_dir=campaign_state["snapshot"],
        train_runner=fake_train,
        runner_factory=factory,
    )
    band = result["noise_band"]
    assert band.k == 1
    assert band.mean == pytest.approx(0.5)
    assert [s.arm for s in result["arm_summaries"]] == ["never", "random", "gate"]
    # Snapshot was written (1 policy file + baseline.json if present).
    assert result["snapshot_files"]
    # Progress log was flushed to disk.
    assert campaign_state["progress"].exists()
    assert "campaign complete" in campaign_state["progress"].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# inspect-cache purge — real campaign purges, --dry-run does NOT
# ---------------------------------------------------------------------------


def test_real_campaign_purges_inspect_cache(
    campaign_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real (non-dry-run) campaign calls purge_inspect_cache at start so the K
    gen-0 measures + cycle audits are independent re-measures, not cache hits."""
    import plugins.petri_audit.runner as petri_runner

    calls = {"n": 0}

    def fake_purge() -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(petri_runner, "purge_inspect_cache", fake_purge)
    (campaign_state["policies_dir"] / "hyperparam.json").write_text("{}", encoding="utf-8")

    def factory(*, arm: str, env: dict[str, str], dry_run: bool) -> _RecordingRunner:
        return _RecordingRunner(arm=arm, env=dict(env), commit_enabled=(arm == "gate"))

    rc.run_campaign(
        n=1,
        k=0,
        arms=("never",),
        dry_run=False,  # real campaign
        progress_path=campaign_state["progress"],
        snapshot_dir=campaign_state["snapshot"],
        train_runner=lambda **_kw: SimpleNamespace(returncode=0, stdout=""),
        runner_factory=factory,
        guard_fn=lambda _s: rc.GuardResult(ok=True, reason="ok"),
    )
    assert calls["n"] == 1
    assert "inspect cache purge: ran at real-campaign start" in campaign_state[
        "progress"
    ].read_text(encoding="utf-8")


def test_dry_run_campaign_does_not_purge_inspect_cache(
    campaign_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run never touches the trajectory cache (synthetic audits)."""
    import plugins.petri_audit.runner as petri_runner

    calls = {"n": 0}

    def fake_purge() -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr(petri_runner, "purge_inspect_cache", fake_purge)
    (campaign_state["policies_dir"] / "hyperparam.json").write_text("{}", encoding="utf-8")

    def factory(*, arm: str, env: dict[str, str], dry_run: bool) -> _RecordingRunner:
        return _RecordingRunner(arm=arm, env=dict(env), commit_enabled=False)

    rc.run_campaign(
        n=1,
        k=1,
        arms=("never",),
        dry_run=True,
        progress_path=campaign_state["progress"],
        snapshot_dir=campaign_state["snapshot"],
        train_runner=lambda **_kw: SimpleNamespace(returncode=0, stdout=""),
        runner_factory=factory,
    )
    assert calls["n"] == 0
    assert "inspect cache purge" not in campaign_state["progress"].read_text(encoding="utf-8")


def test_run_campaign_rejects_unknown_arm(campaign_state: dict[str, Path]) -> None:
    with pytest.raises(ValueError, match="unknown arm"):
        rc.run_campaign(
            arms=("never", "bogus"),
            dry_run=True,
            progress_path=campaign_state["progress"],
            snapshot_dir=campaign_state["snapshot"],
        )


def test_read_latest_attribution_picks_newest(campaign_state: dict[str, Path]) -> None:
    mutations = campaign_state["mutations"]
    _write_attribution(mutations, held_out=0.40, fitness=0.41, source="manual")
    _write_attribution(
        mutations, held_out=0.55, fitness=0.56, delta=0.02, promote_policy="gate", source="mutator"
    )
    signal = rc.read_latest_attribution(mutations)
    assert signal is not None
    assert signal.held_out_fitness == pytest.approx(0.55)
    assert signal.fitness == pytest.approx(0.56)
    assert signal.promote_policy == "gate"
    assert signal.source == "mutator"


def test_read_latest_attribution_none_when_absent(campaign_state: dict[str, Path]) -> None:
    assert rc.read_latest_attribution(campaign_state["mutations"]) is None


# ---------------------------------------------------------------------------
# Relocation regression — real subprocess dry-run end-to-end
# ---------------------------------------------------------------------------


def test_campaign_dry_run_via_real_subprocess_completes() -> None:
    """``python -m core.self_improving.campaign --dry-run`` runs end-to-end green.

    PR-SELF-IMPROVING-UMBRELLA (2026-05-31) relocated the campaign driver +
    audit runner under ``core.self_improving``. This test exercises the REAL
    moved import wiring + the ``-m core.self_improving.train`` spawn path the
    way the operator runs it — NOT the mocked-subprocess smoke
    (``test_dry_run_end_to_end_smoke``). It is the "logic didn't break" gate:
    a future move that orphans an import or breaks the
    ``campaign → -m core.self_improving.train`` spawn fails here, in the normal
    ``not live`` suite, with NO network / PAYG spend (``--dry-run`` synthesises
    every audit). The campaign writes only to the repo's real
    ``state/autoresearch`` log files in append mode, which is the same
    behaviour as the operator dry-run; it never promotes (dry-run skips the
    baseline rewrite + git commit).
    """
    proc = subprocess.run(  # noqa: S603 — argv is constant, no shell
        [
            sys.executable,
            "-m",
            "core.self_improving.campaign",
            "--dry-run",
            "--n",
            "1",
            "--arms",
            "never,random,gate",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"campaign dry-run exited {proc.returncode} — the moved import wiring or "
        f"the '-m core.self_improving.train' spawn regressed.\n"
        f"stdout tail:\n{proc.stdout[-2000:]}\n"
        f"stderr tail:\n{proc.stderr[-2000:]}"
    )
    combined = proc.stdout + proc.stderr
    assert "campaign complete" in combined, (
        "campaign dry-run did not reach 'campaign complete' — orchestration "
        f"halted early.\nstdout tail:\n{proc.stdout[-2000:]}\n"
        f"stderr tail:\n{proc.stderr[-2000:]}"
    )


# ---------------------------------------------------------------------------
# S3 parallel + S5 stateless — async orchestration with per-worker state
# isolation (PR-ASYNC-FIRST, 2026-06-03)
# ---------------------------------------------------------------------------


def _make_gen0_snapshot(campaign_state: dict[str, Path]) -> Path:
    """Stage a frozen gen-0 snapshot (policies + baseline.json) the async
    isolated workers seed from."""
    policies_dir = campaign_state["policies_dir"]
    (policies_dir / "hyperparam.json").write_text('{"reflection_depth": 3}', encoding="utf-8")
    campaign_state["baseline"].write_text(
        json.dumps({"schema_version": 3, "raw": {"dim_means": {"safety": 9.0}, "dim_stderr": {}}}),
        encoding="utf-8",
    )
    rc.snapshot_sot(campaign_state["snapshot"])
    return campaign_state["snapshot"]


def _fake_async_runner(
    *, dim_per_index: dict[int, dict[str, float]], held_out_per_index: dict[int, float]
) -> Any:
    """Build a fake async runner ``(env, dry_run, per_audit_timeout) -> CompletedProcess``.

    It records each worker's ``GEODE_STATE_ROOT`` (so the test asserts isolation),
    writes a synthetic ``kind="attribution"`` row into THAT worker's isolated
    ``mutations.jsonl``, and emits a ``FITNESS_RESULT`` stdout line — proving the
    gather + per-worker read-back + aggregate wiring with NO real audit.
    """
    seen_roots: list[str] = []

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        state_root = Path(env["GEODE_STATE_ROOT"])
        seen_roots.append(env["GEODE_STATE_ROOT"])
        # Map the worker's state-root to its 1-based index (w1, w2, ...).
        idx = int(state_root.name.removeprefix("w"))
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(
            mutations,
            held_out=held_out_per_index.get(idx),
            fitness=(held_out_per_index.get(idx) or 0.0) + 0.1,
            source="manual",
        )
        stdout = _fitness_result_line(dim_per_index.get(idx, {}))
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    runner.seen_roots = seen_roots  # type: ignore[attr-defined]
    return runner


def test_gen0_async_gathers_k_workers_and_writes_kmean_baseline(
    campaign_state: dict[str, Path],
) -> None:
    _make_gen0_snapshot(campaign_state)
    runner = _fake_async_runner(
        dim_per_index={
            1: {"safety": 2.0},
            2: {"safety": 3.0},
            3: {"safety": 4.0},
        },
        held_out_per_index={1: 0.50, 2: 0.52, 3: 0.54},
    )
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        band = asyncio.run(
            rc.run_gen0_baseline_async(
                k=3,
                dry_run=False,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
            )
        )
    # All 3 path-independent replicates gathered + their held-out values collected.
    assert len(band.held_out_values) == 3
    assert band.mean == pytest.approx((0.50 + 0.52 + 0.54) / 3)
    # baseline.json's raw.dim_means rewritten to the K-mean (2+3+4)/3 = 3.0.
    payload = json.loads(campaign_state["baseline"].read_text(encoding="utf-8"))
    assert payload["raw"]["dim_means"]["safety"] == pytest.approx(3.0)
    # Per-worker STATE_ROOT is DISTINCT (the isolation invariant: no shared root).
    roots = runner.seen_roots  # type: ignore[attr-defined]
    assert len(roots) == 3
    assert len(set(roots)) == 3, f"workers must have distinct GEODE_STATE_ROOT, got {roots}"


def test_gen0_async_drops_failed_worker_without_truncating_silently(
    campaign_state: dict[str, Path],
) -> None:
    _make_gen0_snapshot(campaign_state)

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        state_root = Path(env["GEODE_STATE_ROOT"])
        idx = int(state_root.name.removeprefix("w"))
        if idx == 2:
            # Worker 2 "fails" (non-zero exit) — must be dropped, not crash the gather.
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(mutations, held_out=0.5, fitness=0.6, source="manual")
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line({"safety": 3.0}))

    with rc.ProgressLog(campaign_state["progress"]) as progress:
        band = asyncio.run(
            rc.run_gen0_baseline_async(
                k=3,
                dry_run=False,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
            )
        )
    # Only the 2 surviving workers contribute (the failed one is filtered, logged).
    assert len(band.held_out_values) == 2
    log_text = campaign_state["progress"].read_text(encoding="utf-8")
    assert "DROPPED worker w2" in log_text


def test_gen0_async_dry_run_skips_baseline_rewrite(
    campaign_state: dict[str, Path],
) -> None:
    _make_gen0_snapshot(campaign_state)
    before = campaign_state["baseline"].read_text(encoding="utf-8")
    runner = _fake_async_runner(
        dim_per_index={1: {"safety": 2.0}, 2: {"safety": 8.0}},
        held_out_per_index={1: 0.5, 2: 0.5},
    )
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_gen0_baseline_async(
                k=2,
                dry_run=True,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
            )
        )
    # dry-run must leave baseline.json byte-identical (no synthetic freeze).
    assert campaign_state["baseline"].read_text(encoding="utf-8") == before


def test_control_arm_async_gathers_n_cycles_and_aggregates_floor(
    campaign_state: dict[str, Path],
) -> None:
    _make_gen0_snapshot(campaign_state)
    seen_policies: list[str | None] = []

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        seen_policies.append(env.get("GEODE_PROMOTE_POLICY"))
        state_root = Path(env["GEODE_STATE_ROOT"])
        idx = int(state_root.name.removeprefix("w"))
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(
            mutations, held_out=0.40 + idx * 0.01, fitness=0.41 + idx * 0.01, source="manual"
        )
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line({"safety": 3.0}))

    with rc.ProgressLog(campaign_state["progress"]) as progress:
        floor = asyncio.run(
            rc.run_control_arm_async(
                arm="never",
                arm_index=0,
                n=4,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
            )
        )
    assert floor.cycles_ok == 4
    assert floor.cycles_dropped == 0
    assert floor.held_out_band.mean is not None
    # Every cycle ran the 'never' arm against the frozen baseline.
    assert seen_policies == ["never"] * 4


def test_control_arm_async_refuses_gate_arm(
    campaign_state: dict[str, Path],
) -> None:
    _make_gen0_snapshot(campaign_state)
    with (
        rc.ProgressLog(campaign_state["progress"]) as progress,
        pytest.raises(ValueError, match="path-dependent"),
    ):
        asyncio.run(
            rc.run_control_arm_async(
                arm="gate",
                arm_index=2,
                n=2,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
            )
        )


def test_control_arm_async_random_uses_distinct_per_cycle_seeds(
    campaign_state: dict[str, Path],
) -> None:
    _make_gen0_snapshot(campaign_state)
    seen_seeds: list[str | None] = []

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        seen_seeds.append(env.get("GEODE_PROMOTE_POLICY_SEED"))
        state_root = Path(env["GEODE_STATE_ROOT"])
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(mutations, held_out=0.5, fitness=0.6, source="manual")
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line({"safety": 3.0}))

    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_control_arm_async(
                arm="random",
                arm_index=1,
                n=3,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
            )
        )
    # random arm: every cycle gets a distinct deterministic seed (reproducible).
    assert len(seen_seeds) == 3
    assert all(s is not None for s in seen_seeds)
    assert len(set(seen_seeds)) == 3, f"random cycles must have distinct seeds, got {seen_seeds}"


def test_seed_isolated_state_root_copies_policies_and_baseline_not_mutations(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    _make_gen0_snapshot(campaign_state)
    # Seed the production mutations.jsonl with a stale row that MUST NOT leak in.
    _write_attribution(campaign_state["mutations"], held_out=0.99, fitness=0.99, source="manual")
    worker_root = tmp_path / "w1"
    rc._seed_isolated_state_root(worker_root, campaign_state["snapshot"])
    worker_state = worker_root / "autoresearch"
    assert (worker_state / "policies" / "hyperparam.json").exists()
    assert (worker_state / "baseline.json").exists()
    # mutations.jsonl is deliberately NOT seeded — the worker's ledger starts empty
    # so the row it appends is unambiguously its own (no cross-worker stale reuse).
    assert not (worker_state / "mutations.jsonl").exists()


def test_seed_isolated_state_root_missing_snapshot_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="snapshot dir"):
        rc._seed_isolated_state_root(tmp_path / "w1", tmp_path / "nonexistent-snapshot")


def test_build_worker_env_sets_isolated_state_root_and_arm(tmp_path: Path) -> None:
    worker_root = tmp_path / "w2"
    env = rc._build_worker_env(
        worker_root,
        promote_policy="random",
        promote_policy_seed=777,
        audit_max_samples=3,
        audit_max_connections=8,
    )
    assert env["GEODE_STATE_ROOT"] == str(worker_root)
    assert env["GEODE_PROMOTE_POLICY"] == "random"
    assert env["GEODE_PROMOTE_POLICY_SEED"] == "777"
    # The PAYG + seed-pool campaign env is layered in too.
    assert env["GEODE_CODEX_OAUTH_POLL_DISABLED"] == "1"
    # S6 — when no transcript path / worker id is supplied, the isolation env vars
    # are ABSENT (the worker writes the home-dir transcript — sequential default).
    assert "GEODE_RUN_TRANSCRIPT_PATH" not in env
    assert "GEODE_RUN_WORKER_ID" not in env


def test_build_worker_env_sets_isolated_transcript_path_and_worker_id(tmp_path: Path) -> None:
    """S6 — supplying ``transcript_path`` / ``worker_id`` exports the two env vars
    the worker's ``_emit_journal`` reads to isolate + attribute its transcript."""
    worker_root = tmp_path / "w3"
    transcript = worker_root / "transcript.jsonl"
    env = rc._build_worker_env(
        worker_root,
        promote_policy="never",
        promote_policy_seed=None,
        audit_max_samples=3,
        audit_max_connections=8,
        transcript_path=transcript,
        worker_id="never-w3",
    )
    assert env["GEODE_RUN_TRANSCRIPT_PATH"] == str(transcript)
    assert env["GEODE_RUN_WORKER_ID"] == "never-w3"


def test_spawn_train_subprocess_async_timeout_kills_and_returns_minus_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real :func:`_spawn_train_subprocess_async` must kill + reap a child that
    overruns the tight ``per_audit_timeout`` and return ``returncode=-1`` so the
    aggregator drops it (never a hung gather). We swap the argv it builds for a
    30s sleeper via a patched ``sys.executable -c`` so the timeout branch fires
    deterministically without spawning the heavy real ``train.py``."""
    # Patch create_subprocess_exec so the helper spawns a long sleeper instead of
    # the real train module — the timeout + kill + reap logic is what we test.
    real_exec = asyncio.create_subprocess_exec

    async def sleeper_exec(*_argv: Any, **kwargs: Any) -> Any:
        # Forward ``start_new_session`` so the sleeper is its OWN process-group leader
        # exactly like production — otherwise it would share the pytest group and the
        # timeout-branch ``killpg`` would SIGKILL the test runner itself.
        return await real_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            start_new_session=kwargs.get("start_new_session", False),
        )

    monkeypatch.setattr(rc.asyncio, "create_subprocess_exec", sleeper_exec)
    result = asyncio.run(
        rc._spawn_train_subprocess_async(
            env={**os.environ, "GEODE_STATE_ROOT": str(tmp_path / "unused")},
            dry_run=False,
            per_audit_timeout=0.1,
        )
    )
    assert result.returncode == -1
    assert "timed out" in result.stderr


# ---------------------------------------------------------------------------
# S4 — resume checkpoint (crash-resumable path-independent workers,
# idempotent K-mean baseline write). PR-ASYNC-FIRST, 2026-06-03.
# ---------------------------------------------------------------------------


def _counting_async_runner(*, ran: list[int], fail_indices: set[int] | None = None) -> Any:
    """A fake async runner that RECORDS which worker indices it actually ran.

    Lets a resume test assert that the second run re-ran ONLY the missing workers
    (``ran`` holds exactly the pending indices), writes a synthetic attribution row
    + FITNESS_RESULT for the run workers, and optionally fails a chosen index.
    """
    fails = fail_indices or set()

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        state_root = Path(env["GEODE_STATE_ROOT"])
        idx = int(state_root.name.removeprefix("w"))
        ran.append(idx)
        if idx in fails:
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(mutations, held_out=0.50 + idx * 0.01, fitness=0.6, source="manual")
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line({"safety": float(idx)}))

    return runner


def test_run_checkpoint_disabled_is_a_no_op(tmp_path: Path) -> None:
    """A ``run_id=None`` checkpoint short-circuits every method — no file, no
    completed set, never idempotent (the pre-S4 behaviour is preserved)."""
    ckpt = rc.RunCheckpoint(run_id=None, runs_dir=tmp_path)
    assert not ckpt.enabled
    assert ckpt.completed_indices(rc.GEN0_CHECKPOINT_GROUP) == set()
    assert ckpt.resumed_outcomes(rc.GEN0_CHECKPOINT_GROUP) == []
    assert ckpt.kmean_already_written(rc.GEN0_CHECKPOINT_GROUP) is False
    outcome = rc.WorkerOutcome(
        index=1, ok=True, returncode=0, dim_means={"safety": 3.0}, signal=None, reason="ok"
    )
    ckpt.record_completed(rc.GEN0_CHECKPOINT_GROUP, [outcome])
    ckpt.mark_kmean_written(rc.GEN0_CHECKPOINT_GROUP)
    # Nothing was persisted — a disabled checkpoint never writes a marker file.
    assert list(tmp_path.glob("*.json")) == []


def test_run_checkpoint_round_trips_completed_workers(tmp_path: Path) -> None:
    """``record_completed`` persists ok workers; a fresh ``load`` recovers them as
    the same indices + dims + floor signal, and DROPS the failed ones."""
    ckpt = rc.RunCheckpoint(run_id="run-xyz", runs_dir=tmp_path)
    ok = rc.WorkerOutcome(
        index=2,
        ok=True,
        returncode=0,
        dim_means={"safety": 4.0},
        signal=rc.CycleSignal(
            held_out_fitness=0.55,
            fitness=0.6,
            fitness_delta=None,
            promote_policy=None,
            source=None,
            between_seed_stderr=None,
        ),
        reason="ok",
    )
    failed = rc.WorkerOutcome(
        index=3, ok=False, returncode=1, dim_means={}, signal=None, reason="train.py exited 1"
    )
    ckpt.record_completed(rc.GEN0_CHECKPOINT_GROUP, [ok, failed])
    # A FRESH instance reads the same marker file from disk.
    reloaded = rc.RunCheckpoint(run_id="run-xyz", runs_dir=tmp_path).load()
    assert reloaded.completed_indices(rc.GEN0_CHECKPOINT_GROUP) == {2}
    recovered = reloaded.resumed_outcomes(rc.GEN0_CHECKPOINT_GROUP)
    assert len(recovered) == 1
    assert recovered[0].index == 2
    assert recovered[0].dim_means == {"safety": 4.0}
    assert recovered[0].signal is not None
    assert recovered[0].signal.held_out_fitness == pytest.approx(0.55)


def test_run_checkpoint_load_corrupt_file_degrades_to_empty(tmp_path: Path) -> None:
    """A malformed marker file leaves ``groups`` empty (re-run everything) rather
    than raising — a corrupt checkpoint must never crash the campaign."""
    marker = tmp_path / "run-bad.json"
    marker.write_text("{not json", encoding="utf-8")
    ckpt = rc.RunCheckpoint(run_id="run-bad", runs_dir=tmp_path).load()
    assert ckpt.completed_indices(rc.GEN0_CHECKPOINT_GROUP) == set()


def test_gen0_async_resume_skips_completed_reruns_only_missing(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """A re-run with a checkpoint that already records replicates 1+2 complete
    re-runs ONLY replicate 3, then aggregates the UNION of all three."""
    _make_gen0_snapshot(campaign_state)
    ckpt = rc.RunCheckpoint(run_id="gen0-resume", runs_dir=tmp_path)
    # Pre-seed the marker as if a prior run finished replicates 1 + 2.
    for idx in (1, 2):
        ckpt.record_completed(
            rc.GEN0_CHECKPOINT_GROUP,
            [
                rc.WorkerOutcome(
                    index=idx,
                    ok=True,
                    returncode=0,
                    dim_means={"safety": float(idx)},
                    signal=rc.CycleSignal(
                        held_out_fitness=0.50 + idx * 0.01,
                        fitness=0.6,
                        fitness_delta=None,
                        promote_policy=None,
                        source=None,
                        between_seed_stderr=None,
                    ),
                    reason="ok",
                )
            ],
        )
    ran: list[int] = []
    runner = _counting_async_runner(ran=ran)
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        band = asyncio.run(
            rc.run_gen0_baseline_async(
                k=3,
                dry_run=False,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
                checkpoint=ckpt,
            )
        )
    # ONLY the missing replicate (3) was actually re-run.
    assert ran == [3]
    # The union of all 3 contributes to the band (2 resumed + 1 fresh held-out).
    assert len(band.held_out_values) == 3
    # baseline.json's raw.dim_means is the K-mean over the UNION (1+2+3)/3 = 2.0.
    payload = json.loads(campaign_state["baseline"].read_text(encoding="utf-8"))
    assert payload["raw"]["dim_means"]["safety"] == pytest.approx(2.0)


def test_gen0_async_idempotent_kmean_write_second_run_is_noop(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """A second run with the SAME run id (marker shows the K-mean already written)
    must NOT re-aggregate or re-overwrite baseline.json (idempotent)."""
    _make_gen0_snapshot(campaign_state)
    runner1 = _fake_async_runner(
        dim_per_index={1: {"safety": 2.0}, 2: {"safety": 4.0}},
        held_out_per_index={1: 0.50, 2: 0.52},
    )
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_gen0_baseline_async(
                k=2,
                dry_run=False,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner1,
                checkpoint=rc.RunCheckpoint(run_id="idem", runs_dir=tmp_path),
            )
        )
    after_first = campaign_state["baseline"].read_text(encoding="utf-8")
    assert json.loads(after_first)["raw"]["dim_means"]["safety"] == pytest.approx(3.0)

    # A second run reloading the SAME marker: the K-mean is flagged written, and a
    # runner that would aggregate to a DIFFERENT value must NOT touch baseline.json.
    runner2 = _fake_async_runner(
        dim_per_index={1: {"safety": 99.0}, 2: {"safety": 99.0}},
        held_out_per_index={1: 0.9, 2: 0.9},
    )
    ran2: list[str] = []

    async def tracking_runner(
        *, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None
    ) -> Any:
        ran2.append(env["GEODE_STATE_ROOT"])
        return await runner2(env=env, dry_run=dry_run, per_audit_timeout=per_audit_timeout)

    reloaded = rc.RunCheckpoint(run_id="idem", runs_dir=tmp_path).load()
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_gen0_baseline_async(
                k=2,
                dry_run=False,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=tracking_runner,
                checkpoint=reloaded,
            )
        )
    # No worker re-ran (both replicates were already complete in the marker)…
    assert ran2 == []
    # …and baseline.json is byte-identical — the K-mean write was a no-op.
    assert campaign_state["baseline"].read_text(encoding="utf-8") == after_first


def test_gen0_async_does_not_checkpoint_dropped_worker(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """A dropped (failed) worker is NOT recorded complete, so a resume RE-RUNS it
    (it may succeed the second time)."""
    _make_gen0_snapshot(campaign_state)
    ckpt = rc.RunCheckpoint(run_id="drop-resume", runs_dir=tmp_path)
    ran_first: list[int] = []
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_gen0_baseline_async(
                k=2,
                dry_run=False,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=_counting_async_runner(ran=ran_first, fail_indices={2}),
                checkpoint=ckpt,
            )
        )
    assert sorted(ran_first) == [1, 2]
    # Worker 1 ok → checkpointed; worker 2 failed → NOT checkpointed.
    reloaded = rc.RunCheckpoint(run_id="drop-resume", runs_dir=tmp_path).load()
    assert reloaded.completed_indices(rc.GEN0_CHECKPOINT_GROUP) == {1}
    # Resume: worker 2 (the previously-dropped one) is re-attempted, worker 1 is not.
    ran_second: list[int] = []
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_gen0_baseline_async(
                k=2,
                dry_run=False,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=_counting_async_runner(ran=ran_second),
                checkpoint=reloaded,
            )
        )
    assert ran_second == [2]


def test_control_arm_async_resume_skips_completed_cycles(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """A control arm keys its cycles under its OWN group (the arm name) — a resume
    re-runs only the missing cycles and aggregates the union floor."""
    _make_gen0_snapshot(campaign_state)
    ckpt = rc.RunCheckpoint(run_id="arm-resume", runs_dir=tmp_path)
    # Pre-seed cycles 1 + 3 of the 'never' arm as already complete.
    for idx in (1, 3):
        ckpt.record_completed(
            "never",
            [
                rc.WorkerOutcome(
                    index=idx,
                    ok=True,
                    returncode=0,
                    dim_means={"safety": float(idx)},
                    signal=rc.CycleSignal(
                        held_out_fitness=0.40 + idx * 0.01,
                        fitness=0.5,
                        fitness_delta=None,
                        promote_policy=None,
                        source=None,
                        between_seed_stderr=None,
                    ),
                    reason="ok",
                )
            ],
        )
    ran: list[int] = []
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        floor = asyncio.run(
            rc.run_control_arm_async(
                arm="never",
                arm_index=0,
                n=4,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=_counting_async_runner(ran=ran),
                checkpoint=ckpt,
            )
        )
    # Only the 2 missing cycles (2, 4) re-ran; the union of all 4 is aggregated.
    assert sorted(ran) == [2, 4]
    assert floor.cycles_ok == 4
    assert floor.cycles_dropped == 0


def test_control_arm_resume_group_isolated_from_gen0(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """gen-0 and each arm checkpoint under DISTINCT groups, so a completed gen-0
    replicate index never masks the same-numbered control cycle."""
    ckpt = rc.RunCheckpoint(run_id="grouped", runs_dir=tmp_path)
    ckpt.record_completed(
        rc.GEN0_CHECKPOINT_GROUP,
        [rc.WorkerOutcome(1, True, 0, {"safety": 1.0}, None, "ok")],
    )
    # The gen-0 group has index 1; the 'random' group does NOT (distinct namespace).
    assert ckpt.completed_indices(rc.GEN0_CHECKPOINT_GROUP) == {1}
    assert ckpt.completed_indices("random") == set()


# ---------------------------------------------------------------------------
# S6 — transcript isolation + merge (concurrent workers write OWN jsonls; the
# campaign merges them into one ordered, attributable replay). PR-ASYNC-FIRST.
# ---------------------------------------------------------------------------


def _write_transcript_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write JSONL transcript rows to ``path`` (mirrors the per-worker file each
    ``train.py`` worker subprocess produces via its isolated RunTranscript)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_merge_worker_transcripts_orders_by_ts_and_attributes(tmp_path: Path) -> None:
    """The merged campaign transcript is one coherent replay ordered by ``(ts,
    seq)`` across workers, and every row keeps its ``worker_id`` (attributable)."""
    w1 = tmp_path / "w1" / "transcript.jsonl"
    w2 = tmp_path / "w2" / "transcript.jsonl"
    # Worker timelines INTERLEAVE in wall-clock time (w1@1.0, w2@1.5, w1@2.0, w2@2.5).
    _write_transcript_rows(
        w1,
        [
            {
                "ts": 1.0,
                "seq": 1,
                "event": "subprocess_started",
                "payload": {"worker_id": "gen0-w1"},
            },
            {
                "ts": 2.0,
                "seq": 2,
                "event": "subprocess_finished",
                "payload": {"worker_id": "gen0-w1"},
            },
        ],
    )
    _write_transcript_rows(
        w2,
        [
            {
                "ts": 1.5,
                "seq": 1,
                "event": "subprocess_started",
                "payload": {"worker_id": "gen0-w2"},
            },
            {
                "ts": 2.5,
                "seq": 2,
                "event": "subprocess_finished",
                "payload": {"worker_id": "gen0-w2"},
            },
        ],
    )
    dest = tmp_path / "campaign" / "transcript.jsonl"
    count = rc.merge_worker_transcripts([w1, w2], dest)
    assert count == 4
    rows = [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()]
    # Ordered by ts across BOTH workers (not grouped by worker).
    assert [r["ts"] for r in rows] == [1.0, 1.5, 2.0, 2.5]
    # Each row stays attributable to its origin worker.
    assert [r["payload"]["worker_id"] for r in rows] == [
        "gen0-w1",
        "gen0-w2",
        "gen0-w1",
        "gen0-w2",
    ]


def test_merge_worker_transcripts_two_workers_dont_interleave_corrupt(tmp_path: Path) -> None:
    """The whole point of isolation: each worker wrote its OWN file, so merging
    yields EXACTLY the union with NO lost / garbled rows — the corruption a shared
    concurrent-append jsonl would have produced is structurally impossible."""
    w1 = tmp_path / "w1" / "transcript.jsonl"
    w2 = tmp_path / "w2" / "transcript.jsonl"
    rows1 = [
        {"ts": float(i), "seq": i, "event": f"e{i}", "payload": {"worker_id": "never-w1"}}
        for i in range(1, 21)
    ]
    rows2 = [
        {"ts": float(i) + 0.5, "seq": i, "event": f"e{i}", "payload": {"worker_id": "never-w2"}}
        for i in range(1, 21)
    ]
    _write_transcript_rows(w1, rows1)
    _write_transcript_rows(w2, rows2)
    dest = tmp_path / "campaign" / "transcript.jsonl"
    count = rc.merge_worker_transcripts([w1, w2], dest)
    assert count == 40
    merged = [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()]
    # No row lost; each worker contributes its full 20 events, intact.
    w1_rows = [r for r in merged if r["payload"]["worker_id"] == "never-w1"]
    w2_rows = [r for r in merged if r["payload"]["worker_id"] == "never-w2"]
    assert len(w1_rows) == 20
    assert len(w2_rows) == 20
    # Globally ts-monotonic (the operator sees one ordered replay).
    timestamps = [r["ts"] for r in merged]
    assert timestamps == sorted(timestamps)


def test_merge_worker_transcripts_skips_missing_and_malformed(tmp_path: Path) -> None:
    """Graceful — a ``None`` path, a missing file, and a malformed JSONL line are
    each skipped; the clean rows still merge (one bad row never aborts the merge)."""
    good = tmp_path / "w1" / "transcript.jsonl"
    good.parent.mkdir(parents=True, exist_ok=True)
    # One valid row, then a corrupt half-line (the kind a shared race would create).
    good.write_text(
        json.dumps({"ts": 1.0, "seq": 1, "event": "ok", "payload": {"worker_id": "w1"}})
        + "\n"
        + '{"ts": 2.0, "seq": 2, "event": "trunc'
        + "\n",
        encoding="utf-8",
    )
    missing = tmp_path / "w2" / "transcript.jsonl"  # never created
    dest = tmp_path / "campaign" / "transcript.jsonl"
    count = rc.merge_worker_transcripts([None, good, missing], dest)
    assert count == 1
    rows = [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["event"] == "ok"


def test_merge_worker_transcripts_empty_returns_zero_and_no_dest(tmp_path: Path) -> None:
    """No worker rows → returns 0 and does NOT create the dest file (no empty
    artifact)."""
    dest = tmp_path / "campaign" / "transcript.jsonl"
    count = rc.merge_worker_transcripts([None, tmp_path / "nope" / "transcript.jsonl"], dest)
    assert count == 0
    assert not dest.exists()


def test_merge_worker_transcripts_appends_preserving_existing(tmp_path: Path) -> None:
    """Merge APPENDS (never overwrites), so rows the campaign already wrote to the
    dest transcript survive the merge."""
    dest = tmp_path / "campaign" / "transcript.jsonl"
    _write_transcript_rows(dest, [{"ts": 0.1, "seq": 1, "event": "campaign_start", "payload": {}}])
    w1 = tmp_path / "w1" / "transcript.jsonl"
    _write_transcript_rows(
        w1, [{"ts": 1.0, "seq": 1, "event": "subprocess_started", "payload": {"worker_id": "w1"}}]
    )
    rc.merge_worker_transcripts([w1], dest)
    events = [json.loads(line)["event"] for line in dest.read_text(encoding="utf-8").splitlines()]
    assert events == ["campaign_start", "subprocess_started"]


def _transcript_writing_async_runner(*, group: str) -> Any:
    """A fake async runner that WRITES to the worker's ``GEODE_RUN_TRANSCRIPT_PATH``
    (simulating what the real ``train.py`` worker subprocess does via _emit_journal),
    then emits the usual attribution row + FITNESS_RESULT so the gather succeeds."""

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        state_root = Path(env["GEODE_STATE_ROOT"])
        idx = int(state_root.name.removeprefix("w"))
        worker_id = env["GEODE_RUN_WORKER_ID"]
        assert worker_id == f"{group}-w{idx}"
        transcript = Path(env["GEODE_RUN_TRANSCRIPT_PATH"])
        # Two events per worker, ts offset by index so workers interleave globally.
        _write_transcript_rows(
            transcript,
            [
                {
                    "ts": 10.0 + idx,
                    "seq": 1,
                    "event": "subprocess_started",
                    "payload": {"worker_id": worker_id},
                },
                {
                    "ts": 20.0 + idx,
                    "seq": 2,
                    "event": "subprocess_finished",
                    "payload": {"worker_id": worker_id},
                },
            ],
        )
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(mutations, held_out=0.5, fitness=0.6, source="manual")
        return SimpleNamespace(
            returncode=0, stdout=_fitness_result_line({"safety": 3.0}), stderr=""
        )

    return runner


def test_gen0_async_merges_per_worker_transcripts_into_campaign_transcript(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """End-to-end S6: the K concurrent gen-0 workers each write their OWN isolated
    transcript; after the gather the campaign transcript holds the MERGED, ordered,
    per-worker-attributed replay."""
    _make_gen0_snapshot(campaign_state)
    campaign_transcript = tmp_path / "campaign" / "transcript.jsonl"
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_gen0_baseline_async(
                k=3,
                dry_run=False,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=_transcript_writing_async_runner(group="gen0"),
                campaign_transcript=campaign_transcript,
            )
        )
    assert campaign_transcript.is_file()
    rows = [
        json.loads(line) for line in campaign_transcript.read_text(encoding="utf-8").splitlines()
    ]
    # 3 workers × 2 events each, merged.
    assert len(rows) == 6
    # All 3 workers attributable in the merged replay.
    assert {r["payload"]["worker_id"] for r in rows} == {"gen0-w1", "gen0-w2", "gen0-w3"}
    # The merged stream is ts-ordered across workers (started events before finished).
    timestamps = [r["ts"] for r in rows]
    assert timestamps == sorted(timestamps)


def test_gen0_async_no_merge_when_campaign_transcript_none(
    campaign_state: dict[str, Path],
) -> None:
    """S6 no-regression: ``campaign_transcript=None`` (the default) SKIPS the merge
    entirely — the gen-0 fan-out behaves exactly as the pre-S6 path."""
    _make_gen0_snapshot(campaign_state)
    runner = _fake_async_runner(
        dim_per_index={1: {"safety": 2.0}, 2: {"safety": 4.0}},
        held_out_per_index={1: 0.5, 2: 0.5},
    )
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        band = asyncio.run(
            rc.run_gen0_baseline_async(
                k=2,
                dry_run=False,
                audit_max_samples=3,
                audit_max_connections=8,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
            )
        )
    # No merge crash, normal aggregation still happens.
    assert len(band.held_out_values) == 2


def test_control_arm_async_merges_per_cycle_transcripts(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """End-to-end S6 on a control arm: the N concurrent cycles' isolated
    transcripts merge into the campaign transcript, attributed ``random-w*``."""
    _make_gen0_snapshot(campaign_state)
    campaign_transcript = tmp_path / "campaign" / "transcript.jsonl"
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        floor = asyncio.run(
            rc.run_control_arm_async(
                arm="random",
                arm_index=1,
                n=2,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=_transcript_writing_async_runner(group="random"),
                campaign_transcript=campaign_transcript,
            )
        )
    assert floor.cycles_ok == 2
    rows = [
        json.loads(line) for line in campaign_transcript.read_text(encoding="utf-8").splitlines()
    ]
    assert {r["payload"]["worker_id"] for r in rows} == {"random-w1", "random-w2"}


# ---------------------------------------------------------------------------
# PR-ASYNC-FIRST WIRING (Codex MCP BLOCKER) — run_campaign must route the
# path-independent measures through the async subprocess harness in a real
# campaign, and keep the gate (+ all arms on the sync/test path) on run_arm.
# ---------------------------------------------------------------------------


def test_run_campaign_async_first_routes_path_independent_to_async(
    campaign_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A REAL campaign (dry_run=False, no injected runner) with async_first routes
    gen-0 + never/random through the ASYNC subprocess harness and the GATE through
    the sequential run_arm — proving the harness is WIRED into production, not the
    dead test-only code Codex MCP flagged.

    PR-CAMPAIGN-CONCURRENT-CONTROL-ARMS (2026-06-04): never+random now go through
    ONE ``run_control_arms_async`` gather (a SINGLE call carrying BOTH control
    arms), NOT one sequential ``run_control_arm_async`` per arm."""
    import plugins.petri_audit.runner as petri_runner

    monkeypatch.setattr(petri_runner, "purge_inspect_cache", lambda: True)
    (campaign_state["policies_dir"] / "hyperparam.json").write_text("{}", encoding="utf-8")

    band = rc.NoiseBand(
        k=2, held_out_values=(0.85,), fitness_values=(0.89,), mean=0.85, stderr=0.01
    )
    calls: dict[str, Any] = {"gen0": 0, "control_calls": [], "gate": []}

    async def fake_gen0_async(**_kw: Any) -> Any:
        calls["gen0"] += 1
        return band

    async def fake_control_arms_async(*, control_arms: Any, n: int, **_kw: Any) -> dict[str, Any]:
        # ONE call carrying BOTH path-independent arms — record the arm list so the
        # test proves never+random are dispatched together, not arm-by-arm.
        arms_in_call = [arm for arm, _idx in control_arms]
        calls["control_calls"].append(arms_in_call)
        return {
            arm: rc.ControlArmFloor(arm=arm, cycles_ok=n, cycles_dropped=0, held_out_band=band)
            for arm in arms_in_call
        }

    def fake_run_arm(*, arm: str, n: int, **_kw: Any) -> Any:
        calls["gate"].append(arm)
        return rc.ArmSummary(arm=arm, cycles_run=n, cycles_skipped=0, promotes=1, halted=False)

    monkeypatch.setattr(rc, "run_gen0_baseline_async", fake_gen0_async)
    monkeypatch.setattr(rc, "run_control_arms_async", fake_control_arms_async)
    monkeypatch.setattr(rc, "run_arm", fake_run_arm)

    result = rc.run_campaign(
        n=2,
        k=2,
        arms=("never", "random", "gate"),
        dry_run=False,
        async_first=True,
        progress_path=campaign_state["progress"],
        snapshot_dir=campaign_state["snapshot"],
    )
    assert calls["gen0"] == 1
    # ONE concurrent fan-out carrying BOTH control arms (never+random overlap),
    # NOT two sequential per-arm calls.
    assert calls["control_calls"] == [["never", "random"]]
    assert calls["gate"] == ["gate"]  # ONLY the path-dependent gate is sequential
    assert len(result["control_floors"]) == 2
    # Summaries preserved in the ORIGINAL arms order (digest stability).
    assert [s.arm for s in result["arm_summaries"]] == ["never", "random", "gate"]


def test_run_campaign_loads_persisted_checkpoint_for_resume(
    campaign_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A REAL campaign REHYDRATES a pre-existing checkpoint file (Codex MCP HIGH):
    ``run_campaign`` must ``.load()`` the marker so a resumed process skips the
    already-completed cycles instead of re-running (re-paying for) every one."""
    import plugins.petri_audit.runner as petri_runner

    monkeypatch.setattr(petri_runner, "purge_inspect_cache", lambda: True)
    (campaign_state["policies_dir"] / "hyperparam.json").write_text("{}", encoding="utf-8")
    # Point the campaign's checkpoint dir at tmp + pre-seed a marker showing some
    # never+random cycles already complete (the run_id matches run_campaign's).
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setattr(rc, "CAMPAIGN_RUNS_DIR", runs_dir)
    run_id = "campaign-n2-k2-never-random-gate"
    pre_seed = rc.RunCheckpoint(run_id=run_id, runs_dir=runs_dir)
    pre_seed.record_completed(
        "never",
        [rc.WorkerOutcome(1, True, 0, {"safety": 1.0}, None, "ok")],
    )
    pre_seed.record_completed(
        "random",
        [rc.WorkerOutcome(2, True, 0, {"safety": 2.0}, None, "ok")],
    )

    band = rc.NoiseBand(
        k=2, held_out_values=(0.85,), fitness_values=(0.89,), mean=0.85, stderr=0.01
    )
    seen_checkpoint: dict[str, Any] = {}

    async def fake_gen0_async(*, checkpoint: Any, **_kw: Any) -> Any:
        return band

    async def fake_control_arms_async(
        *, control_arms: Any, n: int, checkpoint: Any, **_kw: Any
    ) -> dict[str, Any]:
        # Record what the loaded checkpoint says is already complete PER ARM — proof
        # that run_campaign rehydrated the persisted marker (not a fresh empty one).
        seen_checkpoint["never"] = checkpoint.completed_indices("never")
        seen_checkpoint["random"] = checkpoint.completed_indices("random")
        return {
            arm: rc.ControlArmFloor(arm=arm, cycles_ok=n, cycles_dropped=0, held_out_band=band)
            for arm, _idx in control_arms
        }

    def fake_run_arm(*, arm: str, n: int, **_kw: Any) -> Any:
        return rc.ArmSummary(arm=arm, cycles_run=n, cycles_skipped=0, promotes=0, halted=False)

    monkeypatch.setattr(rc, "run_gen0_baseline_async", fake_gen0_async)
    monkeypatch.setattr(rc, "run_control_arms_async", fake_control_arms_async)
    monkeypatch.setattr(rc, "run_arm", fake_run_arm)

    rc.run_campaign(
        n=2,
        k=2,
        arms=("never", "random", "gate"),
        dry_run=False,
        async_first=True,
        progress_path=campaign_state["progress"],
        snapshot_dir=campaign_state["snapshot"],
    )
    # The checkpoint passed into the control fan-out carries the PERSISTED completed
    # cycles, attributed to the right arm — a fresh (unloaded) marker would be empty.
    assert seen_checkpoint["never"] == {1}
    assert seen_checkpoint["random"] == {2}


def test_run_campaign_async_first_false_keeps_every_arm_on_sync(
    campaign_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """async_first=False keeps every arm — incl. never/random — on the legacy
    sequential run_arm and never touches the async harness (the unit-test + smoke
    path is preserved)."""
    import plugins.petri_audit.runner as petri_runner

    monkeypatch.setattr(petri_runner, "purge_inspect_cache", lambda: True)
    (campaign_state["policies_dir"] / "hyperparam.json").write_text("{}", encoding="utf-8")

    async def boom_async(**_kw: Any) -> Any:
        raise AssertionError("async harness must NOT run when async_first=False")

    arms_seen: list[str] = []

    def fake_run_arm(*, arm: str, n: int, **_kw: Any) -> Any:
        arms_seen.append(arm)
        return rc.ArmSummary(arm=arm, cycles_run=n, cycles_skipped=0, promotes=0, halted=False)

    monkeypatch.setattr(rc, "run_gen0_baseline_async", boom_async)
    monkeypatch.setattr(rc, "run_control_arms_async", boom_async)
    monkeypatch.setattr(rc, "run_arm", fake_run_arm)
    monkeypatch.setattr(
        rc,
        "run_gen0_baseline",
        lambda **_kw: rc.NoiseBand(
            k=0, held_out_values=(), fitness_values=(), mean=None, stderr=None
        ),
    )

    rc.run_campaign(
        n=1,
        k=0,
        arms=("never", "random", "gate"),
        dry_run=False,
        async_first=False,
        progress_path=campaign_state["progress"],
        snapshot_dir=campaign_state["snapshot"],
    )
    assert arms_seen == ["never", "random", "gate"]


# ---------------------------------------------------------------------------
# PR-CAMPAIGN-CONCURRENT-CONTROL-ARMS (2026-06-04) — the PATH-INDEPENDENT
# control arms (never + random) fan out in ONE shared concurrent gather by
# default. These pin the 5 invariants: attribution, promote policy, resume,
# random reproducibility, and per-arm worker-root / transcript isolation.
# ---------------------------------------------------------------------------


def _arm_recording_async_runner(*, observed: list[tuple[str, int]]) -> Any:
    """A fake async runner that records each worker's ``(arm, cycle_index)``.

    The arm is the worker root's PARENT dir name (``<root>/<arm>/w{idx}``) and the
    index is parsed from the leaf (``w{idx}``), so a concurrent never+random
    fan-out is fully attributable per worker. Writes a synthetic attribution row +
    ``FITNESS_RESULT`` keyed off the index so the floor aggregation has values."""

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        state_root = Path(env["GEODE_STATE_ROOT"])
        idx = int(state_root.name.removeprefix("w"))
        arm = state_root.parent.name
        observed.append((arm, idx))
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(
            mutations, held_out=0.40 + idx * 0.01, fitness=0.5, promote_policy=arm, source="manual"
        )
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line({"safety": float(idx)}))

    return runner


def test_control_arms_async_single_gather_dispatches_both_arms_concurrently(
    campaign_state: dict[str, Path],
) -> None:
    """never+random fan out in ONE gather: every cycle of BOTH arms is dispatched
    in a single concurrent fan-out (n per arm = 2n total worker dispatches), not
    two sequential per-arm gathers."""
    _make_gen0_snapshot(campaign_state)
    observed: list[tuple[str, int]] = []
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        floors = asyncio.run(
            rc.run_control_arms_async(
                control_arms=[("never", 0), ("random", 1)],
                n=3,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=_arm_recording_async_runner(observed=observed),
            )
        )
    # 3 never + 3 random = 6 worker dispatches, all in the single fan-out.
    assert sorted(observed) == [
        ("never", 1),
        ("never", 2),
        ("never", 3),
        ("random", 1),
        ("random", 2),
        ("random", 3),
    ]
    # A floor per arm, each aggregating ONLY its own 3 cycles (attribution #1).
    assert set(floors) == {"never", "random"}
    assert floors["never"].arm == "never"
    assert floors["never"].cycles_ok == 3
    assert floors["random"].arm == "random"
    assert floors["random"].cycles_ok == 3


def test_control_arms_async_per_arm_attribution_not_mixed(
    campaign_state: dict[str, Path],
) -> None:
    """The single gather's results are partitioned back PER ARM: a never worker's
    promote policy is 'never', a random worker's is 'random' — never crossed."""
    _make_gen0_snapshot(campaign_state)
    policy_by_root: dict[str, str] = {}

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        state_root = Path(env["GEODE_STATE_ROOT"])
        policy_by_root[str(state_root)] = env["GEODE_PROMOTE_POLICY"]
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(mutations, held_out=0.5, fitness=0.6, source="manual")
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line({"safety": 3.0}))

    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_control_arms_async(
                control_arms=[("never", 0), ("random", 1)],
                n=2,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
            )
        )
    # Each worker's GEODE_PROMOTE_POLICY matches the ARM segment of its isolated
    # root (invariant #2): a never-root never carries 'random' and vice-versa.
    for root, policy in policy_by_root.items():
        assert Path(root).parent.name == policy, f"{root} policy {policy} crossed arms"
    assert sorted(policy_by_root.values()) == ["never", "never", "random", "random"]


def test_control_arms_async_random_seed_matches_legacy_per_arm_formula(
    campaign_state: dict[str, Path],
) -> None:
    """Reproducibility (#4): the random arm's per-cycle seed in the concurrent
    fan-out equals the legacy ``DEFAULT_RANDOM_SEED_BASE + arm_index*n + cycle`` —
    keyed on (arm_index, n, cycle), NOT wall-clock / dispatch order. never is unseeded."""
    _make_gen0_snapshot(campaign_state)
    seed_by_arm_idx: dict[tuple[str, int], str | None] = {}

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        state_root = Path(env["GEODE_STATE_ROOT"])
        idx = int(state_root.name.removeprefix("w"))
        arm = state_root.parent.name
        seed_by_arm_idx[(arm, idx)] = env.get("GEODE_PROMOTE_POLICY_SEED")
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(mutations, held_out=0.5, fitness=0.6, source="manual")
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line({"safety": 3.0}))

    n = 3
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_control_arms_async(
                control_arms=[("never", 0), ("random", 1)],
                n=n,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
            )
        )
    # random (arm_index 1): each cycle's seed == base + 1*n + cycle (byte-identical
    # to the legacy per-arm path, regardless of concurrent interleaving).
    for cycle in range(1, n + 1):
        expected = str(rc.DEFAULT_RANDOM_SEED_BASE + 1 * n + cycle)
        assert seed_by_arm_idx[("random", cycle)] == expected
    # never: every cycle UNSEEDED.
    for cycle in range(1, n + 1):
        assert seed_by_arm_idx[("never", cycle)] is None
    # The helper :func:`_control_cycle_seed` is the single source of the formula.
    assert rc._control_cycle_seed("random", 1, n, 2) == rc.DEFAULT_RANDOM_SEED_BASE + 1 * n + 2
    assert rc._control_cycle_seed("never", 0, n, 2) is None


def test_control_arms_async_resume_skips_completed_per_arm(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """Resume (#3): a checkpoint with SOME never + SOME random cycles done resumes
    ONLY the remaining ones, correctly per-arm (never's done set never masks
    random's, and vice-versa)."""
    _make_gen0_snapshot(campaign_state)
    ckpt = rc.RunCheckpoint(run_id="multi-arm-resume", runs_dir=tmp_path)

    def _done(idx: int) -> rc.WorkerOutcome:
        return rc.WorkerOutcome(
            index=idx,
            ok=True,
            returncode=0,
            dim_means={"safety": float(idx)},
            signal=rc.CycleSignal(
                held_out_fitness=0.40 + idx * 0.01,
                fitness=0.5,
                fitness_delta=None,
                promote_policy=None,
                source=None,
                between_seed_stderr=None,
            ),
            reason="ok",
        )

    # never: cycles 1+2 done (missing 3+4). random: cycle 1 done (missing 2+3+4).
    ckpt.record_completed("never", [_done(1), _done(2)])
    ckpt.record_completed("random", [_done(1)])

    observed: list[tuple[str, int]] = []
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        floors = asyncio.run(
            rc.run_control_arms_async(
                control_arms=[("never", 0), ("random", 1)],
                n=4,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=_arm_recording_async_runner(observed=observed),
                checkpoint=ckpt,
            )
        )
    # Only the missing cycles re-ran, attributed to the RIGHT arm.
    assert sorted(observed) == [
        ("never", 3),
        ("never", 4),
        ("random", 2),
        ("random", 3),
        ("random", 4),
    ]
    # Each arm's floor unions the resumed + freshly-run cycles to the full N=4.
    assert floors["never"].cycles_ok == 4
    assert floors["random"].cycles_ok == 4


def test_control_arms_async_worker_roots_isolated_per_arm(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """Isolation (#5): a never-cycle and a random-cycle with the SAME index live
    under DISTINCT worker roots (``<root>/never/w1`` vs ``<root>/random/w1``), so
    the same-numbered cycles never collide on a state tree / transcript file."""
    _make_gen0_snapshot(campaign_state)
    roots: list[str] = []

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        state_root = Path(env["GEODE_STATE_ROOT"])
        roots.append(str(state_root))
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(mutations, held_out=0.5, fitness=0.6, source="manual")
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line({"safety": 3.0}))

    workers_root = tmp_path / "workers"
    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_control_arms_async(
                control_arms=[("never", 0), ("random", 1)],
                n=1,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                workers_root=workers_root,
                runner_fn=runner,
            )
        )
    # Both arms used cycle index 1 but DISTINCT roots — no collision.
    assert len(set(roots)) == 2
    assert str(workers_root / "never" / "w1") in roots
    assert str(workers_root / "random" / "w1") in roots


def test_control_arms_async_merges_both_arms_transcripts_no_collision(
    campaign_state: dict[str, Path], tmp_path: Path
) -> None:
    """The single gather merges BOTH arms' per-cycle transcripts into the one
    campaign transcript, attributed ``never-w*`` + ``random-w*`` (same index, no
    collision)."""
    _make_gen0_snapshot(campaign_state)
    campaign_transcript = tmp_path / "campaign" / "transcript.jsonl"

    async def runner(*, env: dict[str, str], dry_run: bool, per_audit_timeout: float | None) -> Any:
        transcript = Path(env["GEODE_RUN_TRANSCRIPT_PATH"])
        worker_id = env["GEODE_RUN_WORKER_ID"]
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            json.dumps({"ts": 1.0, "seq": 0, "payload": {"worker_id": worker_id}}) + "\n",
            encoding="utf-8",
        )
        state_root = Path(env["GEODE_STATE_ROOT"])
        mutations = state_root / "autoresearch" / "mutations.jsonl"
        mutations.parent.mkdir(parents=True, exist_ok=True)
        _write_attribution(mutations, held_out=0.5, fitness=0.6, source="manual")
        return SimpleNamespace(returncode=0, stdout=_fitness_result_line({"safety": 3.0}))

    with rc.ProgressLog(campaign_state["progress"]) as progress:
        asyncio.run(
            rc.run_control_arms_async(
                control_arms=[("never", 0), ("random", 1)],
                n=1,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
                runner_fn=runner,
                campaign_transcript=campaign_transcript,
            )
        )
    rows = [
        json.loads(line) for line in campaign_transcript.read_text(encoding="utf-8").splitlines()
    ]
    assert {r["payload"]["worker_id"] for r in rows} == {"never-w1", "random-w1"}


def test_control_arms_async_refuses_gate_arm(campaign_state: dict[str, Path]) -> None:
    """The gate arm is path-dependent and MUST never be routed through the
    concurrent control fan-out."""
    _make_gen0_snapshot(campaign_state)
    with (
        rc.ProgressLog(campaign_state["progress"]) as progress,
        pytest.raises(ValueError, match="path-dependent"),
    ):
        asyncio.run(
            rc.run_control_arms_async(
                control_arms=[("never", 0), ("gate", 2)],
                n=2,
                audit_max_samples=3,
                audit_max_connections=8,
                dry_run=False,
                progress=progress,
                snapshot_dir=campaign_state["snapshot"],
                per_audit_timeout=5.0,
            )
        )
