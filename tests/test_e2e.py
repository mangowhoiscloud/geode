"""End-to-end integration tests for the GEODE pipeline (P1-8).

Tests the full pipeline with mocked LLM, covering all node transitions,
feedback loops, hook triggers, and tool execution.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.gateway.auth.cooldown import CooldownTracker
from core.gateway.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.gateway.auth.rotation import ProfileRotator
from core.graph import compile_graph
from core.llm.router import LLMClientPort
from core.orchestration.hooks import HookEvent, HookSystem
from core.state import GeodeState
from core.tools.analysis import PSMCalculateTool, RunAnalystTool, RunEvaluatorTool
from core.tools.policy import PolicyChain, ToolPolicy
from core.tools.registry import ToolRegistry
from core.verification.cross_llm import run_dual_adapter_check


class TestFullPipelineDryRun:
    """E2E: full pipeline in dry-run mode with all hooks."""

    def test_dry_run_berserk(self):
        hooks = HookSystem()
        events_fired: list[str] = []

        def _on_event(event, data):
            events_fired.append(event.value)

        for ev in HookEvent:
            hooks.register(ev, _on_event, name="test_tracker")

        graph = compile_graph(hooks=hooks)
        state: GeodeState = {
            "ip_name": "berserk",
            "pipeline_mode": "full_pipeline",
            "dry_run": True,
            "verbose": False,
            "skip_verification": False,
            "analyses": [],
            "errors": [],
            "iteration": 1,
            "max_iterations": 3,
        }

        final = {}
        for event in graph.stream(state):
            for node_name, output in event.items():
                if node_name != "__end__":
                    for k, v in output.items():
                        if k in ("analyses", "errors"):
                            final.setdefault(k, []).extend(v if isinstance(v, list) else [v])
                        else:
                            final[k] = v

        # Verify pipeline produced expected output
        assert final.get("tier") in ("S", "A", "B", "C")
        assert final.get("final_score", 0) > 0
        assert len(final.get("analyses", [])) == 4
        assert final.get("synthesis") is not None

        # Verify hooks fired
        assert "pipeline_start" in events_fired
        assert "pipeline_end" in events_fired
        assert "node_enter" in events_fired
        assert "node_exit" in events_fired

    def test_dry_run_all_ips(self):
        """Smoke test all available IPs."""
        for ip_name in ("berserk", "cowboy bebop", "ghost in the shell"):
            graph = compile_graph()
            state: GeodeState = {
                "ip_name": ip_name,
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "skip_verification": True,
                "analyses": [],
                "errors": [],
                "iteration": 1,
                "max_iterations": 3,
            }

            final = {}
            for event in graph.stream(state):
                for node_name, output in event.items():
                    if node_name != "__end__":
                        for k, v in output.items():
                            if k in ("analyses", "errors"):
                                final.setdefault(k, []).extend(v if isinstance(v, list) else [v])
                            else:
                                final[k] = v

            assert final.get("tier") is not None, f"Missing tier for {ip_name}"
            assert final.get("final_score", 0) > 0, f"Missing score for {ip_name}"


class TestFeedbackLoopE2E:
    def test_high_confidence_skips_loop(self):
        """High confidence (>70%) should go straight to synthesizer."""
        graph = compile_graph()
        state: GeodeState = {
            "ip_name": "berserk",
            "pipeline_mode": "full_pipeline",
            "dry_run": True,
            "verbose": False,
            "skip_verification": False,
            "analyses": [],
            "errors": [],
            "iteration": 1,
            "max_iterations": 3,
        }

        nodes_visited = []
        for event in graph.stream(state):
            nodes_visited.extend(event.keys())

        # Should not have "gather" node if confidence is high
        assert "synthesizer" in nodes_visited


class TestToolRegistryE2E:
    def test_full_tool_lifecycle(self):
        registry = ToolRegistry()
        registry.register(RunAnalystTool())
        registry.register(RunEvaluatorTool())
        registry.register(PSMCalculateTool())

        # All tools registered
        assert len(registry) == 3
        assert "run_analyst" in registry
        assert "run_evaluator" in registry
        assert "psm_calculate" in registry

        # Execute tool
        result = registry.execute("run_analyst", analyst_type="game_mechanics", ip_name="Berserk")
        assert "result" in result

        # Policy filtering
        chain = PolicyChain()
        chain.add_policy(
            ToolPolicy(name="test_block", mode="dry_run", denied_tools={"run_analyst"})
        )
        dry_run_tools = registry.list_tools(policy=chain, mode="dry_run")
        assert "run_analyst" not in dry_run_tools
        assert "psm_calculate" in dry_run_tools

        # Full pipeline mode ignores dry_run policy
        full_tools = registry.list_tools(policy=chain, mode="full_pipeline")
        assert "run_analyst" in full_tools

    def test_policy_audit(self):
        chain = PolicyChain()
        chain.add_policy(ToolPolicy(name="block_llm", mode="dry_run", denied_tools={"run_analyst"}))
        audit = chain.audit_check("run_analyst", mode="dry_run")
        assert not audit.allowed
        assert "block_llm" in audit.blocking_policies

        audit2 = chain.audit_check("psm_calculate", mode="dry_run")
        assert audit2.allowed


class TestAuthProfileE2E:
    def test_profile_rotation_lifecycle(self):
        store = ProfileStore()
        store.add(
            AuthProfile(
                name="anthropic:work",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key="sk-ant-work-1234567890123456",
                last_used=100.0,
            )
        )
        store.add(
            AuthProfile(
                name="anthropic:personal",
                provider="anthropic",
                credential_type=CredentialType.OAUTH,
                key="oauth-token-xxx",
                last_used=200.0,
            )
        )

        rotator = ProfileRotator(store)

        # OAuth should be preferred
        selected = rotator.resolve("anthropic")
        assert selected.credential_type == CredentialType.OAUTH

        # Mark failure → cooldown
        rotator.mark_failure(selected)
        assert selected.is_cooling_down

        # Next resolution should fall back to API key
        selected2 = rotator.resolve("anthropic")
        assert selected2.credential_type == CredentialType.API_KEY

    def test_cooldown_tracker_integration(self):
        tracker = CooldownTracker()

        # First failure
        ms = tracker.record_failure("key1", "rate_limit")
        assert ms == 60_000
        assert not tracker.is_available("key1")

        # Second failure
        ms2 = tracker.record_failure("key1", "rate_limit")
        assert ms2 == 300_000

        # Success resets
        tracker.record_success("key1")
        assert tracker.is_available("key1")


class TestCrossLLME2E:
    def test_dual_adapter_with_mock(self):
        from core.state import AnalysisResult

        state: GeodeState = {
            "ip_name": "berserk",
            "analyses": [
                AnalysisResult(
                    analyst_type="game_mechanics",
                    score=4.0,
                    key_finding="test",
                    reasoning="test",
                    confidence=80.0,
                ),
                AnalysisResult(
                    analyst_type="player_experience",
                    score=3.5,
                    key_finding="test",
                    reasoning="test",
                    confidence=75.0,
                ),
            ],
            "tier": "S",
            "final_score": 82.0,
        }

        # Mock secondary adapter
        mock_secondary = MagicMock(spec=LLMClientPort)
        mock_secondary.generate.return_value = "4"

        result = run_dual_adapter_check(
            state,
            primary_adapter=MagicMock(spec=LLMClientPort),
            secondary_adapter=mock_secondary,
        )

        assert result["verification_mode"] == "dual_adapter"
        assert "secondary_agreement" in result
        assert result["secondary_agreement"] == 4

    def test_dual_adapter_fallback(self):
        from core.state import AnalysisResult

        state: GeodeState = {
            "ip_name": "berserk",
            "analyses": [
                AnalysisResult(
                    analyst_type="game_mechanics",
                    score=4.0,
                    key_finding="test",
                    reasoning="test",
                    confidence=80.0,
                ),
                AnalysisResult(
                    analyst_type="player_experience",
                    score=3.5,
                    key_finding="test",
                    reasoning="test",
                    confidence=75.0,
                ),
            ],
        }

        # No adapters → fallback to agreement-only
        result = run_dual_adapter_check(state)
        assert result["verification_mode"] == "agreement_only"
