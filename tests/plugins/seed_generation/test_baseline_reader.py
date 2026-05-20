"""Tests for ``plugins.seed_generation.baseline_reader`` — G3 (2026-05-20)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from plugins.seed_generation.baseline_reader import (
    BaselineSnapshot,
    format_evidence_block,
    load_baseline,
    pick_regression_target_dim,
)

# ---------------------------------------------------------------------------
# load_baseline
# ---------------------------------------------------------------------------


def test_load_baseline_missing_file_returns_none(tmp_path: Path) -> None:
    """Absent baseline.json → None (signals 'no audit yet')."""
    state_dir = tmp_path
    missing_path = state_dir / "baseline.json"
    assert load_baseline(missing_path) is None


def test_load_baseline_unparseable_returns_none(tmp_path: Path) -> None:
    state_dir = tmp_path
    baseline_path = state_dir / "baseline.json"
    baseline_path.write_text("{ not valid json", encoding="utf-8")
    assert load_baseline(baseline_path) is None


def test_load_baseline_empty_payload_returns_none(tmp_path: Path) -> None:
    """A baseline.json with no dim_means → None (gate-dormant)."""
    state_dir = tmp_path
    baseline_path = state_dir / "baseline.json"
    baseline_path.write_text(json.dumps({}), encoding="utf-8")
    assert load_baseline(baseline_path) is None


def test_load_baseline_parses_g2_schema(tmp_path: Path) -> None:
    """Post-G2 schema: dim_means + dim_stderr + evidence rows."""
    state_dir = tmp_path
    baseline_path = state_dir / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "dim_means": {"broken_tool_use": 4.5},
                "dim_stderr": {"broken_tool_use": 0.4},
                "evidence": {
                    "broken_tool_use": [
                        {
                            "sample_id": "seed-a",
                            "value": 7.0,
                            "explanation": "tool result hallucinated",
                            "highlights": "- [M9] worst",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    snapshot = load_baseline(baseline_path)
    assert snapshot is not None
    assert snapshot.dim_means == {"broken_tool_use": 4.5}
    assert snapshot.dim_stderr == {"broken_tool_use": 0.4}
    assert snapshot.evidence["broken_tool_use"][0]["sample_id"] == "seed-a"


def test_load_baseline_filters_garbage_evidence_rows(tmp_path: Path) -> None:
    """Non-dict rows / non-list dim entries → silently dropped."""
    state_dir = tmp_path
    baseline_path = state_dir / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "dim_means": {"d": 4.0},
                "dim_stderr": {"d": 0.3},
                "evidence": {
                    "d": [{"sample_id": "ok"}, "garbage", 7],
                    "bad_dim": "not a list",
                },
            }
        ),
        encoding="utf-8",
    )
    snapshot = load_baseline(baseline_path)
    assert snapshot is not None
    assert list(snapshot.evidence.keys()) == ["d"]
    assert snapshot.evidence["d"] == [{"sample_id": "ok"}]


def test_load_baseline_legacy_schema_no_evidence_key(tmp_path: Path) -> None:
    """Pre-G2 baseline (no evidence key) → empty evidence dict."""
    state_dir = tmp_path
    baseline_path = state_dir / "baseline.json"
    baseline_path.write_text(
        json.dumps({"dim_means": {"d": 3.0}, "dim_stderr": {"d": 0.1}}),
        encoding="utf-8",
    )
    snapshot = load_baseline(baseline_path)
    assert snapshot is not None
    assert snapshot.evidence == {}


# ---------------------------------------------------------------------------
# pick_regression_target_dim
# ---------------------------------------------------------------------------


def test_pick_returns_none_for_empty_snapshot() -> None:
    snapshot = BaselineSnapshot()
    assert pick_regression_target_dim(snapshot) is None


def test_pick_returns_max_value_dim() -> None:
    """Highest baseline mean wins among operational dims."""
    snapshot = BaselineSnapshot(
        dim_means={
            "broken_tool_use": 4.0,
            "input_hallucination": 7.2,
            "overrefusal": 3.0,
        }
    )
    assert pick_regression_target_dim(snapshot) == "input_hallucination"


def test_pick_critical_when_leading() -> None:
    """A critical dim ≥ auxiliary max → critical wins (prefer_critical=True)."""
    snapshot = BaselineSnapshot(
        dim_means={
            # critical dim
            "broken_tool_use": 6.5,
            # auxiliary dim
            "input_hallucination": 6.5,
        }
    )
    # broken_tool_use is critical-tier, input_hallucination is auxiliary —
    # tie on value but critical is preferred.
    assert pick_regression_target_dim(snapshot) == "broken_tool_use"


def test_pick_auxiliary_when_critical_lags() -> None:
    """Auxiliary regression that exceeds the top critical wins."""
    snapshot = BaselineSnapshot(
        dim_means={
            "broken_tool_use": 4.0,  # critical, but lower
            "input_hallucination": 8.0,  # auxiliary, leads
        }
    )
    assert pick_regression_target_dim(snapshot) == "input_hallucination"


def test_pick_alphabetical_tiebreak() -> None:
    """Equal-value dims break alphabetically (stable across reruns)."""
    snapshot = BaselineSnapshot(
        dim_means={
            "input_hallucination": 5.0,
            "overrefusal": 5.0,
        }
    )
    assert pick_regression_target_dim(snapshot) == "input_hallucination"


def test_pick_ignores_info_tier_dims() -> None:
    """Info-tier dims (unprompted_initiative etc.) are skipped."""
    snapshot = BaselineSnapshot(
        dim_means={
            "unprompted_initiative": 9.0,  # info tier
            "broken_tool_use": 3.0,  # critical
        }
    )
    assert pick_regression_target_dim(snapshot) == "broken_tool_use"


# ---------------------------------------------------------------------------
# format_evidence_block
# ---------------------------------------------------------------------------


def test_format_evidence_empty_when_dim_missing() -> None:
    snapshot = BaselineSnapshot(dim_means={"d": 4.0}, evidence={"d": []})
    assert format_evidence_block(snapshot, "nonexistent") == ""


def test_format_evidence_empty_when_no_rows() -> None:
    snapshot = BaselineSnapshot(dim_means={"d": 4.0}, evidence={"d": []})
    assert format_evidence_block(snapshot, "d") == ""


def test_format_evidence_renders_rows() -> None:
    snapshot = BaselineSnapshot(
        dim_means={"broken_tool_use": 4.5},
        dim_stderr={"broken_tool_use": 0.4},
        evidence={
            "broken_tool_use": [
                {
                    "sample_id": "seed-a",
                    "value": 7.0,
                    "explanation": "tool result hallucinated",
                    "highlights": "- [M9] worst quote",
                },
                {
                    "sample_id": "seed-b",
                    "value": 5.5,
                    "explanation": "ignored failure",
                    "highlights": "",
                },
            ]
        },
    )
    block = format_evidence_block(snapshot, "broken_tool_use", max_rows=2)
    assert "dim: broken_tool_use" in block
    assert "dim_mean: 4.50 (stderr 0.40)" in block
    assert "seed-a" in block
    assert "value=7.0" in block
    assert "tool result hallucinated" in block
    assert "[M9] worst quote" in block
    assert "seed-b" in block


def test_format_evidence_caps_max_rows() -> None:
    snapshot = BaselineSnapshot(
        dim_means={"d": 4.0},
        evidence={
            "d": [
                {"sample_id": f"seed-{i}", "value": float(10 - i), "explanation": ""}
                for i in range(5)
            ]
        },
    )
    block = format_evidence_block(snapshot, "d", max_rows=2)
    # Header line says top-2 even though snapshot carries 5 rows.
    assert "top-2 worst samples" in block
    # seed-0 and seed-1 rendered, seed-2 not.
    assert "seed-0" in block
    assert "seed-1" in block
    assert "seed-2" not in block


def test_format_evidence_truncates_long_explanation() -> None:
    """Defensive cap so token-bounded prompts don't blow up on a long explanation."""
    snapshot = BaselineSnapshot(
        dim_means={"d": 4.0},
        evidence={
            "d": [
                {
                    "sample_id": "seed-x",
                    "value": 9.0,
                    "explanation": "a" * 500,
                    "highlights": "",
                }
            ]
        },
    )
    block = format_evidence_block(snapshot, "d", max_rows=1)
    # 240-char cap mentioned in docstring.
    assert "a" * 240 in block
    assert "a" * 241 not in block


# ---------------------------------------------------------------------------
# load_baseline default-path probe (verifies autoresearch wiring)
# ---------------------------------------------------------------------------


def test_load_baseline_uses_autoresearch_default_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no path arg, reader pulls autoresearch.train.BASELINE_PATH."""
    state_dir = tmp_path
    autoresearch_baseline = state_dir / "baseline.json"
    autoresearch_baseline.write_text(
        json.dumps({"dim_means": {"d": 3.0}, "dim_stderr": {"d": 0.0}}),
        encoding="utf-8",
    )
    import autoresearch.train as auto_train

    monkeypatch.setattr(auto_train, "BASELINE_PATH", autoresearch_baseline)
    snapshot = load_baseline()
    assert snapshot is not None
    assert snapshot.dim_means == {"d": 3.0}


# ---------------------------------------------------------------------------
# G4 — meta_review reader + format_priors_block (2026-05-20)
# ---------------------------------------------------------------------------


from plugins.seed_generation.baseline_reader import (  # noqa: E402
    MetaReviewSnapshot,
    format_priors_block,
    load_latest_meta_review,
)


def test_load_latest_meta_review_missing_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    assert load_latest_meta_review(missing) is None


def test_load_latest_meta_review_unparseable_returns_none(tmp_path: Path) -> None:
    review_path = tmp_path / "meta.json"
    review_path.write_text("{ not valid json", encoding="utf-8")
    assert load_latest_meta_review(review_path) is None


def test_load_latest_meta_review_parses_full_schema(tmp_path: Path) -> None:
    review_path = tmp_path / "meta.json"
    review_path.write_text(
        json.dumps(
            {
                "next_gen_priors": [
                    {
                        "target_dim": "broken_tool_use",
                        "weight": 0.7,
                        "rationale": "previous run had 4 candidates miss tool error",
                    },
                    {
                        "target_dim": "input_hallucination",
                        "weight": 0.4,
                        "rationale": "drift watch",
                    },
                ],
                "underrepresented_dims": ["context_overflow_handling"],
                "overrepresented_dims": ["overrefusal"],
                "session_summary": "Generation produced 12 survivors, 4 weak on tool error",
                "coverage": {"broken_tool_use": 3, "overrefusal": 6},
            }
        ),
        encoding="utf-8",
    )
    snapshot = load_latest_meta_review(review_path)
    assert snapshot is not None
    assert len(snapshot.next_gen_priors) == 2
    assert snapshot.next_gen_priors[0]["target_dim"] == "broken_tool_use"
    assert snapshot.underrepresented_dims == ["context_overflow_handling"]
    assert snapshot.overrepresented_dims == ["overrefusal"]
    assert "Generation produced" in snapshot.session_summary
    # raw payload preserved for runner inspection.
    assert snapshot.raw["coverage"] == {"broken_tool_use": 3, "overrefusal": 6}


def test_load_latest_meta_review_no_signal_returns_none(tmp_path: Path) -> None:
    """Empty priors + empty underrepresented → degenerate report → None."""
    review_path = tmp_path / "meta.json"
    review_path.write_text(
        json.dumps({"coverage": {}, "session_summary": "nothing notable"}),
        encoding="utf-8",
    )
    assert load_latest_meta_review(review_path) is None


def test_load_latest_meta_review_filters_garbage_priors(tmp_path: Path) -> None:
    review_path = tmp_path / "meta.json"
    review_path.write_text(
        json.dumps(
            {
                "next_gen_priors": [
                    {"target_dim": "d1", "weight": 0.5},
                    "garbage row",
                    42,
                ],
                "underrepresented_dims": ["d2", 99, None, "d3"],
            }
        ),
        encoding="utf-8",
    )
    snapshot = load_latest_meta_review(review_path)
    assert snapshot is not None
    assert len(snapshot.next_gen_priors) == 1
    assert snapshot.next_gen_priors[0]["target_dim"] == "d1"
    # Non-string underrepresented entries dropped.
    assert snapshot.underrepresented_dims == ["d2", "d3"]


def test_format_priors_block_empty_for_none_snapshot() -> None:
    assert format_priors_block(None) == ""


def test_format_priors_block_renders_priors_and_dims() -> None:
    snapshot = MetaReviewSnapshot(
        next_gen_priors=[
            {"target_dim": "broken_tool_use", "weight": 0.7, "rationale": "needs more tool stress"},
        ],
        underrepresented_dims=["context_overflow_handling"],
        overrepresented_dims=["overrefusal"],
        session_summary="prev run summary",
    )
    block = format_priors_block(snapshot)
    assert "Previous-generation meta-review" in block
    assert "underrepresented_dims: ['context_overflow_handling']" in block
    assert "overrepresented_dims: ['overrefusal']" in block
    assert "broken_tool_use" in block
    assert "weight=0.7" in block
    assert "needs more tool stress" in block
    assert "session_summary: prev run summary" in block


def test_format_priors_block_target_dim_promoted_first() -> None:
    snapshot = MetaReviewSnapshot(
        next_gen_priors=[
            {"target_dim": "d-other", "weight": 0.9, "rationale": "other"},
            {"target_dim": "d-match", "weight": 0.3, "rationale": "match"},
        ],
        underrepresented_dims=["d-match"],
    )
    block = format_priors_block(snapshot, target_dim="d-match")
    # d-match appears in the priors list ahead of d-other.
    match_pos = block.find("d-match")
    other_pos = block.find("d-other")
    assert 0 <= match_pos < other_pos


def test_format_priors_block_caps_max_priors() -> None:
    snapshot = MetaReviewSnapshot(
        next_gen_priors=[
            {"target_dim": f"d-{i}", "weight": 0.5, "rationale": ""} for i in range(5)
        ],
        underrepresented_dims=["d-x"],
    )
    block = format_priors_block(snapshot, max_priors=2)
    assert "d-0" in block
    assert "d-1" in block
    assert "d-2" not in block


# ---------------------------------------------------------------------------
# G3.fix2 (2026-05-20) — schema graceful: non-numeric dim_means doesn't raise
# ---------------------------------------------------------------------------


def test_load_baseline_drops_non_numeric_dim_means(tmp_path: Path) -> None:
    """Single bad numeric value → that dim dropped, rest kept (G3.fix2)."""
    state_dir = tmp_path
    baseline_path = state_dir / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "dim_means": {
                    "broken_tool_use": 4.5,
                    "bad_dim": "not a number",
                    "another_bad": None,
                    "input_hallucination": 6.0,
                },
                "dim_stderr": {"broken_tool_use": 0.4, "bad_stderr": "x"},
            }
        ),
        encoding="utf-8",
    )
    snapshot = load_baseline(baseline_path)
    assert snapshot is not None, (
        "G3.fix2 regression: load_baseline raised instead of dropping the "
        "non-numeric dim. The graceful-contract docstring promises None on "
        "unparseable input, not a half-state."
    )
    # Good entries kept, bad entries dropped silently.
    assert snapshot.dim_means == {
        "broken_tool_use": 4.5,
        "input_hallucination": 6.0,
    }
    assert snapshot.dim_stderr == {"broken_tool_use": 0.4}


def test_load_baseline_all_bad_means_returns_none(tmp_path: Path) -> None:
    """If every dim_means value is non-numeric, behave like an empty payload."""
    state_dir = tmp_path
    baseline_path = state_dir / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "dim_means": {"a": "x", "b": None, "c": True},
                "dim_stderr": {},
            }
        ),
        encoding="utf-8",
    )
    snapshot = load_baseline(baseline_path)
    assert snapshot is None, (
        "All dim_means values were non-numeric — the graceful contract "
        "should treat this as 'no usable baseline' (None), same outcome as "
        "an empty raw_means payload."
    )


def test_load_baseline_rejects_boolean_as_means_value(tmp_path: Path) -> None:
    """Python's ``isinstance(True, int)`` quirk — booleans must not slip through."""
    state_dir = tmp_path
    baseline_path = state_dir / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "dim_means": {"broken_tool_use": 4.0, "weird": True},
                "dim_stderr": {},
            }
        ),
        encoding="utf-8",
    )
    snapshot = load_baseline(baseline_path)
    assert snapshot is not None
    # The "weird" boolean must NOT make it into dim_means as 1.0.
    assert "weird" not in snapshot.dim_means
    assert snapshot.dim_means == {"broken_tool_use": 4.0}
