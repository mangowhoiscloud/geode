from core.orchestration.task_bridge import TaskGraphHookBridge
from core.orchestration.task_system import Task, TaskGraph, TaskStatus

from core.hooks import HookEvent, HookSystem


def test_bridge_marks_node_enter_exit_complete() -> None:
    graph = TaskGraph()
    graph.add_task(Task("subject_analysis", "Analysis"))
    bridge = TaskGraphHookBridge(graph, subject_prefix="subject")
    hooks = HookSystem()
    bridge.register(hooks)

    hooks.trigger(HookEvent.NODE_ENTERED, {"node": "analysis"})
    assert graph.get_task("subject_analysis").status == TaskStatus.RUNNING

    hooks.trigger(HookEvent.NODE_EXITED, {"node": "analysis"})
    assert graph.get_task("subject_analysis").status == TaskStatus.COMPLETED

    bridge.unregister()
    graph.add_task(Task("subject_synthesis", "Synthesis"))
    hooks.trigger(HookEvent.NODE_ENTERED, {"node": "synthesis"})
    assert graph.get_task("subject_synthesis").status == TaskStatus.PENDING


def test_bridge_error_fails_task_and_skips_dependents() -> None:
    graph = TaskGraph()
    graph.add_task(Task("subject_analysis", "Analysis"))
    graph.add_task(Task("subject_synthesis", "Synthesis", dependencies=["subject_analysis"]))
    bridge = TaskGraphHookBridge(graph, subject_prefix="subject")

    bridge._on_node_error(HookEvent.NODE_ERROR, {"node": "analysis", "error": "boom"})

    assert graph.get_task("subject_analysis").status == TaskStatus.FAILED
    assert graph.get_task("subject_synthesis").status == TaskStatus.SKIPPED


def test_bridge_skips_blocked_task_on_enter() -> None:
    graph = TaskGraph()
    graph.add_task(Task("subject_analysis", "Analysis"))
    graph.add_task(Task("subject_synthesis", "Synthesis", dependencies=["subject_analysis"]))
    graph.mark_failed("subject_analysis", error="boom")
    bridge = TaskGraphHookBridge(graph, subject_prefix="subject")
    data = {"node": "synthesis"}

    bridge._on_node_enter(HookEvent.NODE_ENTERED, data)

    assert data["_skip_node"] is True
    assert graph.get_task("subject_synthesis").status == TaskStatus.SKIPPED
