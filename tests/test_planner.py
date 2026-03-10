"""Tests for Planner — rule-based request routing."""

from __future__ import annotations

from core.orchestration.planner import (
    ROUTE_PROFILES,
    Planner,
    Route,
    RouteProfile,
)


class TestPlanner:
    def test_command_routes_to_script(self):
        planner = Planner()
        decision = planner.classify("/status")
        assert decision.route == Route.SCRIPT_ROUTE
        assert decision.intent == "command_shortcut"
        assert decision.metadata["command"] == "/status"

    def test_slash_commands_various(self):
        planner = Planner()
        for cmd in ["/help", "/search berserk", "/config"]:
            decision = planner.classify(cmd)
            assert decision.route == Route.SCRIPT_ROUTE

    def test_cache_hit_routes_to_direct_answer(self):
        planner = Planner(memory_ttl_s=60.0)
        planner.cache_result("Berserk", {"score": 82.5})

        decision = planner.classify("Tell me about Berserk", ip_name="Berserk")
        assert decision.route == Route.DIRECT_ANSWER
        assert decision.intent == "cache_hit"
        assert planner.stats.cache_hits == 1

    def test_expired_cache_does_not_hit(self):
        planner = Planner(memory_ttl_s=0.0)  # Immediate expiry
        planner.cache_result("Berserk", {"score": 82.5})

        decision = planner.classify("Tell me about Berserk", ip_name="Berserk")
        assert decision.route != Route.DIRECT_ANSWER

    def test_refresh_keywords_route_to_data_refresh(self):
        planner = Planner()
        for text in ["refresh data for Berserk", "update the analysis", "re-fetch signals"]:
            decision = planner.classify(text)
            assert decision.route == Route.DATA_REFRESH, f"Failed for: {text}"

    def test_partial_rerun_patterns(self):
        planner = Planner()
        for text in [
            "re-analyze the scoring",
            "re-evaluate just the signals",
            "only the evaluation",
            "partial rerun of scoring",
        ]:
            decision = planner.classify(text)
            assert decision.route == Route.PARTIAL_RERUN, f"Failed for: {text}"

    def test_prospect_patterns(self):
        planner = Planner()
        for text in [
            "Analyze this manga IP",
            "How about this anime franchise?",
            "Evaluate this webtoon",
            "prospect analysis for this novel",
        ]:
            decision = planner.classify(text)
            assert decision.route == Route.PROSPECT, f"Failed for: {text}"

    def test_default_routes_to_full_pipeline(self):
        planner = Planner()
        decision = planner.classify("Analyze Berserk")
        assert decision.route == Route.FULL_PIPELINE
        assert decision.intent == "full_analysis"
        assert decision.requires_plan_mode is True

    def test_cost_and_time_from_profile(self):
        planner = Planner()
        decision = planner.classify("Analyze Berserk")
        assert decision.estimated_cost == 1.50
        assert decision.estimated_time_s == 120.0

    def test_profile_property(self):
        planner = Planner()
        decision = planner.classify("/help")
        profile = decision.profile
        assert isinstance(profile, RouteProfile)
        assert profile.route == Route.SCRIPT_ROUTE

    def test_stats_tracking(self):
        planner = Planner()
        planner.classify("/help")
        planner.classify("Analyze Berserk")
        planner.classify("Analyze Berserk")

        assert planner.stats.classifications == 3
        assert planner.stats.by_route[Route.SCRIPT_ROUTE] == 1
        assert planner.stats.by_route[Route.FULL_PIPELINE] == 2

    def test_stats_to_dict(self):
        planner = Planner()
        planner.classify("/help")
        d = planner.stats.to_dict()
        assert "classifications" in d
        assert "cache_hits" in d
        assert "by_route" in d

    def test_cache_invalidate(self):
        planner = Planner()
        planner.cache_result("Berserk", {"score": 82.5})
        assert planner.invalidate_cache("Berserk") is True
        assert planner.invalidate_cache("Berserk") is False
        assert planner.get_cached("Berserk") is None

    def test_clear_cache(self):
        planner = Planner()
        planner.cache_result("Berserk", {"score": 82.5})
        planner.cache_result("Claymore", {"score": 71.0})
        count = planner.clear_cache()
        assert count == 2

    def test_memory_ttl_property(self):
        planner = Planner(memory_ttl_s=999.0)
        assert planner.memory_ttl_s == 999.0

    def test_all_route_profiles_exist(self):
        for route in Route:
            assert route in ROUTE_PROFILES
            profile = ROUTE_PROFILES[route]
            assert profile.estimated_cost > 0
            assert profile.estimated_time_s > 0
            assert len(profile.description) > 0
