"""Tests for Agent Reflection -- auto-learn patterns from pipeline results."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from core.orchestration.agent_reflection import make_reflection_handler
from core.orchestration.hooks import HookEvent, HookSystem


class FakeUserProfile:
    """Minimal fake for FileBasedUserProfile to capture learned patterns."""

    def __init__(self) -> None:
        self.patterns: list[tuple[str, str]] = []

    def add_learned_pattern(self, pattern: str, category: str = "general") -> bool:
        self.patterns.append((pattern, category))
        return True


class FakeResultCache:
    """Minimal fake for ResultCache."""

    def __init__(self, data: dict[str, dict[str, Any]] | None = None) -> None:
        self._data = data or {}

    def get(self, ip_name: str) -> dict[str, Any] | None:
        return self._data.get(ip_name.lower())


class TestMakeReflectionHandler:
    """Tests for the reflection handler factory."""

    def test_returns_handler_tuple(self):
        profile = FakeUserProfile()
        name, handler = make_reflection_handler(profile)
        assert name == "agent_reflection"
        assert callable(handler)

    def test_handler_ignores_non_pipeline_end(self):
        profile = FakeUserProfile()
        _, handler = make_reflection_handler(profile)
        handler(HookEvent.PIPELINE_START, {"ip_name": "Berserk"})
        assert len(profile.patterns) == 0

    def test_records_analysis_completion(self):
        profile = FakeUserProfile()
        _, handler = make_reflection_handler(profile)
        handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 81.3,
                "cause": "conversion_failure",
            },
        )
        assert len(profile.patterns) == 1
        pattern, category = profile.patterns[0]
        assert "[Berserk]" in pattern
        assert "Tier S" in pattern
        assert "81.3" in pattern
        assert "conversion_failure" in pattern
        assert category == "analysis"

    def test_records_failure(self):
        profile = FakeUserProfile()
        _, handler = make_reflection_handler(profile)
        handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Unknown",
                "status": "error",
                "error": "API timeout",
            },
        )
        assert any("failed" in p[0].lower() for p in profile.patterns)
        assert any(p[1] == "failure" for p in profile.patterns)

    def test_records_confidence_iterations(self):
        profile = FakeUserProfile()
        _, handler = make_reflection_handler(profile)
        handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 81.3,
                "cause": "conversion_failure",
                "iterations": 3,
            },
        )
        confidence_patterns = [p for p in profile.patterns if p[1] == "confidence"]
        assert len(confidence_patterns) == 1
        assert "3 confidence iterations" in confidence_patterns[0][0]

    def test_skips_single_iteration(self):
        profile = FakeUserProfile()
        _, handler = make_reflection_handler(profile)
        handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 81.3,
                "cause": "conversion_failure",
                "iterations": 1,
            },
        )
        confidence_patterns = [p for p in profile.patterns if p[1] == "confidence"]
        assert len(confidence_patterns) == 0

    def test_ignores_empty_ip_name(self):
        profile = FakeUserProfile()
        _, handler = make_reflection_handler(profile)
        handler(HookEvent.PIPELINE_END, {"tier": "S", "score": 81.3})
        assert len(profile.patterns) == 0


class TestTierChangeDetection:
    """Tests for tier change detection (Karpathy P4 Ratchet)."""

    def test_detects_tier_upgrade(self):
        profile = FakeUserProfile()
        cache = FakeResultCache({"berserk": {"tier": "A", "final_score": 68.0}})
        _, handler = make_reflection_handler(profile, result_cache=cache)
        handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 81.3,
                "cause": "conversion_failure",
            },
        )
        upgrade_patterns = [p for p in profile.patterns if p[1] == "tier_upgrade"]
        assert len(upgrade_patterns) == 1
        assert "upgraded" in upgrade_patterns[0][0]
        assert "A -> S" in upgrade_patterns[0][0]

    def test_detects_tier_downgrade(self):
        profile = FakeUserProfile()
        cache = FakeResultCache({"berserk": {"tier": "S", "final_score": 81.3}})
        _, handler = make_reflection_handler(profile, result_cache=cache)
        handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "A",
                "score": 68.0,
                "cause": "undermarketed",
            },
        )
        regression_patterns = [p for p in profile.patterns if p[1] == "tier_regression"]
        assert len(regression_patterns) == 1
        assert "downgraded" in regression_patterns[0][0]
        assert "S -> A" in regression_patterns[0][0]

    def test_no_change_when_same_tier(self):
        profile = FakeUserProfile()
        cache = FakeResultCache({"berserk": {"tier": "S", "final_score": 81.3}})
        _, handler = make_reflection_handler(profile, result_cache=cache)
        handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 82.0,
                "cause": "conversion_failure",
            },
        )
        change_patterns = [
            p for p in profile.patterns if p[1] in ("tier_upgrade", "tier_regression")
        ]
        assert len(change_patterns) == 0

    def test_no_change_when_no_cache(self):
        profile = FakeUserProfile()
        cache = FakeResultCache({})
        _, handler = make_reflection_handler(profile, result_cache=cache)
        handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 81.3,
                "cause": "conversion_failure",
            },
        )
        change_patterns = [
            p for p in profile.patterns if p[1] in ("tier_upgrade", "tier_regression")
        ]
        assert len(change_patterns) == 0

    def test_score_info_in_tier_change(self):
        profile = FakeUserProfile()
        cache = FakeResultCache({"berserk": {"tier": "B", "final_score": 51.6}})
        _, handler = make_reflection_handler(profile, result_cache=cache)
        handler(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 81.3,
                "cause": "conversion_failure",
            },
        )
        upgrade_patterns = [p for p in profile.patterns if p[1] == "tier_upgrade"]
        assert "51.6" in upgrade_patterns[0][0]
        assert "81.3" in upgrade_patterns[0][0]


class TestHookIntegration:
    """Test that reflection handler integrates properly with HookSystem."""

    def test_register_and_trigger(self):
        hooks = HookSystem()
        profile = FakeUserProfile()
        name, handler = make_reflection_handler(profile)
        hooks.register(HookEvent.PIPELINE_END, handler, name=name, priority=90)

        results = hooks.trigger(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 81.3,
                "cause": "conversion_failure",
            },
        )
        assert len(results) == 1
        assert results[0].success is True
        assert len(profile.patterns) >= 1

    def test_handler_error_does_not_crash(self):
        """Handler errors should be caught by HookSystem."""
        hooks = HookSystem()
        profile = MagicMock()
        profile.add_learned_pattern.side_effect = RuntimeError("disk full")
        name, handler = make_reflection_handler(profile)
        hooks.register(HookEvent.PIPELINE_END, handler, name=name)

        # Should not raise
        results = hooks.trigger(
            HookEvent.PIPELINE_END,
            {
                "ip_name": "Berserk",
                "tier": "S",
                "score": 81.3,
                "cause": "conversion_failure",
            },
        )
        assert len(results) == 1
        assert results[0].success is False
