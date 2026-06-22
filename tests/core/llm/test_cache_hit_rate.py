"""Prompt-cache hit-rate telemetry + degraded-cache warning (2026-06).

``LLMUsageAccumulator`` records cache_creation / cache_read token counts but
never derived a hit RATE or alerted on a degraded one, so a silently-busted
prefix cache (volatile content, below-minimum prefix, 20-block lookback
exceeded) was invisible until the provider noticed the bill. These tests pin
the new ``cache_hit_rate`` property + one-shot ``maybe_warn_low_cache_hit_rate``.
"""

from __future__ import annotations

import logging

from core.llm.token_tracker import LLMUsage, LLMUsageAccumulator


def _usage(*, creation: int = 0, read: int = 0) -> LLMUsage:
    return LLMUsage(
        model="claude-opus-4-8",
        input_tokens=10,
        output_tokens=5,
        cache_creation_tokens=creation,
        cache_read_tokens=read,
    )


class TestCacheHitRate:
    def test_zero_when_no_cache_activity(self):
        acc = LLMUsageAccumulator()
        acc.record(_usage())
        assert acc.cache_hit_rate == 0.0

    def test_ratio_is_read_over_read_plus_creation(self):
        acc = LLMUsageAccumulator()
        acc.record(_usage(creation=1000, read=3000))
        assert acc.cache_hit_rate == 0.75

    def test_to_dict_includes_rate_only_with_cache_activity(self):
        acc = LLMUsageAccumulator()
        acc.record(_usage())  # no cache tokens
        assert "cache_hit_rate" not in acc.to_dict()
        acc.record(_usage(creation=100, read=900))
        assert acc.to_dict()["cache_hit_rate"] == 0.9


class TestDegradedCacheWarning:
    def _degraded(self, r: logging.LogRecord) -> bool:
        return "hit rate degraded" in r.getMessage()

    def test_warns_once_below_threshold(self, caplog):
        acc = LLMUsageAccumulator()
        with caplog.at_level(logging.WARNING, logger="core.llm.token_tracker"):
            # 60k cacheable tokens at 10% hit rate → below 30% / above 50k min.
            acc.record(_usage(creation=54_000, read=6_000))
        assert len([r for r in caplog.records if self._degraded(r)]) == 1

    def test_one_shot_guard_prevents_repeat(self, caplog):
        acc = LLMUsageAccumulator()
        with caplog.at_level(logging.WARNING, logger="core.llm.token_tracker"):
            acc.record(_usage(creation=54_000, read=6_000))
            acc.record(_usage(creation=54_000, read=6_000))
        assert len([r for r in caplog.records if self._degraded(r)]) == 1

    def test_no_warning_below_min_tokens(self, caplog):
        acc = LLMUsageAccumulator()
        with caplog.at_level(logging.WARNING, logger="core.llm.token_tracker"):
            acc.record(_usage(creation=900, read=100))  # 1k « 50k min
        assert not [r for r in caplog.records if self._degraded(r)]

    def test_no_warning_above_threshold(self, caplog):
        acc = LLMUsageAccumulator()
        with caplog.at_level(logging.WARNING, logger="core.llm.token_tracker"):
            acc.record(_usage(creation=10_000, read=90_000))  # 90% hit on 100k
        assert not [r for r in caplog.records if self._degraded(r)]

    def test_record_tolerates_non_int_tokens(self):
        # A mocked usage object (MagicMock token fields, as test_failover does)
        # must not raise from the record() -> maybe_warn hook — advisory
        # telemetry never breaks the call path.
        from unittest.mock import MagicMock

        acc = LLMUsageAccumulator()
        acc.record(
            LLMUsage(
                model="claude-test",
                input_tokens=MagicMock(),
                output_tokens=MagicMock(),
                cache_creation_tokens=MagicMock(),
                cache_read_tokens=MagicMock(),
            )
        )  # no exception
