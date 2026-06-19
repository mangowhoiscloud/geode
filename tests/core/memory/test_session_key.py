"""Tests for hierarchical Session Key builder."""

from __future__ import annotations

from core.memory.session_key import (
    ALL_PHASES,
    ANALYSIS,
    EVALUATION,
    ROUTER,
    SCORING,
    SIGNALS,
    SYNTHESIS,
    VERIFICATION,
    build_session_key,
)


class TestBuildSessionKey:
    def test_basic_key(self):
        key = build_session_key("demo", ROUTER)
        assert key == "subject:demo:router"

    def test_multi_word_name(self):
        key = build_session_key("Demo Subject", ANALYSIS)
        assert key == "subject:demo_subject:analysis"

    def test_with_sub_context(self):
        key = build_session_key("demo", EVALUATION, "quality_judge")
        assert key == "subject:demo:evaluation:quality_judge"

    def test_special_characters_normalized(self):
        key = build_session_key("Project Helix", SCORING)
        assert key == "subject:project_helix:scoring"

    def test_all_phases(self):
        for phase in ALL_PHASES:
            key = build_session_key("test", phase)
            assert key.startswith("subject:test:")
            assert phase in key

    def test_uppercase_normalized(self):
        key = build_session_key("DEMO", ROUTER)
        assert key == "subject:demo:router"


class TestPhaseConstants:
    def test_all_phases_has_7(self):
        assert len(ALL_PHASES) == 7

    def test_phase_values(self):
        assert ROUTER == "router"
        assert SIGNALS == "signals"
        assert ANALYSIS == "analysis"
        assert EVALUATION == "evaluation"
        assert SCORING == "scoring"
        assert VERIFICATION == "verification"
        assert SYNTHESIS == "synthesis"
