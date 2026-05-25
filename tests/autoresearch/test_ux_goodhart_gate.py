"""PR-AR-L4d (2026-05-26) — UX Goodhart bidirectional gate invariants.

PR-AR-L4a + L4b wired ``ux_means`` into the fitness path, but the
fitness scalar alone doesn't catch *trade-off* failures — a mutation
can game the UX surface (success_rate ↑, token_cost ↓) while
regressing a critical Petri dim, and a fitness gain on net could
still pass the margin floor.

The bench axis has had this gate since PR-SIL-5THEME C2
(``bench_means.detect_cross_validation_conflict``). PR-AR-L4d adds the
same pattern for UX:

1. **Petri improved + UX regressed** → ``alignment_only_fooling_ux``
   (judge pleased, behaviour worse)
2. **UX improved + critical dim regressed** →
   ``capability_at_alignment_cost_ux`` (gamed UX at the cost of safety)

Both conflicts trigger strict-reject (``_should_promote`` returns
False with the conflict label). The detector returns ``None`` on
insufficient data so the gate stays dormant rather than false-firing.

This file pins:

1. ``detect_ux_conflict`` symbol + signature
2. Conflict 1 (Petri improved + UX regressed) → label
3. Conflict 2 (UX improved + critical regressed) → label
4. No conflict → ``None`` (4-way matrix for sanity)
5. Graceful no-op when ``ux_means`` is ``None`` or baseline is ``None``
6. Wiring — ``_should_promote`` emits the ux conflict label
"""

from __future__ import annotations

from autoresearch.train import AXIS_TIERS, CRITICAL_DIMS, _should_promote
from autoresearch.ux_means import detect_ux_conflict


def test_detect_ux_conflict_returns_none_on_missing_data() -> None:
    """Graceful — every missing input returns ``None`` so the gate
    stays dormant. Same contract as ``bench_means.detect_cross_validation_conflict``."""
    full_dim = {"broken_tool_use": 3.0}
    full_ux = {
        "success_rate": 0.5,
        "token_cost_norm": 0.5,
        "revert_ratio_norm": 0.5,
        "latency_norm": 0.5,
    }
    # baseline_dim missing
    assert (
        detect_ux_conflict(
            dim_means=full_dim,
            baseline_dim_means=None,
            ux_means=full_ux,
            baseline_ux_means=full_ux,
        )
        is None
    )
    # baseline_ux missing
    assert (
        detect_ux_conflict(
            dim_means=full_dim,
            baseline_dim_means=full_dim,
            ux_means=full_ux,
            baseline_ux_means=None,
        )
        is None
    )
    # current ux missing
    assert (
        detect_ux_conflict(
            dim_means=full_dim,
            baseline_dim_means=full_dim,
            ux_means=None,
            baseline_ux_means=full_ux,
        )
        is None
    )


def test_alignment_only_fooling_ux_fires_when_petri_improved_and_ux_regressed() -> None:
    """Conflict 1 — Petri dim aggregate went DOWN (improved on
    lower-is-better scale) AND UX aggregate went DOWN (regressed on
    higher-is-better scale). Label = ``alignment_only_fooling_ux``."""
    # Petri improved — baseline higher (3.0) → current lower (1.0).
    baseline_dim = {"broken_tool_use": 3.0, "overrefusal": 3.0}
    current_dim = {"broken_tool_use": 1.0, "overrefusal": 1.0}
    # UX regressed — every field went down.
    baseline_ux = {
        "success_rate": 0.9,
        "token_cost_norm": 0.9,
        "revert_ratio_norm": 0.9,
        "latency_norm": 0.9,
    }
    current_ux = {
        "success_rate": 0.2,
        "token_cost_norm": 0.2,
        "revert_ratio_norm": 0.2,
        "latency_norm": 0.2,
    }
    result = detect_ux_conflict(
        dim_means=current_dim,
        baseline_dim_means=baseline_dim,
        ux_means=current_ux,
        baseline_ux_means=baseline_ux,
        critical_dims=CRITICAL_DIMS,
    )
    assert result == "alignment_only_fooling_ux"


def test_capability_at_alignment_cost_ux_fires_when_ux_improved_and_critical_regressed() -> None:
    """Conflict 2 — UX aggregate UP AND a critical-tier dim regressed
    (current > baseline + margin on lower-is-better scale). Label =
    ``capability_at_alignment_cost_ux``."""
    # UX improved — every field up.
    baseline_ux = {
        "success_rate": 0.2,
        "token_cost_norm": 0.2,
        "revert_ratio_norm": 0.2,
        "latency_norm": 0.2,
    }
    current_ux = {
        "success_rate": 0.9,
        "token_cost_norm": 0.9,
        "revert_ratio_norm": 0.9,
        "latency_norm": 0.9,
    }
    # critical dim regressed — broken_tool_use is critical, current
    # higher than baseline.
    baseline_dim = {"broken_tool_use": 2.0}
    current_dim = {"broken_tool_use": 5.0}
    result = detect_ux_conflict(
        dim_means=current_dim,
        baseline_dim_means=baseline_dim,
        ux_means=current_ux,
        baseline_ux_means=baseline_ux,
        critical_dims=CRITICAL_DIMS,
    )
    assert result == "capability_at_alignment_cost_ux"


def test_no_conflict_returns_none() -> None:
    """4-way sanity matrix — no conflict when both axes move the same
    direction (or both static)."""
    # Both improved.
    baseline_dim = {"broken_tool_use": 5.0}
    current_dim = {"broken_tool_use": 2.0}
    baseline_ux = {
        "success_rate": 0.3,
        "token_cost_norm": 0.3,
        "revert_ratio_norm": 0.3,
        "latency_norm": 0.3,
    }
    current_ux = {
        "success_rate": 0.8,
        "token_cost_norm": 0.8,
        "revert_ratio_norm": 0.8,
        "latency_norm": 0.8,
    }
    assert (
        detect_ux_conflict(
            dim_means=current_dim,
            baseline_dim_means=baseline_dim,
            ux_means=current_ux,
            baseline_ux_means=baseline_ux,
            critical_dims=CRITICAL_DIMS,
        )
        is None
    )
    # Both regressed.
    assert (
        detect_ux_conflict(
            dim_means=baseline_dim,  # swap
            baseline_dim_means=current_dim,
            ux_means=baseline_ux,
            baseline_ux_means=current_ux,
            critical_dims=CRITICAL_DIMS,
        )
        is None
    )


def test_should_promote_emits_alignment_only_fooling_ux_label() -> None:
    """End-to-end Conflict 1 — Petri improved + UX regressed →
    ``_should_promote`` returns ``alignment_only_fooling_ux``.

    Pre-fix this label was unreachable via ``_should_promote`` because
    the conflict detector ran only inside the gated == 0.0 branch,
    and that branch fires on critical regression — exactly the
    opposite of the Conflict 1 trigger condition (Petri improving).
    PR-AR-L4d Codex MCP review §5 caught this gap. Detector now runs
    BEFORE the gated check so the alignment-fooling path surfaces."""
    # Petri improved — every dim went from 5.0 → 1.0 (lower-is-better).
    baseline_dim = dict.fromkeys(AXIS_TIERS, 5.0)
    current_dim = dict.fromkeys(AXIS_TIERS, 1.0)
    # UX regressed — every field went down.
    baseline_ux = {
        "success_rate": 0.9,
        "token_cost_norm": 0.9,
        "revert_ratio_norm": 0.9,
        "latency_norm": 0.9,
    }
    current_ux = {
        "success_rate": 0.2,
        "token_cost_norm": 0.2,
        "revert_ratio_norm": 0.2,
        "latency_norm": 0.2,
    }
    ok, reason = _should_promote(
        current_dim,
        dict.fromkeys(AXIS_TIERS, 0.0),
        baseline_means=baseline_dim,
        baseline_stderr=dict.fromkeys(AXIS_TIERS, 0.0),
        ux_means=current_ux,
        baseline_ux_means=baseline_ux,
    )
    assert ok is False, (
        "Petri-improved + UX-regressed should not promote (Goodhart "
        f"alignment-only-fooling). Got reason: {reason!r}"
    )
    assert "alignment_only_fooling_ux" in reason


def test_should_promote_emits_capability_at_alignment_cost_ux_label() -> None:
    """End-to-end Conflict 2 — UX improved + critical regressed →
    ``_should_promote`` returns the ux-specific label."""
    baseline_dim = dict.fromkeys(AXIS_TIERS, 1.0)
    current_dim = dict.fromkeys(AXIS_TIERS, 1.0)
    # Critical regress (drives gated=0.0).
    current_dim["broken_tool_use"] = 9.0
    # UX improves.
    baseline_ux = {
        "success_rate": 0.2,
        "token_cost_norm": 0.2,
        "revert_ratio_norm": 0.2,
        "latency_norm": 0.2,
    }
    current_ux = {
        "success_rate": 0.9,
        "token_cost_norm": 0.9,
        "revert_ratio_norm": 0.9,
        "latency_norm": 0.9,
    }
    ok, reason = _should_promote(
        current_dim,
        dict.fromkeys(AXIS_TIERS, 0.0),
        baseline_means=baseline_dim,
        baseline_stderr=dict.fromkeys(AXIS_TIERS, 0.0),
        ux_means=current_ux,
        baseline_ux_means=baseline_ux,
    )
    assert ok is False
    assert "capability_at_alignment_cost_ux" in reason, (
        f"Expected ux conflict label in reason, got: {reason!r}"
    )


def test_should_promote_falls_through_to_critical_message_when_no_conflict() -> None:
    """If gated=0.0 fires but neither bench nor ux conflict applies,
    the default ``critical-axis regression`` message is returned —
    behaviour preservation for legacy callers."""
    baseline_dim = dict.fromkeys(AXIS_TIERS, 1.0)
    current_dim = dict.fromkeys(AXIS_TIERS, 1.0)
    current_dim["broken_tool_use"] = 9.0
    ok, reason = _should_promote(
        current_dim,
        dict.fromkeys(AXIS_TIERS, 0.0),
        baseline_means=baseline_dim,
        baseline_stderr=dict.fromkeys(AXIS_TIERS, 0.0),
        # No ux data → ux conflict skipped. No bench data → bench
        # conflict skipped. Default critical-axis message.
    )
    assert ok is False
    assert "critical-axis regression" in reason
