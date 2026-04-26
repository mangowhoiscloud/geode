"""Unit tests for ReasoningMetrics + audit-logger key contract."""

from __future__ import annotations

from core.agent.reasoning_metrics import ReasoningMetrics


class TestReasoningMetrics:
    def test_thinking_ratio_normal(self) -> None:
        m = ReasoningMetrics(thinking_tokens=300, output_tokens=700)
        m.compute_derived()
        assert m.thinking_ratio == 0.3

    def test_thinking_ratio_zero_total(self) -> None:
        m = ReasoningMetrics(thinking_tokens=0, output_tokens=0)
        m.compute_derived()
        assert m.thinking_ratio == 0.0

    def test_cost_per_tool_call_with_tools(self) -> None:
        m = ReasoningMetrics(cost_usd=0.50, tool_calls_total=4)
        m.compute_derived()
        assert m.cost_per_tool_call == 0.125

    def test_cost_per_tool_call_no_tools_is_none(self) -> None:
        """Sentinel: 0 tool calls → None (distinguishes from 'very cheap per call')."""
        m = ReasoningMetrics(cost_usd=1.00, tool_calls_total=0)
        m.compute_derived()
        assert m.cost_per_tool_call is None

    def test_to_dict_omits_cost_per_tool_when_none(self) -> None:
        m = ReasoningMetrics(cost_usd=1.00, tool_calls_total=0)
        m.compute_derived()
        d = m.to_dict()
        assert "cost_per_tool_call" not in d

    def test_to_dict_includes_cost_per_tool_when_set(self) -> None:
        m = ReasoningMetrics(cost_usd=0.50, tool_calls_total=2)
        m.compute_derived()
        d = m.to_dict()
        assert d["cost_per_tool_call"] == 0.25


class TestAuditLoggerKeyContract:
    """Lock the bootstrap REASONING_METRICS audit-logger keys to to_dict() schema.

    Drift between the two would silently empty the audit log (logs render '').
    """

    def test_audit_logger_keys_present_in_to_dict(self) -> None:
        import inspect

        from core.lifecycle import bootstrap

        # Pull the audit-logger spec table by source inspection — the table
        # is defined inside _register_default_plugins as a local list, so we
        # don't have a clean module-level handle to it.
        src = inspect.getsource(bootstrap)
        # Confirm the keys list now matches ReasoningMetrics.to_dict().
        assert '["total_rounds", "tool_calls_total"]' in src, (
            "REASONING_METRICS audit logger keys must match ReasoningMetrics.to_dict() field names. "
            "See core/agent/reasoning_metrics.py."
        )

        m = ReasoningMetrics(total_rounds=5, tool_calls_total=3)
        m.compute_derived()
        d = m.to_dict()
        assert "total_rounds" in d
        assert "tool_calls_total" in d
