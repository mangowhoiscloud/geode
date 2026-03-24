"""Tests for synthesizer node (dry-run mode)."""

from __future__ import annotations

from core.domains.game_ip.nodes.synthesizer import (
    ACTION_DESCRIPTIONS,
    CAUSE_DESCRIPTIONS,
    CAUSE_TO_ACTION,
    _build_dry_run_synthesis,
    _detect_timing_issue,
    _extract_def_scores,
)
from core.state import EvaluatorResult


class TestExtractDefScores:
    def test_normal_extraction(self):
        evaluations = {
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 4.2, "e_score": 3.7, "f_score": 4.8},
                composite_score=50.0,
                rationale="test",
            ),
        }
        d, e, f = _extract_def_scores(evaluations)
        assert d == 4  # round(4.2)
        assert e == 4  # round(3.7)
        assert f == 5  # round(4.8)

    def test_missing_hidden_value(self):
        d, e, f = _extract_def_scores({})
        assert d == 3
        assert e == 3
        assert f == 3


class TestDetectTimingIssue:
    def test_timing_issue_detected(self):
        monolake = {
            "last_game_year": 2010,
            "active_game_count": 0,
            "metacritic_score": 75,
        }
        assert _detect_timing_issue(monolake) is True

    def test_no_timing_low_metacritic(self):
        monolake = {
            "last_game_year": 2010,
            "active_game_count": 0,
            "metacritic_score": 50,
        }
        assert _detect_timing_issue(monolake) is False

    def test_no_timing_active_game(self):
        monolake = {
            "last_game_year": 2020,
            "active_game_count": 1,
            "metacritic_score": 80,
        }
        assert _detect_timing_issue(monolake) is False

    def test_no_game_ever(self):
        assert _detect_timing_issue({}) is False


class TestCauseDescriptions:
    def test_all_causes_have_descriptions(self):
        for cause in CAUSE_TO_ACTION:
            assert cause in CAUSE_DESCRIPTIONS

    def test_all_actions_have_descriptions(self):
        for action in CAUSE_TO_ACTION.values():
            assert action in ACTION_DESCRIPTIONS


class TestBuildDryRunSynthesis:
    def test_includes_signal_data(self):
        state = {
            "ip_name": "Cowboy Bebop",
            "signals": {
                "youtube_views": 12000000,
                "reddit_subscribers": 180000,
                "fan_art_yoy_pct": 42.0,
            },
            "analyses": [],
            "ip_info": {"genre": ["action"]},
        }
        result = _build_dry_run_synthesis(
            state,
            "undermarketed",
            "marketing_boost",
            "IP 파워 대비 마케팅/노출 절대 부족 — 마케팅 예산 증액",
        )
        assert "12M" in result.value_narrative
        assert "180K" in result.value_narrative
        assert result.undervaluation_cause == "undermarketed"

    def test_genre_aware_segment(self):
        state = {
            "ip_name": "Test",
            "signals": {},
            "analyses": [],
            "ip_info": {"genre": ["dark fantasy"]},
        }
        result = _build_dry_run_synthesis(
            state,
            "niche_gem",
            "platform_expansion",
            "품질 좋으나 확장 미진출 상태 — 플랫폼 확장",
        )
        assert "Dark Fantasy" in result.target_segment
