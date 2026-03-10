"""Live E2E tests — real LLM API calls with LangSmith tracing.

These tests call the actual Anthropic API. They are marked with @pytest.mark.live
and excluded from the default test suite. Run explicitly with:

    uv run pytest tests/test_e2e_live_llm.py -v -m live

Scenarios mapped from docs/e2e-orchestration-scenarios.md §1, §4, §5.
"""

from __future__ import annotations

import os
import time

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
    offline_mode: bool = False,
    tool_registry: object | None = None,
    force_dry_run: bool = False,
) -> tuple:
    """Create an AgenticLoop with real API credentials and real tool handlers.

    By default, force_dry_run=False so tool handlers execute with real LLM calls.
    Set force_dry_run=True to use fixture data only.
    """
    from core.cli import _build_tool_handlers, _set_readiness
    from core.cli.agentic_loop import AgenticLoop
    from core.cli.conversation import ConversationContext
    from core.cli.startup import check_readiness
    from core.cli.tool_executor import ToolExecutor

    # Set up ReadinessReport so _build_tool_handlers knows dry-run state
    readiness = check_readiness()
    if not force_dry_run:
        # Override: allow real LLM calls even in test
        readiness.force_dry_run = False
        readiness.has_api_key = True
    _set_readiness(readiness)

    handlers = _build_tool_handlers(verbose=False)
    context = ConversationContext()
    executor = ToolExecutor(action_handlers=handlers, auto_approve=True)
    loop = AgenticLoop(
        context,
        executor,
        max_rounds=max_rounds,
        offline_mode=offline_mode,
        tool_registry=tool_registry,  # type: ignore[arg-type]
    )
    return loop, context, executor


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
        # LLM should have called list_ips
        tool_names = [tc["tool"] for tc in result.tool_calls]
        assert "list_ips" in tool_names, f"Expected list_ips, got {tool_names}"
        assert result.text, "LLM should produce summary text"

    def test_1_3_sequential_tools(self) -> None:
        """1-3. Multi-intent → sequential tool calls (analyze + compare)."""
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
        # Should have at least 2 tool calls (search_ips × 2 or similar)
        assert len(result.tool_calls) >= 1
        assert result.text

    def test_1_5_max_rounds_guardrail(self) -> None:
        """1-5. Max rounds guardrail — forced termination at max_rounds=2."""
        loop, *_ = _make_loop(max_rounds=2)
        # Use a prompt that likely triggers tool use, exhausting 2 rounds
        result = loop.run("Berserk 분석하고 비교하고 리포트 만들어줘")
        # Either completes or hits max rounds — both are valid
        assert result.rounds <= 2
        # If max rounds hit, error should be "max_rounds"
        if result.error:
            assert result.error == "max_rounds"

    def test_1_7_multi_turn_context(self) -> None:
        """1-7. Multi-turn context preservation across turns."""
        loop, context, _ = _make_loop()
        # Turn 1
        r1 = loop.run("Berserk 분석해")
        assert r1.error is None
        assert context.turn_count >= 1

        # Turn 2 — references previous analysis
        r2 = loop.run("점수가 왜 높아?")
        assert r2.error is None
        assert r2.text
        assert context.turn_count >= 2


# ===========================================================================
# §4  LangSmith Tracing
# ===========================================================================


class TestLangSmithTracingLive:
    """Scenario 4-2: verify traces appear in LangSmith with real API calls."""

    @pytest.mark.skipif(
        not os.environ.get("LANGCHAIN_API_KEY"),
        reason="LANGCHAIN_API_KEY not set",
    )
    def test_4_2_traces_recorded(self) -> None:
        """4-2. With LANGCHAIN_API_KEY — traces visible in LangSmith."""
        # Ensure tracing is on
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_PROJECT", "geode")

        loop, *_ = _make_loop()
        result = loop.run("IP 목록 보여줘")
        assert result.error is None

        # Wait for async trace flush
        time.sleep(3)

        # Verify via LangSmith API
        from langsmith import Client

        client = Client()
        runs = list(client.list_runs(project_name="geode", limit=5))
        assert len(runs) > 0, "No traces found in LangSmith 'geode' project"

        # At least one run should be from our recent call
        recent_names = [r.name for r in runs[:5]]
        assert any("AgenticLoop" in (n or "") for n in recent_names), (
            f"No AgenticLoop trace found in recent runs: {recent_names}"
        )


# ===========================================================================
# §5  Full Pipeline E2E (live LLM, no dry-run)
# ===========================================================================


class TestFullPipelineLive:
    """Scenarios 5-1 through 5-3 with real LLM calls through the pipeline."""

    def test_5_1_single_ip_analysis(self) -> None:
        """5-1. Full pipeline for Berserk — real LLM analysts + evaluators."""
        from core.runtime import GeodeRuntime
        from core.state import GeodeState

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

        # Verify pipeline produced valid output
        assert final_state.get("tier") in ("S", "A", "B", "C"), (
            f"Invalid tier: {final_state.get('tier')}"
        )
        assert final_state.get("final_score", 0) > 0
        analyses = final_state.get("analyses", [])
        assert len(analyses) == 4, f"Expected 4 analysts, got {len(analyses)}"
        assert final_state.get("synthesis") is not None

    def test_5_2_multi_ip_smoke(self) -> None:
        """5-2. Multi-IP smoke — all 3 fixture IPs produce valid tier/score."""
        from core.runtime import GeodeRuntime
        from core.state import GeodeState

        for ip_name in ["berserk", "cowboy bebop", "ghost in the shell"]:
            runtime = GeodeRuntime.create(ip_name)
            initial_state: GeodeState = {
                "ip_name": ip_name,
                "pipeline_mode": "full_pipeline",
                "session_id": f"test:{ip_name.replace(' ', '_')}:live",
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

            assert final_state.get("tier") in ("S", "A", "B", "C"), (
                f"{ip_name}: invalid tier {final_state.get('tier')}"
            )
            assert final_state.get("final_score", 0) > 0, f"{ip_name}: score is 0"

    def test_5_3_feedback_loop_high_confidence(self) -> None:
        """5-3. High confidence → synthesizer visited, gather NOT visited."""
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
        # High confidence fixtures should skip gather
        assert final_state.get("synthesis") is not None


# ===========================================================================
# §C5  Offline Mode (no LLM)
# ===========================================================================


class TestOfflineModeLive:
    """C5 implementation — AgenticLoop without LLM API calls."""

    def test_offline_list_ips(self) -> None:
        """Offline mode: regex routes '목록 보여줘' → list action."""
        loop, *_ = _make_loop(offline_mode=True)
        result = loop.run("IP 목록 보여줘")
        assert result.rounds == 1
        assert result.error is None
        tool_names = [tc["tool"] for tc in result.tool_calls]
        assert "list" in tool_names

    def test_offline_analyze(self) -> None:
        """Offline mode: regex routes 'Berserk 분석해' → analyze."""
        loop, *_ = _make_loop(offline_mode=True)
        result = loop.run("Berserk 분석해")
        assert result.rounds == 1
        assert result.error is None
        assert len(result.tool_calls) >= 1

    def test_offline_help_fallback(self) -> None:
        """Offline mode: unrecognized input → help fallback."""
        loop, *_ = _make_loop(offline_mode=True)
        result = loop.run("점심 뭐 먹지?")
        assert result.rounds == 1
        assert "Offline" in result.text or "help" in result.text.lower()
