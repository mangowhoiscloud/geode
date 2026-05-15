"""Smoke tests for the Petri-signal autoresearch fork.

These cover the surface that ruff/mypy/dry-run already exercise *and* the
real-mode fail-fast that the dry-run can never reach. The point is to make
sure the next time someone tweaks `geode audit` CLI flags or removes the
`WRAPPER_OVERRIDE_HOOK_READY` guard, this catches the regression cheaply.
"""

from __future__ import annotations

import pytest
from autoresearch.train import (
    _build_audit_command,
    compute_fitness,
    run_audit,
)


def test_build_audit_command_uses_current_geode_audit_flags() -> None:
    """argv must match what ``geode audit --help`` accepts today."""
    argv = _build_audit_command()
    # Required current flags
    for flag in ("--seed-select", "--dim-set", "--live", "--yes", "--target", "--judge"):
        assert flag in argv, f"missing required flag {flag} in {argv}"
    # Obsolete flags that an older draft of this scaffold used — must not
    # silently re-appear.
    for stale in ("--rubric", "--budget-minutes"):
        assert stale not in argv, f"obsolete flag {stale} re-introduced in {argv}"


def test_real_mode_fails_fast_until_runtime_hook_lands() -> None:
    """Until ``core/`` reads ``GEODE_WRAPPER_OVERRIDE``, real mode must abort
    rather than silently invoking an audit that ignores the mutation surface."""
    with pytest.raises(RuntimeError, match="GEODE_WRAPPER_OVERRIDE"):
        run_audit(dry_run=False)


def test_dry_run_emits_baseline_dim_means_and_finite_fitness() -> None:
    """The dry-run path is the *only* non-deceptive mode today; pin its
    contract so the outer-loop scaffolding keeps working without quota."""
    dim_means, audit_seconds, _ = run_audit(dry_run=True)
    assert dim_means["input_hallucination"] == pytest.approx(3.7)
    assert dim_means["broken_tool_use"] == pytest.approx(3.4)
    assert dim_means["overrefusal"] == pytest.approx(1.0)
    assert audit_seconds == 0.0
    fitness = compute_fitness(dim_means)
    assert 0.0 < fitness < 1.0
