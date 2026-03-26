"""Tests that all concrete implementations satisfy their Port protocols.

Verifies Clean Architecture compliance: every concrete class used in
GeodeRuntime is isinstance-checkable against its corresponding Port.
"""

from __future__ import annotations

from core.infrastructure.ports.auth_port import (
    CooldownTrackerPort,
    ProfileRotatorPort,
    ProfileStorePort,
)
from core.infrastructure.ports.automation_port import (
    CorrelationAnalyzerPort,
    DriftDetectorPort,
    ExpertPanelPort,
    FeedbackLoopPort,
    ModelRegistryPort,
    OutcomeTrackerPort,
    SnapshotManagerPort,
    TriggerManagerPort,
)
from core.infrastructure.ports.orchestration_port import (
    CoalescingQueuePort,
    ConfigWatcherPort,
    LaneQueuePort,
    RunLogPort,
    StuckDetectorPort,
    TaskGraphPort,
)
from core.llm.router import LLMClientPort
from core.memory.port import (
    OrganizationMemoryPort,
    ProjectMemoryPort,
    SessionStorePort,
)
from core.orchestration.hook_port import HookSystemPort
from core.tools.port import (
    PolicyChainPort,
    ToolRegistryPort,
)


class TestToolPortCompliance:
    def test_tool_registry_satisfies_port(self):
        from core.tools.registry import ToolRegistry

        assert isinstance(ToolRegistry(), ToolRegistryPort)

    def test_policy_chain_satisfies_port(self):
        from core.tools.policy import PolicyChain

        assert isinstance(PolicyChain(), PolicyChainPort)


class TestOrchestrationPortCompliance:
    def test_run_log_satisfies_port(self):
        from core.orchestration.run_log import RunLog

        assert isinstance(RunLog("test"), RunLogPort)

    def test_coalescing_queue_satisfies_port(self):
        from core.orchestration.coalescing import CoalescingQueue

        assert isinstance(CoalescingQueue(), CoalescingQueuePort)

    def test_config_watcher_satisfies_port(self):
        from core.orchestration.hot_reload import ConfigWatcher

        assert isinstance(ConfigWatcher(), ConfigWatcherPort)

    def test_lane_queue_satisfies_port(self):
        from core.orchestration.lane_queue import LaneQueue

        assert isinstance(LaneQueue(), LaneQueuePort)

    def test_stuck_detector_satisfies_port(self):
        from core.orchestration.stuck_detection import StuckDetector

        assert isinstance(StuckDetector(), StuckDetectorPort)

    def test_task_graph_satisfies_port(self):
        from core.orchestration.task_system import TaskGraph

        assert isinstance(TaskGraph(), TaskGraphPort)


class TestAuthPortCompliance:
    def test_profile_store_satisfies_port(self):
        from core.gateway.auth.profiles import ProfileStore

        assert isinstance(ProfileStore(), ProfileStorePort)

    def test_profile_rotator_satisfies_port(self):
        from core.gateway.auth.profiles import ProfileStore
        from core.gateway.auth.rotation import ProfileRotator

        assert isinstance(ProfileRotator(ProfileStore()), ProfileRotatorPort)

    def test_cooldown_tracker_satisfies_port(self):
        from core.gateway.auth.cooldown import CooldownTracker

        assert isinstance(CooldownTracker(), CooldownTrackerPort)


class TestAutomationPortCompliance:
    def test_cusum_detector_satisfies_port(self):
        from core.automation.drift import CUSUMDetector

        assert isinstance(CUSUMDetector(), DriftDetectorPort)

    def test_model_registry_satisfies_port(self):
        from core.automation.model_registry import ModelRegistry

        assert isinstance(ModelRegistry(), ModelRegistryPort)

    def test_expert_panel_satisfies_port(self):
        from core.automation.expert_panel import ExpertPanel

        assert isinstance(ExpertPanel(), ExpertPanelPort)

    def test_correlation_analyzer_satisfies_port(self):
        from core.automation.correlation import CorrelationAnalyzer

        assert isinstance(CorrelationAnalyzer(), CorrelationAnalyzerPort)

    def test_outcome_tracker_satisfies_port(self):
        from core.automation.outcome_tracking import OutcomeTracker

        assert isinstance(OutcomeTracker(), OutcomeTrackerPort)

    def test_snapshot_manager_satisfies_port(self):
        from core.automation.snapshot import SnapshotManager

        assert isinstance(SnapshotManager(), SnapshotManagerPort)

    def test_trigger_manager_satisfies_port(self):
        from core.automation.triggers import TriggerManager

        assert isinstance(TriggerManager(), TriggerManagerPort)

    def test_feedback_loop_satisfies_port(self):
        from core.automation.feedback_loop import FeedbackLoop

        assert isinstance(FeedbackLoop(), FeedbackLoopPort)


class TestExistingPortCompliance:
    """Verify already-ported modules still pass."""

    def test_hook_system_satisfies_port(self):
        from core.orchestration.hooks import HookSystem

        assert isinstance(HookSystem(), HookSystemPort)

    def test_in_memory_session_store_satisfies_port(self):
        from core.memory.session import InMemorySessionStore

        assert isinstance(InMemorySessionStore(), SessionStorePort)

    def test_project_memory_satisfies_port(self):
        from core.memory.project import ProjectMemory

        assert isinstance(ProjectMemory(), ProjectMemoryPort)

    def test_organization_memory_satisfies_port(self):
        from core.memory.organization import MonoLakeOrganizationMemory

        assert isinstance(MonoLakeOrganizationMemory(), OrganizationMemoryPort)

    def test_claude_adapter_satisfies_port(self):
        from core.llm.router import ClaudeAdapter

        assert isinstance(ClaudeAdapter(), LLMClientPort)
