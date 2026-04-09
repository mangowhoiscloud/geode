"""Tests for GeodeRuntime — production wiring integration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from core.hooks import HookEvent, HookSystem
from core.memory.session import InMemorySessionStore
from core.orchestration.hot_reload import ConfigWatcher
from core.orchestration.lane_queue import LaneQueue
from core.orchestration.run_log import RunLog
from core.orchestration.stuck_detection import StuckDetector
from core.orchestration.task_bridge import TaskGraphHookBridge
from core.orchestration.task_system import TaskGraph
from core.runtime import (
    GeodeRuntime,
    _build_default_lanes,
    _build_default_policies,
    _build_default_registry,
    _make_run_log_handler,
)
from core.tools.policy import PolicyChain
from core.tools.registry import ToolRegistry


class TestGeodeRuntimeCreate:
    def test_create_basic(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        assert runtime.ip_name == "Berserk"
        assert runtime.session_key == "ip:berserk:analysis"
        assert isinstance(runtime.hooks, HookSystem)
        assert isinstance(runtime.session_store, InMemorySessionStore)
        assert isinstance(runtime.policy_chain, PolicyChain)
        assert isinstance(runtime.tool_registry, ToolRegistry)
        assert isinstance(runtime.run_log, RunLog)

    def test_create_custom_phase(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Cowboy Bebop", phase="scoring", log_dir=tmp_path)
        assert runtime.session_key == "ip:cowboy_bebop:scoring"

    def test_thread_config(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        config = runtime.thread_config
        assert config["configurable"] == {"thread_id": "ip:berserk:analysis"}
        assert config["run_name"] == "geode:Berserk:analysis"
        assert "ip:Berserk" in config["tags"]


class TestRuntimeHooksRunLog:
    def test_hooks_write_to_run_log(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)

        # Trigger a pipeline event
        runtime.hooks.trigger(
            HookEvent.NODE_ENTER,
            {"node": "router", "ip_name": "Berserk"},
        )
        runtime.hooks.trigger(
            HookEvent.NODE_EXIT,
            {"node": "router", "ip_name": "Berserk", "duration_ms": 42.0},
        )

        # Verify our events exist in the run log
        # (other hooks like scheduler/trigger may add cascading entries)
        entries = runtime.run_log.read(limit=20)
        assert len(entries) >= 2
        node_events = [e for e in entries if e.node == "router"]
        assert len(node_events) == 2
        exit_entry = next(e for e in node_events if e.event == "node_exit")
        assert exit_entry.duration_ms == 42.0
        enter_entry = next(e for e in node_events if e.event == "node_enter")
        assert enter_entry.node == "router"

    def test_all_hook_events_logged(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)

        # Trigger each event type
        for event in HookEvent:
            runtime.hooks.trigger(event, {"node": "test"})

        entries = runtime.run_log.read(limit=100)
        # All direct events + cascading hooks (e.g. SNAPSHOT_CAPTURED from drift→auto-snapshot)
        assert len(entries) >= len(HookEvent)

    def test_error_events_logged_with_error_status(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)

        runtime.hooks.trigger(
            HookEvent.NODE_ERROR,
            {"node": "router", "error": "connection timeout"},
        )

        # Find the node_error entry (cascading hooks may add others)
        entries = runtime.run_log.read(limit=10)
        error_entries = [e for e in entries if e.event == "node_error"]
        assert len(error_entries) >= 1
        assert error_entries[0].status == "error"
        assert error_entries[0].node == "router"


class TestRuntimeSessionStore:
    def test_store_and_retrieve(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)

        runtime.store_session_data({"ip_name": "Berserk", "mode": "full_pipeline"})
        data = runtime.get_session_data()
        assert data is not None
        assert data["ip_name"] == "Berserk"

    def test_no_session_returns_none(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        assert runtime.get_session_data() is None


class TestRuntimePolicyChain:
    def test_dry_run_blocks_llm_tools(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)

        full_tools = runtime.get_available_tools(mode="full_pipeline")
        dry_tools = runtime.get_available_tools(mode="dry_run")

        assert "run_analyst" in full_tools
        assert "run_evaluator" in full_tools
        assert "psm_calculate" in full_tools

        assert "run_analyst" not in dry_tools
        assert "run_evaluator" not in dry_tools
        assert "send_notification" not in dry_tools
        assert "psm_calculate" in dry_tools

    def test_full_pipeline_blocks_notification(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        tools = runtime.get_available_tools(mode="full_pipeline")
        # 24 total minus send_notification = 23
        assert len(tools) == 23
        assert "send_notification" not in tools


class TestRuntimeToolRegistry:
    def test_registry_has_all_tools(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        assert len(runtime.tool_registry) == 24
        assert "run_analyst" in runtime.tool_registry
        assert "run_evaluator" in runtime.tool_registry
        assert "psm_calculate" in runtime.tool_registry
        # Data tools
        assert "query_monolake" in runtime.tool_registry
        assert "cortex_analyst" in runtime.tool_registry
        assert "cortex_search" in runtime.tool_registry
        # Signal tools
        assert "youtube_search" in runtime.tool_registry
        assert "reddit_sentiment" in runtime.tool_registry
        assert "twitch_stats" in runtime.tool_registry
        assert "steam_info" in runtime.tool_registry
        assert "google_trends" in runtime.tool_registry
        # Memory tools
        assert "memory_search" in runtime.tool_registry
        assert "memory_get" in runtime.tool_registry
        assert "memory_save" in runtime.tool_registry
        assert "rule_create" in runtime.tool_registry
        assert "rule_update" in runtime.tool_registry
        assert "rule_delete" in runtime.tool_registry
        assert "rule_list" in runtime.tool_registry
        # Output tools
        assert "generate_report" in runtime.tool_registry
        assert "export_json" in runtime.tool_registry
        assert "send_notification" in runtime.tool_registry


class TestRuntimeCompileGraph:
    def test_compile_without_checkpoint(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        graph = runtime.compile_graph()
        assert graph is not None

    def test_compile_with_checkpoint(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        graph = runtime.compile_graph(enable_checkpoint=True)
        assert graph is not None


class TestRunLogPruning:
    def test_prune_logs(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        # Just verify it doesn't error on empty log
        removed = runtime.prune_logs()
        assert removed == 0


class TestDefaultBuilders:
    def test_default_policies(self):
        chain = _build_default_policies()
        # L1-2 wired: default ProfilePolicy adds no_dangerous (priority 10)
        # + 2 mode-based policies = 3 total (may vary if user has config)
        assert len(chain.list_policies()) >= 2
        # dry_run blocks
        assert chain.is_allowed("psm_calculate", mode="dry_run") is True
        assert chain.is_allowed("run_analyst", mode="dry_run") is False
        assert chain.is_allowed("send_notification", mode="dry_run") is False
        # full_pipeline blocks notification only
        assert chain.is_allowed("run_analyst", mode="full_pipeline") is True
        assert chain.is_allowed("send_notification", mode="full_pipeline") is False

    def test_default_registry(self):
        registry = _build_default_registry()
        assert len(registry) == 24

    def test_make_run_log_handler(self, tmp_path: Path):
        run_log = RunLog("test_session", log_dir=tmp_path)
        name, handler = _make_run_log_handler(run_log, "test_session", "run-001")
        assert name == "run_log_writer"

        handler(HookEvent.PIPELINE_START, {"node": "router"})
        entries = run_log.read(limit=1)
        assert len(entries) == 1
        assert entries[0].event == "pipeline_start"

    def test_default_lanes(self):
        queue = _build_default_lanes()
        assert "session" in queue.list_lanes()
        assert "global" in queue.list_lanes()
        assert "gateway" in queue.list_lanes()
        # SessionLane (per-key serialization)
        sl = queue.session_lane
        assert sl is not None
        assert sl.max_sessions == 256
        # Global Lane (total capacity)
        global_lane = queue.get_lane("global")
        assert global_lane is not None and global_lane.max_concurrent == 8
        # Gateway Lane (workload-specific cap)
        gw_lane = queue.get_lane("gateway")
        assert gw_lane is not None and gw_lane.max_concurrent == 4


class TestRuntimeNewComponents:
    def test_config_watcher_wired(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        assert isinstance(runtime.config_watcher, ConfigWatcher)

    def test_stuck_detector_wired(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        assert isinstance(runtime.stuck_detector, StuckDetector)

    def test_lane_queue_wired(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        assert isinstance(runtime.lane_queue, LaneQueue)
        assert "session" in runtime.lane_queue.list_lanes()
        assert "global" in runtime.lane_queue.list_lanes()

    def test_stuck_detector_hooks_wired(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)

        # Trigger PIPELINE_START → should mark running
        runtime.hooks.trigger(
            HookEvent.PIPELINE_START,
            {"node": "router", "ip_name": "Berserk"},
        )
        assert runtime.stuck_detector.running_count == 1

        # Trigger PIPELINE_END → should mark completed
        runtime.hooks.trigger(
            HookEvent.PIPELINE_END,
            {"node": "synthesizer", "ip_name": "Berserk"},
        )
        assert runtime.stuck_detector.running_count == 0

    def test_shutdown(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        runtime.shutdown()  # Should not raise


class TestGetHealth:
    def test_get_health_has_all_components(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        health = runtime.get_health()
        assert health["ip_name"] == "Berserk"
        assert "drift" in health
        assert "model_registry" in health
        assert "expert_panel" in health
        assert "correlation" in health
        assert "outcome_tracker" in health
        assert "triggers" in health
        assert "feedback_loop" in health
        assert "stuck_tasks" in health
        assert "scheduler_running" in health

    def test_get_health_stats_types(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        health = runtime.get_health()
        assert isinstance(health["drift"], dict)
        assert isinstance(health["model_registry"], dict)
        assert isinstance(health["stuck_tasks"], int)


class TestReactiveChains:
    def test_drift_triggers_snapshot(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Isolate SnapshotManager storage to tmp_path so stale .geode/snapshots/
        # files from previous runs don't pollute snapshot counts.
        monkeypatch.setattr(
            "core.config.settings.snapshot_dir",
            str(tmp_path / "snapshots"),
        )
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        initial_snaps = runtime.snapshot_manager.list_snapshots()

        runtime.hooks.trigger(
            HookEvent.DRIFT_DETECTED,
            {"metric": "spearman_rho", "severity": "warning"},
        )

        after_snaps = runtime.snapshot_manager.list_snapshots()
        assert len(after_snaps) == len(initial_snaps) + 1

    def test_pipeline_end_triggers_snapshot(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Isolate SnapshotManager storage to tmp_path so stale .geode/snapshots/
        # files from previous runs don't pollute snapshot counts.
        monkeypatch.setattr(
            "core.config.settings.snapshot_dir",
            str(tmp_path / "snapshots"),
        )
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        initial_snaps = runtime.snapshot_manager.list_snapshots()

        runtime.hooks.trigger(
            HookEvent.PIPELINE_END,
            {"node": "synthesizer", "ip_name": "Berserk"},
        )

        after_snaps = runtime.snapshot_manager.list_snapshots()
        assert len(after_snaps) == len(initial_snaps) + 1


class TestRuntimeTaskGraph:
    def test_task_graph_created_on_init(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        assert runtime.task_graph is not None
        assert isinstance(runtime.task_graph, TaskGraph)
        assert runtime.task_graph.task_count == 13

    def test_task_bridge_created(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        assert runtime._task_bridge is not None
        assert isinstance(runtime._task_bridge, TaskGraphHookBridge)

    def test_get_health_includes_task_graph(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        health = runtime.get_health()
        assert "task_graph" in health
        assert health["task_graph"]["total"] == 13
        assert health["task_graph"]["is_complete"] is False

    def test_get_task_status_summary(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        status = runtime.get_task_status()
        assert status["total_tasks"] == 13
        assert status["is_complete"] is False

    def test_get_task_status_single(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        status = runtime.get_task_status("berserk_router")
        assert status["task_id"] == "berserk_router"
        assert status["status"] == "pending"

    def test_get_task_status_missing(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        status = runtime.get_task_status("nonexistent")
        assert "error" in status

    def test_reset_task_graph(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        old_graph = runtime.task_graph
        # Simulate some progress
        runtime.hooks.trigger(HookEvent.NODE_ENTER, {"node": "router", "ip_name": "berserk"})
        assert runtime.task_graph.get_task("berserk_router").status.value == "running"

        # Reset — old handlers should be unregistered
        runtime.reset_task_graph()
        assert runtime.task_graph is not old_graph
        assert runtime.task_graph.get_task("berserk_router").status.value == "pending"
        assert runtime.task_graph.task_count == 13

        # Verify no duplicate handlers: trigger event → only new graph updates
        runtime.hooks.trigger(HookEvent.NODE_ENTER, {"node": "router", "ip_name": "berserk"})
        assert runtime.task_graph.get_task("berserk_router").status.value == "running"
        # Old graph should NOT have been updated again (it was already running)
        assert old_graph.get_task("berserk_router").status.value == "running"

    def test_hook_events_update_task_graph(self, tmp_path: Path):
        runtime = GeodeRuntime.create("Berserk", log_dir=tmp_path)
        runtime.hooks.trigger(HookEvent.NODE_ENTER, {"node": "router", "ip_name": "berserk"})
        runtime.hooks.trigger(HookEvent.NODE_EXIT, {"node": "router", "ip_name": "berserk"})
        assert runtime.task_graph.get_task("berserk_router").status.value == "completed"
