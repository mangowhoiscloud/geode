"""PR-DRY-RUN-NO-ATTR (2026-05-26) — pin existing dry-run attribution skip.

The 2026-05-26 autoresearch attribution sprint Phase A audit (§5.6,
item #7) flagged the risk of ``--dry-run`` runs writing synthetic
``fitness_delta=0`` attribution rows to ``mutations.jsonl`` — a
noise-accumulation surface for downstream credit-assignment readers.

Current state (post-PR-AR-L6, already in develop main as of 2026-05-26):
``core/self_improving/train.py:2692`` guards attribution writes with
``_attribution_should_write = not args.dry_run``. The skip is real.

This PR doesn't change behaviour — it adds an invariant test so the
skip cannot regress silently. The 2026-05-26 sprint discovered the
ALREADY-IMPLEMENTED state during Phase A; pinning it here prevents
the leak from re-opening if a future PR strips the guard.
"""

from __future__ import annotations

import inspect


def test_attribution_write_guarded_by_not_dry_run() -> None:
    """Static pin: the substring ``_attribution_should_write = not args.dry_run``
    must remain in ``core.self_improving.train.main``. Any future refactor that
    removes the guard will break this assertion, forcing the author to
    re-prove the skip semantics rather than silently regressing.

    Brittleness is intentional — the alternative (full subprocess
    integration test of train.py with mocked Petri output) would be
    orders of magnitude slower and equally string-matchy at the
    assertion level."""
    from core.self_improving import train as train_mod

    source = inspect.getsource(train_mod)
    assert "_attribution_should_write = not args.dry_run" in source, (
        "PR-DRY-RUN-NO-ATTR invariant violated — the dry-run attribution "
        "skip guard at train.py around line 2692 has been removed. "
        "Re-add or document the new skip mechanism."
    )


def test_attribution_block_skips_when_should_write_false() -> None:
    """Static pin: the attribution write block must be conditional on
    ``_attribution_should_write`` (not unconditional). Catches the
    refactor where someone moves the write out of the if-guard."""
    from core.self_improving import train as train_mod

    source = inspect.getsource(train_mod)
    assert "if _attribution_should_write:" in source, (
        "PR-DRY-RUN-NO-ATTR invariant violated — the conditional guard "
        "around the attribution write block at train.py is missing. "
        "The write must remain gated by _attribution_should_write."
    )
