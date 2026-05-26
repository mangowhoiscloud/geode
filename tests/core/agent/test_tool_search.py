"""CL-A2 — ``core.agent.tool_search`` invariants.

Pins the Wilson score interval LB math, the
``find_recommended_tools`` aggregation contract, and the rendered
``<tool-ranking>`` block shape. Graceful no-op on empty / malformed
input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest
from core.agent.tool_search import (
    MIN_INVOCATIONS,
    WILSON_THRESHOLD,
    ToolRanking,
    find_recommended_tools,
    format_tool_ranking_block,
    wilson_lower_bound,
)

from core.agent import tool_search


@dataclass
class _FakeEpisode:
    """Minimal duck-typed Episode for the aggregator's getattr lookups."""

    tool_name: str
    success: bool


def test_module_exports_stable():
    expected = {
        "MIN_INVOCATIONS",
        "RECENT_WINDOW",
        "ToolRanking",
        "WILSON_CONFIDENCE",
        "WILSON_THRESHOLD",
        "find_recommended_tools",
        "format_tool_ranking_block",
        "load_recent_episodes",
        "wilson_lower_bound",
    }
    assert set(tool_search.__all__) == expected


# ── Wilson lower-bound math ───────────────────────────────────────────


def test_wilson_lb_zero_total_returns_zero():
    assert wilson_lower_bound(0, 0) == 0.0
    assert wilson_lower_bound(5, 0) == 0.0  # successes ignored when total<=0


def test_wilson_lb_all_failures_returns_zero():
    """0 successes out of N → LB clamps to 0 (formula gives slightly negative)."""
    assert wilson_lower_bound(0, 10) == 0.0


def test_wilson_lb_all_successes_below_raw_for_small_n():
    """5/5 (100%) penalised vs 100/100 — small sample → wider CI → lower LB."""
    small = wilson_lower_bound(5, 5)
    big = wilson_lower_bound(100, 100)
    assert 0.0 < small < big
    # Concrete pin against the published formula (Wilson 1927, z≈1.9600).
    assert math.isclose(small, 0.5655175, rel_tol=1e-4)
    assert math.isclose(big, 0.9630065, rel_tol=1e-4)


def test_wilson_lb_converges_to_success_rate_as_n_grows():
    """For p=0.9, LB(9/10) < LB(90/100) < LB(900/1000) ≈ 0.88."""
    a = wilson_lower_bound(9, 10)
    b = wilson_lower_bound(90, 100)
    c = wilson_lower_bound(900, 1000)
    assert a < b < c < 0.9
    # 1000 trials at p=0.9 — Wilson LB lands within ~2.1pp of the raw rate.
    assert 0.9 - c < 0.03, f"LB(900/1000)={c} should be within 3% of 0.9"


def test_wilson_lb_result_in_unit_interval():
    """Across a range of inputs the LB must stay in [0, 1]."""
    for s in (0, 1, 3, 7, 10):
        for n in (1, 5, 10, 50, 100):
            if s > n:
                continue
            lb = wilson_lower_bound(s, n)
            assert 0.0 <= lb <= 1.0


# ── find_recommended_tools aggregation ───────────────────────────────


def _make_episodes(*pairs: tuple[str, bool]) -> list[_FakeEpisode]:
    return [_FakeEpisode(tool_name=n, success=ok) for n, ok in pairs]


def test_find_recommended_empty_episodes_returns_empty():
    assert find_recommended_tools([], top_k=5) == []


def test_find_recommended_top_k_zero_returns_empty():
    eps = _make_episodes(("read", True), ("read", True), ("read", True))
    assert find_recommended_tools(eps, top_k=0) == []
    assert find_recommended_tools(eps, top_k=-1) == []


def test_find_recommended_min_invocations_gate():
    """Single-call success → excluded even if 100% success rate."""
    eps = _make_episodes(("read", True))
    ranks = find_recommended_tools(eps, top_k=5)
    assert ranks == [], "below MIN_INVOCATIONS must be excluded"


def test_find_recommended_below_wilson_threshold_excluded():
    """4/5 (80% raw, LB ~0.376) is below default 0.5 threshold."""
    eps = _make_episodes(*[("read", True)] * 4, ("read", False))
    ranks = find_recommended_tools(eps, top_k=5)
    assert ranks == [], "Wilson LB < 0.5 must be excluded"


def test_find_recommended_passing_wilson_threshold_surfaces():
    """100% across 10 calls → LB ~0.722, well above 0.5."""
    eps = _make_episodes(*[("read", True)] * 10)
    ranks = find_recommended_tools(eps, top_k=5)
    assert len(ranks) == 1
    r = ranks[0]
    assert r.tool_name == "read"
    assert r.success_count == 10
    assert r.total == 10
    assert r.success_rate == 1.0
    assert r.wilson_lb >= WILSON_THRESHOLD


def test_find_recommended_sorted_by_wilson_lb_desc():
    """Higher Wilson LB ranks first; ties broken by total desc."""
    eps = _make_episodes(
        *[("read", True)] * 50,  # 50/50, LB ~0.929
        *[("bash", True)] * 10,  # 10/10, LB ~0.722
        *[("grep", True)] * 5,  # 5/5, LB ~0.565
    )
    ranks = find_recommended_tools(eps, top_k=5)
    names = [r.tool_name for r in ranks]
    assert names == ["read", "bash", "grep"]


def test_find_recommended_top_k_truncates():
    eps = _make_episodes(
        *[("a", True)] * 20,
        *[("b", True)] * 15,
        *[("c", True)] * 10,
        *[("d", True)] * 5,
    )
    ranks = find_recommended_tools(eps, top_k=2)
    assert len(ranks) == 2
    assert [r.tool_name for r in ranks] == ["a", "b"]


def test_find_recommended_skips_malformed_rows():
    """Non-string tool_name or non-bool success → drop, don't crash."""
    eps: list[object] = list(_make_episodes(*[("read", True)] * 5))
    eps.append(_FakeEpisode(tool_name="", success=True))  # empty name
    eps.append(_FakeEpisode(tool_name=None, success=True))  # type: ignore[arg-type]
    eps.append(_FakeEpisode(tool_name="x", success="yes"))  # type: ignore[arg-type]
    ranks = find_recommended_tools(eps, top_k=5)
    assert len(ranks) == 1
    assert ranks[0].tool_name == "read"


def test_find_recommended_mixed_success_failure_pair():
    """A tool with 8 successes out of 10 (LB ~0.490) is just under
    threshold; with 9/10 (LB ~0.596) it passes."""
    eps_8 = _make_episodes(*[("foo", True)] * 8, *[("foo", False)] * 2)
    eps_9 = _make_episodes(*[("foo", True)] * 9, ("foo", False))
    assert find_recommended_tools(eps_8, top_k=5) == [], "8/10 below threshold"
    ranks = find_recommended_tools(eps_9, top_k=5)
    assert len(ranks) == 1 and ranks[0].tool_name == "foo"


def test_find_recommended_min_invocations_param_override():
    eps = _make_episodes(("read", True), ("read", True))  # only 2 calls
    # default MIN_INVOCATIONS=3 → empty
    assert find_recommended_tools(eps, top_k=5) == []
    # lowered to 2 → surfaces (Wilson LB(2,2) ~0.342 — still below 0.5
    # threshold, so loosen that too).
    ranks = find_recommended_tools(eps, top_k=5, min_invocations=2, wilson_threshold=0.0)
    assert len(ranks) == 1
    assert ranks[0].success_count == 2


# ── format_tool_ranking_block ────────────────────────────────────────


def test_format_block_empty_input_returns_empty_string():
    assert format_tool_ranking_block([]) == ""


def test_format_block_shape():
    ranks = [
        ToolRanking(
            tool_name="read",
            success_count=10,
            total=10,
            success_rate=1.0,
            wilson_lb=0.7224,
        )
    ]
    block = format_tool_ranking_block(ranks)
    assert block.startswith("<tool-ranking>")
    assert block.rstrip().endswith("</tool-ranking>")
    assert "- [read] 10/10 succeeded (LB 0.72)" in block


def test_format_block_two_entry_order_preserved():
    """The formatter renders entries in the order received (caller pre-sorts)."""
    ranks = [
        ToolRanking("first", 50, 50, 1.0, 0.93),
        ToolRanking("second", 10, 10, 1.0, 0.72),
    ]
    block = format_tool_ranking_block(ranks)
    lines = block.split("\n")
    assert "first" in lines[1]
    assert "second" in lines[2]


def test_min_invocations_constant_matches_tool_hints():
    """MVP convergence — both readers gate at 3 calls. If one diverges,
    the docstring claim about a shared window/floor pair breaks."""
    from core.self_improving_loop.tool_hints import (
        MIN_INVOCATIONS as HINTS_MIN_INVOCATIONS,
    )

    assert MIN_INVOCATIONS == HINTS_MIN_INVOCATIONS


def test_load_recent_episodes_handles_missing_store(monkeypatch: pytest.MonkeyPatch):
    """``tool_search.load_recent_episodes`` is the module-internal loader
    used when callers invoke the ranker without going through
    ``in_context_wiring``. The wiring opts to share ``tool_hints``'
    loader as a shared-read optimisation; this test pins the parallel
    public API so it isn't quietly dead code."""
    import core.agent.tool_search as ts_module

    class _ExplodingStore:
        def recent(self, *, limit: int) -> list[object]:
            raise OSError("disk on fire")

    monkeypatch.setattr("core.memory.episodic.EpisodicStore", _ExplodingStore)
    # Read failure → graceful empty list, never raises.
    result = ts_module.load_recent_episodes()
    assert result == []


def test_load_recent_episodes_returns_store_output(monkeypatch: pytest.MonkeyPatch):
    """Happy path — loader forwards the store's ``recent()`` result."""
    import core.agent.tool_search as ts_module

    expected = [_FakeEpisode("read", True), _FakeEpisode("read", False)]

    class _OkStore:
        def recent(self, *, limit: int) -> list[object]:
            assert limit == ts_module.RECENT_WINDOW
            return list(expected)

    monkeypatch.setattr("core.memory.episodic.EpisodicStore", _OkStore)
    result = ts_module.load_recent_episodes()
    assert result == expected
