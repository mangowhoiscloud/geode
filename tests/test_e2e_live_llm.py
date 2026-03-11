"""Live E2E tests — real LLM API calls with LangSmith tracing.

These tests call the actual Anthropic API. They are marked with @pytest.mark.live
and excluded from the default test suite. Run explicitly with:

    uv run pytest tests/test_e2e_live_llm.py -v -m live

Scenarios mapped from docs/e2e-orchestration-scenarios.md §1, §4, §5, §6.
"""

from __future__ import annotations

import os

import pytest

# Gate: skip all tests if no API key
_HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not _HAS_API_KEY, reason="ANTHROPIC_API_KEY not set"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(
    *,
    max_rounds: int = 10,
    tool_registry: object | None = None,
    force_dry_run: bool = False,
) -> tuple:
    """Create an AgenticLoop wired with SubAgentManager.

    Returns (loop, context, executor, sub_mgr) 4-tuple.
    """
    from core.cli import (
        _build_sub_agent_manager,
        _build_tool_handlers,
        _set_readiness,
    )
    from core.cli.agentic_loop import AgenticLoop
    from core.cli.conversation import ConversationContext
    from core.cli.startup import check_readiness
    from core.cli.tool_executor import ToolExecutor

    readiness = check_readiness()
    if not force_dry_run:
        readiness.force_dry_run = False
        readiness.blocked = False
        readiness.has_api_key = True
    _set_readiness(readiness)

    handlers = _build_tool_handlers(verbose=False)
    sub_mgr = _build_sub_agent_manager(verbose=False)
    context = ConversationContext()
    executor = ToolExecutor(
        action_handlers=handlers,
        auto_approve=True,
        sub_agent_manager=sub_mgr,
    )
    loop = AgenticLoop(
        context,
        executor,
        max_rounds=max_rounds,
        tool_registry=tool_registry,  # type: ignore[arg-type]
    )
    return loop, context, executor, sub_mgr


# ===========================================================================
# §1  AgenticLoop — Multi-round Tool Execution (Live)
# ===========================================================================


class TestAgenticLoopLive:
    """Scenarios 1-1 through 1-7 with real Anthropic API calls."""

    def test_1_1_text_only(self) -> None:
        """1-1. Single intent (text-only response) — no tool use."""
        loop, *_ = _make_loop()
        result = loop.run("안녕하세요")
        assert result.text, "LLM should produce text"
        assert result.rounds >= 1
        assert result.tool_calls == []
        assert result.error is None

    def test_1_2_single_tool(self) -> None:
        """1-2. Single intent → single tool (list_ips)."""
        loop, *_ = _make_loop()
        result = loop.run("IP 목록 보여줘")
        assert result.error is None
        assert result.rounds >= 1
        tool_names = [tc["tool"] for tc in result.tool_calls]
        assert "list_ips" in tool_names, f"Expected list_ips, got {tool_names}"
        assert result.text, "LLM should produce summary text"

    def test_1_3_sequential_tools(self) -> None:
        """1-3. Multi-intent → sequential tool calls."""
        loop, *_ = _make_loop(max_rounds=8)
        result = loop.run("Berserk 분석하고 Cowboy Bebop이랑 비교해줘")
        assert result.error is None
        tool_names = [tc["tool"] for tc in result.tool_calls]
        assert "analyze_ip" in tool_names, f"Expected analyze_ip, got {tool_names}"
        assert result.rounds >= 2

    def test_1_4_multi_tool_single_response(self) -> None:
        """1-4. Multi-tool in single response (2 searches)."""
        loop, *_ = _make_loop()
        result = loop.run("Berserk이랑 Cowboy Bebop 둘 다 검색해줘")
        assert result.error is None
        assert len(result.tool_calls) >= 1
        assert result.text

    def test_1_5_max_rounds_guardrail(self) -> None:
        """1-5. Max rounds guardrail — forced termination."""
        loop, *_ = _make_loop(max_rounds=2)
        result = loop.run("Berserk 분석하고 비교하고 리포트 만들어줘")
        assert result.rounds <= 2
        if result.error:
            assert result.error == "max_rounds"

    def test_1_7_multi_turn_context(self) -> None:
        """1-7. Multi-turn context preservation across turns."""
        loop, context, *_ = _make_loop()
        r1 = loop.run("Berserk 분석해")
        assert r1.error is None
        assert context.turn_count >= 1

        r2 = loop.run("점수가 왜 높아?")
        assert r2.error is None
        assert r2.text
        assert context.turn_count >= 2


# ===========================================================================
# §4  LangSmith Tracing
# ===========================================================================


class TestLangSmithTracingLive:
    """Scenario 4-2: verify tracing infrastructure works.

    Uses local LLMUsageAccumulator instead of remote LangSmith API to avoid
    rate limit (429) failures when monthly quota is exceeded.
    """

    def test_4_2_traces_recorded(self) -> None:
        """4-2. Tracing infrastructure — local accumulator records token usage."""
        from core.llm.client import (
            get_usage_accumulator,
            is_langsmith_enabled,
            reset_usage_accumulator,
        )

        reset_usage_accumulator()

        loop, *_ = _make_loop()
        result = loop.run("IP 목록 보여줘")
        assert result.error is None

        # Verify local token accumulator recorded usage
        acc = get_usage_accumulator()
        assert len(acc.calls) > 0, "No LLM calls recorded in accumulator"
        assert acc.total_input_tokens > 0, "No input tokens recorded"
        assert acc.total_output_tokens > 0, "No output tokens recorded"
        assert acc.total_cost_usd > 0, "No cost recorded"

        # Verify tracing gate is correctly configured
        summary = acc.to_dict()
        assert summary["call_count"] >= 1
        assert "total_cost_usd" in summary

        # If LangSmith is enabled, verify decorator is active (no remote call)
        if is_langsmith_enabled():
            from core.llm.client import _maybe_traceable

            decorator = _maybe_traceable(name="test_check")
            assert callable(decorator)


# ===========================================================================
# §5  Full Pipeline E2E (live LLM, no dry-run)
# ===========================================================================


class TestFullPipelineLive:
    """Scenarios 5-1 through 5-3 with real LLM calls."""

    def test_5_1_single_ip_analysis(self) -> None:
        """5-1. Full pipeline for Berserk.

        Disables LangSmith tracing to avoid 429 rate limit interference.
        Tracing correctness is verified separately in test_4_2 via local accumulator.
        """
        from core.llm.client import get_usage_accumulator, reset_usage_accumulator
        from core.runtime import GeodeRuntime
        from core.state import GeodeState

        # Disable LangSmith to prevent 429 rate limit from interfering
        old_tracing = os.environ.pop("LANGCHAIN_TRACING_V2", None)
        reset_usage_accumulator()

        try:
            runtime = GeodeRuntime.create("Berserk")

            initial_state: GeodeState = {
                "ip_name": "berserk",
                "pipeline_mode": "full_pipeline",
                "session_id": "test:berserk:live",
                "dry_run": False,
                "verbose": False,
                "skip_verification": False,
                "analyses": [],
                "errors": [],
                "iteration": 1,
                "max_iterations": 3,
            }

            graph = runtime.compile_graph()
            config = runtime.thread_config
            final_state: dict = dict(initial_state)

            for event in graph.stream(initial_state, config=config):  # type: ignore[arg-type]
                for node_name, output in event.items():
                    if node_name != "__end__":
                        final_state.update(output)

            assert final_state.get("tier") in ("S", "A", "B", "C"), (
                f"Invalid tier: {final_state.get('tier')}"
            )
            assert final_state.get("final_score", 0) > 0
            analyses = final_state.get("analyses", [])
            assert len(analyses) == 4, f"Expected 4 analysts, got {len(analyses)}"
            assert final_state.get("synthesis") is not None

            # Verify token usage recorded locally (no remote dependency)
            acc = get_usage_accumulator()
            assert len(acc.calls) > 0, "Pipeline made no LLM calls"
        finally:
            if old_tracing is not None:
                os.environ["LANGCHAIN_TRACING_V2"] = old_tracing

    def test_5_2_multi_ip_smoke(self) -> None:
        """5-2. Multi-IP smoke — all 3 fixture IPs."""
        from core.runtime import GeodeRuntime
        from core.state import GeodeState

        for ip_name in [
            "berserk",
            "cowboy bebop",
            "ghost in the shell",
        ]:
            runtime = GeodeRuntime.create(ip_name)
            initial_state: GeodeState = {
                "ip_name": ip_name,
                "pipeline_mode": "full_pipeline",
                "session_id": (f"test:{ip_name.replace(' ', '_')}:live"),
                "dry_run": False,
                "verbose": False,
                "skip_verification": True,
                "analyses": [],
                "errors": [],
                "iteration": 1,
                "max_iterations": 3,
            }
            graph = runtime.compile_graph()
            config = runtime.thread_config
            final_state: dict = dict(initial_state)

            for event in graph.stream(initial_state, config=config):  # type: ignore[arg-type]
                for node_name, output in event.items():
                    if node_name != "__end__":
                        final_state.update(output)

            assert final_state.get("tier") in (
                "S",
                "A",
                "B",
                "C",
            ), f"{ip_name}: invalid tier {final_state.get('tier')}"
            assert final_state.get("final_score", 0) > 0, f"{ip_name}: score is 0"

    def test_5_3_feedback_loop_high_confidence(self) -> None:
        """5-3. High confidence → synthesizer visited."""
        from core.runtime import GeodeRuntime
        from core.state import GeodeState

        runtime = GeodeRuntime.create("Berserk")
        initial_state: GeodeState = {
            "ip_name": "berserk",
            "pipeline_mode": "full_pipeline",
            "session_id": "test:berserk:feedback",
            "dry_run": False,
            "verbose": False,
            "skip_verification": False,
            "analyses": [],
            "errors": [],
            "iteration": 1,
            "max_iterations": 3,
        }
        graph = runtime.compile_graph()
        config = runtime.thread_config
        final_state: dict = dict(initial_state)
        visited_nodes: list[str] = []

        for event in graph.stream(initial_state, config=config):  # type: ignore[arg-type]
            for node_name, output in event.items():
                if node_name != "__end__":
                    visited_nodes.append(node_name)
                    final_state.update(output)

        assert "synthesizer" in visited_nodes, "synthesizer must be visited"
        assert final_state.get("synthesis") is not None


# ===========================================================================
# §6  SubAgent Delegation — Live E2E
# ===========================================================================


class TestSubAgentLive:
    """Live E2E for SubAgent delegation (G1-G6 fixes)."""

    def test_6_1_delegate_single_dry_run(self) -> None:
        """E1: delegate_task single — Berserk dry-run."""
        loop, *_ = _make_loop(force_dry_run=True)
        result = loop.run("Berserk를 서브에이전트로 분석해줘")

        tool_names = [tc["tool"] for tc in result.tool_calls]
        assert "delegate_task" in tool_names, f"E1: delegate_task 미호출. 호출: {tool_names}"

        delegate_result = next(
            tc["result"] for tc in result.tool_calls if tc["tool"] == "delegate_task"
        )
        assert "error" not in delegate_result or delegate_result.get("error") is None, (
            f"E1: delegate 에러: {delegate_result.get('error')}"
        )

        assert result.error is None, f"E1: AgenticLoop 에러: {result.error}"

    def test_6_2_delegate_batch_dry_run(self) -> None:
        """E2: delegate_task batch — 2 IP parallel."""
        loop, *_ = _make_loop(force_dry_run=True)
        result = loop.run("Berserk이랑 Cowboy Bebop 동시에 분석해줘. 서브에이전트 병렬로 돌려.")

        tool_names = [tc["tool"] for tc in result.tool_calls]
        has_delegate = "delegate_task" in tool_names
        has_multi_analyze = tool_names.count("analyze_ip") >= 2

        assert has_delegate or has_multi_analyze, f"E2: 배치 위임 미발생. 호출: {tool_names}"

        if has_delegate:
            delegate_result = next(
                tc["result"] for tc in result.tool_calls if tc["tool"] == "delegate_task"
            )
            assert "error" not in delegate_result or delegate_result.get("error") is None, (
                f"E2: delegate 에러: {delegate_result.get('error')}"
            )

        assert result.error is None

    def test_6_3_sub_agent_manager_wired(self) -> None:
        """E3: ToolExecutor has SubAgentManager."""
        _, _, executor, sub_mgr = _make_loop(force_dry_run=True)
        assert sub_mgr is not None
        assert executor._sub_agent_manager is not None
        assert executor._sub_agent_manager is sub_mgr

    def test_6_4_subagent_hook_events(self) -> None:
        """E4: SUBAGENT_STARTED/COMPLETED hooks fire."""
        from core.cli.sub_agent import SubAgentManager, SubTask
        from core.orchestration.hooks import HookEvent, HookSystem
        from core.orchestration.isolated_execution import (
            IsolatedRunner,
        )

        hooks = HookSystem()
        events: list[tuple[str, str]] = []

        def on_event(event: HookEvent, data: dict) -> None:
            events.append((event.value, data.get("task_id", "")))

        hooks.register(
            HookEvent.SUBAGENT_STARTED,
            on_event,
            name="e4_start",
        )
        hooks.register(
            HookEvent.SUBAGENT_COMPLETED,
            on_event,
            name="e4_complete",
        )

        def handler(task_type: str, args: dict) -> dict:
            return {"ok": True, "ip": args.get("ip_name", "")}

        runner = IsolatedRunner()
        mgr = SubAgentManager(runner, handler, timeout_s=30, hooks=hooks)
        results = mgr.delegate(
            [
                SubTask(
                    "e4_t1",
                    "Test",
                    "analyze",
                    {"ip_name": "Berserk"},
                ),
            ]
        )

        assert len(results) == 1
        assert results[0].success is True

        started = [tid for ev, tid in events if ev == "subagent_started"]
        completed = [tid for ev, tid in events if ev == "subagent_completed"]
        assert "e4_t1" in started, f"E4: SUBAGENT_STARTED missing. events={events}"
        assert "e4_t1" in completed, f"E4: SUBAGENT_COMPLETED missing. events={events}"

    def test_6_5_agent_registry_resolve(self) -> None:
        """E5: AgentRegistry + _resolve_agent integration."""
        from core.cli.sub_agent import SubAgentManager, SubTask
        from core.extensibility.agents import AgentRegistry
        from core.orchestration.isolated_execution import (
            IsolatedRunner,
        )

        registry = AgentRegistry()
        registry.load_defaults()

        received_ctx: list[dict | None] = []

        def handler(
            task_type: str,
            args: dict,
            *,
            agent_context: dict | None = None,
        ) -> dict:
            received_ctx.append(agent_context)
            return {"ok": True}

        runner = IsolatedRunner()
        mgr = SubAgentManager(
            runner,
            handler,
            timeout_s=30,
            agent_registry=registry,
        )
        results = mgr.delegate(
            [
                SubTask(
                    "e5_t1",
                    "Analyze",
                    "analyze",
                    {"ip_name": "Berserk"},
                ),
            ]
        )

        assert len(results) == 1
        assert results[0].success is True
        assert len(received_ctx) == 1
        ctx = received_ctx[0]
        assert ctx is not None, "E5: agent_context=None (registry not wired)"
        assert ctx["agent_name"] == "game_analyst"
        assert "system_prompt" in ctx
        assert len(ctx["tools"]) > 0

    def test_6_6_existing_analysis_no_regression(self) -> None:
        """E6: analyze_ip still works (non-regression)."""
        loop, *_ = _make_loop(force_dry_run=True)
        result = loop.run("Berserk 분석해줘")

        tool_names = [tc["tool"] for tc in result.tool_calls]
        assert "analyze_ip" in tool_names, f"E6: analyze_ip 미호출. 호출: {tool_names}"

        analyze_result = next(
            tc["result"] for tc in result.tool_calls if tc["tool"] == "analyze_ip"
        )
        assert analyze_result.get("tier") in (
            "S",
            "A",
            "B",
            "C",
            "N/A",
        ), f"E6: invalid tier: {analyze_result}"
        assert result.error is None

    def test_6_7_delegate_execute_returns_result(self) -> None:
        """E7: ToolExecutor._execute_delegate returns result."""
        _, _, executor, _ = _make_loop(force_dry_run=True)

        result = executor.execute(
            "delegate_task",
            {
                "task_description": "Analyze Berserk",
                "task_type": "analyze",
                "args": {"ip_name": "Berserk"},
            },
        )

        assert "error" not in result or result.get("error") is None, f"E7: delegate error: {result}"
        assert "result" in result or "results" in result, f"E7: no result: {result}"
        if "result" in result:
            assert result["result"].get("tier") in (
                "S",
                "A",
                "B",
                "C",
                "N/A",
            ), f"E7: invalid tier: {result}"


# ===========================================================================
# §C5  Key Registration Gate
# ===========================================================================


class TestKeyRegistrationGateLive:
    """C5 — key_registration_gate replaces offline mode."""

    def test_key_gate_quit(self) -> None:
        """Key gate returns None on /quit."""
        from unittest.mock import patch

        from core.cli.startup import key_registration_gate

        with patch("core.cli.startup.console") as mock_console:
            mock_console.input.return_value = "/quit"
            assert key_registration_gate() is None
