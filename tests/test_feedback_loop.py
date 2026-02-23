"""Tests for L3 Feedback Loop (VERIFY→GATHER loopback) and Confidence Threshold."""

from geode.graph import (
    CONFIDENCE_THRESHOLD,
    DEFAULT_MAX_ITERATIONS,
    _gather_node,
    _should_continue,
    build_graph,
    compile_graph,
)


class TestConfidenceThreshold:
    def test_threshold_value(self):
        """Confidence threshold is 0.7 per spec."""
        assert CONFIDENCE_THRESHOLD == 0.7

    def test_max_iterations_default(self):
        assert DEFAULT_MAX_ITERATIONS == 3


class TestShouldContinue:
    def test_high_confidence_goes_to_synthesizer(self):
        """confidence >= 0.7 → synthesizer."""
        state = {"analyst_confidence": 85.0, "iteration": 1, "max_iterations": 3}
        assert _should_continue(state) == "synthesizer"

    def test_exactly_threshold_goes_to_synthesizer(self):
        """confidence == 70.0 (0.7 normalized) → synthesizer."""
        state = {"analyst_confidence": 70.0, "iteration": 1, "max_iterations": 3}
        assert _should_continue(state) == "synthesizer"

    def test_low_confidence_loops_back(self):
        """confidence < 0.7 AND iteration < max → gather (loopback)."""
        state = {"analyst_confidence": 50.0, "iteration": 1, "max_iterations": 3}
        assert _should_continue(state) == "gather"

    def test_low_confidence_max_iterations_force_proceeds(self):
        """confidence < 0.7 BUT iteration >= max → synthesizer (force)."""
        state = {"analyst_confidence": 50.0, "iteration": 3, "max_iterations": 3}
        assert _should_continue(state) == "synthesizer"

    def test_default_confidence_proceeds(self):
        """No analyst_confidence defaults to 100.0 → synthesizer."""
        state = {"iteration": 1, "max_iterations": 3}
        assert _should_continue(state) == "synthesizer"

    def test_zero_confidence_loops(self):
        state = {"analyst_confidence": 0.0, "iteration": 1, "max_iterations": 3}
        assert _should_continue(state) == "gather"

    def test_normalized_confidence_input(self):
        """If confidence is already 0-1 range, still works."""
        state = {"analyst_confidence": 0.8, "iteration": 1, "max_iterations": 3}
        assert _should_continue(state) == "synthesizer"

    def test_low_normalized_confidence_loops(self):
        """confidence=0.5 (already normalized) → gather."""
        state = {"analyst_confidence": 0.5, "iteration": 1, "max_iterations": 3}
        assert _should_continue(state) == "gather"


class TestGatherNode:
    def test_increments_iteration(self):
        state = {"iteration": 1}
        result = _gather_node(state)
        assert result["iteration"] == 2

    def test_increments_from_default(self):
        state = {}
        result = _gather_node(state)
        assert result["iteration"] == 2

    def test_increments_multiple(self):
        state = {"iteration": 2}
        result = _gather_node(state)
        assert result["iteration"] == 3


class TestGraphWithFeedbackLoop:
    def test_build_graph_has_gather_node(self):
        graph = build_graph()
        assert graph is not None

    def test_compile_succeeds(self):
        compiled = compile_graph()
        assert compiled is not None

    def test_dry_run_still_works_cowboy_bebop(self):
        """Existing dry-run still passes with feedback loop in place."""
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
                "iteration": 1,
                "max_iterations": 3,
            }
        )
        assert result["tier"] == "A"
        assert result["synthesis"].undervaluation_cause == "undermarketed"

    def test_dry_run_berserk_with_feedback_fields(self):
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
                "iteration": 1,
                "max_iterations": 3,
            }
        )
        assert result["tier"] == "S"
        assert result["synthesis"].undervaluation_cause == "conversion_failure"
