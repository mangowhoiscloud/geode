"""Tests for Pre-defined Automation Templates."""

from __future__ import annotations

import pytest

from geode.automation.predefined import (
    PREDEFINED_AUTOMATIONS,
    AutomationTemplate,
    PipelineConfig,
    get_automation,
    list_automations,
)


class TestPipelineConfig:
    def test_defaults(self):
        config = PipelineConfig()
        assert config.mode == "full_pipeline"
        assert config.batch_size == 1
        assert config.dry_run is False
        assert config.skip_verification is False
        assert config.extra == {}

    def test_custom_config(self):
        config = PipelineConfig(
            mode="evaluation",
            batch_size=50,
            extra={"source": "monolake"},
        )
        assert config.batch_size == 50
        assert config.extra["source"] == "monolake"


class TestAutomationTemplate:
    def test_basic_creation(self):
        template = AutomationTemplate(
            id="test",
            name="Test Template",
            description="A test automation.",
            schedule="0 0 * * *",
            pipeline_config=PipelineConfig(),
        )
        assert template.id == "test"
        assert template.enabled is True
        assert template.tags == []


class TestPredefinedAutomations:
    def test_exactly_ten_templates(self):
        assert len(PREDEFINED_AUTOMATIONS) == 10

    def test_all_have_unique_ids(self):
        ids = [a.id for a in PREDEFINED_AUTOMATIONS]
        assert len(ids) == len(set(ids))

    def test_weekly_discovery_scan(self):
        scan = get_automation("weekly_discovery_scan")
        assert scan.name == "Weekly Discovery Scan"
        assert "9" in scan.schedule  # 09:00
        assert scan.pipeline_config.batch_size == 50
        assert scan.pipeline_config.mode == "full_pipeline"
        assert "discovery" in scan.tags

    def test_calibration_drift_scan(self):
        drift = get_automation("calibration_drift_scan")
        assert "daily" in drift.tags or "drift" in drift.tags
        assert drift.pipeline_config.mode == "evaluation"
        assert drift.pipeline_config.skip_verification is True
        metrics = drift.pipeline_config.extra.get("metrics", [])
        assert "spearman_rho" in metrics

    def test_outcome_tracker(self):
        tracker = get_automation("outcome_tracker")
        assert "monthly" in tracker.tags
        assert tracker.pipeline_config.mode == "scoring"
        windows = tracker.pipeline_config.extra.get("tracking_windows", [])
        assert 30 in windows
        assert 90 in windows

    def test_auto_generate_report(self):
        report = get_automation("auto_generate_report")
        assert report.schedule.startswith("event:")
        assert "report" in report.tags
        assert "include_sections" in report.pipeline_config.extra

    def test_pending_analysis_worker(self):
        worker = get_automation("pending_analysis_worker")
        assert worker.name == "Pending Analysis Worker"
        assert "*/30" in worker.schedule  # Every 30 minutes
        assert worker.pipeline_config.batch_size == 10
        assert worker.pipeline_config.mode == "full_pipeline"
        assert "worker" in worker.tags

    def test_data_quality_scan(self):
        scan = get_automation("data_quality_scan")
        assert scan.name == "Data Quality Scan"
        assert "5" in scan.schedule  # 05:00
        assert scan.pipeline_config.mode == "evaluation"
        checks = scan.pipeline_config.extra.get("checks", [])
        assert "signal_completeness" in checks
        assert "daily" in scan.tags

    def test_anomaly_detector(self):
        detector = get_automation("anomaly_detector")
        assert detector.schedule.startswith("event:")
        assert detector.pipeline_config.mode == "evaluation"
        methods = detector.pipeline_config.extra.get("detection_methods", [])
        assert "zscore" in methods
        assert "anomaly" in detector.tags

    def test_weekly_s_tier_report(self):
        report = get_automation("weekly_s_tier_report")
        assert "10" in report.schedule  # 10:00
        assert "5" in report.schedule  # Friday (day 5)
        assert report.pipeline_config.mode == "scoring"
        assert "s-tier" in report.tags
        tier_filter = report.pipeline_config.extra.get("tier_filter", [])
        assert "S" in tier_filter

    def test_weekly_discovery_summary(self):
        summary = get_automation("weekly_discovery_summary")
        assert summary.name == "Weekly Discovery Summary"
        assert summary.schedule == "0 10 * * 1"  # Monday 10:00 (after scan at 09:00)
        assert summary.pipeline_config.mode == "scoring"
        assert "summary" in summary.tags
        assert summary.pipeline_config.extra.get("lookback_days") == 7

    def test_failed_evaluation_summary(self):
        summary = get_automation("failed_evaluation_summary")
        assert summary.name == "Failed Evaluation Summary"
        assert "8" in summary.schedule  # 08:00
        assert summary.pipeline_config.mode == "evaluation"
        assert "failures" in summary.tags
        categories = summary.pipeline_config.extra.get("failure_categories", [])
        assert "pipeline_error" in categories


class TestGetAutomation:
    def test_get_existing(self):
        template = get_automation("weekly_discovery_scan")
        assert template.id == "weekly_discovery_scan"

    def test_get_nonexistent_raises(self):
        with pytest.raises(KeyError, match="not found"):
            get_automation("nonexistent_automation")


class TestListAutomations:
    def test_list_all(self):
        templates = list_automations()
        assert len(templates) == 10

    def test_list_enabled_only(self):
        templates = list_automations(enabled_only=True)
        assert all(t.enabled for t in templates)
        assert len(templates) == 10  # All default templates are enabled

    def test_list_returns_copies(self):
        t1 = list_automations()
        t2 = list_automations()
        assert t1 is not t2  # Should return new list each time
