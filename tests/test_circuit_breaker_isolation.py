"""Pin the autouse CircuitBreaker reset added in conftest.py.

Reproduces the xdist `loadfile` cascade by forcing the anthropic
breaker into OPEN, then asserting the autouse fixture resets it before
the next test starts. Without the fixture, the second test would
inherit the OPEN state and fail with "Circuit breaker is open …" —
exactly the failure mode seen on PR #1429-#1431 CI.
"""

from __future__ import annotations

import pytest


def test_breaker_reset_class_method_exists() -> None:
    """CircuitBreaker.reset() is the test-only escape hatch — must exist."""
    from core.llm.fallback import CircuitBreaker

    cb = CircuitBreaker(failure_threshold=2)
    cb.record_failure()
    cb.record_failure()
    assert not cb.can_execute()  # OPEN
    cb.reset()
    assert cb.can_execute()  # CLOSED again
    assert cb._failures == 0
    assert cb._state == "closed"


def test_anthropic_breaker_singleton_reset_between_tests_part1() -> None:
    """Step 1: deliberately open the anthropic breaker.

    The conftest autouse fixture must reset it before the next test
    runs. test_..._part2 verifies the reset took effect.
    """
    from core.llm.providers import anthropic as _anth

    cb = _anth._circuit_breaker
    for _ in range(cb._threshold + 1):
        cb.record_failure()
    assert not cb.can_execute(), "test setup: breaker should be OPEN"


def test_anthropic_breaker_singleton_reset_between_tests_part2() -> None:
    """Step 2: previous test left the breaker OPEN — fixture must have reset it."""
    from core.llm.providers import anthropic as _anth

    cb = _anth._circuit_breaker
    assert cb.can_execute(), (
        "Circuit breaker should be CLOSED at start of test — "
        "the autouse fixture in conftest.py did not reset between tests"
    )
    assert cb._failures == 0


@pytest.mark.parametrize(
    "module_path,attr",
    [
        ("core.llm.providers.anthropic", "_circuit_breaker"),
        ("core.llm.providers.openai", "_openai_circuit_breaker"),
        ("core.llm.providers.glm", "_glm_circuit_breaker"),
        ("core.llm.providers.codex", "_codex_circuit_breaker"),
        ("core.llm.provider_dispatch", "_openai_cb"),
        ("core.llm.provider_dispatch", "_glm_cb"),
    ],
)
def test_every_singleton_breaker_starts_closed(module_path: str, attr: str) -> None:
    """All 6 module-level singletons start CLOSED at test entry — fixture covers each."""
    import importlib

    mod = importlib.import_module(module_path)
    cb = getattr(mod, attr)
    assert cb.can_execute(), (
        f"{module_path}.{attr} is not closed at test entry — "
        "the conftest reset fixture is missing this singleton"
    )
