"""Tests for Pre-defined Automation Templates."""

from __future__ import annotations

import pytest

from geode.automation.predefined import (
    AutomationTemplate,
    PipelineConfig,
    PREDEFINED_AUTOMATIONS,
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
    def test_exactly_four_templates(self):
        assert len(PREDEFINED_AUTOMATIONS) == 4

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
        assert len(templates) == 4

    def test_list_enabled_only(self):
        templates = list_automations(enabled_only=True)
        assert all(t.enabled for t in templates)
        assert len(templates) == 4  # All default templates are enabled

    def test_list_returns_copies(self):
        t1 = list_automations()
        t2 = list_automations()
        assert t1 is not t2  # Should return new list each time
