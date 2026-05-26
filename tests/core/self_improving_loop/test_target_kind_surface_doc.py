"""PR-TARGET-KIND-DOC (2026-05-27) — TARGET_KINDS vs _READER_ONLY_KINDS pin.

The 2026-05-26 autoresearch attribution sprint Phase A audit (§5
mutation surface verification) found an asymmetry between the
canonical ``TARGET_KINDS`` (6 active mutation slots) and
``autoresearch.train.run_audit``'s env override block (13 STRICT-mode
env vars for the 6 active + 1 deprecated + 7 reader-only).

The asymmetry is **intentional** (ADR-013 phased rollout) but
previously undocumented in code — a mutator emitting a target_kind
like ``tool_descriptions`` (reader-deployed but not yet a mutation
slot) would fail at ``parse_mutation``'s ValueError without any
operator-visible signal that the surface is reader-only.

This file pins:

1. ``_READER_ONLY_KINDS`` is disjoint from ``TARGET_KINDS`` — no
   accidental double-listing (which would make ``parse_mutation``
   accept a kind that's also marked reader-only).
2. Each reader-only kind, when emitted as a mutator response, fails
   fast at ``parse_mutation`` with a clear ValueError. This is the
   operator-visible signal that the surface isn't yet writable.
3. The reader-only set matches the 7 surfaces with env wiring in
   ``autoresearch/train.py:840-903`` (the audit-side override block).
   A future PR that adds an env var without graduating the kind to
   ``TARGET_KINDS`` or adding to ``_READER_ONLY_KINDS`` will fail
   this test, forcing explicit triage.
"""

from __future__ import annotations

import json

import pytest


def test_target_kinds_and_reader_only_are_disjoint() -> None:
    """A kind can be EITHER mutator-dispatchable (in TARGET_KINDS) OR
    reader-only (in _READER_ONLY_KINDS), never both. Catches a future
    PR that accidentally double-lists a kind during a graduation."""
    from core.self_improving_loop.policies import _READER_ONLY_KINDS, TARGET_KINDS

    overlap = set(TARGET_KINDS) & _READER_ONLY_KINDS
    assert not overlap, (
        f"TARGET_KINDS and _READER_ONLY_KINDS overlap on {overlap!r} — "
        "a kind must be either active (in TARGET_KINDS) or reader-only, "
        "never both. Check the ADR-013 graduation that introduced the "
        "duplicate listing."
    )


def test_reader_only_kind_emit_fails_fast_at_parse_mutation() -> None:
    """Operator-visible signal: mutator response carrying a reader-only
    target_kind raises ValueError at ``parse_mutation``, not silently
    succeeds. Iterates every entry in ``_READER_ONLY_KINDS`` so adding
    a new entry automatically gains test coverage."""
    from core.self_improving_loop.policies import _READER_ONLY_KINDS
    from core.self_improving_loop.runner import parse_mutation

    for kind in _READER_ONLY_KINDS:
        payload = json.dumps(
            {
                "target_section": "any",
                "new_value": "any",
                "rationale": "test",
                "target_kind": kind,
            }
        )
        with pytest.raises(ValueError, match=f"target_kind {kind!r}"):
            parse_mutation(payload)


def test_reader_only_kinds_match_env_override_block() -> None:
    """Static-source pin: every kind in ``_READER_ONLY_KINDS`` must have
    a corresponding ``GEODE_<KIND>_OVERRIDE`` env var set in
    ``autoresearch/train.py:run_audit``'s override block (the audit-
    side STRICT-mode wiring). Catches the future PR that adds env
    wiring for a new SoT without listing it in ``_READER_ONLY_KINDS``.

    Brittleness intent: substring check on the source file, same
    rationale as ``tests/autoresearch/test_dry_run_no_attribution.py``
    — a failing assertion forces explicit triage, which is exactly
    what the doc comment in ``policies.py`` warns about.
    """
    import inspect

    from core.self_improving_loop.policies import _READER_ONLY_KINDS

    from autoresearch import train as train_mod

    src = inspect.getsource(train_mod)
    # Each kind in _READER_ONLY_KINDS must have its env var present.
    # Convention: ``GEODE_{KIND.upper()}_OVERRIDE`` (matches the
    # ``ADR-012 S0a/S0b`` wiring pattern train.py:840-903).
    for kind in _READER_ONLY_KINDS:
        env_var = f"GEODE_{kind.upper()}_OVERRIDE"
        assert env_var in src, (
            f"_READER_ONLY_KINDS contains {kind!r} but "
            f"autoresearch/train.py has no {env_var} env wiring. "
            "Either remove the kind from _READER_ONLY_KINDS (it's not "
            "actually reader-deployed) or add the STRICT-mode env in "
            "run_audit's override block."
        )


def test_reader_only_set_size_matches_audit_finding() -> None:
    """Sanity counter — the 2026-05-26 Phase A audit found 7
    reader-only surfaces; PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27)
    graduated ``tool_descriptions`` to ``TARGET_KINDS``, leaving 6.
    If a future PR graduates another the size should drop; if a new
    surface lands the size should grow. Either way the explicit count
    makes the change impossible to miss in code review."""
    from core.self_improving_loop.policies import _READER_ONLY_KINDS

    assert len(_READER_ONLY_KINDS) == 6, (
        f"_READER_ONLY_KINDS has {len(_READER_ONLY_KINDS)} entries; the "
        "2026-05-27 PR-TOOL-DESCRIPTIONS-MUTATE graduation leaves 6 "
        "(was 7 per the 2026-05-26 attribution sprint Phase A audit). "
        "Update this assertion AND the policies.py doc comment if the "
        "surface count legitimately changed."
    )
