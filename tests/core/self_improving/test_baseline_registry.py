"""PR-BASELINE-REGISTRY (2026-05-30) — baseline registry persistence.

Pins the registry writer: every promote appends one ``kind="baseline"`` row to
``baseline_archive.jsonl`` with the measurement criteria the hub serves
(``margin_rule`` discriminator, ``fitness_stderr``, models, seed pool, intrinsic
fitness). Re-implementation of feature/baseline-registry @69b9d95f Phase 1 on
top of the ux-removed / fitness-scale-margin code — see
docs/self-improving/baseline-schema-history.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.self_improving import fitness, ledger
from core.self_improving import train as auto_train
from core.self_improving.loop.observe.role_provenance import build_role_provenance

# Expected registry-row key set — a drift guard so the live writer and the
# backfill script (scripts/backfill_baseline_registry_row.py) cannot silently
# diverge from what the hub reader will consume.
_EXPECTED_ROW_KEYS = {
    "kind",
    "id",
    "ts_utc",
    "commit",
    "session_id",
    "promoted_by",
    "fitness",
    "fitness_stderr",
    "margin_rule",
    "bench",
    "promote_policy",  # E3 — control-arm tag (gate / random / never)
    "promote_policy_seed",  # E3 — RNG seed recorded for the random arm
    "seed_select",
    "seed_count",
    "epoch_hash",  # PR-BASELINE-EPOCH — content-addressed partition discriminator
    "epoch_label",  # be-NNN display label
    "baseline_spec",  # the hashed surface (row self-verifies)
    "spec_schema_version",
    "role_provenance",  # nested {role: {model, source, lane}} — shared SoT
    "eval_archive",
    "dim_means",
}


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``BASELINE_PATH`` to tmp + stub the config so the registry
    writer resolves role models / seed_select without ``~/.geode/config.toml``.
    (The tracked archive/results sinks co-locate to the same tmp via the autouse
    conftest fixture — production keeps them decoupled to the in-repo SoT.)"""
    monkeypatch.setattr(ledger, "BASELINE_PATH", tmp_path / "baseline.json")
    fake_cfg = SimpleNamespace(
        auditor=SimpleNamespace(model="aud-m", source="api_key"),  # → PAYG
        target=SimpleNamespace(model="tgt-m", source="openai-codex"),  # → Subscription
        judge=SimpleNamespace(model="jdg-m", source="claude-cli"),  # → CLI
        mutator=SimpleNamespace(default_model="mut-m", source="openai-codex"),
        seed_select="petri_17dim",
    )
    monkeypatch.setattr(auto_train, "_get_autoresearch_config", lambda: fake_cfg)
    return tmp_path


def _rows(archive: Path) -> list[dict]:
    return [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line]


# --- id sequencing -----------------------------------------------------------


def test_archive_path_follows_baseline_path(isolated: Path) -> None:
    assert ledger._baseline_archive_path() == isolated / "baseline_archive.jsonl"


def test_next_id_starts_at_one_on_empty(isolated: Path) -> None:
    from datetime import UTC, datetime

    assert ledger._next_baseline_id(datetime(2026, 6, 1, tzinfo=UTC)) == "baseline-2606-1"


def test_next_id_counts_only_baseline_rows(isolated: Path) -> None:
    from datetime import UTC, datetime

    archive = isolated / "baseline_archive.jsonl"
    archive.write_text(
        '{"kind": "baseline", "id": "baseline-2606-1"}\n'
        '{"kind": "other", "id": "x"}\n'  # non-baseline row ignored
        "not json at all\n"  # malformed line skipped
        '{"kind": "baseline", "id": "baseline-2606-2"}\n',
        encoding="utf-8",
    )
    assert ledger._next_baseline_id(datetime(2026, 6, 1, tzinfo=UTC)) == "baseline-2606-3"


# --- write_baseline appends a row --------------------------------------------


def test_write_baseline_appends_registry_row(isolated: Path) -> None:
    ledger._write_baseline(
        {"broken_tool_use": 3.0},
        {"broken_tool_use": 0.2},
        sample_count={"broken_tool_use": 16},
        fitness_stderr=0.013,
        eval_archive="/x.eval",
        session_id="sess-1",
        commit="abc123",
    )
    archive = isolated / "baseline_archive.jsonl"
    assert archive.is_file()
    rows = _rows(archive)
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == _EXPECTED_ROW_KEYS
    assert row["kind"] == "baseline"
    assert row["id"] == "baseline-" + row["id"].split("-")[1] + "-1"
    assert row["margin_rule"] == "fitness-stderr"  # live promote stamps the current rule
    assert row["promoted_by"] == "gate"
    assert row["fitness_stderr"] == pytest.approx(0.013)
    assert row["seed_count"] == 16
    assert row["bench"] is False
    prov = row["role_provenance"]
    # per-role model + source + lane (the credential-lane observability)
    assert prov["auditor"] == {"model": "aud-m", "source": "api_key", "lane": "PAYG"}
    assert prov["target"]["lane"] == "Subscription"  # openai-codex
    assert prov["judge"]["lane"] == "CLI"  # claude-cli
    assert prov["mutator"]["model"] == "mut-m"
    assert row["eval_archive"] == "x.eval"  # basename only (no leaked abs path)


def test_write_baseline_stamps_id_into_anchor(isolated: Path) -> None:
    ledger._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    anchor = json.loads((isolated / "baseline.json").read_text(encoding="utf-8"))
    rows = _rows(isolated / "baseline_archive.jsonl")
    # the anchor's baseline_id must equal the registry row's id (links them)
    assert anchor["baseline_id"] == rows[0]["id"]


def test_manual_promote_marks_operator(isolated: Path) -> None:
    ledger._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2}, manual_promote=True)
    assert _rows(isolated / "baseline_archive.jsonl")[0]["promoted_by"] == "operator"


def test_ids_monotonic_across_promotes(isolated: Path) -> None:
    for _ in range(3):
        ledger._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    ids = [r["id"] for r in _rows(isolated / "baseline_archive.jsonl")]
    assert [i.rsplit("-", 1)[1] for i in ids] == ["1", "2", "3"]


def test_fitness_stderr_null_when_absent(isolated: Path) -> None:
    ledger._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    assert _rows(isolated / "baseline_archive.jsonl")[0]["fitness_stderr"] is None


# --- models override (backfill path) -----------------------------------------


def test_models_override_used_for_backfill(isolated: Path) -> None:
    """The backfill path passes models explicitly (a historical baseline's
    config has changed) — they must win over the live config + stamp the
    dim-stderr cohort."""
    ledger._append_baseline_registry_row(
        "baseline-2605-1",
        dim_means={"broken_tool_use": 3.25},
        dim_stderr={"broken_tool_use": 0.3},
        sample_count={"broken_tool_use": 8},
        measurement_modality=None,
        admire_means=None,
        bench_means=None,
        fitness_stderr=None,
        margin_rule="dim-stderr",
        eval_archive="/vanilla.eval",
        session_id="sess-vanilla",
        commit="HEAD",
        ts_utc="2026-05-29T09:18:30Z",
        promoted_by="backfill",
        role_provenance=build_role_provenance(
            {
                "auditor": ("vanilla-aud", "api_key"),
                "target": ("vanilla-tgt", "openai-codex"),
                "judge": ("vanilla-jdg", "api_key"),
                "mutator": ("vanilla-mut", "openai-codex"),
            }
        ),
    )
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert set(row) == _EXPECTED_ROW_KEYS
    assert row["id"] == "baseline-2605-1"
    assert row["margin_rule"] == "dim-stderr"
    assert row["promoted_by"] == "backfill"
    prov = row["role_provenance"]
    assert prov["auditor"] == {"model": "vanilla-aud", "source": "api_key", "lane": "PAYG"}
    assert prov["target"]["lane"] == "Subscription"  # override, not the live cfg
    assert row["seed_count"] == 8


def test_vanilla_and_fixed_rows_coexist_differentiated(isolated: Path) -> None:
    """The deliverable: a dim-stderr (vanilla) row and a fitness-stderr row
    sit in the registry, distinguishable by margin_rule."""
    ledger._append_baseline_registry_row(
        "baseline-2605-1",
        dim_means={"broken_tool_use": 3.25},
        dim_stderr={"broken_tool_use": 0.3},
        sample_count={"broken_tool_use": 8},
        measurement_modality=None,
        admire_means=None,
        bench_means=None,
        fitness_stderr=None,
        margin_rule="dim-stderr",
        eval_archive="/vanilla.eval",
        session_id="sess-vanilla",
        commit="HEAD",
        ts_utc="2026-05-29T09:18:30Z",
        promoted_by="backfill",
        role_provenance=build_role_provenance(
            {
                "auditor": ("v-a", "api_key"),
                "target": ("v-t", "openai-codex"),
                "judge": ("v-j", "claude-cli"),
                "mutator": ("v-m", "openai-codex"),
            }
        ),
    )
    ledger._write_baseline(
        {"broken_tool_use": 2.5}, {"broken_tool_use": 0.1}, sample_count={"broken_tool_use": 16}
    )
    rows = _rows(isolated / "baseline_archive.jsonl")
    rules = {r["margin_rule"] for r in rows}
    assert rules == {"dim-stderr", "fitness-stderr"}
    assert len(rows) == 2


def test_invalid_margin_rule_rejected(isolated: Path) -> None:
    """The shared writer guards the discriminator — a typo must not silently
    land an un-queryable margin_rule."""
    with pytest.raises(ValueError, match="margin_rule"):
        ledger._append_baseline_registry_row(
            "baseline-2606-1",
            dim_means={"broken_tool_use": 3.0},
            dim_stderr={},
            sample_count=None,
            measurement_modality=None,
            admire_means=None,
            bench_means=None,
            fitness_stderr=None,
            margin_rule="dimstderr",  # typo
            eval_archive=None,
            session_id="s",
            commit="c",
            ts_utc="2026-06-01T00:00:00Z",
            promoted_by="backfill",
            role_provenance=build_role_provenance(
                {
                    "auditor": ("a", "api_key"),
                    "target": ("t", "openai-codex"),
                    "judge": ("j", "claude-cli"),
                    "mutator": ("m", "openai-codex"),
                }
            ),
        )


def test_seed_select_override_freezes_historical_pool(isolated: Path) -> None:
    """Backfill freezes the measured pool; the live ``_resolve_seed_select``
    (here stubbed to ``petri_17dim``) must not overwrite it."""
    ledger._append_baseline_registry_row(
        "baseline-2605-1",
        dim_means={"broken_tool_use": 3.0},
        dim_stderr={},
        sample_count=None,
        measurement_modality=None,
        admire_means=None,
        bench_means=None,
        fitness_stderr=None,
        margin_rule="dim-stderr",
        eval_archive=None,
        session_id="s",
        commit="c",
        ts_utc="2026-05-29T09:18:30Z",
        promoted_by="backfill",
        role_provenance=build_role_provenance(
            {
                "auditor": ("a", "api_key"),
                "target": ("t", "openai-codex"),
                "judge": ("j", "claude-cli"),
                "mutator": ("m", "openai-codex"),
            }
        ),
        seed_select="gen-2605-4-unfaithful+gen-2605-3-broken",
    )
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert row["seed_select"] == "gen-2605-4-unfaithful+gen-2605-3-broken"


def test_backfill_script_end_to_end(isolated: Path) -> None:
    """The backfill CLI maps its args onto a registry row (covers arg→row
    mapping, not just the shared helper)."""
    from scripts.backfill_baseline_registry_row import main as backfill_main

    snapshot = isolated / "vanilla.json"
    snapshot.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "session_id": "sess-vanilla",
                "commit": "HEAD",
                "ts_utc": "2026-05-29T09:18:30Z",
                "raw": {
                    "dim_means": {"broken_tool_use": 3.25},
                    "dim_stderr": {"broken_tool_use": 0.3},
                    "sample_count": {"broken_tool_use": 8},
                    "eval_archive": "/vanilla.eval",
                },
                "axes": {"admire_means": None, "bench_means": None, "ux_means": {"x": 1.0}},
            }
        ),
        encoding="utf-8",
    )
    rc = backfill_main(
        [
            "--snapshot",
            str(snapshot),
            "--margin-rule",
            "dim-stderr",
            "--baseline-id",
            "baseline-2605-1",
            "--seed-select",
            "vanilla-pool",
            "--auditor",
            "v-aud",
            "--auditor-source",
            "api_key",
            "--target",
            "v-tgt",
            "--target-source",
            "openai-codex",
            "--judge",
            "v-jdg",
            "--judge-source",
            "api_key",
            "--mutator-model",
            "v-mut",
            "--mutator-source",
            "openai-codex",
        ]
    )
    assert rc == 0
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert set(row) == _EXPECTED_ROW_KEYS
    assert row["id"] == "baseline-2605-1"
    assert row["margin_rule"] == "dim-stderr"
    assert row["seed_select"] == "vanilla-pool"
    prov = row["role_provenance"]
    assert prov["auditor"] == {"model": "v-aud", "source": "api_key", "lane": "PAYG"}
    assert prov["target"] == {"model": "v-tgt", "source": "openai-codex", "lane": "Subscription"}
    assert row["seed_count"] == 8
    assert row["eval_archive"] == "vanilla.eval"  # basename of /vanilla.eval


# --- PR-BASELINE-EPOCH: content-addressed epoch on the row -------------------


def test_row_self_verifies_epoch_hash(isolated: Path) -> None:
    """A stored row recomputes to its own epoch_hash from the stored
    baseline_spec — the content-address can't have been faked at write time."""
    from core.self_improving.loop.observe.baseline_epoch import compute_epoch_hash

    ledger._write_baseline(
        {"broken_tool_use": 3.0}, {"broken_tool_use": 0.1}, sample_count={"broken_tool_use": 16}
    )
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert row["spec_schema_version"] == "2"  # E3 — promote_policy added to spec
    assert compute_epoch_hash(row["baseline_spec"]) == row["epoch_hash"]
    assert row["epoch_label"] == "be-001"  # first epoch seen in this tmp registry


def test_distinct_margin_rules_fall_into_distinct_epochs(isolated: Path) -> None:
    """margin_rule is part of the hashed spec, so the vanilla (dim-stderr) and
    fixed (fitness-stderr) baselines land in DIFFERENT epochs with DIFFERENT
    labels — they must never be averaged into one comparison."""
    ledger._append_baseline_registry_row(
        "baseline-2605-1",
        dim_means={"broken_tool_use": 3.25},
        dim_stderr={"broken_tool_use": 0.3},
        sample_count={"broken_tool_use": 8},
        measurement_modality=None,
        admire_means=None,
        bench_means=None,
        fitness_stderr=None,
        margin_rule="dim-stderr",
        eval_archive=None,
        session_id="sess-vanilla",
        commit="HEAD",
        ts_utc="2026-05-29T09:18:30Z",
        promoted_by="backfill",
        role_provenance=build_role_provenance(
            {
                "auditor": ("aud-m", "api_key"),
                "target": ("tgt-m", "openai-codex"),
                "judge": ("jdg-m", "claude-cli"),
                "mutator": ("mut-m", "openai-codex"),
            }
        ),
        seed_select="petri_17dim",  # same pool as the live fixture → only margin_rule differs
    )
    ledger._write_baseline(  # live path stamps fitness-stderr + the fixture's roles/pool
        {"broken_tool_use": 3.25},
        {"broken_tool_use": 0.3},
        sample_count={"broken_tool_use": 8},
    )
    vanilla, fixed = _rows(isolated / "baseline_archive.jsonl")
    assert vanilla["baseline_spec"]["margin_rule"] == "dim-stderr"
    assert fixed["baseline_spec"]["margin_rule"] == "fitness-stderr"
    assert vanilla["epoch_hash"] != fixed["epoch_hash"]
    assert {vanilla["epoch_label"], fixed["epoch_label"]} == {"be-001", "be-002"}


def test_epoch_label_map_persisted_git_tracked(isolated: Path) -> None:
    """The epoch_hash→be-NNN map is written next to the archive (git-tracked,
    shared) so the label assignment is stable across machines, not a local-only
    in-memory accident."""
    import json as _json

    ledger._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.1})
    label_map = isolated / "baseline_epochs.json"
    assert label_map.is_file()
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert (
        _json.loads(label_map.read_text(encoding="utf-8"))[row["epoch_hash"]] == row["epoch_label"]
    )


# --- PR-BASELINE-LINEAGE: historical-spec override ---------------------------


def _append_minimal(isolated: Path, baseline_id: str, **kw: object) -> dict:
    """Append one row via the low-level writer + return it (extra kw forwarded)."""
    ledger._append_baseline_registry_row(
        baseline_id,
        dim_means={"broken_tool_use": 3.0},
        dim_stderr={"broken_tool_use": 0.2},
        sample_count={"broken_tool_use": 8},
        measurement_modality=None,
        admire_means=None,
        bench_means=None,
        fitness_stderr=None,
        margin_rule="dim-stderr",
        eval_archive=None,
        session_id="s",
        commit="c",
        ts_utc="2026-05-29T09:18:30Z",
        promoted_by="backfill",
        **kw,
    )
    return _rows(isolated / "baseline_archive.jsonl")[-1]


def test_historical_spec_override_yields_distinct_epoch(isolated: Path) -> None:
    """A backfilled baseline with a historical spec (pre-fix version tags +
    legacy policy) hashes to a DIFFERENT epoch than the live-default row, and the
    row records the historical tags it was stamped with."""
    from core.self_improving.loop.observe.baseline_epoch import HistoricalSpecOverride

    live = _append_minimal(isolated, "baseline-2605-9")  # no override → live constants
    legacy = _append_minimal(
        isolated,
        "baseline-2605-1",
        promote_policy="legacy",
        historical_spec=HistoricalSpecOverride(
            fitness_formula_version="0", margin_logic_version="0"
        ),
    )
    assert legacy["baseline_spec"]["fitness_formula_version"] == "0"
    assert legacy["baseline_spec"]["margin_logic_version"] == "0"
    assert legacy["baseline_spec"]["promote_policy"] == "legacy"
    assert legacy["epoch_hash"] != live["epoch_hash"]
    # the live row used the live constants (NOT "0") — byte-identical-live path
    assert live["baseline_spec"]["fitness_formula_version"] == fitness.FITNESS_FORMULA_VERSION
    assert live["baseline_spec"]["promote_policy"] == "gate"


def test_historical_spec_fitness_preserved_not_recomputed(isolated: Path) -> None:
    """A historical baseline's MEASURED fitness is recorded verbatim, NOT
    recomputed under today's compute_fitness (which would overwrite it)."""
    from core.self_improving.loop.observe.baseline_epoch import HistoricalSpecOverride

    recomputed = _append_minimal(isolated, "baseline-2605-8")  # no override → recompute
    preserved = _append_minimal(
        isolated,
        "baseline-2605-1",
        historical_spec=HistoricalSpecOverride(fitness=0.4242),
    )
    assert preserved["fitness"] == 0.4242  # verbatim, not the dim-derived value
    assert recomputed["fitness"] != 0.4242  # live path genuinely recomputed
