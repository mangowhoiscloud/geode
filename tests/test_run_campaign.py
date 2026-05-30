"""Unit tests for the self-improving campaign driver (``scripts/run_campaign.py``).

PR-CAMPAIGN-DRIVER (2026-05-31). NO live audits — every boundary is mocked:
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
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import scripts.run_campaign as rc
from core.self_improving_loop.mutator_feedback import RepetitionFinding, RepetitiveMutationError
from core.self_improving_loop.runner import Mutation, Proposal

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
