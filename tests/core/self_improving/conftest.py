"""Shared self-improving test fixtures.

PR-STATE-SOT-RUNTIME-SPLIT (2026-06-14) — in PRODUCTION the LATEST baseline
(``baseline.json``) is runtime (~/.geode) while the TRACKED promoted history
(``baseline_archive.jsonl``) + results sinks are the in-repo SoT, so
``ledger._baseline_archive_path`` / ``_results_paths`` are DECOUPLED from
``ledger.BASELINE_PATH``.

The ~30 existing loop tests, however, monkeypatch ``ledger.BASELINE_PATH`` to a
tmp dir for isolation and expect the tracked sinks written alongside it (they
assert ROW CONTENT, not the production path home). This autouse fixture
re-derives the tracked sinks from ``BASELINE_PATH.parent`` AT CALL TIME so those
tests keep their tmp co-location with no per-fixture edit, while production stays
decoupled. The production path HOMES are asserted separately by
``test_runner_repo_root_invariant`` / ``test_ratchet_policies_in_repo``.
"""

from __future__ import annotations

import pytest
from core.self_improving import ledger


@pytest.fixture(autouse=True)
def _colocate_tracked_ledger_with_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    monkeypatch.setattr(
        ledger,
        "_baseline_archive_path",
        lambda: ledger.BASELINE_PATH.parent / "baseline_archive.jsonl",
    )

    def _results() -> tuple:
        parent = ledger.BASELINE_PATH.parent
        return parent / "results.tsv", parent / "results.jsonl"

    monkeypatch.setattr(ledger, "_results_paths", _results)

    # Keep per-run RUNTIME writes (wrapper-override dump etc.) out of the real
    # ~/.geode during tests — measure._dump_wrapper_override lazily reads
    # ``core.paths.WRAPPER_OVERRIDE_PATH`` at call time, so redirecting the
    # source constant isolates it without each test pinning a path. (Replaces
    # the pre-split ``measure.STATE_DIR`` monkeypatch the tests used.)
    import core.paths as _paths

    monkeypatch.setattr(_paths, "WRAPPER_OVERRIDE_PATH", tmp_path / "wrapper-override.json")
