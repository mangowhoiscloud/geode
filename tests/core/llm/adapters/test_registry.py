"""Adapter registry tests — register / unregister / resolve_for / bootstrap."""

from __future__ import annotations

import pytest
from core.llm.adapters.base import (
    CONCRETE_SOURCES,
    SOURCE_AUTO,
    SOURCE_PAYG,
    SOURCE_SUBSCRIPTION,
)
from core.llm.adapters.registry import _reset_for_test

from core.llm.adapters import (
    AdapterAlreadyRegisteredError,
    AdapterBillingType,
    AdapterNotFoundError,
    bootstrap_builtins,
    get_adapter,
    list_adapters,
    register_adapter,
    resolve_for,
    unregister_adapter,
)


class _Stub:
    """Minimum LLMAdapter Protocol stub used across registry tests."""

    def __init__(self, name: str, provider: str, source: str) -> None:
        self.name = name
        self.provider = provider
        self.source = source
        self.billing_type = AdapterBillingType.UNKNOWN

    async def acomplete(self, req):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def astream(self, req):  # type: ignore[no-untyped-def]
        return
        yield  # pragma: no cover — never reached, satisfies async-generator typing

    def test_environment(self):  # type: ignore[no-untyped-def]
        from core.llm.adapters.base import EnvironmentReport

        return EnvironmentReport(ok=True)

    def list_models(self):  # type: ignore[no-untyped-def]
        return []

    def get_quota_windows(self):  # type: ignore[no-untyped-def]
        return None

    def detect_credential(self):  # type: ignore[no-untyped-def]
        return None


@pytest.fixture(autouse=True)
def _clean_registry() -> object:
    """Each registry test runs against a fresh registry."""
    _reset_for_test()
    yield
    _reset_for_test()


def test_register_and_get() -> None:
    s = _Stub("stub-a", "stub", SOURCE_PAYG)
    register_adapter(s)
    assert get_adapter("stub-a") is s


def test_register_duplicate_raises() -> None:
    register_adapter(_Stub("dup", "x", SOURCE_PAYG))
    with pytest.raises(AdapterAlreadyRegisteredError):
        register_adapter(_Stub("dup", "y", SOURCE_PAYG))


def test_register_duplicate_with_replace_overwrites() -> None:
    register_adapter(_Stub("dup", "x", SOURCE_PAYG))
    new = _Stub("dup", "y", SOURCE_SUBSCRIPTION)
    register_adapter(new, replace=True)
    assert get_adapter("dup") is new


def test_register_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match=r"adapter\.name is empty"):
        register_adapter(_Stub("", "x", SOURCE_PAYG))


def test_register_rejects_non_concrete_source() -> None:
    with pytest.raises(ValueError, match="not a concrete value"):
        register_adapter(_Stub("bad", "x", "auto"))


def test_unregister_idempotent() -> None:
    register_adapter(_Stub("x", "p", SOURCE_PAYG))
    unregister_adapter("x")
    unregister_adapter("x")  # No-op second time.


def test_get_adapter_missing_raises() -> None:
    with pytest.raises(AdapterNotFoundError):
        get_adapter("not-here")


def test_list_adapters_preserves_registration_order() -> None:
    register_adapter(_Stub("a", "p", SOURCE_PAYG))
    register_adapter(_Stub("b", "p", SOURCE_SUBSCRIPTION))
    register_adapter(_Stub("c", "q", SOURCE_PAYG))
    names = [a.name for a in list_adapters()]
    assert names == ["a", "b", "c"]


def test_resolve_for_returns_unique_match() -> None:
    a = _Stub("a", "anthropic", SOURCE_PAYG)
    b = _Stub("b", "anthropic", SOURCE_SUBSCRIPTION)
    register_adapter(a)
    register_adapter(b)
    assert resolve_for("anthropic", SOURCE_PAYG) is a
    assert resolve_for("anthropic", SOURCE_SUBSCRIPTION) is b


def test_resolve_for_rejects_auto_sentinel() -> None:
    with pytest.raises(ValueError, match="picker sentinel"):
        resolve_for("anthropic", SOURCE_AUTO)


def test_resolve_for_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="not a concrete value"):
        resolve_for("anthropic", "garbage")


def test_resolve_for_no_match_raises() -> None:
    register_adapter(_Stub("a", "anthropic", SOURCE_PAYG))
    with pytest.raises(AdapterNotFoundError):
        resolve_for("openai", SOURCE_PAYG)


def test_resolve_for_duplicate_pair_raises() -> None:
    register_adapter(_Stub("a", "anthropic", SOURCE_PAYG))
    # Bypass the duplicate-name guard by registering with a different name
    # but the same (provider, source) — invariant violation.
    register_adapter(_Stub("b", "anthropic", SOURCE_PAYG))
    with pytest.raises(RuntimeError, match="multiple adapters match"):
        resolve_for("anthropic", SOURCE_PAYG)


def test_bootstrap_builtins_registers_eight() -> None:
    bootstrap_builtins()
    names = {a.name for a in list_adapters()}
    assert names == {
        "anthropic-payg",
        "anthropic-oauth",
        "claude-cli",
        "openai-payg",
        "codex-oauth",
        "codex-cli",
        "glm-payg",
        "glm-coding-plan",
    }


def test_bootstrap_builtins_idempotent() -> None:
    bootstrap_builtins()
    bootstrap_builtins()  # Second call must not raise.
    assert len(list_adapters()) == 8


def test_bootstrap_builtins_provider_source_pairs() -> None:
    bootstrap_builtins()
    pairs = {(a.provider, a.source) for a in list_adapters()}
    assert pairs == {
        ("anthropic", "payg"),
        ("anthropic", "subscription"),
        ("anthropic", "adapter"),
        ("openai", "payg"),
        ("openai", "subscription"),
        ("openai", "adapter"),
        ("glm", "payg"),
        ("glm", "subscription"),
    }


def test_all_concrete_sources_covered_by_some_builtin() -> None:
    bootstrap_builtins()
    seen = {a.source for a in list_adapters()}
    assert seen >= CONCRETE_SOURCES
