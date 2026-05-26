"""PR-PARETO-INTEGRATE (2026-05-27) — promote-gate Pareto archive wiring.

The 2026-05-26 autoresearch attribution sprint Phase A audit (§5.7)
found that ``core.self_improving_loop.pareto_archive.append_archive_entry``
was wired only inside ``runner.apply_group_proposals`` (sibling-group
path, fitness scalar only). The promote gate in ``autoresearch.train.main``
— the one site where full ``dim_means`` meets the accept/reject
decision — never archived its observation. Every rejected mutation's
per-dim scores vanished at cycle end, so regret analysis ("what was
the multi-axis cost of rejecting mutation M?") was impossible.

This PR adds an archive write inside ``main()`` after the promote
decision is finalized, gated by:
* ``[self_improving_loop.autoresearch] pareto_mode = true`` (operator
  opt-in; default off preserves backward-compat).
* Not ``--dry-run`` (synthetic dim_means has no Pareto signal).

The entry rides ArchiveEntry's ``extra="allow"`` to attach
``promoted`` (bool) + ``reason`` (str) so downstream regret-analysis
readers can join on them.

This file pins the wiring as opt-in (off by default), accept+reject
parity (both write), dry-run skip, and the regret-analysis fields.
The actual archive read/write/dominate-prune behavior is covered in
``tests/core/self_improving_loop/test_pareto_archive.py``.
"""

from __future__ import annotations

import inspect


def test_pareto_archive_write_lives_in_promote_gate() -> None:
    """Static-source pin: the new archive-write block is in
    ``autoresearch.train.main`` (not just inside the runner's group
    path). Closes the §5.7 audit finding that the promote gate had no
    archive integration."""
    from autoresearch import train as train_mod

    src = inspect.getsource(train_mod)
    assert "PR-PARETO-INTEGRATE" in src, (
        "PR-PARETO-INTEGRATE marker missing from autoresearch.train — "
        "the promote-gate archive write block was removed or moved. "
        "Either restore the wiring or update the §5.7 audit follow-up "
        "documentation."
    )
    assert "append_archive_entry" in src, (
        "autoresearch.train no longer references pareto_archive's "
        "append_archive_entry — the promote-gate wiring is broken."
    )


def test_pareto_archive_block_gated_by_pareto_mode_and_dry_run() -> None:
    """The archive write must be gated by BOTH ``pareto_mode`` opt-in
    AND ``not args.dry_run``. Catches a refactor that loosens either
    guard (which would write spurious archive rows or break the
    dry-run no-cost invariant)."""
    from autoresearch import train as train_mod

    src = inspect.getsource(train_mod)
    # Substring grep for the two guards. Brittle on rename, but that
    # rename is exactly the case the audit asks us to surface.
    assert "if not args.dry_run:" in src
    assert "pareto_mode" in src


def test_pareto_archive_entry_carries_promoted_and_reason() -> None:
    """The ArchiveEntry constructed in train.py must pass ``promoted``
    + ``reason`` so downstream regret-analysis readers can compute
    "what was the multi-axis cost of rejecting mutation M?". Pin
    these field names because they're the join keys."""
    from autoresearch import train as train_mod

    src = inspect.getsource(train_mod)
    # Both kwargs must appear inside the PR-PARETO-INTEGRATE block.
    # Substring presence is sufficient — the block is small.
    pr_block_start = src.find("PR-PARETO-INTEGRATE")
    pr_block_end = src.find("# W2 (2026-05-25)", pr_block_start)
    if pr_block_end < 0:
        pr_block_end = pr_block_start + 4000  # safety fallback
    block = src[pr_block_start:pr_block_end]
    assert "promoted=" in block, (
        "ArchiveEntry kwarg ``promoted`` missing in the PR-PARETO-"
        "INTEGRATE block — regret analysis needs the accept/reject "
        "bit to filter rejected mutations."
    )
    assert "reason=" in block, (
        "ArchiveEntry kwarg ``reason`` missing — downstream readers "
        "lose the human-readable promote_line context."
    )


def test_pareto_archive_promoted_derived_from_promoted_line() -> None:
    """``promoted_line`` is set in every promote branch
    (dry-run/--no-promote/--promote/auto). Deriving ``promoted`` from
    its prefix (``"true"`` vs ``"false"``) keeps the four branches
    agreeing without re-implementing the gate logic. Pin this so a
    refactor that splits the derivation can't drift the boolean."""
    from autoresearch import train as train_mod

    src = inspect.getsource(train_mod)
    pr_block_start = src.find("PR-PARETO-INTEGRATE")
    pr_block_end = src.find("# W2 (2026-05-25)", pr_block_start)
    if pr_block_end < 0:
        pr_block_end = pr_block_start + 4000
    block = src[pr_block_start:pr_block_end]
    assert 'promoted_line.startswith("true")' in block, (
        "PR-PARETO-INTEGRATE block must derive ``promoted`` from "
        '``promoted_line.startswith("true")`` so the four branches '
        "(dry-run/--no-promote/--promote/auto) share one source of "
        "truth for the accept/reject bit."
    )


def test_pareto_archive_phase_tag_distinguishes_pre_post_audit() -> None:
    """Codex MCP review (CONDITIONAL_PASS must-fix #1) — when group
    sampling fires runner.apply_group_proposals, BOTH runner-side
    (per-sibling pre-audit fitness) AND train-side (post-audit full
    dim_means) writers append to the archive on the same mutation_id.
    The ``phase`` field (ArchiveEntry.extra="allow") distinguishes the
    two so downstream readers don't read duplicate-key data as
    conflicting.

    Train-side: ``phase="post_audit"``. Runner-side:
    ``phase="pre_audit_sibling"``. Pin both literals so a refactor
    can't drift them apart and silently break the join."""
    import inspect

    from autoresearch import train as train_mod
    from core.self_improving_loop import runner as runner_mod

    train_src = inspect.getsource(train_mod)
    runner_src = inspect.getsource(runner_mod)

    assert 'phase="post_audit"' in train_src, (
        'Train-side pareto archive entry must tag ``phase="post_audit"`` '
        "to distinguish from runner-side sibling rows. Without this tag, "
        "downstream readers see duplicate mutation_id rows with "
        "conflicting dim_means shapes."
    )
    assert 'phase="pre_audit_sibling"' in runner_src, (
        "Runner-side pareto archive entry must tag "
        '``phase="pre_audit_sibling"`` so downstream readers can filter '
        "to the per-sibling fitness-scalar pre-audit signal."
    )


def test_pareto_archive_failure_is_best_effort() -> None:
    """An exception inside the archive-append block must NOT propagate
    out of ``main()``. The audit cycle continues even if the JSONL
    writer fails (matches the pattern from runner.apply_group_proposals's
    existing pareto wiring at runner.py:1667-1673)."""
    from autoresearch import train as train_mod

    src = inspect.getsource(train_mod)
    pr_block_start = src.find("PR-PARETO-INTEGRATE")
    pr_block_end = src.find("# W2 (2026-05-25)", pr_block_start)
    if pr_block_end < 0:
        pr_block_end = pr_block_start + 4000
    block = src[pr_block_start:pr_block_end]
    assert "except Exception:" in block, (
        "PR-PARETO-INTEGRATE block must wrap the archive append in "
        "try/except so a JSONL writer failure can't break the audit "
        "cycle. The existing runner-side pareto wiring uses the same "
        "best-effort pattern (runner.py:1667-1673)."
    )
