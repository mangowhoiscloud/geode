"""Tests for the audit-lane capacity knob (PR-ASYNC-FIRST, 2026-06-03).

``GEODE_AUDIT_MAX_CONCURRENT`` lets the async-first campaign harness fan audits
out concurrently when the audit roles run on a PAYG ``api_key`` rate bucket
(separate from the host Claude Code OAuth session), instead of serialising on the
default ``max_concurrent=1`` lane. Default stays 1 (subscription-safe).
"""

from __future__ import annotations

import pytest
from core.llm.audit_lane import (
    AUDIT_LANE_MAX_CONCURRENT_ENV,
    resolve_audit_max_concurrent,
)


def test_default_is_one_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset → 1: the host OAuth session shares the Anthropic rate bucket, so the
    subscription-safe default must serialise audits."""
    monkeypatch.delenv(AUDIT_LANE_MAX_CONCURRENT_ENV, raising=False)
    assert resolve_audit_max_concurrent() == 1


def test_positive_int_sets_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AUDIT_LANE_MAX_CONCURRENT_ENV, "8")
    assert resolve_audit_max_concurrent() == 8


def test_zero_is_unbounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 → the unbounded sentinel (operator's no-CAP PAYG directive): far above any
    realistic fan-out so the lane never blocks, while staying a real Semaphore."""
    monkeypatch.setenv(AUDIT_LANE_MAX_CONCURRENT_ENV, "0")
    assert resolve_audit_max_concurrent() >= 100_000


def test_non_numeric_falls_back_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operator-supplied env → graceful boundary: a typo must not crash the audit."""
    monkeypatch.setenv(AUDIT_LANE_MAX_CONCURRENT_ENV, "lots")
    assert resolve_audit_max_concurrent() == 1


def test_negative_falls_back_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AUDIT_LANE_MAX_CONCURRENT_ENV, "-4")
    assert resolve_audit_max_concurrent() == 1
