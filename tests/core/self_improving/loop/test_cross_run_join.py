"""C.6 (2026-05-25) — cross-run SoT 3중첩 unification invariants (PR-26)."""

from __future__ import annotations

import json
from pathlib import Path

from core.self_improving.loop.cross_run_join import (
    CrossRunJoinKey,
    compose_history_view,
    keys_match,
    load_cross_run_join_key,
)

# ---------------------------------------------------------------------------
# 1. CrossRunJoinKey — schema
# ---------------------------------------------------------------------------


def test_key_minimal_construction() -> None:
    key = CrossRunJoinKey(run_id="r1", gen_tag="g1")
    assert key.run_id == "r1"
    assert key.gen_tag == "g1"
    assert key.source_label == ""  # default


def test_key_with_source_label() -> None:
    key = CrossRunJoinKey(run_id="r1", gen_tag="g1", source_label="latest_pointer")
    assert key.source_label == "latest_pointer"


def test_key_is_frozen() -> None:
    """Pydantic frozen=True — immutable after construction."""
    key = CrossRunJoinKey(run_id="r1", gen_tag="g1")
    import pytest

    with pytest.raises(Exception):  # ValidationError
        key.run_id = "r2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. load_cross_run_join_key — latest_pointer reader
# ---------------------------------------------------------------------------


def test_load_missing_pointer_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "latest_pointer.json"
    assert load_cross_run_join_key(missing) is None


def test_load_valid_pointer_returns_key(tmp_path: Path) -> None:
    pointer = tmp_path / "latest_pointer.json"
    pointer.write_text(
        json.dumps({"version": 1, "run_id": "2026-05-25", "gen_tag": "g7"}),
        encoding="utf-8",
    )
    key = load_cross_run_join_key(pointer)
    assert key is not None
    assert key.run_id == "2026-05-25"
    assert key.gen_tag == "g7"
    assert key.source_label == "latest_pointer"


def test_load_malformed_returns_none(tmp_path: Path) -> None:
    pointer = tmp_path / "latest_pointer.json"
    pointer.write_text("not json {", encoding="utf-8")
    assert load_cross_run_join_key(pointer) is None


def test_load_missing_run_id_returns_none(tmp_path: Path) -> None:
    pointer = tmp_path / "latest_pointer.json"
    pointer.write_text(json.dumps({"gen_tag": "g1"}), encoding="utf-8")
    assert load_cross_run_join_key(pointer) is None


def test_load_missing_gen_tag_returns_none(tmp_path: Path) -> None:
    pointer = tmp_path / "latest_pointer.json"
    pointer.write_text(json.dumps({"run_id": "r1"}), encoding="utf-8")
    assert load_cross_run_join_key(pointer) is None


def test_load_non_dict_payload_returns_none(tmp_path: Path) -> None:
    pointer = tmp_path / "latest_pointer.json"
    pointer.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_cross_run_join_key(pointer) is None


# ---------------------------------------------------------------------------
# 3. keys_match
# ---------------------------------------------------------------------------


def test_keys_match_identical() -> None:
    a = CrossRunJoinKey(run_id="r1", gen_tag="g1", source_label="A")
    b = CrossRunJoinKey(run_id="r1", gen_tag="g1", source_label="B")
    assert keys_match(a, b) is True


def test_keys_match_different_run_id() -> None:
    a = CrossRunJoinKey(run_id="r1", gen_tag="g1")
    b = CrossRunJoinKey(run_id="r2", gen_tag="g1")
    assert keys_match(a, b) is False


def test_keys_match_different_gen_tag() -> None:
    a = CrossRunJoinKey(run_id="r1", gen_tag="g1")
    b = CrossRunJoinKey(run_id="r1", gen_tag="g2")
    assert keys_match(a, b) is False


def test_keys_match_none_returns_false() -> None:
    a = CrossRunJoinKey(run_id="r1", gen_tag="g1")
    assert keys_match(a, None) is False
    assert keys_match(None, a) is False
    assert keys_match(None, None) is False


# ---------------------------------------------------------------------------
# 4. compose_history_view
# ---------------------------------------------------------------------------


def test_compose_history_filters_matching_rows() -> None:
    key = CrossRunJoinKey(run_id="r1", gen_tag="g1")
    rows = [
        {"run_id": "r1", "gen_tag": "g1", "data": "A"},  # match
        {"run_id": "r2", "gen_tag": "g1", "data": "B"},  # different run_id
        {"run_id": "r1", "gen_tag": "g2", "data": "C"},  # different gen_tag
        {"run_id": "r1", "gen_tag": "g1", "data": "D"},  # match
    ]
    result = list(compose_history_view(key, rows))
    assert len(result) == 2
    assert [r["data"] for r in result] == ["A", "D"]


def test_compose_history_empty_iterator() -> None:
    key = CrossRunJoinKey(run_id="r1", gen_tag="g1")
    assert list(compose_history_view(key, [])) == []


def test_compose_history_skips_rows_missing_keys() -> None:
    """Rows lacking run_id or gen_tag → skip (forward-compat)."""
    key = CrossRunJoinKey(run_id="r1", gen_tag="g1")
    rows = [
        {"run_id": "r1", "gen_tag": "g1"},  # match
        {"run_id": "r1"},  # missing gen_tag
        {"gen_tag": "g1"},  # missing run_id
        {"unrelated": "x"},  # neither
    ]
    result = list(compose_history_view(key, rows))
    assert len(result) == 1


def test_compose_history_skips_non_dict_rows() -> None:
    """Non-dict items in iterator → skip (defensive)."""
    key = CrossRunJoinKey(run_id="r1", gen_tag="g1")
    rows = [
        {"run_id": "r1", "gen_tag": "g1"},
        "not a dict",  # type: ignore[list-item]
        ["also not a dict"],
        None,
    ]
    result = list(compose_history_view(key, rows))  # type: ignore[arg-type]
    assert len(result) == 1


# ---------------------------------------------------------------------------
# 5. End-to-end — latest_pointer → join key → history filter
# ---------------------------------------------------------------------------


def test_pipeline_pointer_to_history_filter(tmp_path: Path) -> None:
    """latest_pointer.json 의 key 로 sessions.jsonl iterator 필터."""
    pointer = tmp_path / "latest_pointer.json"
    pointer.write_text(
        json.dumps({"version": 1, "run_id": "R-9", "gen_tag": "G-3"}),
        encoding="utf-8",
    )
    key = load_cross_run_join_key(pointer)
    assert key is not None

    sessions = [
        {"run_id": "R-9", "gen_tag": "G-3", "row": 0},
        {"run_id": "R-9", "gen_tag": "G-2", "row": 1},
        {"run_id": "R-8", "gen_tag": "G-3", "row": 2},
        {"run_id": "R-9", "gen_tag": "G-3", "row": 3},
    ]
    matched = list(compose_history_view(key, sessions))
    assert [r["row"] for r in matched] == [0, 3]
