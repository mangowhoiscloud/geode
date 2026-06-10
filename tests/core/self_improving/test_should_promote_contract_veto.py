"""PR-CONTRACT-EVAL (2026-06-03) — promote-gate hard-contract veto.

A FAILED hard tool-call contract (``required_tool_path`` / ``args_shape_valid``)
must reject the promotion REGARDLESS of a real fitness improvement — a discrete
behavioural failure cannot be averaged away by a strong showing on the
continuous judge dims. A soft contract (``claim_grounded``, hard=False) must
NOT veto. The default (no veto arg) must be byte-identical to the prior gate.
"""

from __future__ import annotations

from core.audit.contracts import ContractResult
from core.self_improving.fitness import AUXILIARY_DIMS, CRITICAL_DIMS
from core.self_improving.gate import _hard_contract_violations, _should_promote

# A real fitness improvement (lower = better on the Petri scale): baseline 5.0,
# current 2.0 — the exact shape of ``test_should_promote_accepts_significant_
# improvement``, which promotes WITHOUT a veto.
_BASELINE_MEANS = dict.fromkeys(CRITICAL_DIMS + AUXILIARY_DIMS, 5.0)
_BASELINE_STDERR = dict.fromkeys(CRITICAL_DIMS + AUXILIARY_DIMS, 0.05)
_CURRENT_MEANS = dict.fromkeys(CRITICAL_DIMS + AUXILIARY_DIMS, 2.0)
_CURRENT_STDERR = dict.fromkeys(CRITICAL_DIMS + AUXILIARY_DIMS, 0.05)


def test_improving_fitness_still_rejected_on_hard_contract_failure() -> None:
    """Fitness improves big, but a hard contract FAILs → REJECT with the
    veto reason. This is the core of PR-2."""
    ok, reason = _should_promote(
        _CURRENT_MEANS,
        _CURRENT_STDERR,
        baseline_means=_BASELINE_MEANS,
        baseline_stderr=_BASELINE_STDERR,
        contract_veto=("required_tool_path",),
    )
    assert ok is False
    assert "hard-contract violation" in reason
    assert "required_tool_path" in reason


def test_no_veto_promotes_exactly_as_before() -> None:
    """Same improving audit with NO veto arg promotes (default unchanged)."""
    ok, reason = _should_promote(
        _CURRENT_MEANS,
        _CURRENT_STDERR,
        baseline_means=_BASELINE_MEANS,
        baseline_stderr=_BASELINE_STDERR,
    )
    assert ok is True
    assert "fitness" in reason


def test_bootstrap_first_audit_vetoed_on_hard_contract_failure() -> None:
    """A FRESH first audit (no baseline yet) with a hard-contract failure must
    NOT become the baseline — the veto runs BEFORE the bootstrap branch.
    (Codex review, 2026-06-03: the veto was bypassed on bootstrap.)"""
    from core.self_improving.fitness import AXIS_TIERS

    # Complete dims + high fitness → the bootstrap branch WOULD promote.
    dim_means = dict.fromkeys(AXIS_TIERS, 1.0)
    dim_stderr = dict.fromkeys(AXIS_TIERS, 0.0)
    ok, reason = _should_promote(
        dim_means,
        dim_stderr,
        baseline_means=None,
        baseline_stderr=None,
        contract_veto=("required_tool_path",),
    )
    assert ok is False
    assert "hard-contract violation" in reason


def test_bootstrap_first_audit_promotes_without_veto() -> None:
    """The same fresh audit WITHOUT a veto still bootstrap-promotes (the veto
    fix did not change the no-veto bootstrap path)."""
    from core.self_improving.fitness import AXIS_TIERS

    dim_means = dict.fromkeys(AXIS_TIERS, 1.0)
    dim_stderr = dict.fromkeys(AXIS_TIERS, 0.0)
    ok, reason = _should_promote(
        dim_means,
        dim_stderr,
        baseline_means=None,
        baseline_stderr=None,
    )
    assert ok is True
    assert "bootstrap_promote" in reason


def test_empty_veto_tuple_promotes() -> None:
    """An EMPTY veto tuple (no hard failure) is a no-op — still promotes."""
    ok, _reason = _should_promote(
        _CURRENT_MEANS,
        _CURRENT_STDERR,
        baseline_means=_BASELINE_MEANS,
        baseline_stderr=_BASELINE_STDERR,
        contract_veto=(),
    )
    assert ok is True


def test_multiple_hard_failures_listed_in_reason() -> None:
    """Both hard contracts failing → both ids in the reason string."""
    ok, reason = _should_promote(
        _CURRENT_MEANS,
        _CURRENT_STDERR,
        baseline_means=_BASELINE_MEANS,
        baseline_stderr=_BASELINE_STDERR,
        contract_veto=("required_tool_path", "args_shape_valid"),
    )
    assert ok is False
    assert "required_tool_path" in reason
    assert "args_shape_valid" in reason


# ---------------------------------------------------------------------------
# _hard_contract_violations — the selector that feeds contract_veto
# ---------------------------------------------------------------------------


def _ledger(*results: ContractResult) -> list[dict]:
    return [r.as_dict() for r in results]


def test_hard_violations_selects_only_hard_fails() -> None:
    """Only rows that are BOTH hard AND status==fail are selected."""
    ledger = _ledger(
        ContractResult("required_tool_path", "fail", ["s1"], "...", hard=True),
        ContractResult("args_shape_valid", "pass", [], "...", hard=True),
        ContractResult("claim_grounded", "not_evaluated", [], "...", hard=False),
    )
    assert _hard_contract_violations(ledger) == ("required_tool_path",)


def test_claim_grounded_failure_never_vetoes() -> None:
    """A soft contract (hard=False) FAILing is NOT a veto — even if some future
    path marks claim_grounded as 'fail', it must not appear in the veto set."""
    ledger = _ledger(
        ContractResult("required_tool_path", "skipped", [], "...", hard=True),
        ContractResult("args_shape_valid", "pass", [], "...", hard=True),
        ContractResult("claim_grounded", "fail", ["s1"], "...", hard=False),
    )
    assert _hard_contract_violations(ledger) == ()


def test_skipped_and_indeterminate_are_not_violations() -> None:
    """``skipped`` / ``indeterminate`` hard contracts never veto."""
    ledger = _ledger(
        ContractResult("required_tool_path", "skipped", [], "...", hard=True),
        ContractResult("args_shape_valid", "indeterminate", [], "...", hard=True),
        ContractResult("claim_grounded", "not_evaluated", [], "...", hard=False),
    )
    assert _hard_contract_violations(ledger) == ()


def test_hard_violations_empty_ledger() -> None:
    """An empty ledger (dry-run / archive-missing) → empty tuple → no veto."""
    assert _hard_contract_violations([]) == ()


def test_end_to_end_failed_required_tool_path_vetoes_via_selector() -> None:
    """The full path: a real ContractResult ledger with a hard FAIL flows
    through ``_hard_contract_violations`` into ``_should_promote`` and rejects
    an otherwise-promotable audit."""
    ledger = _ledger(
        ContractResult("required_tool_path", "fail", ["s1"], "tool X never invoked", hard=True),
        ContractResult("args_shape_valid", "pass", [], "ok", hard=True),
        ContractResult("claim_grounded", "not_evaluated", [], "stub", hard=False),
    )
    ok, reason = _should_promote(
        _CURRENT_MEANS,
        _CURRENT_STDERR,
        baseline_means=_BASELINE_MEANS,
        baseline_stderr=_BASELINE_STDERR,
        contract_veto=_hard_contract_violations(ledger),
    )
    assert ok is False
    assert "required_tool_path" in reason
