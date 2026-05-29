"""C.2 (2026-05-25) — mutations.jsonl reader invariants (PR-12).

Scope: iter_mutations / read_recent_attributions / read_recent_applies 의
- discriminator (kind → ApplyRecord / AttributionRecord)
- kind filter + limit
- malformed row graceful skip
- file 부재 → 빈 iterator
- include_siblings 옵션
- N 최근 ordering (file append-order = chronological)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from core.self_improving_loop.attribution import AttributionRecord
from core.self_improving_loop.mutations_reader import (
    iter_mutations,
    read_recent_applies,
    read_recent_attributions,
)
from core.self_improving_loop.runner import ApplyRecord


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    """Helper — append rows as JSONL."""
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _apply_row(
    mutation_id: str,
    *,
    kind: str = "applied",
    ts: float | None = None,
    group_id: str | None = None,
) -> dict:
    return {
        "ts": ts if ts is not None else time.time(),
        "kind": kind,
        "mutation_id": mutation_id,
        "target_kind": "prompt",
        "target_section": "role",
        "previous_value": "x",
        "new_value": "y",
        **({"group_id": group_id} if group_id else {}),
    }


def _attribution_row(
    mutation_id: str,
    *,
    ts: float | None = None,
    group_id: str | None = None,
) -> dict:
    return {
        "ts": ts if ts is not None else time.time(),
        "kind": "attribution",
        "mutation_id": mutation_id,
        "observed_dim": {"safety": 0.1},
        "ci95": {"safety": 0.05},
        "significant": {"safety": True},
        "attribution_score": 0.3,
        "missing_baseline": False,
        **({"group_id": group_id} if group_id else {}),
    }


# ---------------------------------------------------------------------------
# 1. File absent → empty iterator
# ---------------------------------------------------------------------------


def test_iter_mutations_file_absent_returns_empty(tmp_path: Path) -> None:
    """File 자체 부재 → 빈 iterator (fresh repo / 처음 audit 직전)."""
    missing = tmp_path / "mutations.jsonl"
    assert list(iter_mutations(missing)) == []


def test_read_recent_attributions_file_absent_empty(tmp_path: Path) -> None:
    missing = tmp_path / "mutations.jsonl"
    assert read_recent_attributions(5, missing) == []


def test_read_recent_applies_file_absent_empty(tmp_path: Path) -> None:
    missing = tmp_path / "mutations.jsonl"
    assert read_recent_applies(5, missing) == []


# ---------------------------------------------------------------------------
# 2. Discriminator (kind → record type)
# ---------------------------------------------------------------------------


def test_discriminator_routes_applied_to_apply_record(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_jsonl(log, [_apply_row("m1")])
    rows = list(iter_mutations(log))
    assert len(rows) == 1
    assert isinstance(rows[0], ApplyRecord)
    assert rows[0].mutation_id == "m1"


def test_discriminator_routes_attribution_to_attribution_record(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_jsonl(log, [_attribution_row("m1")])
    rows = list(iter_mutations(log))
    assert len(rows) == 1
    assert isinstance(rows[0], AttributionRecord)
    assert rows[0].mutation_id == "m1"
    assert rows[0].kind == "attribution"


# ---------------------------------------------------------------------------
# 3. Kind filter
# ---------------------------------------------------------------------------


def test_kind_filter_attribution_only(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_jsonl(
        log,
        [
            _apply_row("m1"),
            _attribution_row("m1"),
            _apply_row("m2", kind="applied_sibling"),
            _attribution_row("m2"),
        ],
    )
    rows = list(iter_mutations(log, kinds={"attribution"}))
    assert len(rows) == 2
    assert all(isinstance(r, AttributionRecord) for r in rows)


def test_kind_filter_applied_only_excludes_sibling(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_jsonl(
        log,
        [
            _apply_row("m1", kind="applied"),
            _apply_row("m2", kind="applied_sibling"),
            _apply_row("m3", kind="applied"),
        ],
    )
    rows = list(iter_mutations(log, kinds={"applied"}))
    assert [r.mutation_id for r in rows] == ["m1", "m3"]


# ---------------------------------------------------------------------------
# 4. Limit
# ---------------------------------------------------------------------------


def test_limit_caps_iteration(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_jsonl(log, [_apply_row(f"m{i}") for i in range(10)])
    rows = list(iter_mutations(log, limit=3))
    assert len(rows) == 3
    assert [r.mutation_id for r in rows] == ["m0", "m1", "m2"]


def test_limit_post_filter(tmp_path: Path) -> None:
    """limit 는 kind filter 후 카운트 (filter 후 N row 까지만)."""
    log = tmp_path / "mutations.jsonl"
    _write_jsonl(
        log,
        [
            _apply_row("m1"),
            _attribution_row("m1"),
            _apply_row("m2"),
            _attribution_row("m2"),
            _apply_row("m3"),
        ],
    )
    rows = list(iter_mutations(log, kinds={"applied"}, limit=2))
    assert [r.mutation_id for r in rows] == ["m1", "m2"]


# ---------------------------------------------------------------------------
# 5. Malformed row graceful skip
# ---------------------------------------------------------------------------


def test_malformed_json_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    log = tmp_path / "mutations.jsonl"
    with log.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_apply_row("m1")) + "\n")
        fh.write("not valid json {\n")
        fh.write(json.dumps(_apply_row("m2")) + "\n")
    rows = list(iter_mutations(log))
    assert [r.mutation_id for r in rows] == ["m1", "m2"]


def test_blank_line_skipped(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    with log.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_apply_row("m1")) + "\n")
        fh.write("\n")
        fh.write("   \n")
        fh.write(json.dumps(_apply_row("m2")) + "\n")
    rows = list(iter_mutations(log))
    assert [r.mutation_id for r in rows] == ["m1", "m2"]


def test_non_dict_row_skipped(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    with log.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps([1, 2, 3]) + "\n")  # array, not dict
        fh.write(json.dumps(_apply_row("m1")) + "\n")
    rows = list(iter_mutations(log))
    assert len(rows) == 1
    assert rows[0].mutation_id == "m1"


def test_schema_invalid_row_skipped(tmp_path: Path) -> None:
    """Missing required field (mutation_id) → ValidationError → skip."""
    log = tmp_path / "mutations.jsonl"
    bad_row = {"ts": time.time(), "kind": "applied", "target_kind": "prompt"}
    with log.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(bad_row) + "\n")
        fh.write(json.dumps(_apply_row("m1")) + "\n")
    rows = list(iter_mutations(log))
    assert len(rows) == 1
    assert rows[0].mutation_id == "m1"


def test_unknown_kind_skipped(tmp_path: Path) -> None:
    """Future-added kind → silent skip (forward compat)."""
    log = tmp_path / "mutations.jsonl"
    weird = {"ts": time.time(), "kind": "future_kind_v9", "mutation_id": "m1"}
    with log.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(weird) + "\n")
        fh.write(json.dumps(_apply_row("m1")) + "\n")
    rows = list(iter_mutations(log))
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# 6. Recent ordering (file append-order = chronological)
# ---------------------------------------------------------------------------


def test_read_recent_attributions_returns_last_n(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    rows_to_write = [_attribution_row(f"m{i}", ts=float(i)) for i in range(10)]
    _write_jsonl(log, rows_to_write)
    recent = read_recent_attributions(3, log)
    assert [r.mutation_id for r in recent] == ["m7", "m8", "m9"]


def test_read_recent_applies_skips_attribution_rows(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_jsonl(
        log,
        [
            _apply_row("m1"),
            _attribution_row("m1"),
            _apply_row("m2"),
            _attribution_row("m2"),
        ],
    )
    recent = read_recent_applies(10, log)
    assert [r.mutation_id for r in recent] == ["m1", "m2"]
    assert all(isinstance(r, ApplyRecord) for r in recent)


def test_read_recent_attributions_negative_n_raises(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_jsonl(log, [_attribution_row("m1")])
    with pytest.raises(ValueError, match=r"n must be >= 1"):
        read_recent_attributions(0, log)


def test_read_recent_applies_negative_n_raises(tmp_path: Path) -> None:
    log = tmp_path / "mutations.jsonl"
    _write_jsonl(log, [_apply_row("m1")])
    with pytest.raises(ValueError, match=r"n must be >= 1"):
        read_recent_applies(-3, log)
