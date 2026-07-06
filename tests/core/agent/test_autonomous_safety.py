"""Tests for autonomous safety mechanisms: cost auto-stop, runtime ratchet, diversity forcing."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticResult
from core.agent.tool_executor import ToolExecutor
from core.observability.session_metrics import session_metrics_scope


@pytest.fixture(autouse=True)
def _isolated_session_metrics() -> Iterator[None]:
    """Step J-b.1 fix-up (2026-05-23) — isolate SessionMetrics per test.

    PR-CL-A1 (#1548) added ``_maybe_replan_async`` which reads
    ``current_session_metrics().last_verify_passed`` / ``.active_plan`` at
    every round entry. The ContextVar's lazy-init pattern means state
    from a prior test in the same xdist worker (xdist ``loadfile``
    packs all tests in this file into one worker) leaks into the next
    test's ``arun``. ``test_diversity_hint_injected`` is the canary —
    when the leaked state trips a verify_fail replan trigger, the
    planner mock consumes the tool-response slot and the diversity
    tracker never advances to 5.

    Wrapping every test in this file with a fresh ``session_metrics_scope``
    closes the leak. Each test sees a clean SessionMetrics with default
    ``last_verify_passed=True`` and ``active_plan=None`` so the replan
    trigger stays silent.
    """
    with session_metrics_scope():
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_response(text: str = "done") -> MagicMock:
    """Create a mock LLM response with text content (end_turn)."""
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.usage = MagicMock()
    resp.usage.input_tokens = 100
    resp.usage.output_tokens = 50
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    return resp


def _make_tool_block(tool_name: str, tool_id: str, tool_input: dict[str, Any]) -> MagicMock:
    """Create a single mock tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    return block


def _make_tool_response(
    tool_name: str = "web_search",
    tool_id: str = "toolu_1",
    tool_input: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock LLM response with a single tool_use block."""
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.usage = MagicMock()
    resp.usage.input_tokens = 100
    resp.usage.output_tokens = 50
    resp.content = [_make_tool_block(tool_name, tool_id, tool_input or {"query": "test"})]
    return resp


def _make_parallel_tool_response(tool_name: str, inputs: list[dict[str, Any]]) -> MagicMock:
    """Create ONE mock LLM response fanning out several parallel tool_use blocks."""
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.usage = MagicMock()
    resp.usage.input_tokens = 100
    resp.usage.output_tokens = 50
    resp.content = [
        _make_tool_block(tool_name, f"toolu_par_{i}", inp) for i, inp in enumerate(inputs)
    ]
    return resp


# ---------------------------------------------------------------------------
# 1. Cost budget auto-stop
# ---------------------------------------------------------------------------


class TestCostBudgetAutoStop:
    """Verify the loop terminates when session cost exceeds cost_budget."""

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler = MagicMock(return_value={"status": "ok"})
        return ToolExecutor(action_handlers={"web_search": handler})

    def test_cost_budget_terminates(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """When session cost >= cost_budget, loop should terminate with cost_budget_exceeded."""
        loop = AgenticLoop(context, executor, cost_budget=1.00)

        # Mock tracker with accumulated cost above budget
        mock_tracker = MagicMock()
        mock_tracker.accumulator.total_cost_usd = 1.50

        response = _make_text_response("Hello")

        # Patch the module that the inline import resolves to
        mock_module = MagicMock(get_tracker=lambda: mock_tracker)
        with (
            patch.object(loop, "_call_llm", return_value=response),
            patch.object(loop, "_track_usage"),
            patch.dict(
                "sys.modules",
                {"core.llm.token_tracker": mock_module},
            ),
        ):
            result = asyncio.run(loop.arun("test cost"))

        assert result.termination_reason == "cost_budget_exceeded"
        assert "1.00" in result.text
        assert "1.50" in result.text

    def test_cost_budget_zero_no_check(
        self,
        context: ConversationContext,
        executor: ToolExecutor,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When cost_budget=0 AND settings.cost_limit_usd=0, no cost check happens."""
        from core.config import settings

        monkeypatch.setattr(settings, "cost_limit_usd", 0.0, raising=False)
        loop = AgenticLoop(context, executor, cost_budget=0.0)
        assert loop._cost_budget == 0.0

        response = _make_text_response("Hello")
        with (
            patch.object(loop, "_call_llm", return_value=response),
            patch.object(loop, "_track_usage"),
        ):
            result = asyncio.run(loop.arun("test no budget"))

        assert result.termination_reason == "natural"

    def test_cost_limit_usd_seeds_budget(
        self,
        context: ConversationContext,
        executor: ToolExecutor,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No explicit cost_budget → settings.cost_limit_usd seeds the enforced guard."""
        from core.config import settings

        monkeypatch.setattr(settings, "cost_limit_usd", 2.5, raising=False)
        loop = AgenticLoop(context, executor)
        assert loop._cost_budget == 2.5

    def test_explicit_cost_budget_wins_over_settings(
        self,
        context: ConversationContext,
        executor: ToolExecutor,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An explicit caller cost_budget overrides settings.cost_limit_usd."""
        from core.config import settings

        monkeypatch.setattr(settings, "cost_limit_usd", 2.5, raising=False)
        loop = AgenticLoop(context, executor, cost_budget=7.0)
        assert loop._cost_budget == 7.0

    def test_cost_limit_usd_terminates_loop(
        self,
        context: ConversationContext,
        executor: ToolExecutor,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The config knob alone (no constructor param) hard-stops the loop."""
        from core.config import settings

        monkeypatch.setattr(settings, "cost_limit_usd", 1.00, raising=False)
        loop = AgenticLoop(context, executor)

        mock_tracker = MagicMock()
        mock_tracker.accumulator.total_cost_usd = 1.50

        response = _make_text_response("Hello")
        mock_module = MagicMock(get_tracker=lambda: mock_tracker)
        with (
            patch.object(loop, "_call_llm", return_value=response),
            patch.object(loop, "_track_usage"),
            patch.dict("sys.modules", {"core.llm.token_tracker": mock_module}),
        ):
            result = asyncio.run(loop.arun("test cost via settings"))

        assert result.termination_reason == "cost_budget_exceeded"

    def test_cost_budget_under_limit_continues(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """When session cost < cost_budget, loop should continue normally."""
        loop = AgenticLoop(context, executor, cost_budget=10.00)

        mock_tracker = MagicMock()
        mock_tracker.accumulator.total_cost_usd = 0.50

        response = _make_text_response("Hello")

        with (
            patch.object(loop, "_call_llm", return_value=response),
            patch.object(loop, "_track_usage"),
            patch.dict(
                "sys.modules",
                {"core.llm.token_tracker": MagicMock(get_tracker=lambda: mock_tracker)},
            ),
        ):
            result = asyncio.run(loop.arun("test under budget"))

        assert result.termination_reason == "natural"


# ---------------------------------------------------------------------------
# 2. Convergence break — v0.90.0: 3 identical errors stop the loop
# ---------------------------------------------------------------------------


class TestConvergenceBreak:
    """Verify convergence detection breaks the loop without auto-escalation.

    v0.90.0 — auto-escalation was removed. Three identical tool errors
    now break the loop on first detection so the AgenticLoop can surface
    a ``model_action_required`` diagnostic; the user picks the next
    model with ``/model``.
    """

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler = MagicMock(return_value={"status": "ok"})
        return ToolExecutor(action_handlers={"web_search": handler})

    def test_3_identical_errors_break(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """3 identical errors → break immediately (no auto-escalation)."""
        loop = AgenticLoop(context, executor)
        loop._convergence.recent_errors = [
            "web_search:timeout",
            "web_search:timeout",
            "web_search:timeout",
        ]
        assert loop._check_convergence_break() is True

    def test_two_identical_errors_no_break(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Fewer than 3 identical errors → loop continues."""
        loop = AgenticLoop(context, executor)
        loop._convergence.recent_errors = ["web_search:timeout", "web_search:timeout"]
        assert loop._check_convergence_break() is False

    def test_mixed_errors_no_break(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Different error keys → loop continues even past 3 errors."""
        loop = AgenticLoop(context, executor)
        loop._convergence.recent_errors = [
            "web_search:timeout",
            "fs:not_found",
            "web_search:timeout",
        ]
        assert loop._check_convergence_break() is False

    def test_no_escalation_state_on_detector(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """v0.90.0 — the detector must not expose any auto-escalation state."""
        loop = AgenticLoop(context, executor)
        assert not hasattr(loop._convergence, "convergence_escalated")
        assert not hasattr(loop._convergence, "_escalation_fn")


# ---------------------------------------------------------------------------
# 3. Diversity forcing
# ---------------------------------------------------------------------------


class TestDiversityForcing:
    """The guard must fire only on a genuine no-progress loop: the SAME tool
    called with IDENTICAL arguments N times. It folds args into the call
    identity (name-only tripped on healthy fan-out research), deduplicates a
    parallel batch to its distinct-signature count, and no longer special-cases
    any "naturally repetitive" tool via an exempt list.
    """

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=30)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler = MagicMock(return_value={"status": "ok"})
        return ToolExecutor(action_handlers={"grep_files": handler})

    @staticmethod
    def _drive(loop: AgenticLoop, responses: list[Any]) -> tuple[Any, MagicMock]:
        """Run ``loop.arun`` against a scripted LLM response sequence.

        Tool results carry a per-call counter so their success fingerprint
        varies each round — that keeps the *repeated-success-no-progress* guard
        (which keys on tool+input+result) from pre-empting the diversity guard
        under test, isolating the behaviour we mean to assert.
        """
        seq = list(responses)
        counter = {"n": 0}

        async def fake_call_llm(system_prompt: str, messages: list, **kwargs: Any) -> Any:
            return seq.pop(0) if seq else _make_text_response("Done")

        def fake_process(response: Any) -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            for idx, block in enumerate(getattr(response, "content", []) or []):
                if getattr(block, "type", None) == "tool_use":
                    counter["n"] += 1
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": getattr(block, "id", "") or f"t{idx}",
                            "content": f'{{"status": "ok", "n": {counter["n"]}}}',
                        }
                    )
            return results

        with (
            patch.object(loop, "_call_llm", side_effect=fake_call_llm),
            patch.object(loop, "_track_usage"),
            patch.object(loop._tool_processor, "process", side_effect=fake_process),
            patch("core.ui.agentic_ui.emit_tool_diversity_forced") as mock_emit,
        ):
            result = asyncio.run(loop.arun("go"))
        return result, mock_emit

    def test_distinct_args_across_turns_no_hint(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """(a) 5 grep_files with DIFFERENT patterns across turns must NOT fire."""
        loop = AgenticLoop(context, executor)
        responses = [
            _make_tool_response("grep_files", f"t{i}", {"pattern": f"pat_{i}"}) for i in range(5)
        ]
        _result, mock_emit = self._drive(loop, responses)

        mock_emit.assert_not_called()
        # 5 distinct (name, args_sig) accumulated, none cleared
        assert len(loop._consecutive_tool_tracker) == 5
        assert len({sig for _name, sig in loop._consecutive_tool_tracker}) == 5

    def test_identical_args_across_turns_fires(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """(b) 5 grep_files with IDENTICAL args across turns MUST fire."""
        loop = AgenticLoop(context, executor)
        same = {"pattern": "the_same_pattern"}
        responses = [_make_tool_response("grep_files", f"t{i}", same) for i in range(5)]
        _result, mock_emit = self._drive(loop, responses)

        mock_emit.assert_called_once_with("grep_files", 5)
        assert loop._consecutive_tool_tracker == []  # cleared after firing

    def test_parallel_batch_distinct_no_hint(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """(c) ONE response fanning out 5 distinct parallel calls must NOT fire."""
        loop = AgenticLoop(context, executor)
        parallel = _make_parallel_tool_response(
            "grep_files", [{"pattern": f"pat_{i}"} for i in range(5)]
        )
        _result, mock_emit = self._drive(loop, [parallel])

        mock_emit.assert_not_called()
        # one batch of 5 distinct sigs adds 5 distinct entries, never trips
        assert len(loop._consecutive_tool_tracker) == 5
        assert len({sig for _name, sig in loop._consecutive_tool_tracker}) == 5

    def test_parallel_batch_identical_deduped_no_hint(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """A single parallel batch of 5 IDENTICAL calls dedups to one occurrence."""
        loop = AgenticLoop(context, executor)
        parallel = _make_parallel_tool_response(
            "grep_files", [{"pattern": "dup"} for _ in range(5)]
        )
        _result, mock_emit = self._drive(loop, [parallel])

        mock_emit.assert_not_called()
        assert len(loop._consecutive_tool_tracker) == 1  # deduped within the batch

    def test_formerly_exempt_tool_not_special_cased(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """(d) A tool that used to be on the exempt list (general_web_search)
        now fires on identical args like any other — no special-casing remains.
        """
        loop = AgenticLoop(context, executor)
        same = {"query": "same question"}
        responses = [_make_tool_response("general_web_search", f"t{i}", same) for i in range(5)]
        _result, mock_emit = self._drive(loop, responses)

        # Previously this name sat in _DIVERSITY_EXEMPT and was cleared without
        # firing; with the exempt list removed it fires on identical args.
        mock_emit.assert_called_once_with("general_web_search", 5)

    def test_args_signature_distinguishes_inputs(self) -> None:
        """The args signature separates different inputs and matches identical ones."""
        from core.agent.loop.agent_loop import _tool_args_signature

        assert _tool_args_signature({"pattern": "a"}) != _tool_args_signature({"pattern": "b"})
        # order-independent (sort_keys) and stable across calls
        assert _tool_args_signature({"a": 1, "b": 2}) == _tool_args_signature({"b": 2, "a": 1})

    def test_tracker_capped_at_10(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Tracker keeps at most 10 (name, args_sig) entries."""
        loop = AgenticLoop(context, executor)
        # 12 distinct-arg calls across turns: never fires, but caps at 10
        responses = [
            _make_tool_response("grep_files", f"t{i}", {"pattern": f"p{i}"}) for i in range(12)
        ]
        _result, mock_emit = self._drive(loop, responses)

        mock_emit.assert_not_called()
        assert len(loop._consecutive_tool_tracker) == 10


# ---------------------------------------------------------------------------
# Integration: AgenticResult fields
# ---------------------------------------------------------------------------


class TestAgenticResultSafety:
    """Verify AgenticResult supports safety-related termination reasons."""

    def test_cost_budget_exceeded_reason(self) -> None:
        result = AgenticResult(
            text="Cost exceeded",
            termination_reason="cost_budget_exceeded",
            error="cost_budget_exceeded",
        )
        assert result.termination_reason == "cost_budget_exceeded"
        d = result.to_dict()
        assert d["termination_reason"] == "cost_budget_exceeded"

    def test_convergence_detected_reason(self) -> None:
        result = AgenticResult(
            text="Convergence",
            termination_reason="convergence_detected",
        )
        assert result.termination_reason == "convergence_detected"
