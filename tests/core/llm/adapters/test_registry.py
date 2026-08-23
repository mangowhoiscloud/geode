"""Adapter registry tests — register / unregister / resolve_for / bootstrap."""

from __future__ import annotations

import pytest
from core.llm.adapters import (
    AdapterAlreadyRegisteredError,
    AdapterBillingType,
    AdapterNotFoundError,
    AdapterOverride,
    adapter_health,
    bootstrap_builtins,
    get_adapter,
    list_adapters,
    register_adapter,
    registry_snapshot,
    reload_adapters,
    resolve_for,
    unregister_adapter,
    use_registry_snapshot,
)
from core.llm.adapters.base import (
    SOURCE_ADAPTER,
    SOURCE_AUTO,
    SOURCE_PAYG,
    SOURCE_SUBSCRIPTION,
)
from core.llm.adapters.registry import (
    AdapterRegistration,
    AdapterRegistrySnapshot,
    AdapterValidationReport,
    _reset_for_test,
)


class _Stub:
    """Completion-only LLMAdapter used across registry tests."""

    def __init__(self, name: str, provider: str, source: str) -> None:
        self.name = name
        self.provider = provider
        self.source = source
        self.billing_type = AdapterBillingType.UNKNOWN

    async def acomplete(self, req):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class _DiagnosticStub(_Stub):
    def test_environment(self):  # type: ignore[no-untyped-def]
        from core.llm.adapters.base import EnvironmentReport

        return EnvironmentReport(ok=True)


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
    register_adapter(new, replace=True, trust_decision="test override")
    assert get_adapter("dup") is new
    assert registry_snapshot().report.overrides == (
        ("dup", f"runtime:{type(new).__module__}:{type(new).__qualname__}", 0, "test override"),
    )


def test_replace_requires_explicit_trust_decision() -> None:
    register_adapter(_Stub("dup", "x", SOURCE_PAYG))
    with pytest.raises(ValueError, match="requires trust_decision"):
        register_adapter(_Stub("dup", "y", SOURCE_SUBSCRIPTION), replace=True)


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


def test_register_duplicate_pair_fails_before_session() -> None:
    register_adapter(_Stub("a", "anthropic", SOURCE_PAYG))
    with pytest.raises(ValueError, match="both own route"):
        register_adapter(_Stub("b", "anthropic", SOURCE_PAYG))


def test_bootstrap_builtins_registers_five() -> None:
    bootstrap_builtins()
    names = {a.name for a in list_adapters()}
    assert names == {
        "anthropic-payg",
        "openai-payg",
        "codex-oauth",
        "glm-payg",
        "glm-coding-plan",
    }


def test_bootstrap_builtins_idempotent() -> None:
    first = bootstrap_builtins()
    second = bootstrap_builtins()  # Second call must not publish a generation.
    assert second is first
    assert len(list_adapters()) == 5


class _FakeDistribution:
    metadata = {"Name": "acme-geode-adapter"}


class _FakeEntryPoint:
    value = "acme_adapter:create"
    dist = _FakeDistribution()

    def __init__(self, name: str, factory: object) -> None:
        self.name = name
        self._factory = factory

    def load(self) -> object:
        return self._factory


def test_entry_point_discovery_publishes_generation_and_report(monkeypatch) -> None:
    plugin = _Stub("acme-adapter", "acme", SOURCE_ADAPTER)
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda *, group: [_FakeEntryPoint("acme-adapter", lambda: plugin)],
    )

    snapshot = reload_adapters()

    assert snapshot.generation == 1
    assert snapshot.get_adapter("acme-adapter") is plugin
    assert snapshot.report.loaded[-1] == "acme-adapter"
    assert snapshot.report.origins[-1] == (
        "acme-adapter",
        "entrypoint:acme-geode-adapter:acme-adapter",
    )


def test_entry_point_duplicate_requires_audited_override(monkeypatch) -> None:
    plugin = _Stub("anthropic-payg", "acme", SOURCE_ADAPTER)
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda *, group: [_FakeEntryPoint("anthropic-payg", lambda: plugin)],
    )
    with pytest.raises(AdapterAlreadyRegisteredError, match="multiple origins"):
        reload_adapters()

    snapshot = reload_adapters(
        overrides={
            "anthropic-payg": AdapterOverride(
                origin="entrypoint:acme-geode-adapter:anthropic-payg",
                priority=200,
                trust_decision="operator approved acme distribution",
            )
        }
    )
    assert snapshot.get_adapter("anthropic-payg") is plugin
    assert snapshot.report.overrides == (
        (
            "anthropic-payg",
            "entrypoint:acme-geode-adapter:anthropic-payg",
            200,
            "operator approved acme distribution",
        ),
    )


def test_discovery_rejects_unused_override(monkeypatch) -> None:
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **_kwargs: [])
    with pytest.raises(ValueError, match="did not resolve a collision"):
        reload_adapters(
            overrides={
                "missing": AdapterOverride(
                    origin="entrypoint:missing:missing",
                    priority=1,
                    trust_decision="operator approved",
                )
            }
        )


def test_session_binding_retains_immutable_generation() -> None:
    first = _Stub("first", "first", SOURCE_PAYG)
    second = _Stub("second", "second", SOURCE_PAYG)
    register_adapter(first)
    captured = registry_snapshot()
    register_adapter(second)
    current = registry_snapshot()

    assert current.generation == captured.generation + 1
    assert not hasattr(captured.registrations, "__setitem__")
    with use_registry_snapshot(captured):
        assert list_adapters() == [first]
        with pytest.raises(AdapterNotFoundError):
            get_adapter("second")
    assert list_adapters() == [first, second]


def test_snapshot_rejects_a_validation_report_for_different_contents() -> None:
    record = AdapterRegistration(
        adapter=_Stub("actual", "actual", SOURCE_PAYG),
        origin="test:actual",
        priority=0,
        trust_decision="test fixture",
    )
    with pytest.raises(ValueError, match="report does not match"):
        AdapterRegistrySnapshot(
            generation=1,
            registrations={"actual": record},
            report=AdapterValidationReport(
                generation=1,
                loaded=("claimed",),
                origins=(("claimed", "test:claimed"),),
            ),
        )


def test_bootstrap_builtins_provider_source_pairs() -> None:
    bootstrap_builtins()
    pairs = {(a.provider, a.source) for a in list_adapters()}
    assert pairs == {
        ("anthropic", "payg"),
        ("openai", "payg"),
        ("openai", "subscription"),
        ("glm", "payg"),
        ("glm", "subscription"),
    }


def test_builtin_sources_cover_payg_and_subscription() -> None:
    bootstrap_builtins()
    seen = {a.source for a in list_adapters()}
    assert seen == {SOURCE_PAYG, SOURCE_SUBSCRIPTION}


def test_retired_codex_cli_has_actionable_error() -> None:
    with pytest.raises(AdapterNotFoundError, match="use 'codex-oauth'"):
        get_adapter("codex-cli")


# ---------------------------------------------------------------------------
# Step I.c (2026-05-23) — adapter_health(name) registry accessor
# ---------------------------------------------------------------------------


def test_adapter_health_returns_environment_report_for_stub() -> None:
    """``adapter_health(name)`` delegates to ``adapter.test_environment()``.

    Step I.c — the accessor is the ergonomic one-call probe over the
    optional environment-diagnostic capability. The stub above
    always reports ``ok=True``; this confirms the helper threads the
    result through unchanged.
    """
    from core.llm.adapters.base import EnvironmentReport

    register_adapter(_DiagnosticStub("stub-health-ok", "stub", SOURCE_PAYG))
    report = adapter_health("stub-health-ok")
    assert isinstance(report, EnvironmentReport)
    assert report.ok is True


def test_adapter_health_surfaces_not_ok_report() -> None:
    """An adapter that returns ``ok=False`` must surface verbatim — no
    ``adapter_health`` post-processing. Picker UIs depend on the report's
    full structure (``checks`` + ``hints``) to render actionable errors.
    """
    from core.llm.adapters.base import EnvironmentReport

    class _UnhealthyStub(_DiagnosticStub):
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


def test_adapter_health_reports_unsupported_optional_capability() -> None:
    register_adapter(_Stub("minimal", "stub", SOURCE_PAYG))
    report = adapter_health("minimal")
    assert report.ok is False
    assert report.hints == ("adapter 'minimal' does not support environment diagnostics",)


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
