"""Tests for graph construction and dry-run execution."""

from core.domains.game_ip.nodes.synthesizer import CAUSE_TO_ACTION, _classify_cause
from core.graph import build_graph, compile_graph


class TestGraphBuild:
    def test_build_succeeds(self):
        graph = build_graph()
        assert graph is not None

    def test_compile_succeeds(self):
        compiled = compile_graph()
        assert compiled is not None

    def test_dry_run_cowboy_bebop(self):
        """Full pipeline dry-run: Cowboy Bebop → Tier A, undermarketed."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Cowboy Bebop",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "skip_verification": False,
                "analyses": [],
                "errors": [],
            }
        )

        assert result["ip_info"]["ip_name"] == "Cowboy Bebop"
        assert result["monolake"]["dau_current"] == 0
        assert len(result["analyses"]) == 4
        assert "quality_judge" in result["evaluations"]
        assert "hidden_value" in result["evaluations"]
        assert "community_momentum" in result["evaluations"]
        assert result["psm_result"].psm_valid is True
        assert 60 <= result["final_score"] < 80  # A-tier
        assert result["tier"] == "A"
        assert result["synthesis"].undervaluation_cause == "undermarketed"
        assert result["synthesis"].action_type == "marketing_boost"
        assert result["guardrails"].all_passed is True

    def test_dry_run_berserk(self):
        """Full pipeline dry-run: Berserk → S-tier, conversion_failure."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Berserk",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "skip_verification": False,
                "analyses": [],
                "errors": [],
            }
        )

        assert result["ip_info"]["ip_name"] == "Berserk"
        assert len(result["analyses"]) == 4
        assert result["final_score"] >= 80  # S-tier
        assert result["tier"] == "S"
        assert result["synthesis"].undervaluation_cause == "conversion_failure"
        assert result["synthesis"].action_type == "marketing_boost"

    def test_dry_run_ghost_in_shell(self):
        """Full pipeline dry-run: Ghost in the Shell → discovery_failure."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Ghost in the Shell",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "skip_verification": False,
                "analyses": [],
                "errors": [],
            }
        )

        assert result["ip_info"]["ip_name"] == "Ghost in the Shell"
        assert result["synthesis"].undervaluation_cause == "discovery_failure"
        assert result["synthesis"].action_type == "community_activation"


class TestDecisionTree:
    """Test _classify_cause matches architecture-v6 §13.9.2 exactly."""

    def test_timing_mismatch(self):
        cause, _ = _classify_cause(d_score=4, e_score=2, f_score=3, release_timing_issue=True)
        assert cause == "timing_mismatch"

    def test_timing_mismatch_requires_high_d(self):
        """timing_mismatch needs D>=3 + release_timing_issue."""
        cause, _ = _classify_cause(d_score=2, e_score=2, f_score=3, release_timing_issue=True)
        assert cause != "timing_mismatch"  # D<3, falls through

    def test_conversion_failure(self):
        """D>=3 AND E>=3 → conversion_failure."""
        cause, _ = _classify_cause(d_score=3, e_score=4, f_score=2)
        assert cause == "conversion_failure"

    def test_undermarketed(self):
        """D>=3 AND E<3 → undermarketed."""
        cause, _ = _classify_cause(d_score=5, e_score=2, f_score=4)
        assert cause == "undermarketed"

    def test_monetization_misfit(self):
        """D<=2 AND E>=3 → monetization_misfit."""
        cause, _ = _classify_cause(d_score=2, e_score=4, f_score=3)
        assert cause == "monetization_misfit"

    def test_niche_gem(self):
        """D<=2, E<=2, F>=3 → niche_gem."""
        cause, _ = _classify_cause(d_score=1, e_score=2, f_score=4)
        assert cause == "niche_gem"

    def test_discovery_failure(self):
        """D<=2, E<=2, F<=2 → discovery_failure."""
        cause, _ = _classify_cause(d_score=1, e_score=1, f_score=2)
        assert cause == "discovery_failure"

    def test_cause_to_action_mapping(self):
        """Verify CAUSE_TO_ACTION matches §13.9.3."""
        assert CAUSE_TO_ACTION["undermarketed"] == "marketing_boost"
        assert CAUSE_TO_ACTION["conversion_failure"] == "marketing_boost"
        assert CAUSE_TO_ACTION["monetization_misfit"] == "monetization_pivot"
        assert CAUSE_TO_ACTION["niche_gem"] == "platform_expansion"
        assert CAUSE_TO_ACTION["timing_mismatch"] == "timing_optimization"
        assert CAUSE_TO_ACTION["discovery_failure"] == "community_activation"
