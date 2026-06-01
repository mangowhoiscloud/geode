"""PR-BASELINE-LINEAGE (2026-05-30) — versioned baseline stacking storage.

Before the 10-cycle re-measures the hub's baseline side, the storage structure
must serve PREVIOUS + NEW baselines stacked + versioned (each in its own
production-logic epoch). This pins:
  - the ``HistoricalSpecOverride`` mechanism (a backfilled baseline carries its
    TRUE historical spec → its OWN epoch, distinct from today's);
  - the committed vanilla ``baseline-2605-1`` is now the genesis epoch ``be-001``
    (no longer "untagged"), self-verifying, with its measured fitness preserved;
  - the hub renders the versioned lineage (≥2 epochs as separate stacked blocks).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from core.self_improving.loop.baseline_epoch import (
    HistoricalSpecOverride,
    build_baseline_spec,
    compute_epoch_hash,
    seed_pool_content_hash,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
# Canonical paths from core.paths (PR-STATE-SELF-IMPROVING-RENAME 2026-06-01 —
# moved from autoresearch/state to state/autoresearch). _EPOCHS is the sibling
# of the archive, exactly as train.py derives it.
from core.paths import BASELINE_ARCHIVE_PATH as _ARCHIVE  # noqa: E402

_EPOCHS = _ARCHIVE.parent / "baseline_epochs.json"

_ROLE_PROV = {
    "auditor": {"model": "claude-opus-4-8", "source": "api_key"},
    "target": {"model": "gpt-5.5", "source": "openai-codex"},
    "judge": {"model": "claude-opus-4-8", "source": "api_key"},
    "mutator": {"model": "gpt-5.5", "source": "openai-codex"},
}


def _spec(**over: object) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "margin_rule": "fitness-stderr",
        "margin_logic_version": "1",
        "fitness_formula_version": "1",
        "rubric_version": "v3-22dim-PR0",
        "dim_set": "subset",
        "bench": False,
        "role_provenance": _ROLE_PROV,
        "seed_pool_id": "sel-deadbeef",
        "promote_policy": "gate",
    }
    kw.update(over)
    return build_baseline_spec(**kw)


# --- HistoricalSpecOverride → distinct epoch ---------------------------------


def test_historical_version_tags_yield_distinct_epoch() -> None:
    """A pre-fix spec (version "0", dim-stderr, legacy) hashes to a DIFFERENT
    epoch than today's (version "1", fitness-stderr, gate)."""
    live = compute_epoch_hash(_spec())
    legacy = compute_epoch_hash(
        _spec(
            margin_rule="dim-stderr",
            margin_logic_version="0",
            fitness_formula_version="0",
            promote_policy="legacy",
        )
    )
    assert legacy != live


def test_override_dataclass_defaults_are_none() -> None:
    o = HistoricalSpecOverride()
    assert o.fitness_formula_version is None
    assert o.margin_logic_version is None
    assert o.rubric_version is None
    assert o.dim_set is None


# --- the committed vanilla row is the genesis epoch --------------------------


def _committed_rows() -> list[dict[str, Any]]:
    return [
        json.loads(ln) for ln in _ARCHIVE.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]


def test_committed_vanilla_is_genesis_epoch_be001() -> None:
    rows = {r["id"]: r for r in _committed_rows()}
    assert "baseline-2605-1" in rows, "vanilla baseline missing from the registry"
    v = rows["baseline-2605-1"]
    assert v.get("epoch_hash"), "vanilla is still UNTAGGED (no epoch_hash)"
    assert v["epoch_label"] == "be-001"
    assert v["promote_policy"] == "legacy"
    assert v["baseline_spec"]["margin_rule"] == "dim-stderr"
    assert v["baseline_spec"]["fitness_formula_version"] == "0"
    assert v["baseline_spec"]["margin_logic_version"] == "0"
    # row self-verifies: stored spec re-hashes to the stored epoch_hash
    assert compute_epoch_hash(v["baseline_spec"]) == v["epoch_hash"]
    # the measured fitness was PRESERVED (not recomputed under today's formula)
    assert abs(float(v["fitness"]) - 0.7915331427172898) < 1e-12


def test_committed_vanilla_epoch_distinct_from_live_gate() -> None:
    rows = {r["id"]: r for r in _committed_rows()}
    v = rows["baseline-2605-1"]
    live_gate = compute_epoch_hash(_spec(seed_pool_id=seed_pool_content_hash(v.get("seed_select"))))
    assert v["epoch_hash"] != live_gate, "vanilla must not collide with a live gate epoch"


def test_epoch_label_map_records_vanilla() -> None:
    label_map = json.loads(_EPOCHS.read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in _committed_rows()}
    v = rows["baseline-2605-1"]
    assert label_map.get(v["epoch_hash"]) == "be-001"


# --- hub renders the versioned lineage ---------------------------------------


def _load_hub() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_hub_lineage", REPO_ROOT / "scripts" / "build_self_improving_hub.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_hub_renders_two_epoch_versioned_lineage() -> None:
    hub = _load_hub()
    vanilla = {r["id"]: r for r in _committed_rows()}["baseline-2605-1"]
    live = {
        **vanilla,
        "id": "baseline-2606-1",
        "ts_utc": "2026-06-01T00:00:00Z",
        "epoch_hash": "501d6d8de4ef",
        "epoch_label": "be-002",
        "promote_policy": "gate",
        "baseline_spec": {
            **vanilla["baseline_spec"],
            "margin_rule": "fitness-stderr",
            "promote_policy": "gate",
        },
    }
    html = hub._render_baseline_registry_index([vanilla, live])
    assert "be-001" in html and "be-002" in html
    assert "pre-epoch (backfill pending)" not in html  # vanilla is properly tagged
    assert html.count('class="namespace-block"') == 2  # two distinct stacked epochs
    assert "policy <code>legacy</code>" in html  # the version marker is visible
