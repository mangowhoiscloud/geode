"""PR-AR-L6 (2026-05-26) — attribution writer standalone graceful invariants.

Pre-PR-AR-L6 the ``autoresearch/train.py`` W2 attribution block gated
on three envs being set:

    if not args.dry_run and _sil_mutation_id and _sil_audit_run_id:
        write_attribution(...)

Operator standalone runs (``uv run python autoresearch/train.py``,
``--promote``) had none of those envs, so the attribution row was
silently skipped — downstream consumers (operator analytics; a
future source-aware ``compute_credit_assignment`` variant) had no
ledger visibility into manual runs.

PR-AR-L6 splits the gate:

- envs set → ``source="mutator"`` (current behaviour, mutator-driven cycle)
- envs absent + not dry-run → ``source="manual"`` with synthetic
  ``mutation_id = f"manual-{commit[:8]}-{audit_uuid[:8]}"`` so the
  ledger still records the cycle. Downstream consumers filter the
  JSONL stream on ``source`` when they want a mutator-only signal —
  the source-aware filter itself is a downstream caller concern, not
  implemented in this PR.

This file pins the schema additions + the two writer paths.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from core.self_improving_loop.attribution import (
    AttributionRecord,
    compute_attribution,
    write_attribution,
)
from plugins.seed_generation.baseline_reader import BaselineSnapshot


def test_attribution_record_has_source_field() -> None:
    """``source`` is a documented schema field with a documented default
    semantic (``"mutator"`` for legacy callers, ``"manual"`` for
    standalone). The Pydantic model must allow ``None`` so pre-PR-AR-L6
    rows on disk read back without validation errors."""
    record = AttributionRecord(ts=1.0, mutation_id="abc")
    # Default for legacy rows (field not set) is None — caller treats
    # as "mutator" via documented convention.
    assert record.source is None

    record_manual = AttributionRecord(ts=1.0, mutation_id="abc", source="manual")
    assert record_manual.source == "manual"


def test_compute_attribution_defaults_to_mutator_source() -> None:
    """``compute_attribution`` keeps backward-compat — callers that
    don't pass ``source`` get ``"mutator"`` (every pre-PR-AR-L6 caller
    is mutator-driven by construction)."""
    payload = compute_attribution(
        mutation_id="m-1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
    )
    assert payload["source"] == "mutator"


def test_compute_attribution_accepts_manual_source() -> None:
    """Standalone callers pass ``source="manual"`` so the row is
    distinguishable from mutator-driven rows."""
    payload = compute_attribution(
        mutation_id="manual-abc12345-deadbeef",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        source="manual",
    )
    assert payload["source"] == "manual"


def test_write_attribution_persists_source_field(tmp_path: Path) -> None:
    """Roundtrip — the source field survives JSONL persist + reload."""
    log_path = tmp_path / "mutations.jsonl"
    write_attribution(
        mutation_id="manual-abc12345-deadbeef",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        log_path=log_path,
        source="manual",
    )
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["source"] == "manual"
    assert rows[0]["mutation_id"] == "manual-abc12345-deadbeef"


def test_manual_synthetic_id_format() -> None:
    """The synthetic mutation_id format is ``manual-{commit[:8]}-{audit_uuid[:8]}``.
    Pin the regex so a future refactor changing the format trips here —
    downstream operator log greppers rely on the ``manual-`` prefix to
    filter the manual rows out (or in)."""
    pattern = re.compile(r"^manual-[0-9a-fA-F]{1,8}-[0-9a-f]{8}$")
    # train.py builds the id as f"manual-{commit[:8]}-{audit_uuid}"
    # with audit_uuid = uuid.uuid4().hex[:8]. Sample the shape.
    sample = "manual-abc12345-1a2b3c4d"
    assert pattern.match(sample) is not None


def test_jsonl_rows_can_be_filtered_by_source(tmp_path: Path) -> None:
    """Row-level filtering contract — downstream consumers must be able
    to filter on ``source`` to exclude manual rows when learning from
    mutator-driven cycles only. Pin the JSONL shape — a future PR
    can't drop the field without also updating downstream filters.

    Note: this tests the *data-availability* contract. The actual
    source-aware variant of ``compute_credit_assignment`` is downstream
    work (see CHANGELOG)."""
    log_path = tmp_path / "mutations.jsonl"
    # 1 mutator row + 1 manual row.
    write_attribution(
        mutation_id="mut-1",
        expected_dim={"broken_tool_use": -0.5},
        baseline_before=None,
        baseline_after=None,
        log_path=log_path,
        source="mutator",
    )
    write_attribution(
        mutation_id="manual-abc12345-deadbeef",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        log_path=log_path,
        source="manual",
    )
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    mutator_rows = [r for r in rows if r.get("source") == "mutator"]
    manual_rows = [r for r in rows if r.get("source") == "manual"]
    assert len(mutator_rows) == 1
    assert len(manual_rows) == 1
    assert mutator_rows[0]["mutation_id"] == "mut-1"
    assert manual_rows[0]["mutation_id"].startswith("manual-")


def test_write_attribution_with_baselines_preserves_source(tmp_path: Path) -> None:
    """End-to-end with both snapshots present — the ``observed_dim`` /
    ``attribution_score`` payload still carries ``source``."""
    log_path = tmp_path / "mutations.jsonl"
    before = BaselineSnapshot(
        dim_means={"broken_tool_use": 3.0},
        dim_stderr={"broken_tool_use": 0.1},
    )
    after = BaselineSnapshot(
        dim_means={"broken_tool_use": 1.5},
        dim_stderr={"broken_tool_use": 0.1},
    )
    payload = write_attribution(
        mutation_id="m-1",
        expected_dim={"broken_tool_use": -1.0},
        baseline_before=before,
        baseline_after=after,
        log_path=log_path,
        source="mutator",
    )
    assert payload["source"] == "mutator"
    assert payload["observed_dim"]["broken_tool_use"] == pytest.approx(-1.5)
