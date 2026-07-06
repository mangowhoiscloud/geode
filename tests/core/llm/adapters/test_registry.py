"""Adapter registry tests — register / unregister / resolve_for / bootstrap."""

from __future__ import annotations

import pytest
from core.llm.adapters import (
    AdapterAlreadyRegisteredError,
    AdapterBillingType,
    AdapterNotFoundError,
    adapter_health,
    bootstrap_builtins,
    get_adapter,
    list_adapters,
    register_adapter,
    resolve_for,
    unregister_adapter,
)
from core.llm.adapters.base import (
    CONCRETE_SOURCES,
    SOURCE_AUTO,
    SOURCE_PAYG,
    SOURCE_SUBSCRIPTION,
)
from core.llm.adapters.registry import _reset_for_test


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


# ---------------------------------------------------------------------------
# Step I.c (2026-05-23) — adapter_health(name) registry accessor
# ---------------------------------------------------------------------------


def test_adapter_health_returns_environment_report_for_stub() -> None:
    """``adapter_health(name)`` delegates to ``adapter.test_environment()``.

    Step I.c — the accessor is the ergonomic one-call probe over the
    existing ``LLMAdapter.test_environment`` method. The stub above
    always reports ``ok=True``; this confirms the helper threads the
    result through unchanged.
    """
    from core.llm.adapters.base import EnvironmentReport

    register_adapter(_Stub("stub-health-ok", "stub", SOURCE_PAYG))
    report = adapter_health("stub-health-ok")
    assert isinstance(report, EnvironmentReport)
    assert report.ok is True


def test_adapter_health_surfaces_not_ok_report() -> None:
    """An adapter that returns ``ok=False`` must surface verbatim — no
    ``adapter_health`` post-processing. Picker UIs depend on the report's
    full structure (``checks`` + ``hints``) to render actionable errors.
    """
    from core.llm.adapters.base import EnvironmentReport

    class _UnhealthyStub(_Stub):
        def test_environment(self) -> EnvironmentReport:
            return EnvironmentReport(
                ok=False,
                checks=(("ANTHROPIC_API_KEY", "missing"),),
                hints=("set ANTHROPIC_API_KEY",),
            )

    register_adapter(_UnhealthyStub("stub-health-fail", "stub", SOURCE_PAYG))
    report = adapter_health("stub-health-fail")
    assert report.ok is False
    assert report.checks == (("ANTHROPIC_API_KEY", "missing"),)
    assert report.hints == ("set ANTHROPIC_API_KEY",)


def test_adapter_health_missing_adapter_raises_keyerror() -> None:
    """The accessor delegates to :func:`get_adapter` for the lookup,
    which raises :class:`KeyError` on a typo. Confirm the behaviour
    propagates (no silent ``ok=False`` swallow that would mask
    operator typos)."""
    with pytest.raises(KeyError):
        adapter_health("never-registered")


def test_adapter_health_runs_on_every_builtin() -> None:
    """Smoke-call ``adapter_health`` on every bootstrapped built-in.

    The probe must not raise for any of the 8 adapters even when
    credentials are absent (the test environment has no API keys).
    Adapters honor the contract: ``test_environment`` returns an
    :class:`EnvironmentReport` with ``ok=False`` instead of raising.
    """
    from core.llm.adapters.base import EnvironmentReport

    bootstrap_builtins()
    for adapter in list_adapters():
        report = adapter_health(adapter.name)
        assert isinstance(report, EnvironmentReport), (
            f"adapter_health({adapter.name!r}) returned {type(report).__name__}; "
            "every built-in must honor the EnvironmentReport contract."
        )


def test_resolve_for_normalizes_routing_variant_ids() -> None:
    """Boundary normalization (fast-chat incident 2026-07-06) — the
    routing layer's variant vocabulary resolves without the caller
    translating first."""
    codex = _Stub("codex-oauth", "openai", SOURCE_SUBSCRIPTION)
    glm = _Stub("glm-coding-plan", "glm", SOURCE_SUBSCRIPTION)
    register_adapter(codex)
    register_adapter(glm)
    assert resolve_for("openai-codex", SOURCE_SUBSCRIPTION) is codex
    assert resolve_for("glm-coding", SOURCE_SUBSCRIPTION) is glm
    assert resolve_for("zhipuai", SOURCE_SUBSCRIPTION) is glm
    # identity for already-normalized family names
    assert resolve_for("openai", SOURCE_SUBSCRIPTION) is codex
