"""C.7 (2026-05-25) — MutatorContextView invariants (PR-27)."""

from __future__ import annotations

import pytest
from core.self_improving_loop.mutator_context_view import (
    MutatorContextView,
    compose_mutator_context_view,
    source_count,
)

# ---------------------------------------------------------------------------
# 1. Default construction
# ---------------------------------------------------------------------------


def test_default_view_all_empty() -> None:
    view = MutatorContextView()
    assert view.baseline_snapshot is None
    assert view.policy_snapshots == {}
    assert view.program_md == ""
    assert view.meta_review_snapshot is None
    assert view.recent_mutations == []
    assert view.cross_run_key is None


def test_default_view_is_frozen() -> None:
    view = MutatorContextView()
    with pytest.raises(Exception):  # ValidationError on frozen
        view.program_md = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. compose_mutator_context_view
# ---------------------------------------------------------------------------


def test_compose_with_no_args_returns_empty_view() -> None:
    view = compose_mutator_context_view()
    assert source_count(view) == 0


def test_compose_with_baseline_only() -> None:
    view = compose_mutator_context_view(baseline_snapshot={"dim": 1})
    assert view.baseline_snapshot == {"dim": 1}
    assert source_count(view) == 1


def test_compose_with_all_sources() -> None:
    view = compose_mutator_context_view(
        baseline_snapshot={"x": 1},
        policy_snapshots={"prompt": "y"},
        program_md="frontier rules",
        meta_review_snapshot={"meta": True},
        recent_mutations=[{"mut": 1}],
        cross_run_key={"run_id": "r1"},
    )
    assert source_count(view) == 6


def test_compose_policy_snapshots_default_empty() -> None:
    """policy_snapshots=None → {} (graceful)."""
    view = compose_mutator_context_view(policy_snapshots=None)
    assert view.policy_snapshots == {}


def test_compose_recent_mutations_default_empty() -> None:
    view = compose_mutator_context_view(recent_mutations=None)
    assert view.recent_mutations == []


# ---------------------------------------------------------------------------
# 3. source_count
# ---------------------------------------------------------------------------


def test_source_count_empty_view() -> None:
    assert source_count(MutatorContextView()) == 0


def test_source_count_only_baseline() -> None:
    view = MutatorContextView(baseline_snapshot="x")
    assert source_count(view) == 1


def test_source_count_only_program_md() -> None:
    view = MutatorContextView(program_md="content")
    assert source_count(view) == 1


def test_source_count_empty_program_md_not_counted() -> None:
    """program_md="" → not counted (empty string falsy)."""
    view = MutatorContextView(program_md="")
    assert source_count(view) == 0


def test_source_count_empty_dict_not_counted() -> None:
    """policy_snapshots={} → not counted."""
    view = MutatorContextView(policy_snapshots={})
    assert source_count(view) == 0


def test_source_count_empty_list_not_counted() -> None:
    """recent_mutations=[] → not counted."""
    view = MutatorContextView(recent_mutations=[])
    assert source_count(view) == 0


def test_source_count_all_max() -> None:
    """All 6 sources populated → count 6."""
    view = MutatorContextView(
        baseline_snapshot="a",
        policy_snapshots={"k": "v"},
        program_md="md",
        meta_review_snapshot={"m": 1},
        recent_mutations=[1],
        cross_run_key={"k": "v"},
    )
    assert source_count(view) == 6


# ---------------------------------------------------------------------------
# 4. extra="allow" forward-compat
# ---------------------------------------------------------------------------


def test_extra_allow_accepts_future_fields() -> None:
    """신규 source field 추가 시 schema 변경 없이 forward-compat."""
    view = MutatorContextView(future_source="new")  # type: ignore[call-arg]
    # extra="allow" → extra field stored under model_extra
    assert view.model_extra is not None
    assert view.model_extra.get("future_source") == "new"
