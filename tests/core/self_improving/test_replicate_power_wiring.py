"""E4 (2026-05-30) — wiring tests for the per-mutation replicate loop + the power /
gain-evidence records in ``core/self_improving/train.py``.

The pure statistics (decomposition / ci-excludes-0 / power formula) are pinned in
``test_statistical_power.py``; this file pins the WIRING:

  1. ``--replicate`` / ``--target-effect-size`` resolver precedence (env → CLI →
     config → constant) + graceful malformed-env fallback.
  2. ``main`` runs the audit inside an M-loop and decomposes within vs between —
     static guards (matching the E2 / E3 ``inspect.getsource`` convention) that the
     loop + decomposition + power line are actually wired, not just defined.
  3. M=1 is the DEFAULT path (no cost / behaviour regression): the loop runs the
     audit exactly once, and the new record fields are None-omitting so M=1 / legacy
     readers are backward-compatible.
  4. The new fields flow into BOTH record sinks — the per-cycle attribution row and
     the on-promote baseline registry row — backward-compatibly.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.self_improving import gate, ledger
from core.self_improving import train as auto_train

# --- resolver precedence -----------------------------------------------------


def _stub_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    replicate: int | None = 1,
    target_effect_size: float | None = 0.02,
) -> None:
    monkeypatch.setattr(
        auto_train,
        "_get_autoresearch_config",
        lambda: SimpleNamespace(replicate=replicate, target_effect_size=target_effect_size),
    )


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GEODE_AUDIT_REPLICATE",
        "AUTORESEARCH_REPLICATE",
        "GEODE_TARGET_EFFECT_SIZE",
        "AUTORESEARCH_TARGET_EFFECT_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_replicate_default_is_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env, no CLI, config M=1 → 1 (today's zero-cost default)."""
    _clear_env(monkeypatch)
    _stub_config(monkeypatch, replicate=1)
    assert gate._resolve_audit_replicate(None) == 1


def test_replicate_reads_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    _stub_config(monkeypatch, replicate=3)
    assert gate._resolve_audit_replicate(None) == 3


def test_replicate_cli_wins_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    _stub_config(monkeypatch, replicate=1)
    assert gate._resolve_audit_replicate(5) == 5


def test_replicate_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_AUDIT_REPLICATE", "4")
    monkeypatch.delenv("AUTORESEARCH_REPLICATE", raising=False)
    _stub_config(monkeypatch, replicate=1)
    assert gate._resolve_audit_replicate(2) == 4


def test_replicate_malformed_env_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Graceful contract: a non-integer / <1 env value must not crash or silently
    change cost — it warns + degrades to the next tier."""
    monkeypatch.setenv("GEODE_AUDIT_REPLICATE", "not-an-int")
    monkeypatch.delenv("AUTORESEARCH_REPLICATE", raising=False)
    _stub_config(monkeypatch, replicate=2)
    assert gate._resolve_audit_replicate(None) == 2
    monkeypatch.setenv("GEODE_AUDIT_REPLICATE", "0")
    assert gate._resolve_audit_replicate(None) == 2


def test_target_effect_size_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    _stub_config(monkeypatch, target_effect_size=0.02)
    assert gate._resolve_target_effect_size(None) == pytest.approx(0.02)


def test_target_effect_size_cli_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    _stub_config(monkeypatch, target_effect_size=0.02)
    assert gate._resolve_target_effect_size(0.05) == pytest.approx(0.05)


def test_target_effect_size_malformed_env_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_TARGET_EFFECT_SIZE", "nope")
    monkeypatch.delenv("AUTORESEARCH_TARGET_EFFECT_SIZE", raising=False)
    _stub_config(monkeypatch, target_effect_size=0.03)
    assert gate._resolve_target_effect_size(None) == pytest.approx(0.03)
    # non-positive env likewise skipped (ill-posed for the power formula)
    monkeypatch.setenv("GEODE_TARGET_EFFECT_SIZE", "0")
    assert gate._resolve_target_effect_size(None) == pytest.approx(0.03)
    # non-finite env (nan/inf) likewise skipped (would crash the power formula)
    monkeypatch.setenv("GEODE_TARGET_EFFECT_SIZE", "nan")
    assert gate._resolve_target_effect_size(None) == pytest.approx(0.03)


def test_resolver_cli_overrides_graceful_on_nonfinite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Graceful contract (Codex MCP catch): a non-finite / malformed CLI override
    (argparse ``type=float`` accepts ``nan``/``inf``) must not crash — it degrades to
    the config / default tier."""
    _clear_env(monkeypatch)
    _stub_config(monkeypatch, replicate=2, target_effect_size=0.03)
    # nan/inf δ from the CLI must not propagate into the power formula
    assert gate._resolve_target_effect_size(float("nan")) == pytest.approx(0.03)
    assert gate._resolve_target_effect_size(float("inf")) == pytest.approx(0.03)
    assert gate._resolve_target_effect_size(-1.0) == pytest.approx(0.03)
    # int(float("inf")) raises OverflowError — the replicate resolver must catch it
    assert gate._resolve_audit_replicate(float("inf")) == 2  # falls back to config


# --- main() static wiring guards (E2 / E3 convention) ------------------------


def test_main_resolves_replicate_and_effect_size() -> None:
    source = inspect.getsource(auto_train.main)
    assert "audit_replicate = gate._resolve_audit_replicate(args.replicate)" in source
    assert (
        "target_effect_size = gate._resolve_target_effect_size(args.target_effect_size)" in source
    )


def test_main_runs_audit_in_replicate_loop() -> None:
    """The audit MUST be invoked inside ``for _replicate_idx in range(audit_replicate)``
    — the M-loop is wired, not just the knob defined. M=1 → exactly one iteration
    (no cost change)."""
    source = inspect.getsource(auto_train.main)
    assert "for _replicate_idx in range(audit_replicate):" in source
    # the run_audit call lives inside that loop body (after the for, before the gain block)
    loop_at = source.index("for _replicate_idx in range(audit_replicate):")
    decomp_at = source.index("variance_decomposition = decompose_variance(")
    run_at = source.index("measure.run_audit(", loop_at)
    assert loop_at < run_at < decomp_at


def test_main_decomposes_within_and_between() -> None:
    source = inspect.getsource(auto_train.main)
    assert "decompose_variance(" in source
    assert "_replicate_raw_fitnesses" in source
    assert "_replicate_between_seed_stderrs" in source
    # the gain CI verdict + the per-campaign power line are both computed
    assert "gain_ci_excludes_zero(" in source
    assert "required_samples(" in source
    assert "format_power_line(" in source


def test_main_emits_power_line_and_verdict() -> None:
    source = inspect.getsource(auto_train.main)
    assert "e4_power_line:" in source
    assert "e4_gain_verdict:" in source
    assert 'log.info("E4 %s", _power_line)' in source


def test_main_verdict_uses_gate_sigma_and_floor() -> None:
    """The gain VERDICT must reconcile with the promote gate: it uses the gate's own
    σ (``current_fitness_stderr``, NOT the combined within+between σ) and passes the
    gate's effective floor (Codex MCP catches — the verdict previously used combined
    σ + ignored the floor, both of which could contradict the gate)."""
    source = inspect.getsource(auto_train.main)
    # gain σ uses the gate's current_fitness_stderr (the bootstrap), NOT the
    # combined within+between σ
    assert "if current_fitness_stderr is not None:" in source
    assert "_sigma_current = current_fitness_stderr" in source
    # σ fallback mirrors the gate's MC fallback when the bootstrap / persisted
    # stderr is absent (so a v1/summary baseline's verdict σ is not falsely 0)
    assert "_sigma_current = fitness_spec._fitness_scale_stderr(" in source
    assert "_sigma_baseline = fitness_spec._fitness_scale_stderr(" in source
    # the verdict passes the gate's effective floor
    assert "floor=_gate_effective_floor" in source
    # the floor reproduces the gate's N=1 widening
    assert "N1_FITNESS_MARGIN_FLOOR" in source
    # the power analysis (NOT the verdict) is the one that uses the combined σ
    power_call = source.index("power_requirement = required_samples(")
    assert "variance_decomposition.combined_stderr" in source[power_call : power_call + 200]


def test_fitness_margin_floor_default_is_single_sot() -> None:
    """The gate's ``fitness_margin_floor`` default and the verdict's floor must be
    the SAME constant (no dual-SoT drift) — both read _FITNESS_MARGIN_FLOOR_DEFAULT."""
    import inspect as _inspect

    gate_sig = _inspect.signature(gate._should_promote)
    assert gate_sig.parameters["fitness_margin_floor"].default == gate._FITNESS_MARGIN_FLOOR_DEFAULT


def test_main_threads_e4_fields_into_both_sinks() -> None:
    """The decomposition + verdict must flow into BOTH the attribution row (kwargs
    dict ``**_e4_record_fields``) and the on-promote baseline provenance
    (``power_stats`` bundle) — the two record sinks."""
    source = inspect.getsource(auto_train.main)
    assert "_e4_record_fields: dict[str, Any] = {" in source
    assert "_e4_power_stats = PowerRecordFields.from_evidence(" in source
    # attribution row consumes the kwargs dict; baseline provenance the bundle
    assert "**_e4_record_fields" in source
    assert '"power_stats": _e4_power_stats' in source


# --- record backward-compat: attribution row --------------------------------


def test_attribution_carries_e4_fields() -> None:
    """When supplied, the per-cycle attribution row records the decomposition +
    gain-evidence verdict."""
    from core.self_improving.loop.attribution import compute_attribution

    payload = compute_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        within_mutation_stderr=0.011,
        between_seed_stderr=0.013,
        gain_ci_low=0.04,
        gain_ci_high=0.08,
        gain_ci_excludes_zero=True,
        gain_verdict="gain significant",
    )
    assert payload["within_mutation_stderr"] == pytest.approx(0.011)
    assert payload["between_seed_stderr"] == pytest.approx(0.013)
    assert payload["gain_ci_excludes_zero"] is True
    assert payload["gain_verdict"] == "gain significant"


def test_attribution_m1_omits_within_keeps_between() -> None:
    """M=1: within is unestimated (None) → omitted from the row, but the
    between-seed stderr + the verdict are still present (the row stays useful)."""
    from core.self_improving.loop.attribution import compute_attribution

    payload = compute_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        within_mutation_stderr=None,
        between_seed_stderr=0.013,
        gain_ci_low=-0.01,
        gain_ci_high=0.03,
        gain_ci_excludes_zero=False,
        gain_verdict="no evidence yet",
    )
    assert "within_mutation_stderr" not in payload
    assert payload["between_seed_stderr"] == pytest.approx(0.013)
    assert payload["gain_ci_excludes_zero"] is False


def test_attribution_legacy_omits_all_e4_fields() -> None:
    """A pre-E4 / no-power caller omits every E4 field → the row shape is exactly
    the legacy shape (no new required key breaks a reader)."""
    from core.self_improving.loop.attribution import AttributionRecord, compute_attribution

    payload = compute_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
    )
    for key in (
        "within_mutation_stderr",
        "between_seed_stderr",
        "gain_ci_low",
        "gain_ci_high",
        "gain_ci_excludes_zero",
        "gain_verdict",
    ):
        assert key not in payload
    # and the schema validates the bare payload (defaults to None for the new fields)
    record = AttributionRecord.model_validate(payload)
    assert record.within_mutation_stderr is None
    assert record.gain_ci_excludes_zero is None


# --- record backward-compat: baseline registry row --------------------------


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "BASELINE_PATH", tmp_path / "baseline.json")
    fake_cfg = SimpleNamespace(
        auditor=SimpleNamespace(model="aud-m", source="claude-cli"),
        target=SimpleNamespace(model="tgt-m", source="openai-codex"),
        judge=SimpleNamespace(model="jdg-m", source="claude-cli"),
        mutator=SimpleNamespace(default_model="mut-m", source="openai-codex"),
        seed_select="petri_17dim",
        held_out_bench=None,
        promote_policy="gate",
        promote_policy_seed=0,
        replicate=1,
        target_effect_size=0.02,
    )
    monkeypatch.setattr(auto_train, "_get_autoresearch_config", lambda: fake_cfg)
    return tmp_path


def _rows(archive: Path) -> list[dict]:
    return [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line]


def test_registry_row_records_e4_fields_when_present(isolated: Path) -> None:
    from core.self_improving.loop.statistical_power import PowerRecordFields

    ledger._write_baseline(
        {"broken_tool_use": 3.0},
        {"broken_tool_use": 0.2},
        power_stats=PowerRecordFields(
            within_mutation_stderr=0.011,
            between_seed_stderr=0.013,
            gain_ci_low=0.04,
            gain_ci_high=0.08,
            gain_ci_excludes_zero=True,
            gain_verdict="gain significant",
        ),
    )
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert row["within_mutation_stderr"] == pytest.approx(0.011)
    assert row["between_seed_stderr"] == pytest.approx(0.013)
    assert row["gain_ci_excludes_zero"] is True
    assert row["gain_verdict"] == "gain significant"


def test_registry_row_m1_default_omits_e4_block(isolated: Path) -> None:
    """The default ``_write_baseline`` (no E4 args — the M=1 / pre-E4 path) writes a
    row with NO E4 keys: backward-compatible shape, no new required key."""
    ledger._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    for key in (
        "within_mutation_stderr",
        "between_seed_stderr",
        "gain_ci_low",
        "gain_ci_high",
        "gain_ci_excludes_zero",
        "gain_verdict",
    ):
        assert key not in row


def test_baseline_raw_payload_carries_decomposition(isolated: Path) -> None:
    """The promoted ``baseline.json`` ``raw`` namespace carries the within/between
    decomposition (alongside ``fitness_stderr``) when present — so the next cycle's
    reader sees the noise split, not just the combined stderr."""
    from core.self_improving.loop.statistical_power import PowerRecordFields

    ledger._write_baseline(
        {"broken_tool_use": 3.0},
        {"broken_tool_use": 0.2},
        power_stats=PowerRecordFields(within_mutation_stderr=0.011, between_seed_stderr=0.013),
    )
    anchor = json.loads((isolated / "baseline.json").read_text(encoding="utf-8"))
    assert anchor["raw"]["within_mutation_stderr"] == pytest.approx(0.011)
    assert anchor["raw"]["between_seed_stderr"] == pytest.approx(0.013)


def test_baseline_raw_payload_m1_omits_within(isolated: Path) -> None:
    from core.self_improving.loop.statistical_power import PowerRecordFields

    ledger._write_baseline(
        {"broken_tool_use": 3.0},
        {"broken_tool_use": 0.2},
        power_stats=PowerRecordFields(within_mutation_stderr=None, between_seed_stderr=0.013),
    )
    anchor = json.loads((isolated / "baseline.json").read_text(encoding="utf-8"))
    assert "within_mutation_stderr" not in anchor["raw"]
    assert anchor["raw"]["between_seed_stderr"] == pytest.approx(0.013)
