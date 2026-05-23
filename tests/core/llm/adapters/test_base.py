"""Layer 4 base dataclasses + Protocol smoke tests."""

from __future__ import annotations

from core.llm.adapters.base import (
    CONCRETE_SOURCES,
    SOURCE_ADAPTER,
    SOURCE_AUTO,
    SOURCE_PAYG,
    SOURCE_SUBSCRIPTION,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    EnvironmentReport,
    LLMAdapter,
    Message,
    ModelSpec,
    QuotaWindows,
    ToolSpec,
    UsageSummary,
)


def test_concrete_sources_set() -> None:
    assert frozenset({SOURCE_PAYG, SOURCE_SUBSCRIPTION, SOURCE_ADAPTER}) == CONCRETE_SOURCES
    assert SOURCE_AUTO not in CONCRETE_SOURCES


def test_billing_type_values() -> None:
    assert AdapterBillingType.API.value == "api"
    assert AdapterBillingType.SUBSCRIPTION.value == "subscription"
    assert AdapterBillingType.SUBSCRIPTION_INCLUDED.value == "subscription_included"
    assert AdapterBillingType.UNKNOWN.value == "unknown"


def test_adapter_call_request_defaults() -> None:
    req = AdapterCallRequest(model="claude-haiku-4-5", messages=[])
    assert req.system_prompt == ""
    assert req.max_tokens == 8192
    assert req.temperature is None
    assert req.tools == ()
    assert req.stop_sequences == ()


def test_message_shape() -> None:
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.tool_use_id is None


def test_tool_spec_required_fields() -> None:
    t = ToolSpec(name="search", description="", input_schema={"type": "object"})
    assert t.name == "search"


def test_usage_summary_defaults_zero() -> None:
    u = UsageSummary()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.cached_input_tokens == 0


def test_environment_report_ok_path() -> None:
    r = EnvironmentReport(ok=True, checks=(("key", "value"),))
    assert r.ok
    assert r.checks == (("key", "value"),)
    assert r.hints == ()


def test_quota_windows_carries_window() -> None:
    q = QuotaWindows(used_tokens=10, total_tokens=100, window_seconds=300)
    assert q.used_tokens == 10
    assert q.total_tokens == 100
    assert q.window_seconds == 300


def test_model_spec_supports_flags() -> None:
    m = ModelSpec(id="claude-haiku-4-5", label="Haiku", context_tokens=200_000)
    assert m.supports_tools is True
    assert m.supports_thinking is False


def test_adapter_call_result_immutable_tuple_tool_uses() -> None:
    r = AdapterCallResult(text="ok", usage=UsageSummary(), stop_reason="end_turn")
    assert r.tool_uses == ()
    assert r.raw_response is None


class _StubAdapter:
    """Minimum-viable concrete adapter for runtime_checkable Protocol test."""

    name = "stub"
    provider = "stub-provider"
    source = SOURCE_PAYG
    billing_type = AdapterBillingType.UNKNOWN

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        return AdapterCallResult(text="", usage=UsageSummary(), stop_reason="end_turn")

    async def astream(self, req):  # type: ignore[no-untyped-def]
        return
        yield  # pragma: no cover — never reached, satisfies async-generator typing

    def test_environment(self) -> EnvironmentReport:
        return EnvironmentReport(ok=True)

    def list_models(self) -> list[ModelSpec]:
        return []

    def get_quota_windows(self) -> QuotaWindows | None:
        return None

    def detect_credential(self) -> None:
        return None


def test_protocol_runtime_checkable() -> None:
    """A class satisfying the LLMAdapter Protocol passes isinstance check."""
    assert isinstance(_StubAdapter(), LLMAdapter)
