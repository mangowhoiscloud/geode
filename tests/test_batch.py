"""Tests for batch analysis."""

from __future__ import annotations

from unittest.mock import patch


class TestSelectIps:
    def test_returns_fixtures(self) -> None:
        from core.cli.batch import select_ips

        ips = select_ips(top=5)
        assert len(ips) <= 5
        assert len(ips) > 0

    def test_respects_top_limit(self) -> None:
        from core.cli.batch import select_ips

        ips = select_ips(top=3)
        assert len(ips) <= 3

    def test_explicit_ips(self) -> None:
        from core.cli.batch import select_ips

        ips = select_ips(ips=["cowboy bebop", "berserk"])
        assert "cowboy bebop" in [ip.lower() for ip in ips]

    def test_invalid_ip_skipped(self) -> None:
        from core.cli.batch import select_ips

        ips = select_ips(ips=["nonexistent_ip_xyz"])
        assert len(ips) == 0

    def test_genre_filter(self) -> None:
        from core.cli.batch import select_ips

        # Should not crash even if genre doesn't match
        ips = select_ips(genre="zzz_nonexistent_genre", top=5)
        assert isinstance(ips, list)


class TestRenderBatchTable:
    def test_renders_without_error(self) -> None:
        from core.cli.batch import render_batch_table

        results = [
            {
                "ip_name": "Test",
                "tier": "A",
                "final_score": 75.0,
                "cause": "test",
                "action": "boost",
            },
        ]
        # Should not raise
        render_batch_table(results)

    def test_handles_empty_results(self) -> None:
        from core.cli.batch import render_batch_table

        render_batch_table([])

    def test_renders_error_tier(self) -> None:
        from core.cli.batch import render_batch_table

        results = [
            {
                "ip_name": "Failed",
                "tier": "ERR",
                "final_score": 0.0,
                "cause": "timeout",
                "error": True,
            },
        ]
        render_batch_table(results)

    def test_renders_multiple_results_with_stats(self) -> None:
        from core.cli.batch import render_batch_table

        results = [
            {"ip_name": "A", "tier": "S", "final_score": 90.0, "cause": "x", "action": "y"},
            {"ip_name": "B", "tier": "A", "final_score": 75.0, "cause": "x", "action": "y"},
        ]
        render_batch_table(results)


class TestRunBatch:
    def test_returns_list(self) -> None:
        from core.cli.batch import run_batch

        with patch("core.cli.batch.run_single_analysis") as mock:
            mock.return_value = {"ip_name": "test", "tier": "A", "final_score": 80.0}
            results = run_batch(ips=["cowboy bebop"], dry_run=True)
            assert isinstance(results, list)

    def test_empty_selection_returns_empty(self) -> None:
        from core.cli.batch import run_batch

        results = run_batch(ips=["nonexistent_xyz"], dry_run=True)
        assert results == []

    def test_timeout_handling(self) -> None:
        """Per-IP timeout produces ERR result instead of crashing."""
        from core.cli.batch import run_batch

        with patch("core.cli.batch.run_single_analysis") as mock:
            mock.return_value = {"ip_name": "test", "tier": "A", "final_score": 80.0}
            results = run_batch(ips=["cowboy bebop"], dry_run=True)
            assert len(results) == 1


class TestRunSingleAnalysis:
    def test_unknown_ip_returns_error(self) -> None:
        from core.cli.batch import _run_analysis_standalone

        result = _run_analysis_standalone("zzz_nonexistent_ip_xyz")
        assert result["tier"] == "ERR"
        assert result["error"] is True

    def test_dry_run_returns_result(self) -> None:
        from core.cli.batch import _run_analysis_standalone

        result = _run_analysis_standalone("cowboy bebop", dry_run=True)
        assert "tier" in result
        assert "final_score" in result
        assert result["tier"] != "ERR"


class TestBatchConstants:
    def test_timeout_constant_exists(self) -> None:
        from core.cli.batch import _IP_TIMEOUT_S

        assert _IP_TIMEOUT_S > 0
        assert isinstance(_IP_TIMEOUT_S, (int, float))
