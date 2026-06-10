"""Tests for hierarchical Session Key builder."""

from __future__ import annotations

import pytest
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
    build_thread_config,
    parse_session_key,
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


class TestParseSessionKey:
    def test_basic_parse(self):
        result = parse_session_key("subject:demo:router")
        assert result["prefix"] == "subject"
        assert result["subject_id"] == "demo"
        assert result["phase"] == "router"
        assert result["sub_context"] is None

    def test_parse_with_sub_context(self):
        result = parse_session_key("subject:demo:evaluation:quality_judge")
        assert result["subject_id"] == "demo"
        assert result["phase"] == "evaluation"
        assert result["sub_context"] == "quality_judge"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid session key"):
            parse_session_key("bad_key")

    def test_wrong_prefix_raises(self):
        with pytest.raises(ValueError, match="Invalid session key"):
            parse_session_key("user:demo:router")

    def test_roundtrip(self):
        original = build_session_key("Demo Subject", VERIFICATION, "guardrails")
        parsed = parse_session_key(original)
        rebuilt = build_session_key(parsed["subject_id"], parsed["phase"], parsed["sub_context"])
        assert rebuilt == original


class TestBuildThreadConfig:
    def test_basic_config(self):
        config = build_thread_config("demo", ANALYSIS)
        assert config["configurable"] == {"thread_id": "subject:demo:analysis"}
        assert config["run_name"] == "geode:demo:analysis"
        assert "subject:demo" in config["tags"]
        assert config["metadata"]["subject_id"] == "demo"

    def test_config_with_sub_context(self):
        config = build_thread_config("demo", EVALUATION, "hidden_value")
        assert config["configurable"]["thread_id"] == "subject:demo:evaluation:hidden_value"


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
