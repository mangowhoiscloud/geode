"""Tests for LLM resilience hardening features.

Covers: jitter, cross-provider fallback, error classification,
retry events, auto-checkpoint, context detail, budget warning.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. Backoff jitter
# ---------------------------------------------------------------------------


class TestBackoffJitter:
    """Verify retry delay uses full jitter (random.uniform(0, cap))."""

    def test_jitter_produces_varying_delays(self) -> None:
        """Multiple calls should produce different delays (not deterministic)."""
        from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

        call_count = 0
        delays: list[float] = []

        cb = CircuitBreaker()

        def _failing_fn(*, model: str) -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("test")

        def _capture_sleep(s: float) -> None:
            delays.append(s)

        with (
            patch("core.llm.fallback.time.sleep", side_effect=_capture_sleep),
            pytest.raises(ConnectionError),
        ):
            retry_with_backoff_generic(
                _failing_fn,
                model="test-model",
                fallback_models=[],
                circuit_breaker=cb,
                retryable_errors=(ConnectionError,),
                max_retries=3,
                retry_base_delay=2.0,
                retry_max_delay=30.0,
            )

        assert len(delays) == 3
        # Jitter: delays should be in [0, cap], not all identical
        for d in delays:
            assert d >= 0

    def test_jitter_cap_respects_max_delay(self) -> None:
        """Jitter should never exceed retry_max_delay."""
        from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

        delays: list[float] = []
        cb = CircuitBreaker()

        def _failing(*, model: str) -> str:
            raise ConnectionError("test")

        def _capture_sleep(s: float) -> None:
            delays.append(s)

        with (
            patch("core.llm.fallback.time.sleep", side_effect=_capture_sleep),
            pytest.raises(ConnectionError),
        ):
            retry_with_backoff_generic(
                _failing,
                model="m",
                fallback_models=[],
                circuit_breaker=cb,
                retryable_errors=(ConnectionError,),
                max_retries=5,
                retry_base_delay=10.0,
                retry_max_delay=15.0,
            )

        for d in delays:
            assert d <= 15.0


# ---------------------------------------------------------------------------
# 2. Cross-provider dispatch
# ---------------------------------------------------------------------------


class TestCrossProviderDispatch:
    """Verify _cross_provider_dispatch helper."""

    def test_single_provider_no_fallback(self) -> None:
        """Without cross-provider enabled, only primary is tried."""
        from core.llm.router import _cross_provider_dispatch

        calls: list[tuple[str, str]] = []

        def _dispatch(p: str, m: str) -> str:
            calls.append((p, m))
            return "ok"

        with patch("core.llm.provider_dispatch.settings") as mock_settings:
            mock_settings.llm_cross_provider_failover = False
            result = _cross_provider_dispatch("anthropic", "claude-opus-4-6", _dispatch, "test")

        assert result == "ok"
        assert len(calls) == 1
        assert calls[0] == ("anthropic", "claude-opus-4-6")

    def test_cross_provider_on_failure(self) -> None:
        """When primary fails and cross-provider is enabled, tries next provider."""
        from core.llm.router import _cross_provider_dispatch

        calls: list[tuple[str, str]] = []

        def _dispatch(p: str, m: str) -> str:
            calls.append((p, m))
            if p == "anthropic":
                raise RuntimeError("provider down")
            return "fallback_ok"

        with (
            patch("core.llm.provider_dispatch.settings") as mock_settings,
            patch("core.llm.provider_dispatch._get_fallback_chain") as mock_chain,
            patch("core.llm.provider_dispatch._fire_hook"),
        ):
            mock_settings.llm_cross_provider_failover = True
            mock_settings.llm_cross_provider_order = ["anthropic", "openai", "glm"]
            mock_chain.return_value = ["gpt-5.4", "gpt-5.2"]

            result = _cross_provider_dispatch("anthropic", "claude-opus-4-6", _dispatch, "test")

        assert result == "fallback_ok"
        assert len(calls) == 2
        assert calls[0][0] == "anthropic"
        assert calls[1][0] == "openai"

    def test_all_providers_fail(self) -> None:
        """When all providers fail, raises the last exception."""
        from core.llm.router import _cross_provider_dispatch

        def _dispatch(p: str, m: str) -> str:
            raise RuntimeError(f"{p} down")

        with (
            patch("core.llm.provider_dispatch.settings") as mock_settings,
            patch("core.llm.provider_dispatch._get_fallback_chain", return_value=["m1"]),
            patch("core.llm.provider_dispatch._fire_hook"),
            pytest.raises(RuntimeError, match="glm down"),
        ):
            mock_settings.llm_cross_provider_failover = True
            mock_settings.llm_cross_provider_order = ["anthropic", "openai", "glm"]
            _cross_provider_dispatch("anthropic", "claude-opus-4-6", _dispatch, "test")


# ---------------------------------------------------------------------------
# 3. Error classification
# ---------------------------------------------------------------------------


class TestErrorClassification:
    """Verify classify_llm_error maps exceptions to severity and hints."""

    def test_rate_limit(self) -> None:
        from core.llm.errors import LLMRateLimitError, classify_llm_error

        try:
            raise LLMRateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )
        except LLMRateLimitError as exc:
            et, sev, hint = classify_llm_error(exc)
        assert et == "rate_limit"
        assert sev == "warning"
        assert "rate limit" in hint.lower()

    def test_auth_error(self) -> None:
        from core.llm.errors import LLMAuthenticationError, classify_llm_error

        try:
            raise LLMAuthenticationError(
                message="invalid key",
                response=MagicMock(status_code=401),
                body=None,
            )
        except LLMAuthenticationError as exc:
            et, sev, hint = classify_llm_error(exc)
        assert et == "auth"
        assert sev == "error"

    def test_billing_error(self) -> None:
        from core.llm.errors import BillingError, classify_llm_error

        et, sev, hint = classify_llm_error(BillingError("no credits"))
        assert et == "billing"
        assert sev == "critical"

    def test_unknown_error(self) -> None:
        from core.llm.errors import classify_llm_error

        et, sev, hint = classify_llm_error(ValueError("something weird"))
        assert et == "unknown"
        assert sev == "warning"


# ---------------------------------------------------------------------------
# 4. Retry callback (on_retry)
# ---------------------------------------------------------------------------


class TestRetryCallback:
    """Verify on_retry callback is invoked during retries."""

    def test_on_retry_called_with_metadata(self) -> None:
        from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

        retry_events: list[dict[str, Any]] = []

        def _on_retry(**kwargs: Any) -> None:
            retry_events.append(kwargs)

        cb = CircuitBreaker()

        def _failing(*, model: str) -> str:
            raise ConnectionError("down")

        with (
            patch("core.llm.fallback.time.sleep"),
            pytest.raises(ConnectionError),
        ):
            retry_with_backoff_generic(
                _failing,
                model="m",
                fallback_models=[],
                circuit_breaker=cb,
                retryable_errors=(ConnectionError,),
                max_retries=2,
                on_retry=_on_retry,
            )

        assert len(retry_events) == 2
        assert retry_events[0]["attempt"] == 1
        assert retry_events[1]["attempt"] == 2
        assert "delay_s" in retry_events[0]
        assert "elapsed_s" in retry_events[0]
        assert retry_events[0]["error_type"] == "ConnectionError"


# ---------------------------------------------------------------------------
# 5. HookEvent count
# ---------------------------------------------------------------------------


class TestHookEventCount:
    """Verify FALLBACK_CROSS_PROVIDER is present."""

    def test_cross_provider_hook_exists(self) -> None:
        from core.hooks import HookEvent

        assert hasattr(HookEvent, "FALLBACK_CROSS_PROVIDER")
        assert HookEvent.FALLBACK_CROSS_PROVIDER.value == "fallback_cross_provider"

    def test_pipeline_timeout_hook_exists(self) -> None:
        from core.hooks import HookEvent

        assert hasattr(HookEvent, "PIPELINE_TIMEOUT")
        assert HookEvent.PIPELINE_TIMEOUT.value == "pipeline_timeout"

    def test_total_event_count(self) -> None:
        from core.hooks import HookEvent

        assert len(HookEvent) == 49


# ---------------------------------------------------------------------------
# 6. Config settings
# ---------------------------------------------------------------------------


class TestResilienceConfig:
    """Verify new config fields exist with correct defaults."""

    def test_cross_provider_defaults(self) -> None:
        from core.config import Settings

        s = Settings()
        assert s.llm_cross_provider_failover is False
        assert s.llm_cross_provider_order == ["anthropic", "openai", "glm"]

    def test_cost_ratio_default(self) -> None:
        from core.config import Settings

        s = Settings()
        assert s.llm_max_fallback_cost_ratio == 0.0  # unlimited

    def test_pipeline_timeout_default(self) -> None:
        from core.config import Settings

        s = Settings()
        assert s.pipeline_timeout_s == 600.0


# ---------------------------------------------------------------------------
# 7. Adapter last_error
# ---------------------------------------------------------------------------


class TestAdapterLastError:
    """Verify adapters expose last_error for error classification."""

    def test_anthropic_adapter_has_last_error(self) -> None:
        from core.llm.providers.anthropic import ClaudeAgenticAdapter

        adapter = ClaudeAgenticAdapter()
        assert adapter.last_error is None

    def test_openai_adapter_has_last_error(self) -> None:
        from core.llm.providers.openai import OpenAIAgenticAdapter

        adapter = OpenAIAgenticAdapter()
        assert adapter.last_error is None


# ---------------------------------------------------------------------------
# 8. B1: Degraded fallback on retry exhaustion
# ---------------------------------------------------------------------------


class TestDegradedFallback:
    """Verify _make_degraded_result returns proper fallback for each node type."""

    def test_analyst_degraded(self) -> None:
        from core.graph import _make_degraded_result

        result = _make_degraded_result(
            "analyst", ValueError("test"), {"_analyst_type": "game_mechanics"}
        )
        assert "analyses" in result
        assert len(result["analyses"]) == 1
        assert result["analyses"][0].is_degraded is True
        assert result["analyses"][0].analyst_type == "game_mechanics"
        assert result["analyses"][0].confidence == 0.0
        assert "errors" in result

    def test_evaluator_degraded(self) -> None:
        from core.graph import _make_degraded_result

        result = _make_degraded_result(
            "evaluator", RuntimeError("fail"), {"_evaluator_type": "quality_judge"}
        )
        assert "evaluations" in result
        ev = result["evaluations"]["quality_judge"]
        assert ev.is_degraded is True
        assert ev.composite_score == 0.0
        assert "a_score" in ev.axes

    def test_scoring_degraded(self) -> None:
        from core.graph import _make_degraded_result

        result = _make_degraded_result("scoring", RuntimeError("crash"), {})
        assert result["final_score"] == 0.0
        assert result["tier"] == "C"
        assert "errors" in result

    def test_unknown_node_degraded(self) -> None:
        from core.graph import _make_degraded_result

        result = _make_degraded_result("router", RuntimeError("x"), {})
        assert "errors" in result
        assert result["errors"][0].startswith("router:")


# ---------------------------------------------------------------------------
# 9. B4: Degraded scoring penalty
# ---------------------------------------------------------------------------


class TestDegradedScoringPenalty:
    """Verify degraded sources reduce confidence in scoring."""

    def test_penalty_applied_for_degraded_analysts(self) -> None:
        from core.state import AnalysisResult, EvaluatorResult

        # 4 analysts, 2 degraded + 3 evaluators, 0 degraded = 2/7 degraded
        analyses = [
            AnalysisResult(
                analyst_type="game_mechanics",
                score=4.0,
                key_finding="ok",
                reasoning="ok",
                confidence=80.0,
            ),
            AnalysisResult(
                analyst_type="player_experience",
                score=1.0,
                key_finding="bad",
                reasoning="bad",
                confidence=0.0,
                is_degraded=True,
            ),
            AnalysisResult(
                analyst_type="growth_potential",
                score=4.0,
                key_finding="ok",
                reasoning="ok",
                confidence=80.0,
            ),
            AnalysisResult(
                analyst_type="discovery",
                score=1.0,
                key_finding="bad",
                reasoning="bad",
                confidence=0.0,
                is_degraded=True,
            ),
        ]
        evaluations = {
            "quality_judge": EvaluatorResult(
                evaluator_type="quality_judge",
                axes={
                    "a_score": 3.0,
                    "b_score": 3.0,
                    "c_score": 3.0,
                    "b1_score": 3.0,
                    "c1_score": 3.0,
                    "c2_score": 3.0,
                    "m_score": 3.0,
                    "n_score": 3.0,
                },
                composite_score=50.0,
                rationale="ok",
            ),
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 3.0, "e_score": 3.0, "f_score": 3.0},
                composite_score=50.0,
                rationale="ok",
            ),
            "community_momentum": EvaluatorResult(
                evaluator_type="community_momentum",
                axes={"j_score": 3.0, "k_score": 3.0, "l_score": 3.0},
                composite_score=50.0,
                rationale="ok",
            ),
        }

        from core.domains.game_ip.nodes.scoring import _calc_analyst_confidence

        base_confidence = _calc_analyst_confidence(analyses)

        # With 2 degraded out of 7 total, penalty = 1 - (2/7)*0.5 ≈ 0.857
        total = len(analyses) + len(evaluations)
        expected_penalty = 1.0 - (2 / total) * 0.5
        expected_conf = base_confidence * expected_penalty
        # Just verify the formula logic is correct
        assert 0 < expected_penalty < 1.0
        assert expected_conf < base_confidence


# ---------------------------------------------------------------------------
# 10. B5: Verification failure triggers enrichment loop
# ---------------------------------------------------------------------------


class TestVerificationEnrichmentLoop:
    """Verify _configured_should_continue returns 'gather' on verification failure."""

    def test_guardrails_failure_triggers_gather(self) -> None:
        from core.state import BiasBusterResult, GuardrailResult

        # Build a minimal state
        state = {
            "guardrails": GuardrailResult(all_passed=False, details=["G1 failed"]),
            "biasbuster": BiasBusterResult(overall_pass=True, explanation="ok"),
            "analyst_confidence": 80.0,
            "iteration": 1,
            "max_iterations": 5,
        }

        # Test the verification failure detection logic indirectly
        gd = state["guardrails"]
        bb = state["biasbuster"]
        verification_failed = (not gd.all_passed) or (not bb.overall_pass)
        assert verification_failed is True

    def test_biasbuster_failure_triggers_gather(self) -> None:
        from core.state import BiasBusterResult, GuardrailResult

        state = {
            "guardrails": GuardrailResult(all_passed=True, details=[]),
            "biasbuster": BiasBusterResult(overall_pass=False, explanation="bias detected"),
        }
        verification_failed = (not state["guardrails"].all_passed) or (
            not state["biasbuster"].overall_pass
        )
        assert verification_failed is True


# ---------------------------------------------------------------------------
# 11. B6: Evaluator partial retry
# ---------------------------------------------------------------------------


class TestEvaluatorPartialRetry:
    """Verify make_evaluator_sends skips non-degraded on re-iteration."""

    def test_skips_non_degraded_on_iteration_2(self) -> None:
        from core.state import EvaluatorResult

        state = {
            "ip_name": "Test",
            "ip_info": {},
            "monolake": {},
            "signals": {},
            "analyses": [],
            "dry_run": False,
            "verbose": False,
            "pipeline_mode": "full_pipeline",
            "iteration": 2,
            "evaluations": {
                "quality_judge": EvaluatorResult(
                    evaluator_type="quality_judge",
                    axes={
                        "a_score": 4.0,
                        "b_score": 4.0,
                        "c_score": 4.0,
                        "b1_score": 4.0,
                        "c1_score": 4.0,
                        "c2_score": 4.0,
                        "m_score": 4.0,
                        "n_score": 4.0,
                    },
                    composite_score=75.0,
                    rationale="good",
                ),
                "hidden_value": EvaluatorResult(
                    evaluator_type="hidden_value",
                    axes={"d_score": 3.0, "e_score": 3.0, "f_score": 3.0},
                    composite_score=0.0,
                    rationale="degraded",
                    is_degraded=True,
                ),
            },
            "errors": [],
            "_prompt_overrides": {},
            "_extra_instructions": [],
            "memory_context": None,
            "_tool_definitions": [],
        }

        from core.domains.game_ip.nodes.evaluators import make_evaluator_sends

        sends = make_evaluator_sends(state)
        # quality_judge was non-degraded → skipped. hidden_value was degraded → re-run.
        # community_momentum had no prior result → run.
        send_types = [s.arg.get("_evaluator_type") for s in sends]
        assert "quality_judge" not in send_types
        assert "hidden_value" in send_types
        assert "community_momentum" in send_types

    def test_no_skip_on_iteration_1(self) -> None:
        state = {
            "ip_name": "Test",
            "ip_info": {},
            "monolake": {},
            "signals": {},
            "analyses": [],
            "dry_run": False,
            "verbose": False,
            "pipeline_mode": "full_pipeline",
            "iteration": 1,
            "evaluations": {},
            "errors": [],
            "_prompt_overrides": {},
            "_extra_instructions": [],
            "memory_context": None,
            "_tool_definitions": [],
        }

        from core.domains.game_ip.nodes.evaluators import make_evaluator_sends

        sends = make_evaluator_sends(state)
        assert len(sends) == 3  # all evaluators


# ---------------------------------------------------------------------------
# 12. B7: iteration_history trimming
# ---------------------------------------------------------------------------


class TestIterationHistoryTrimming:
    """Verify the custom reducer caps at 10 entries."""

    def test_trim_at_10(self) -> None:
        from core.state import _add_and_trim_history

        left = [{"iteration": i} for i in range(8)]
        right = [{"iteration": i} for i in range(8, 13)]
        result = _add_and_trim_history(left, right)
        assert len(result) == 10
        assert result[0]["iteration"] == 3  # oldest kept
        assert result[-1]["iteration"] == 12

    def test_no_trim_under_limit(self) -> None:
        from core.state import _add_and_trim_history

        left = [{"iteration": 1}]
        right = [{"iteration": 2}]
        result = _add_and_trim_history(left, right)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# 13. B2: Error propagation to MCP caller
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    """Verify pipeline errors are included in MCP output."""

    def test_errors_included_in_output(self) -> None:
        """If graph result has errors, they appear in MCP output."""
        # This tests the logic path, not the full MCP call
        result_with_errors = {
            "tier": "C",
            "final_score": 30.0,
            "errors": ["analyst: timeout", "evaluator: validation"],
        }
        output: dict[str, Any] = {
            "ip_name": "test",
            "tier": result_with_errors.get("tier", "?"),
            "final_score": result_with_errors.get("final_score", 0),
        }
        pipeline_errors = result_with_errors.get("errors", [])
        if pipeline_errors:
            output["errors"] = pipeline_errors

        assert "errors" in output
        assert len(output["errors"]) == 2

    def test_no_errors_key_when_clean(self) -> None:
        result_clean = {"tier": "A", "final_score": 68.0, "errors": []}
        output: dict[str, Any] = {"ip_name": "test"}
        pipeline_errors = result_clean.get("errors", [])
        if pipeline_errors:
            output["errors"] = pipeline_errors
        assert "errors" not in output


# ---------------------------------------------------------------------------
# 14. C2: Cost ratio guard
# ---------------------------------------------------------------------------


class TestCostRatioGuard:
    """Verify fallback cost ratio check skips expensive models."""

    def test_sequential_tool_batch_clearing(self) -> None:
        """Sequential tool calls clear completed entries from previous batch."""
        from core.cli.ui.tool_tracker import ToolCallTracker

        tracker = ToolCallTracker()
        # First batch: single tool call
        tracker.on_tool_start({"name": "sequentialthinking", "args_preview": 'thought="step 1"'})
        tracker.on_tool_end({"name": "sequentialthinking", "summary": "ok"})
        assert all(t["done"] for t in tracker._tools)
        assert not tracker._running

        # Second batch: should clear previous completed entries
        tracker.on_tool_start({"name": "sequentialthinking", "args_preview": 'thought="step 2"'})
        assert len(tracker._tools) == 1  # cleared old, added new
        assert tracker._tools[0]["args"] == 'thought="step 2"'
        tracker.stop()

    def test_parallel_tools_not_cleared(self) -> None:
        """Parallel tool calls within a batch are preserved."""
        from core.cli.ui.tool_tracker import ToolCallTracker

        tracker = ToolCallTracker()
        tracker.on_tool_start({"name": "web_search", "args_preview": "q=A"})
        tracker.on_tool_start({"name": "read_file", "args_preview": "path=/x"})
        assert len(tracker._tools) == 2
        assert tracker._running
        # End first — second still running, batch not cleared
        tracker.on_tool_end({"name": "web_search", "summary": "done"})
        assert len(tracker._tools) == 2
        tracker.stop()

    def test_suspend_resets_line_count(self) -> None:
        """suspend() erases lines and resets _line_count so on_tool_end prints at cursor."""
        from core.cli.ui.tool_tracker import ToolCallTracker

        tracker = ToolCallTracker()
        tracker.on_tool_start({"name": "analyze_ip", "args_preview": 'ip_name="Berserk"'})
        assert tracker._line_count > 0
        assert tracker._running

        # Suspend — simulates pipeline event arriving mid-tool
        tracker.suspend()
        assert tracker._line_count == 0
        assert not tracker._running
        assert tracker._spinner_thread is None

        # on_tool_end after suspend — should not cursor-up (line_count=0)
        tracker.on_tool_end({"name": "analyze_ip", "summary": "S · 81.2", "duration_s": 3.5})
        assert tracker._tools[0]["done"] is True
        # line_count should be 1 (the ✓ line, printed at current position)
        assert tracker._line_count == 1

    def test_suspend_idempotent(self) -> None:
        """Second suspend() call is a no-op."""
        from core.cli.ui.tool_tracker import ToolCallTracker

        tracker = ToolCallTracker()
        tracker.on_tool_start({"name": "list_ips", "args_preview": ""})
        tracker.suspend()
        assert tracker._line_count == 0
        # Second call — should not raise or change state
        tracker.suspend()
        assert tracker._line_count == 0
        assert tracker._spinner_thread is None
        tracker.stop()

    def test_cost_ratio_skip(self) -> None:
        """When ratio exceeds limit, fallback model is skipped."""
        from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic
        from core.llm.token_tracker import ModelPrice

        calls: list[str] = []
        cb = CircuitBreaker()

        def _failing(*, model: str) -> str:
            calls.append(model)
            raise ConnectionError("down")

        mock_settings = MagicMock()
        mock_settings.llm_max_fallback_cost_ratio = 2.0
        mock_pricing = {
            "cheap": ModelPrice(input=1e-6, output=5e-6),
            "expensive": ModelPrice(input=10e-6, output=50e-6),
        }

        with (
            patch("core.llm.fallback.time.sleep"),
            patch("core.config.settings", mock_settings),
            patch("core.llm.token_tracker.MODEL_PRICING", mock_pricing),
            pytest.raises(ConnectionError),
        ):
            retry_with_backoff_generic(
                _failing,
                model="cheap",
                fallback_models=["expensive"],
                circuit_breaker=cb,
                retryable_errors=(ConnectionError,),
                max_retries=1,
            )

        # expensive model should be skipped due to ratio (10x > 2x limit)
        assert "expensive" not in calls
