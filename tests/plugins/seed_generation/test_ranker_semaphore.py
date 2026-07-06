"""PR-LANE-CAP-AGGRESSIVE (2026-05-27) — ranker phase-local semaphore invariants.

The ranker wraps each ``asyncio.gather`` task in a phase-local
``asyncio.Semaphore`` so the gather submission queue depth never
exceeds the per-adapter lane ceiling. These tests pin the
resolver (``resolve_ranker_max_inflight_matches``) + env override
+ default value. The integration with the gather call itself is
covered by the existing ``test_ranker.py::test_ranker_dispatches_matches_concurrently``
test, which observes start timestamps under the semaphore.
"""

from __future__ import annotations

import pytest
from plugins.seed_generation.agents.ranker import (
    DEFAULT_RANKER_MAX_INFLIGHT_MATCHES,
    RANKER_MAX_INFLIGHT_MATCHES_ENV,
    resolve_ranker_max_inflight_matches,
)


@pytest.fixture(autouse=True)
def _clear_ranker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(RANKER_MAX_INFLIGHT_MATCHES_ENV, raising=False)


def test_default_is_three() -> None:
    """The default cap is 3 — PR-LANE-CAP-TIGHTER (v0.99.76,
    2026-05-27) lowered from 5 to 3 because cap 5 still required ~3 GB
    of free host RAM per burst (5 × ~487 MB per match) and the
    operator's M3 16 GB host typically has 150-750 MB unused at
    steady state. Cap 3 brings the burst to ~1.5 GB and survives
    without an explicit desktop-app cleanup pass. New cap balances
    the three lanes exactly: 3 matches × 3 voters = 9 tasks,
    saturating claude_cli_lane=3 + 2 × openai_api_lane=6 with zero
    hidden queue depth."""
    assert DEFAULT_RANKER_MAX_INFLIGHT_MATCHES == 3
    assert resolve_ranker_max_inflight_matches() == 3


def test_env_override_positive_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RANKER_MAX_INFLIGHT_MATCHES_ENV, "12")
    assert resolve_ranker_max_inflight_matches() == 12


def test_env_override_empty_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RANKER_MAX_INFLIGHT_MATCHES_ENV, "")
    assert resolve_ranker_max_inflight_matches() == DEFAULT_RANKER_MAX_INFLIGHT_MATCHES


def test_env_override_non_integer_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typos must NEVER harden into "no inflight matches" — the lane
    falls back to the safe default so the operator's smoke run keeps
    progressing instead of jamming on a malformed env var."""
    monkeypatch.setenv(RANKER_MAX_INFLIGHT_MATCHES_ENV, "not-a-number")
    assert resolve_ranker_max_inflight_matches() == DEFAULT_RANKER_MAX_INFLIGHT_MATCHES


def test_env_override_zero_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 / negative override → fall back. Zero would lock the gather
    (Semaphore(0) means no one acquires); negatives are nonsensical."""
    for value in ("0", "-3", "-1"):
        monkeypatch.setenv(RANKER_MAX_INFLIGHT_MATCHES_ENV, value)
        assert resolve_ranker_max_inflight_matches() == DEFAULT_RANKER_MAX_INFLIGHT_MATCHES


def test_env_override_large_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operator may set this very high to disable phase-local
    throttling (rely on lane caps only). 1000 = effectively unbounded
    for the 59-match smoke."""
    monkeypatch.setenv(RANKER_MAX_INFLIGHT_MATCHES_ENV, "1000")
    assert resolve_ranker_max_inflight_matches() == 1000
