"""PR-CONTRACT-EVAL (2026-06-03) — end-to-end check against a REAL ``.eval``.

Runs the deterministic contract checker against the real archived audit
``gen-2606-blend3-009`` (under ``~/.geode/petri/logs/``) to confirm the parser
handles real-world ``create_tool`` / target-text-form data end-to-end — not
just synthetic fakes.

This is a local-only check: it skips gracefully (``pytest.skip``) when neither
``inspect_ai`` nor the archive is present, so CI (which has neither) stays
green. ``required_tool_path`` is "skipped" on this archive (it predates the
``contract`` block in seed front-matter), so the load-bearing assertion is on
``args_shape_valid``, which exercises the real ``create_tool`` schema +
``TOOL_CALL:`` text-form parsing path against ~150 real tool calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("inspect_ai.log")

from core.audit.contracts import extract_contract_results

_ARCHIVE = Path(
    "~/.geode/petri/logs/2026-06-03T11-36-41-00-00_audit_EtqxABSGWnjeZJzZ4QnMpM.eval"
).expanduser()


@pytest.mark.skipif(not _ARCHIVE.is_file(), reason="gen-2606-blend3-009 archive not present")
def test_real_archive_produces_concrete_args_shape_result() -> None:
    """The checker runs end-to-end on real data and returns the 3-row ledger
    with a CONCRETE (non-stub) ``args_shape_valid`` verdict."""
    results = extract_contract_results(_ARCHIVE)
    assert results, "real archive should yield a non-empty ledger"
    by_id = {r["contract_id"]: r for r in results}
    assert set(by_id) == {"required_tool_path", "args_shape_valid", "claim_grounded"}

    # No contract block in this already-run archive → required_tool_path skipped.
    assert by_id["required_tool_path"]["status"] == "skipped"

    # args_shape_valid must be a CONCRETE verdict (not the claim_grounded stub):
    # the target's text-form TOOL_CALL: calls were validated against the
    # auditor's create_tool schemas. The known-good gen-2606-blend3-009 target
    # emits well-formed calls (e.g. order_sync_status(batch_id=4488)), so the
    # expected verdict is a non-failing concrete status.
    args = by_id["args_shape_valid"]
    # "skipped" is EXCLUDED: this archive has real target tool calls, so a
    # "skipped" result would mean the parser found nothing — a regression the
    # test must FAIL on, not pass vacuously. (The known-good archive yields
    # "pass"; "indeterminate" stays allowed for un-parseable-arg drift.)
    assert args["status"] in {"pass", "indeterminate"}, (
        f"unexpected args_shape_valid status on real data: {args}"
    )
    assert args["hard"] is True
    assert args["failed_samples"] == []

    # claim_grounded is the forward-stable stub.
    assert by_id["claim_grounded"]["status"] == "not_evaluated"
    assert by_id["claim_grounded"]["hard"] is False
