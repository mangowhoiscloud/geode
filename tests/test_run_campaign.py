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

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import core.self_improving.campaign as rc
import pytest
from core.self_improving.loop.mutator_feedback import RepetitionFinding, RepetitiveMutationError
from core.self_improving.loop.runner import Mutation, Proposal

# tests/test_run_campaign.py → parents[1] = repo root (where ``core/`` is importable
# so ``python -m core.self_improving.campaign`` / ``…train`` resolve their package).
_REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Fixtures — redirect the module-level SoT paths into tmp dirs
# ---------------------------------------------------------------------------


@pytest.fixture
def campaign_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect every SoT path the driver touches into ``tmp_path``."""
    state_dir = tmp_path / "autoresearch" / "state"
    policies_dir = state_dir / "policies"
    policies_dir.mkdir(parents=True)
    baseline = state_dir / "baseline.json"
    mutations = state_dir / "mutations.jsonl"
    progress = state_dir / "campaign-progress.log"
    snapshot = tmp_path / "state" / "campaign" / "gen-0-snapshot"
    petri_logs = tmp_path / "petri-logs"
    petri_logs.mkdir(parents=True)

    monkeypatch.setattr(rc, "AUTORESEARCH_STATE_DIR", state_dir)
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
    ``autoresearch/state`` log files in append mode, which is the same
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
