"""PR-AR-L4b (2026-05-26) — ``compute_fitness`` 5-caller forward invariants.

Pre-PR-AR-L4b ``autoresearch.ux_means.collect_ux_means_from_sources``
returned a real dict (per PR-AR-L4a) but no caller forwarded it to
``compute_fitness``. The fitness scalar therefore stayed dim-only,
ignoring the entire ux axis even when the data was available.

PR-AR-L4b wires the 5 ``compute_fitness`` call sites:

- main caller at ``train.py:fitness = compute_fitness(...)`` (line ~2237)
- 4 internal ``_should_promote`` calls (bootstrap / gated / current_raw
  / prior_raw)

All 5 must forward the same ``ux_means`` / ``admire_means`` kwargs to
maintain caller symmetry (PR-11 anchor multiplier pattern from
[[feedback-signature-forward-audit]]). ``admire_means`` is reserved as
``None`` here — PR-AR-L4c wires the seed-gen ranker handoff after
Scope A ships ``evaluate_mutation_pairwise``.

This file pins:

1. ``_should_promote`` signature accepts the 4 new kwargs
2. All 5 ``compute_fitness`` call sites mention both ``ux_means=``
   and ``admire_means=`` kwargs (grep invariant — PR-11 caught the
   missing-forward bug via this exact pattern)
3. ``_write_baseline`` persists the ``ux_means`` slot when caller
   supplies a non-empty dict
4. baseline.json roundtrip — ``_load_baseline`` reads the slot back
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest
from autoresearch.train import (
    AXIS_TIERS,
    _load_baseline,
    _should_promote,
    _write_baseline,
)


def test_should_promote_accepts_ux_admire_kwargs() -> None:
    """``_should_promote`` signature must expose the 4 new kwargs so
    callers can forward without TypeErrors."""
    sig = inspect.signature(_should_promote)
    for kw in ("ux_means", "baseline_ux_means", "admire_means", "baseline_admire_means"):
        assert kw in sig.parameters, f"{kw} missing from _should_promote signature"
        assert sig.parameters[kw].default is None, (
            f"{kw} must default to None for backward-compat with legacy callers"
        )


def test_compute_fitness_callers_all_forward_ux_means() -> None:
    """Caller-symmetry grep — every ``compute_fitness(`` call in
    ``train.py`` must reference ``ux_means=`` somewhere in its
    argument block. The PR-11 anchor multiplier pattern caught a
    Codex regression where 4 internal calls forwarded the kwarg but
    1 didn't (silent half-wired fitness). Same pattern, same risk
    here. The check is a defence-in-depth on top of the test that
    actually exercises the 5 paths."""
    from autoresearch import train as auto_train

    source = inspect.getsource(auto_train)
    # Strip the function definition line itself (compute_fitness signature
    # doesn't count as a "call" — only invocations matter).
    call_blocks = re.findall(r"compute_fitness\((.*?)\)", source, flags=re.DOTALL)
    # Expect 5 invocations (4 in _should_promote + 1 in main()) PLUS
    # 1 type-only self-reference inside the docstring example. Real
    # call blocks contain ``dim_means`` / ``current_means`` as first
    # positional — filter on that.
    real_calls = [block for block in call_blocks if "_means" in block or "current_means" in block]
    assert len(real_calls) >= 5, (
        f"Expected at least 5 compute_fitness call blocks in train.py "
        f"(1 main caller + 4 _should_promote internals). Got {len(real_calls)}."
    )
    for idx, block in enumerate(real_calls):
        assert "ux_means" in block, (
            f"compute_fitness call #{idx + 1} missing ux_means= forward. "
            f"Caller symmetry violated — [[feedback-signature-forward-audit]] "
            f"pattern. Block:\n{block}"
        )
        assert "admire_means" in block, (
            f"compute_fitness call #{idx + 1} missing admire_means= forward. "
            f"Same caller symmetry rule. Block:\n{block}"
        )


def test_should_promote_internal_calls_forward_ux_admire() -> None:
    """End-to-end exercise — feed a `_should_promote` call with non-None
    ux_means and verify the bootstrap branch fitness drifts from a
    dim-only baseline. Catches the case where the kwarg was added to
    signature but forgotten in the internal compute_fitness call body."""
    dim_means = dict.fromkeys(AXIS_TIERS, 1.0)
    dim_stderr = dict.fromkeys(AXIS_TIERS, 0.0)
    # Bootstrap path (baseline=None) — fitness signature must change
    # when ux_means is non-None vs None. compute_fitness's 3-axis
    # math (UX_FITNESS_DIM_WEIGHT × dim + UX_FITNESS_UX_WEIGHT × ux)
    # diverges from dim-only fitness when ux_means is supplied.
    ok_without_ux, reason_without = _should_promote(
        dim_means,
        dim_stderr,
        baseline_means=None,
        baseline_stderr=None,
    )
    ok_with_ux, reason_with = _should_promote(
        dim_means,
        dim_stderr,
        baseline_means=None,
        baseline_stderr=None,
        ux_means={
            "success_rate": 0.0,
            "token_cost_norm": 0.0,
            "revert_ratio_norm": 0.0,
            "latency_norm": 0.0,
        },
    )
    # Both must promote (full dim_means, fitness above floor) — the
    # test isn't about the verdict, it's about the fitness scalar
    # appearing in the reason changing.
    assert ok_without_ux is True
    assert ok_with_ux is True
    # The fitness numbers in the reasons differ → the kwarg actually
    # reaches compute_fitness inside the bootstrap branch.
    fit_without = float(reason_without.split("fitness ")[1].split(" ")[0])
    fit_with = float(reason_with.split("fitness ")[1].split(" ")[0])
    assert fit_with != fit_without, (
        f"ux_means kwarg has no effect on bootstrap fitness ({fit_without} == "
        f"{fit_with}) — the forward is broken inside _should_promote's "
        f"bootstrap branch."
    )
    # ux all zeros should drag fitness DOWN vs dim-only (which falls
    # back to ux_means=None → ux_aggregate=0.5 neutral).
    assert fit_with < fit_without


def test_write_baseline_persists_ux_means_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_write_baseline`` writes the ``axes.ux_means`` slot when
    caller forwards a non-empty dict. Pin so the slot stays populated
    end-to-end (compute → forward → persist → load)."""
    from autoresearch import train as auto_train

    target = tmp_path / "baseline.json"
    monkeypatch.setattr(auto_train, "BASELINE_PATH", target)
    ux = {
        "success_rate": 0.7,
        "token_cost_norm": 0.9,
        "revert_ratio_norm": 0.8,
        "latency_norm": 0.95,
    }
    _write_baseline(
        dim_means=dict.fromkeys(AXIS_TIERS, 1.0),
        dim_stderr=dict.fromkeys(AXIS_TIERS, 0.0),
        ux_means=ux,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert "axes" in payload
    assert payload["axes"]["ux_means"] == pytest.approx(ux)


def test_load_baseline_roundtrips_ux_means_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end roundtrip — write → load → caller gets the ux dict
    back. This is the slot wiring's full lifecycle pinned in one test."""
    from autoresearch import train as auto_train

    target = tmp_path / "baseline.json"
    monkeypatch.setattr(auto_train, "BASELINE_PATH", target)
    ux = {
        "success_rate": 0.66,
        "token_cost_norm": 0.99,
        "revert_ratio_norm": 0.66,
        "latency_norm": 0.95,
    }
    _write_baseline(
        dim_means=dict.fromkeys(AXIS_TIERS, 1.0),
        dim_stderr=dict.fromkeys(AXIS_TIERS, 0.0),
        ux_means=ux,
    )
    _, _, baseline_ux, _, _ = _load_baseline()
    assert baseline_ux == pytest.approx(ux)


def test_main_caller_collects_ux_means_via_l4a_collector() -> None:
    """The main ``fitness = compute_fitness(...)`` call must reach
    ``collect_ux_means_from_sources`` to gather current ux. grep
    invariant — a future refactor removing the call would silently
    half-disconnect the ux axis (signature still has slot, just always
    forwards None)."""
    from autoresearch import train as auto_train

    source = inspect.getsource(auto_train)
    assert "collect_ux_means_from_sources" in source, (
        "train.py must call collect_ux_means_from_sources for the main "
        "compute_fitness invocation. PR-AR-L4b wiring contract."
    )
