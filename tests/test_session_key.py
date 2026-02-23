"""Tests for hierarchical Session Key builder."""

from __future__ import annotations

import pytest

from geode.memory.session_key import (
    ALL_PHASES,
    ANALYSIS,
    CORTEX,
    EVALUATION,
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
        key = build_session_key("Berserk", CORTEX)
        assert key == "ip:berserk:cortex"

    def test_multi_word_name(self):
        key = build_session_key("Cowboy Bebop", ANALYSIS)
        assert key == "ip:cowboy_bebop:analysis"

    def test_with_sub_context(self):
        key = build_session_key("Berserk", EVALUATION, "quality_judge")
        assert key == "ip:berserk:evaluation:quality_judge"

    def test_special_characters_normalized(self):
        key = build_session_key("Ghost in the Shell", SCORING)
        assert key == "ip:ghost_in_the_shell:scoring"

    def test_all_phases(self):
        for phase in ALL_PHASES:
            key = build_session_key("test", phase)
            assert key.startswith("ip:test:")
            assert phase in key

    def test_uppercase_normalized(self):
        key = build_session_key("BERSERK", CORTEX)
        assert key == "ip:berserk:cortex"


class TestParseSessionKey:
    def test_basic_parse(self):
        result = parse_session_key("ip:berserk:cortex")
        assert result["prefix"] == "ip"
        assert result["ip_name"] == "berserk"
        assert result["phase"] == "cortex"
        assert result["sub_context"] is None

    def test_parse_with_sub_context(self):
        result = parse_session_key("ip:berserk:evaluation:quality_judge")
        assert result["ip_name"] == "berserk"
        assert result["phase"] == "evaluation"
        assert result["sub_context"] == "quality_judge"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid session key"):
            parse_session_key("bad_key")

    def test_wrong_prefix_raises(self):
        with pytest.raises(ValueError, match="Invalid session key"):
            parse_session_key("user:berserk:cortex")

    def test_roundtrip(self):
        original = build_session_key("Cowboy Bebop", VERIFICATION, "guardrails")
        parsed = parse_session_key(original)
        rebuilt = build_session_key(parsed["ip_name"], parsed["phase"], parsed["sub_context"])
        assert rebuilt == original


class TestBuildThreadConfig:
    def test_basic_config(self):
        config = build_thread_config("Berserk", ANALYSIS)
        assert "configurable" in config
        assert config["configurable"]["thread_id"] == "ip:berserk:analysis"

    def test_config_with_sub_context(self):
        config = build_thread_config("Berserk", EVALUATION, "hidden_value")
        assert config["configurable"]["thread_id"] == "ip:berserk:evaluation:hidden_value"


class TestPhaseConstants:
    def test_all_phases_has_7(self):
        assert len(ALL_PHASES) == 7

    def test_phase_values(self):
        assert CORTEX == "cortex"
        assert SIGNALS == "signals"
        assert ANALYSIS == "analysis"
        assert EVALUATION == "evaluation"
        assert SCORING == "scoring"
        assert VERIFICATION == "verification"
        assert SYNTHESIS == "synthesis"
