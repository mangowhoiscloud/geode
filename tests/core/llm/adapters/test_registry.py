"""Adapter registry tests — register / unregister / resolve_for / bootstrap."""

from __future__ import annotations

import pytest
from core.extensions import ExtensionPolicy, ExtensionState
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
from core.llm.registry import CredentialRoute, ProviderProfile, ProviderSpec, TransportSpec


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


def test_explicit_third_party_composition_needs_no_builtin_provider_entry() -> None:
    adapter = _Stub("acme-oauth", "acme", SOURCE_ADAPTER)
    spec = ProviderSpec(
        profile=ProviderProfile("acme", "acme", "Acme", "acme"),
        credential=CredentialRoute(
            source=SOURCE_ADAPTER,
            account_provider="acme:user",
            selector="plugin",
            auth_type="adapter",
            billing_type=AdapterBillingType.UNKNOWN,
            default=True,
        ),
        transport=TransportSpec(
            id="acme-rpc",
            api="acme-rpc",
            default_base_url="https://acme.invalid",
            retry_policy="adapter-owned",
        ),
    )

    register_adapter(adapter, provider_spec=spec)

    record = registry_snapshot().get_registration("acme-oauth")
    assert record.provider_spec is spec
    assert resolve_for("acme", SOURCE_ADAPTER) is adapter


def test_registration_rejects_compatibility_identity_drift() -> None:
    adapter = _Stub("drift", "acme", SOURCE_PAYG)
    mismatched = ProviderSpec(
        profile=ProviderProfile("other", "other", "Other", "other"),
        credential=CredentialRoute(
            source=SOURCE_PAYG,
            account_provider="other",
            selector="adapter",
            auth_type="adapter",
            billing_type=AdapterBillingType.UNKNOWN,
            default=True,
        ),
        transport=TransportSpec(
            id="other",
            api="adapter",
            default_base_url="",
            retry_policy="adapter-owned",
        ),
    )
    with pytest.raises(ValueError, match="compatibility identity"):
        register_adapter(adapter, provider_spec=mismatched)


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


def _trusted_extension_policy(name: str) -> ExtensionPolicy:
    return ExtensionPolicy.from_mapping(
        {
            "version": 1,
            "extensions": {
                f"llm-adapter:{name}": {
                    "enabled": True,
                    "trusted": True,
                    "execution": "trusted",
                    "capabilities": [],
                }
            },
        }
    )


def test_entry_point_discovery_publishes_generation_and_report(monkeypatch) -> None:
    plugin = _Stub("acme-adapter", "acme", SOURCE_ADAPTER)
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda *, group: [_FakeEntryPoint("acme-adapter", lambda: plugin)],
    )

    snapshot = reload_adapters(extension_policy=_trusted_extension_policy("acme-adapter"))

    assert snapshot.generation == 1
    assert snapshot.get_adapter("acme-adapter") is plugin
    assert snapshot.report.loaded[-1] == "acme-adapter"
    assert snapshot.report.origins[-1] == (
        "acme-adapter",
        "entrypoint:acme-geode-adapter:acme-adapter",
    )


def test_entry_point_factory_receives_narrow_extension_context(monkeypatch) -> None:
    plugin = _Stub("acme-adapter", "acme", SOURCE_ADAPTER)
    observed: list[object] = []

    def factory(context):
        observed.append(context)
        return plugin

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda *, group: [_FakeEntryPoint("acme-adapter", factory)],
    )

    reload_adapters(extension_policy=_trusted_extension_policy("acme-adapter"))

    assert len(observed) == 1
    context = observed[0]
    assert context.extension_id == "llm-adapter:acme-adapter"
    assert context.capabilities == ()
    assert dict(context.ports) == {}


def test_entry_point_preserves_explicit_provider_composition(monkeypatch) -> None:
    plugin = _Stub("acme-adapter", "acme", SOURCE_ADAPTER)
    plugin.provider_spec = ProviderSpec(
        profile=ProviderProfile("acme", "acme", "Acme", "acme"),
        credential=CredentialRoute(
            source=SOURCE_ADAPTER,
            account_provider="acme:user",
            selector="plugin",
            auth_type="adapter",
            billing_type=AdapterBillingType.UNKNOWN,
        ),
        transport=TransportSpec(
            id="acme-rpc",
            api="acme-rpc",
            default_base_url="https://acme.invalid",
            retry_policy="adapter-owned",
        ),
    )
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda *, group: [_FakeEntryPoint("acme-adapter", lambda: plugin)],
    )

    snapshot = reload_adapters(extension_policy=_trusted_extension_policy("acme-adapter"))

    assert snapshot.get_registration("acme-adapter").provider_spec is plugin.provider_spec


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("auth_type", "invalid", ValueError),
        ("billing_type", "api", TypeError),
        ("settings_values", "api_key", TypeError),
        ("settings_values", (1,), TypeError),
    ],
)
def test_credential_route_rejects_invalid_public_input(field, value, error) -> None:
    kwargs = {
        "source": SOURCE_PAYG,
        "account_provider": "acme",
        "selector": "plugin",
        "auth_type": "adapter",
        "billing_type": AdapterBillingType.UNKNOWN,
    }
    kwargs[field] = value

    with pytest.raises(error):
        CredentialRoute(**kwargs)


def test_entry_point_duplicate_requires_audited_override(monkeypatch) -> None:
    plugin = _Stub("anthropic-payg", "acme", SOURCE_ADAPTER)
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda *, group: [_FakeEntryPoint("anthropic-payg", lambda: plugin)],
    )
    with pytest.raises(AdapterAlreadyRegisteredError, match="multiple origins"):
        reload_adapters()

    snapshot = reload_adapters(
        extension_policy=_trusted_extension_policy("anthropic-payg"),
        overrides={
            "anthropic-payg": AdapterOverride(
                origin="entrypoint:acme-geode-adapter:anthropic-payg",
                priority=200,
                trust_decision="operator approved acme distribution",
            )
        },
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


def test_untrusted_entry_point_is_never_loaded(monkeypatch) -> None:
    class PoisonEntryPoint(_FakeEntryPoint):
        def load(self) -> object:
            raise AssertionError("untrusted entry point was loaded")

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda *, group: [PoisonEntryPoint("poison", object())],
    )

    snapshot = reload_adapters(extension_policy=ExtensionPolicy.empty())

    assert "poison" not in snapshot.registrations
    assert snapshot.report.extensions[0].state is ExtensionState.REJECTED


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


def test_builtin_registrations_pin_profile_credential_transport() -> None:
    snapshot = bootstrap_builtins()
    actual = {
        name: (
            record.provider_spec.profile.id,
            record.provider_spec.credential.selector,
            record.provider_spec.transport.id,
        )
        for name, record in snapshot.registrations.items()
        if record.provider_spec is not None
    }
    assert actual == {
        "anthropic-payg": ("anthropic", "settings", "anthropic-messages"),
        "openai-payg": ("openai", "settings", "openai-platform-responses"),
        "codex-oauth": ("openai-codex", "codex-oauth", "openai-codex-responses"),
        "glm-payg": ("glm", "settings", "glm-payg-chat-completions"),
        "glm-coding-plan": (
            "glm-coding",
            "profile-store",
            "glm-coding-chat-completions",
        ),
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
