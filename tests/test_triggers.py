"""Tests for L4.5 Trigger Manager (F1-F4) and Dispatch Layer (§12.2)."""

from __future__ import annotations

from typing import Any

import pytest
from core.scheduler.triggers import (
    CronParser,
    TriggerConfig,
    TriggerManager,
    TriggerResult,
    TriggerType,
)


class TestTriggerType:
    def test_all_types(self):
        assert len(TriggerType) == 4
        assert TriggerType.MANUAL.value == "manual"
        assert TriggerType.SCHEDULED.value == "scheduled"
        assert TriggerType.EVENT.value == "event"
        assert TriggerType.WEBHOOK.value == "webhook"


class TestCronParser:
    def test_all_stars_matches(self):
        assert CronParser.matches("* * * * *", (0, 0, 1, 1, 0)) is True

    def test_specific_minute(self):
        assert CronParser.matches("30 * * * *", (30, 12, 1, 1, 0)) is True
        assert CronParser.matches("30 * * * *", (15, 12, 1, 1, 0)) is False

    def test_comma_separated(self):
        assert CronParser.matches("0,30 * * * *", (0, 0, 1, 1, 0)) is True
        assert CronParser.matches("0,30 * * * *", (30, 0, 1, 1, 0)) is True
        assert CronParser.matches("0,30 * * * *", (15, 0, 1, 1, 0)) is False

    def test_range(self):
        assert CronParser.matches("* 9-17 * * *", (0, 12, 1, 1, 0)) is True
        assert CronParser.matches("* 9-17 * * *", (0, 20, 1, 1, 0)) is False

    def test_invalid_cron_raises(self):
        with pytest.raises(ValueError, match="Invalid cron"):
            CronParser.matches("* *", (0, 0, 0, 0, 0))

    def test_current_tuple(self):
        t = CronParser.current_tuple()
        assert len(t) == 5
        assert 0 <= t[0] <= 59  # minute
        assert 0 <= t[1] <= 23  # hour


class TestTriggerResult:
    def test_to_dict(self):
        r = TriggerResult(
            trigger_id="t1",
            trigger_type=TriggerType.MANUAL,
            success=True,
        )
        d = r.to_dict()
        assert d["trigger_id"] == "t1"
        assert d["success"] is True


class TestTriggerManager:
    def test_register_and_list(self):
        mgr = TriggerManager()
        mgr.register(TriggerConfig(trigger_id="t1", trigger_type=TriggerType.MANUAL))
        assert len(mgr.list_triggers()) == 1

    def test_unregister(self):
        mgr = TriggerManager()
        mgr.register(TriggerConfig(trigger_id="t1", trigger_type=TriggerType.MANUAL))
        assert mgr.unregister("t1") is True
        assert mgr.unregister("t1") is False

    def test_fire_manual(self):
        calls = []
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="t1",
                trigger_type=TriggerType.MANUAL,
                callback=lambda data: calls.append(data),
            )
        )
        result = mgr.fire_manual("t1", {"ip": "Berserk"})
        assert result.success is True
        assert len(calls) == 1
        assert mgr.stats.fired == 1

    def test_fire_manual_not_found(self):
        mgr = TriggerManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.fire_manual("nope")

    def test_fire_manual_error(self):
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="t1",
                trigger_type=TriggerType.MANUAL,
                callback=lambda data: 1 / 0,
            )
        )
        result = mgr.fire_manual("t1")
        assert result.success is False
        assert "division" in result.error
        assert mgr.stats.errors == 1

    def test_check_scheduled(self):
        calls = []
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="t1",
                trigger_type=TriggerType.SCHEDULED,
                cron_expr="30 12 * * *",
                callback=lambda data: calls.append(data),
            )
        )
        results = mgr.check_scheduled((30, 12, 15, 6, 2))
        assert len(results) == 1
        assert results[0].success is True

    def test_check_scheduled_no_match(self):
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="t1",
                trigger_type=TriggerType.SCHEDULED,
                cron_expr="30 12 * * *",
                callback=lambda data: None,
            )
        )
        results = mgr.check_scheduled((0, 0, 1, 1, 0))
        assert len(results) == 0

    def test_make_event_handler(self):
        calls = []
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="t1",
                trigger_type=TriggerType.EVENT,
                callback=lambda data: calls.append(data),
            )
        )
        handler = mgr.make_event_handler("t1")
        handler("NODE_ENTER", {"node": "router"})
        assert len(calls) == 1

    def test_handle_webhook(self):
        calls = []
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="wh1",
                trigger_type=TriggerType.WEBHOOK,
                callback=lambda data: calls.append(data),
            )
        )
        result = mgr.handle_webhook("wh1", {"payload": "test"})
        assert result.success is True

    def test_handle_webhook_wrong_type(self):
        mgr = TriggerManager()
        mgr.register(TriggerConfig(trigger_id="t1", trigger_type=TriggerType.MANUAL))
        with pytest.raises(ValueError, match="not a WEBHOOK"):
            mgr.handle_webhook("t1", {})

    def test_scheduler_start_stop(self):
        mgr = TriggerManager(scheduler_interval_s=0.1)
        mgr.start_scheduler()
        assert mgr.is_scheduler_running is True
        mgr.stop_scheduler()
        assert mgr.is_scheduler_running is False

    def test_get_results(self):
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="t1",
                trigger_type=TriggerType.MANUAL,
                callback=lambda data: None,
            )
        )
        mgr.fire_manual("t1")
        mgr.fire_manual("t1")
        results = mgr.get_results("t1")
        assert len(results) == 2

    def test_list_triggers_by_type(self):
        mgr = TriggerManager()
        mgr.register(TriggerConfig(trigger_id="m1", trigger_type=TriggerType.MANUAL))
        mgr.register(TriggerConfig(trigger_id="s1", trigger_type=TriggerType.SCHEDULED))
        manual = mgr.list_triggers(TriggerType.MANUAL)
        assert len(manual) == 1
        assert manual[0].trigger_id == "m1"

    def test_register_pipeline_trigger(self):
        mgr = TriggerManager()
        fired = []
        config = mgr.register_pipeline_trigger(
            trigger_id="pipe-1",
            ip_name="Berserk",
            callback=lambda data: fired.append(data),
        )
        assert config.trigger_id == "pipe-1"
        assert config.metadata["ip_name"] == "Berserk"
        assert config.metadata["source"] == "pipeline_trigger"
        # Fire it and verify callback
        result = mgr.fire_manual("pipe-1", {"test": True})
        assert result.success
        assert len(fired) == 1

    def test_results_pruning(self):
        """Results list should be bounded by MAX_RESULTS."""
        mgr = TriggerManager()
        mgr.MAX_RESULTS = 5  # Lower for testing
        mgr.register(
            TriggerConfig(
                trigger_id="t1",
                trigger_type=TriggerType.MANUAL,
            )
        )
        for _ in range(10):
            mgr.fire_manual("t1")
        results = mgr.get_results()
        assert len(results) <= 5


class TestDispatch:
    """Tests for unified dispatch method (§12.2 Dispatch Layer)."""

    def test_dispatch_manual_with_registered_trigger(self):
        calls: list[dict[str, Any]] = []
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="auto-1",
                trigger_type=TriggerType.MANUAL,
                callback=lambda data: calls.append(data),
            )
        )
        result = mgr.dispatch(TriggerType.MANUAL, {"ip": "Berserk"}, automation_id="auto-1")
        assert result.success is True
        assert len(calls) == 1
        assert calls[0]["_dispatch"]["trigger_type"] == "manual"
        assert calls[0]["_dispatch"]["automation_id"] == "auto-1"

    def test_dispatch_ephemeral_without_automation_id(self):
        mgr = TriggerManager()
        result = mgr.dispatch(TriggerType.MANUAL, {"query": "test"})
        assert result.success is True
        assert result.trigger_type == TriggerType.MANUAL

    def test_dispatch_scheduled_batch_mode(self):
        calls: list[dict[str, Any]] = []
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="batch-scan",
                trigger_type=TriggerType.SCHEDULED,
                callback=lambda data: calls.append(data),
            )
        )
        result = mgr.dispatch(
            TriggerType.SCHEDULED,
            {"batch": True, "ip_list": ["IP1", "IP2"]},
            automation_id="batch-scan",
        )
        assert result.success is True
        assert calls[0]["_batch_mode"] is True

    def test_dispatch_webhook_source(self):
        mgr = TriggerManager()
        result = mgr.dispatch(
            TriggerType.WEBHOOK,
            {"source": "monolake", "data": "payload"},
        )
        assert result.success is True
        assert result.data["_source"] == "monolake"

    def test_dispatch_event_follow_up(self):
        mgr = TriggerManager()
        result = mgr.dispatch(
            TriggerType.EVENT,
            {"event": "pipeline_complete", "ip": "test"},
        )
        assert result.success is True
        assert result.data["_follow_up"] is True

    def test_dispatch_event_no_follow_up(self):
        mgr = TriggerManager()
        result = mgr.dispatch(
            TriggerType.EVENT,
            {"event": "scoring_complete"},
        )
        assert result.data["_follow_up"] is False

    def test_dispatch_with_snapshot_manager(self):
        from core.automation.snapshot import SnapshotManager

        snap_mgr = SnapshotManager()
        mgr = TriggerManager(snapshot_manager=snap_mgr)
        result = mgr.dispatch(
            TriggerType.MANUAL,
            {"session_id": "test-session"},
        )
        assert result.success is True
        assert result.data["_dispatch"]["snapshot_id"].startswith("snap-")
        # Verify snapshot was captured
        snaps = snap_mgr.list_snapshots("test-session")
        assert len(snaps) == 1
        assert snaps[0].context["trigger_type"] == "manual"

    def test_dispatch_callback_error(self):
        mgr = TriggerManager()
        mgr.register(
            TriggerConfig(
                trigger_id="err-1",
                trigger_type=TriggerType.MANUAL,
                callback=lambda data: 1 / 0,
            )
        )
        result = mgr.dispatch(TriggerType.MANUAL, {}, automation_id="err-1")
        assert result.success is False
        assert "division" in result.error
