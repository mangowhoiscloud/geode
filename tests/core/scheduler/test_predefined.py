import pytest
from core.scheduler.predefined import (
    AutomationTemplate,
    PipelineConfig,
    get_automation,
    list_automations,
    to_trigger_config,
)
from core.scheduler.triggers import TriggerType


def test_pipeline_config_defaults_are_generic() -> None:
    config = PipelineConfig()

    assert config.mode == "pipeline"
    assert config.batch_size == 1
    assert config.extra == {}


def test_core_ships_no_domain_specific_predefined_automations() -> None:
    assert list_automations() == []
    assert list_automations(tag="anything") == []
    assert list_automations(enabled_only=True) == []
    with pytest.raises(KeyError):
        get_automation("weekly_discovery_scan")


def test_to_trigger_config_supports_scheduled_and_event_templates() -> None:
    scheduled = AutomationTemplate(
        id="nightly",
        name="Nightly",
        description="Nightly pipeline",
        schedule="0 0 * * *",
        pipeline_config=PipelineConfig(extra={"scope": "all"}),
        tags=["ops"],
    )
    evented = AutomationTemplate(
        id="on-result",
        name="On result",
        description="Event pipeline",
        schedule="event:result.ready",
        pipeline_config=PipelineConfig(mode="event"),
        enabled=False,
    )

    scheduled_trigger = to_trigger_config(scheduled)
    event_trigger = to_trigger_config(evented)

    assert scheduled_trigger.trigger_type == TriggerType.SCHEDULED
    assert scheduled_trigger.cron_expr == "0 0 * * *"
    assert scheduled_trigger.metadata["pipeline_config"]["extra"] == {"scope": "all"}
    assert event_trigger.trigger_type == TriggerType.EVENT
    assert event_trigger.metadata["event_name"] == "result.ready"
    assert event_trigger.enabled is False
