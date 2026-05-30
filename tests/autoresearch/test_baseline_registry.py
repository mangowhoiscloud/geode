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

from autoresearch import train as auto_train

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
    "seed_select",
    "seed_count",
    "auditor_model",
    "target_model",
    "judge_model",
    "mutator_model",
    "mutator_source",
    "eval_archive",
    "dim_means",
}


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``BASELINE_PATH`` to tmp + stub the config so the registry
    writer resolves role models / seed_select without ``~/.geode/config.toml``."""
    monkeypatch.setattr(auto_train, "BASELINE_PATH", tmp_path / "baseline.json")
    fake_cfg = SimpleNamespace(
        auditor=SimpleNamespace(model="aud-m"),
        target=SimpleNamespace(model="tgt-m"),
        judge=SimpleNamespace(model="jdg-m"),
        mutator=SimpleNamespace(default_model="mut-m", source="mut-src"),
        seed_select="petri_17dim",
    )
    monkeypatch.setattr(auto_train, "_get_autoresearch_config", lambda: fake_cfg)
    return tmp_path


def _rows(archive: Path) -> list[dict]:
    return [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line]


# --- id sequencing -----------------------------------------------------------


def test_archive_path_follows_baseline_path(isolated: Path) -> None:
    assert auto_train._baseline_archive_path() == isolated / "baseline_archive.jsonl"


def test_next_id_starts_at_one_on_empty(isolated: Path) -> None:
    from datetime import UTC, datetime

    assert auto_train._next_baseline_id(datetime(2026, 6, 1, tzinfo=UTC)) == "baseline-2606-1"


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
    assert auto_train._next_baseline_id(datetime(2026, 6, 1, tzinfo=UTC)) == "baseline-2606-3"


# --- write_baseline appends a row --------------------------------------------


def test_write_baseline_appends_registry_row(isolated: Path) -> None:
    auto_train._write_baseline(
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
    assert row["auditor_model"] == "aud-m"
    assert row["mutator_source"] == "mut-src"
    assert row["eval_archive"] == "/x.eval"


def test_write_baseline_stamps_id_into_anchor(isolated: Path) -> None:
    auto_train._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    anchor = json.loads((isolated / "baseline.json").read_text(encoding="utf-8"))
    rows = _rows(isolated / "baseline_archive.jsonl")
    # the anchor's baseline_id must equal the registry row's id (links them)
    assert anchor["baseline_id"] == rows[0]["id"]


def test_manual_promote_marks_operator(isolated: Path) -> None:
    auto_train._write_baseline(
        {"broken_tool_use": 3.0}, {"broken_tool_use": 0.2}, manual_promote=True
    )
    assert _rows(isolated / "baseline_archive.jsonl")[0]["promoted_by"] == "operator"


def test_ids_monotonic_across_promotes(isolated: Path) -> None:
    for _ in range(3):
        auto_train._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    ids = [r["id"] for r in _rows(isolated / "baseline_archive.jsonl")]
    assert [i.rsplit("-", 1)[1] for i in ids] == ["1", "2", "3"]


def test_fitness_stderr_null_when_absent(isolated: Path) -> None:
    auto_train._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    assert _rows(isolated / "baseline_archive.jsonl")[0]["fitness_stderr"] is None


# --- models override (backfill path) -----------------------------------------


def test_models_override_used_for_backfill(isolated: Path) -> None:
    """The backfill path passes models explicitly (a historical baseline's
    config has changed) — they must win over the live config + stamp the
    dim-stderr cohort."""
    auto_train._append_baseline_registry_row(
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
        models={
            "auditor": "vanilla-aud",
            "target": "vanilla-tgt",
            "judge": "vanilla-jdg",
            "mutator_model": "vanilla-mut",
            "mutator_source": "vanilla-src",
        },
    )
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert set(row) == _EXPECTED_ROW_KEYS
    assert row["id"] == "baseline-2605-1"
    assert row["margin_rule"] == "dim-stderr"
    assert row["promoted_by"] == "backfill"
    assert row["auditor_model"] == "vanilla-aud"  # override, not the live "aud-m"
    assert row["seed_count"] == 8


def test_vanilla_and_fixed_rows_coexist_differentiated(isolated: Path) -> None:
    """The deliverable: a dim-stderr (vanilla) row and a fitness-stderr row
    sit in the registry, distinguishable by margin_rule."""
    auto_train._append_baseline_registry_row(
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
        models={
            "auditor": "v-a",
            "target": "v-t",
            "judge": "v-j",
            "mutator_model": "v-m",
            "mutator_source": "v-s",
        },
    )
    auto_train._write_baseline(
        {"broken_tool_use": 2.5}, {"broken_tool_use": 0.1}, sample_count={"broken_tool_use": 16}
    )
    rows = _rows(isolated / "baseline_archive.jsonl")
    rules = {r["margin_rule"] for r in rows}
    assert rules == {"dim-stderr", "fitness-stderr"}
    assert len(rows) == 2
