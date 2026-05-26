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


def test_default_is_eight() -> None:
    """The default cap is 8, matching the per-adapter lane ceiling
    (claude_cli=4 voter * 1 + openai_api=16 voter * 2 = 24 inflight =
    8 matches * 3 voters)."""
    assert DEFAULT_RANKER_MAX_INFLIGHT_MATCHES == 8
    assert resolve_ranker_max_inflight_matches() == 8


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
