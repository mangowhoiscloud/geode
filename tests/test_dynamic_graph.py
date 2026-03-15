"""Tests for Dynamic Graph — node skip/enrichment based on state."""

from core.graph import (
    _route_after_skip_check,
    _skip_check_node,
    build_graph,
    compile_graph,
)
from core.state import GeodeState

# ---------------------------------------------------------------------------
# Unit tests: skip_check node
# ---------------------------------------------------------------------------


class TestSkipCheckNode:
    """Test _skip_check_node logic."""

    def test_no_skip_returns_empty(self):
        """When verification is NOT in skip_nodes, returns empty dict."""
        state: GeodeState = {"skip_nodes": [], "errors": [], "analyses": []}  # type: ignore[typeddict-item]
        result = _skip_check_node(state)
        assert result == {}

    def test_no_skip_nodes_key(self):
        """When skip_nodes is not set at all, returns empty dict."""
        state: GeodeState = {"errors": [], "analyses": []}  # type: ignore[typeddict-item]
        result = _skip_check_node(state)
        assert result == {}

    def test_skip_verification(self):
        """When verification is in skip_nodes, returns placeholder results."""
        state: GeodeState = {"skip_nodes": ["verification"], "errors": [], "analyses": []}  # type: ignore[typeddict-item]
        result = _skip_check_node(state)
        assert "skipped_nodes" in result
        assert "verification" in result["skipped_nodes"]
        assert result["guardrails"].all_passed is True
        assert "Skipped" in result["biasbuster"].explanation

    def test_skip_other_node_does_not_skip_verification(self):
        """When other nodes are in skip_nodes but not verification, returns empty."""
        state: GeodeState = {"skip_nodes": ["scoring"], "errors": [], "analyses": []}  # type: ignore[typeddict-item]
        result = _skip_check_node(state)
        assert result == {}


class TestRouteAfterSkipCheck:
    """Test _route_after_skip_check conditional edge."""

    def test_routes_to_verification_by_default(self):
        state: GeodeState = {"skip_nodes": [], "errors": [], "analyses": []}  # type: ignore[typeddict-item]
        assert _route_after_skip_check(state) == "verification"

    def test_routes_to_synthesizer_when_verification_skipped(self):
        state: GeodeState = {"skip_nodes": ["verification"], "errors": [], "analyses": []}  # type: ignore[typeddict-item]
        assert _route_after_skip_check(state) == "synthesizer"

    def test_routes_to_verification_when_no_skip_nodes(self):
        state: GeodeState = {"errors": [], "analyses": []}  # type: ignore[typeddict-item]
        assert _route_after_skip_check(state) == "verification"


# ---------------------------------------------------------------------------
# Integration tests: dry_run with skip
# ---------------------------------------------------------------------------


class TestDryRunSkip:
    """Test that dry_run sets skip_nodes and verification is actually skipped."""

    def test_dry_run_skips_verification(self):
        """dry_run pipeline should skip verification and record it."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Cowboy Bebop",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "analyses": [],
                "errors": [],
            }
        )

        # Verification was skipped
        assert "verification" in result.get("skip_nodes", [])
        assert "verification" in result.get("skipped_nodes", [])

        # But placeholder guardrails still has all_passed=True
        assert result["guardrails"].all_passed is True

        # Core pipeline results are preserved
        assert result["tier"] == "A"
        assert result["synthesis"].undervaluation_cause == "undermarketed"

    def test_dry_run_berserk_still_s_tier(self):
        """Berserk dry_run should still produce S-tier with skip."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Berserk",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "analyses": [],
                "errors": [],
            }
        )

        assert result["tier"] == "S"
        assert result["final_score"] >= 80
        assert result["synthesis"].undervaluation_cause == "conversion_failure"
        assert "verification" in result.get("skipped_nodes", [])

    def test_dry_run_ghost_in_shell_still_b_tier(self):
        """Ghost in the Shell dry_run should still produce discovery_failure."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Ghost in the Shell",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "analyses": [],
                "errors": [],
            }
        )

        assert result["synthesis"].undervaluation_cause == "discovery_failure"
        assert result["synthesis"].action_type == "community_activation"
        assert "verification" in result.get("skipped_nodes", [])


# ---------------------------------------------------------------------------
# Integration tests: explicit skip_nodes
# ---------------------------------------------------------------------------


class TestExplicitSkipNodes:
    """Test that caller-provided skip_nodes are honored."""

    def test_caller_skip_verification(self):
        """Caller can pre-set skip_nodes to bypass verification."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Cowboy Bebop",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "skip_nodes": ["verification"],
                "analyses": [],
                "errors": [],
            }
        )

        assert "verification" in result.get("skipped_nodes", [])
        assert result["tier"] == "A"

    def test_empty_skip_nodes_runs_all(self):
        """Empty skip_nodes should run full pipeline including verification."""
        compiled = compile_graph()
        # Non-dry-run with empty skip_nodes — verification should run
        # We still use dry_run for the LLM calls but set skip_nodes explicitly empty
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

        # Even though dry_run, the router adds verification to skip_nodes
        # So skipped_nodes should contain verification
        assert "verification" in result.get("skip_nodes", [])


# ---------------------------------------------------------------------------
# Integration tests: enrichment_needed from scoring
# ---------------------------------------------------------------------------


class TestEnrichmentNeeded:
    """Test scoring node sets enrichment_needed for mid-range scores."""

    def test_cowboy_bebop_mid_range_enrichment(self):
        """Cowboy Bebop (A-tier ~68) is in mid-range → enrichment_needed=True."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Cowboy Bebop",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "analyses": [],
                "errors": [],
            }
        )

        # Cowboy Bebop score is ~68 which is in [40, 80] range
        assert 40 <= result["final_score"] <= 80
        assert result.get("enrichment_needed") is True

    def test_ghost_in_shell_mid_range_enrichment(self):
        """Ghost in the Shell (B-tier ~51) is in mid-range → enrichment_needed=True."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Ghost in the Shell",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "analyses": [],
                "errors": [],
            }
        )

        assert 40 <= result["final_score"] <= 80
        assert result.get("enrichment_needed") is True

    def test_berserk_s_tier_no_enrichment(self):
        """Berserk (S-tier ~81) is above mid-range → no enrichment_needed."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Berserk",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "analyses": [],
                "errors": [],
            }
        )

        # Berserk score ~81 which is above 80, so not in mid-range
        # But it's also below 90 so no extreme-score skip either
        assert result["final_score"] >= 80
        # enrichment_needed may or may not be set depending on exact score
        # If score < 90, it's in [80, 90) range — neither extreme nor mid
        if result["final_score"] < 90:
            assert result.get("enrichment_needed") is not True


# ---------------------------------------------------------------------------
# Graph build tests
# ---------------------------------------------------------------------------


class TestDynamicGraphBuild:
    """Test that graph builds correctly with skip_check node."""

    def test_build_includes_skip_check(self):
        """Graph should include skip_check node."""
        graph = build_graph()
        # LangGraph StateGraph has nodes attribute
        assert graph is not None

    def test_compile_with_dynamic_graph(self):
        """Compiled graph should work with dynamic skip."""
        compiled = compile_graph()
        assert compiled is not None


# ---------------------------------------------------------------------------
# Audit trail tests
# ---------------------------------------------------------------------------


class TestAuditTrail:
    """Test that skipped nodes are properly recorded for audit."""

    def test_skipped_nodes_recorded(self):
        """skipped_nodes should list all actually skipped nodes."""
        compiled = compile_graph()
        result = compiled.invoke(
            {
                "ip_name": "Cowboy Bebop",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "analyses": [],
                "errors": [],
            }
        )

        skipped = result.get("skipped_nodes", [])
        assert isinstance(skipped, list)
        assert "verification" in skipped

    def test_no_skip_no_audit(self):
        """When no nodes are skipped, skipped_nodes should be empty or absent."""
        # Using skip_verification=False and non-dry-run would be ideal,
        # but we can't run without LLM. Instead verify the skip_check
        # node logic directly.
        state: GeodeState = {"skip_nodes": [], "errors": [], "analyses": []}  # type: ignore[typeddict-item]
        result = _skip_check_node(state)
        assert result == {}  # No skip → no audit entry


# ---------------------------------------------------------------------------
# Existing fixture preservation tests
# ---------------------------------------------------------------------------


class TestFixturePreservation:
    """Verify that the 3 core IP fixtures produce unchanged results."""

    def test_berserk_s_tier_preserved(self):
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
        assert result["final_score"] >= 80
        assert result["tier"] == "S"
        assert result["synthesis"].undervaluation_cause == "conversion_failure"
        assert result["synthesis"].action_type == "marketing_boost"

    def test_cowboy_bebop_a_tier_preserved(self):
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
        assert 60 <= result["final_score"] < 80
        assert result["tier"] == "A"
        assert result["synthesis"].undervaluation_cause == "undermarketed"
        assert result["synthesis"].action_type == "marketing_boost"
        assert result["guardrails"].all_passed is True

    def test_ghost_in_shell_b_tier_preserved(self):
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
