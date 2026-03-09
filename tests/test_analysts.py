"""Tests for analyst node (dry-run mode)."""

from __future__ import annotations

from geode.nodes.analysts import ANALYST_TYPES, _build_analyst_prompt, _run_analyst
from geode.nodes.analysts import get_dry_run_result as _dry_run_result


class TestAnalystTypes:
    def test_four_analysts(self):
        assert len(ANALYST_TYPES) == 4

    def test_expected_names(self):
        expected = {"game_mechanics", "player_experience", "growth_potential", "discovery"}
        assert set(ANALYST_TYPES) == expected


class TestDryRunResult:
    def test_cowboy_bebop_all_types(self):
        for atype in ANALYST_TYPES:
            result = _dry_run_result(atype, "Cowboy Bebop")
            assert result.analyst_type == atype
            assert 1.0 <= result.score <= 5.0
            assert result.key_finding
            assert result.evidence

    def test_berserk_all_types(self):
        for atype in ANALYST_TYPES:
            result = _dry_run_result(atype, "Berserk")
            assert result.analyst_type == atype
            assert 1.0 <= result.score <= 5.0

    def test_ghost_in_shell_all_types(self):
        for atype in ANALYST_TYPES:
            result = _dry_run_result(atype, "Ghost in the Shell")
            assert result.analyst_type == atype
            assert 1.0 <= result.score <= 5.0

    def test_unknown_ip_falls_back(self):
        """Unknown IP should fall back to cowboy_bebop data."""
        result = _dry_run_result("game_mechanics", "Unknown IP")
        assert result.analyst_type == "game_mechanics"

    def test_case_insensitive(self):
        r1 = _dry_run_result("game_mechanics", "cowboy bebop")
        r2 = _dry_run_result("game_mechanics", "COWBOY BEBOP")
        assert r1.score == r2.score


def _full_monolake() -> dict:
    return {
        "dau_current": 0,
        "revenue_ltm": 0,
        "active_game_count": 0,
        "last_game_year": 2005,
    }


def _full_signals() -> dict:
    return {
        "youtube_views": 1000000,
        "reddit_subscribers": 50000,
        "fan_art_yoy_pct": 20.0,
        "google_trends_index": 50,
        "twitter_mentions_monthly": 10000,
    }


class TestBuildPrompt:
    def test_prompt_has_ip_info(self):
        state = {
            "ip_name": "Test",
            "ip_info": {
                "ip_name": "Test",
                "media_type": "anime",
                "release_year": 2000,
                "studio": "Studio",
                "genre": ["action"],
                "synopsis": "A test IP.",
            },
            "monolake": _full_monolake(),
            "signals": _full_signals(),
        }
        system, user = _build_analyst_prompt("game_mechanics", state)
        assert "game_mechanics" in system
        assert "Test" in user


class TestRunAnalyst:
    def test_dry_run_returns_result(self):
        state = {
            "ip_name": "Cowboy Bebop",
            "ip_info": {
                "ip_name": "Cowboy Bebop",
                "media_type": "anime",
                "release_year": 1998,
                "studio": "Sunrise",
                "genre": ["action"],
                "synopsis": "Bounty hunters in space.",
            },
            "monolake": _full_monolake(),
            "signals": _full_signals(),
            "dry_run": True,
        }
        result = _run_analyst("game_mechanics", state)
        assert result.analyst_type == "game_mechanics"
        assert result.score == 4.2
