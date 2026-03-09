"""Tests that all concrete implementations satisfy their Port protocols.

Verifies Clean Architecture compliance: every concrete class used in
GeodeRuntime is isinstance-checkable against its corresponding Port.
"""

from __future__ import annotations

from geode.infrastructure.ports.auth_port import (
    CooldownTrackerPort,
    ProfileRotatorPort,
    ProfileStorePort,
)
from geode.infrastructure.ports.automation_port import (
    CorrelationAnalyzerPort,
    DriftDetectorPort,
    ExpertPanelPort,
    FeedbackLoopPort,
    ModelRegistryPort,
    OutcomeTrackerPort,
    SnapshotManagerPort,
    TriggerManagerPort,
)
from geode.infrastructure.ports.hook_port import HookSystemPort
from geode.infrastructure.ports.llm_port import LLMClientPort
from geode.infrastructure.ports.memory_port import (
    OrganizationMemoryPort,
    ProjectMemoryPort,
    SessionStorePort,
)
from geode.infrastructure.ports.orchestration_port import (
    CoalescingQueuePort,
    ConfigWatcherPort,
    LaneQueuePort,
    RunLogPort,
    StuckDetectorPort,
    TaskGraphPort,
)
from geode.infrastructure.ports.tool_port import (
    PolicyChainPort,
    ToolRegistryPort,
)


class TestToolPortCompliance:
    def test_tool_registry_satisfies_port(self):
        from geode.tools.registry import ToolRegistry

        assert isinstance(ToolRegistry(), ToolRegistryPort)

    def test_policy_chain_satisfies_port(self):
        from geode.tools.policy import PolicyChain

        assert isinstance(PolicyChain(), PolicyChainPort)


class TestOrchestrationPortCompliance:
    def test_run_log_satisfies_port(self):
        from geode.orchestration.run_log import RunLog

        assert isinstance(RunLog("test"), RunLogPort)

    def test_coalescing_queue_satisfies_port(self):
        from geode.orchestration.coalescing import CoalescingQueue

        assert isinstance(CoalescingQueue(), CoalescingQueuePort)

    def test_config_watcher_satisfies_port(self):
        from geode.orchestration.hot_reload import ConfigWatcher

        assert isinstance(ConfigWatcher(), ConfigWatcherPort)

    def test_lane_queue_satisfies_port(self):
        from geode.orchestration.lane_queue import LaneQueue

        assert isinstance(LaneQueue(), LaneQueuePort)

    def test_stuck_detector_satisfies_port(self):
        from geode.orchestration.stuck_detection import StuckDetector

        assert isinstance(StuckDetector(), StuckDetectorPort)

    def test_task_graph_satisfies_port(self):
        from geode.orchestration.task_system import TaskGraph

        assert isinstance(TaskGraph(), TaskGraphPort)


class TestAuthPortCompliance:
    def test_profile_store_satisfies_port(self):
        from geode.auth.profiles import ProfileStore

        assert isinstance(ProfileStore(), ProfileStorePort)

    def test_profile_rotator_satisfies_port(self):
        from geode.auth.profiles import ProfileStore
        from geode.auth.rotation import ProfileRotator

        assert isinstance(ProfileRotator(ProfileStore()), ProfileRotatorPort)

    def test_cooldown_tracker_satisfies_port(self):
        from geode.auth.cooldown import CooldownTracker

        assert isinstance(CooldownTracker(), CooldownTrackerPort)


class TestAutomationPortCompliance:
    def test_cusum_detector_satisfies_port(self):
        from geode.automation.drift import CUSUMDetector

        assert isinstance(CUSUMDetector(), DriftDetectorPort)

    def test_model_registry_satisfies_port(self):
        from geode.automation.model_registry import ModelRegistry

        assert isinstance(ModelRegistry(), ModelRegistryPort)

    def test_expert_panel_satisfies_port(self):
        from geode.automation.expert_panel import ExpertPanel

        assert isinstance(ExpertPanel(), ExpertPanelPort)

    def test_correlation_analyzer_satisfies_port(self):
        from geode.automation.correlation import CorrelationAnalyzer

        assert isinstance(CorrelationAnalyzer(), CorrelationAnalyzerPort)

    def test_outcome_tracker_satisfies_port(self):
        from geode.automation.outcome_tracking import OutcomeTracker

        assert isinstance(OutcomeTracker(), OutcomeTrackerPort)

    def test_snapshot_manager_satisfies_port(self):
        from geode.automation.snapshot import SnapshotManager

        assert isinstance(SnapshotManager(), SnapshotManagerPort)

    def test_trigger_manager_satisfies_port(self):
        from geode.automation.triggers import TriggerManager

        assert isinstance(TriggerManager(), TriggerManagerPort)

    def test_feedback_loop_satisfies_port(self):
        from geode.automation.feedback_loop import FeedbackLoop

        assert isinstance(FeedbackLoop(), FeedbackLoopPort)


class TestExistingPortCompliance:
    """Verify already-ported modules still pass."""

    def test_hook_system_satisfies_port(self):
        from geode.orchestration.hooks import HookSystem

        assert isinstance(HookSystem(), HookSystemPort)

    def test_in_memory_session_store_satisfies_port(self):
        from geode.memory.session import InMemorySessionStore

        assert isinstance(InMemorySessionStore(), SessionStorePort)

    def test_project_memory_satisfies_port(self):
        from geode.memory.project import ProjectMemory

        assert isinstance(ProjectMemory(), ProjectMemoryPort)

    def test_organization_memory_satisfies_port(self):
        from geode.memory.organization import MonoLakeOrganizationMemory

        assert isinstance(MonoLakeOrganizationMemory(), OrganizationMemoryPort)

    def test_claude_adapter_satisfies_port(self):
        from geode.infrastructure.adapters.llm.claude_adapter import ClaudeAdapter

        assert isinstance(ClaudeAdapter(), LLMClientPort)
