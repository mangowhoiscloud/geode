"""ADR-012 M4.3 — DPO pack stats invariants.

Pins:
- ``pack_stats`` returns an empty dict for missing / empty / all-malformed
  packs (graceful).
- For a parseable pack, the returned dict carries the documented keys
  with correct math (count + delta min/max/mean/median + source
  histograms + unique_prompts).
- Malformed rows are silently dropped (consistent with the rest of M4).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from core.self_improving_loop.dpo_stats import pack_stats


@pytest.fixture
def pack_path(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "pack.jsonl"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_pack_stats_missing_file_returns_empty(tmp_path: Path) -> None:
    assert pack_stats(tmp_path / "nope.jsonl") == {}


def test_pack_stats_empty_file_returns_empty(pack_path: Path) -> None:
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text("", encoding="utf-8")
    assert pack_stats(pack_path) == {}


def test_pack_stats_all_malformed_returns_empty(pack_path: Path) -> None:
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text(
        "\n".join(["not json", json.dumps(["array not dict"]), '{"missing": "fields"}']),
        encoding="utf-8",
    )
    assert pack_stats(pack_path) == {}


def test_pack_stats_basic_aggregates(pack_path: Path) -> None:
    _write(
        pack_path,
        [
            {
                "prompt": "q1",
                "fitness_delta": 0.6,
                "source_chosen": "petri",
                "source_rejected": "live",
            },
            {
                "prompt": "q2",
                "fitness_delta": 0.4,
                "source_chosen": "petri",
                "source_rejected": "live",
            },
            {
                "prompt": "q3",
                "fitness_delta": 0.8,
                "source_chosen": "live",
                "source_rejected": "petri",
            },
        ],
    )
    stats = pack_stats(pack_path)
    assert stats["pair_count"] == 3
    assert stats["unique_prompts"] == 3
    assert stats["fitness_delta_min"] == 0.4
    assert stats["fitness_delta_max"] == 0.8
    assert stats["fitness_delta_mean"] == pytest.approx((0.6 + 0.4 + 0.8) / 3)
    assert stats["fitness_delta_median"] == 0.6
    assert stats["source_chosen_histogram"] == {"petri": 2, "live": 1}
    assert stats["source_rejected_histogram"] == {"live": 2, "petri": 1}


def test_pack_stats_unique_prompt_count(pack_path: Path) -> None:
    """Same prompt repeated → unique_prompts < pair_count."""
    _write(
        pack_path,
        [
            {"prompt": "q1", "fitness_delta": 0.5},
            {"prompt": "q1", "fitness_delta": 0.3},  # duplicate prompt
            {"prompt": "q2", "fitness_delta": 0.7},
        ],
    )
    stats = pack_stats(pack_path)
    assert stats["pair_count"] == 3
    assert stats["unique_prompts"] == 2


def test_pack_stats_drops_rows_without_required_fields(pack_path: Path) -> None:
    """Rows missing prompt / fitness_delta / wrong type → dropped silently."""
    _write(
        pack_path,
        [
            {"prompt": "q1", "fitness_delta": 0.5},
            {"prompt": "q2"},  # missing fitness_delta
            {"fitness_delta": 0.6},  # missing prompt
            {"prompt": "q3", "fitness_delta": "not_a_number"},  # bad type
            {"prompt": "q4", "fitness_delta": 0.9},
        ],
    )
    stats = pack_stats(pack_path)
    assert stats["pair_count"] == 2  # only the 2 valid rows
    assert stats["unique_prompts"] == 2


def test_pack_stats_int_delta_accepted(pack_path: Path) -> None:
    """``fitness_delta`` as int still counts (numeric coerce)."""
    _write(
        pack_path,
        [{"prompt": "q", "fitness_delta": 1}],
    )
    stats = pack_stats(pack_path)
    assert stats["pair_count"] == 1
    assert stats["fitness_delta_min"] == 1.0


def test_pack_stats_handles_missing_source_tags(pack_path: Path) -> None:
    """Rows without source_* fields → histogram has empty-string bucket."""
    _write(
        pack_path,
        [{"prompt": "q", "fitness_delta": 0.5}],
    )
    stats = pack_stats(pack_path)
    assert stats["source_chosen_histogram"] == {"": 1}
    assert stats["source_rejected_histogram"] == {"": 1}
