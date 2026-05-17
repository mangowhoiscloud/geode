import pytest
from core.orchestration.task_system import Task, TaskGraph


def test_task_lifecycle_and_summary() -> None:
    graph = TaskGraph()
    graph.add_task(Task("a", "A"))
    graph.add_task(Task("b", "B", dependencies=["a"]))

    assert [task.task_id for task in graph.get_ready_tasks()] == ["a"]
    graph.mark_running("a")
    graph.mark_completed("a", result={"ok": True})
    assert graph.get_task("a").result == {"ok": True}
    assert [task.task_id for task in graph.get_ready_tasks()] == ["b"]

    graph.mark_running("b")
    graph.mark_completed("b")
    summary = graph.execution_summary()

    assert summary["is_complete"] is True
    assert summary["by_status"] == {"completed": 2}
    assert graph.stats.to_dict()["completed"] == 2


def test_failure_propagates_to_downstream_tasks() -> None:
    graph = TaskGraph()
    graph.add_task(Task("root", "Root"))
    graph.add_task(Task("child", "Child", dependencies=["root"]))
    graph.add_task(Task("grandchild", "Grandchild", dependencies=["child"]))

    graph.mark_failed("root", error="boom")
    skipped = graph.propagate_failure("root")

    assert skipped == ["child", "grandchild"]
    assert graph.is_blocked("child") is True
    assert graph.has_failed_dependency("child", "child") is True


def test_topological_order_validation_and_errors() -> None:
    graph = TaskGraph()
    graph.add_task(Task("a", "A", dependencies=["missing"]))

    assert graph.validate() == ["Task 'a' depends on 'missing' which does not exist"]
    with pytest.raises(ValueError):
        graph.topological_order(strict=True)

    cycle = TaskGraph()
    cycle.add_task(Task("a", "A", dependencies=["b"]))
    cycle.add_task(Task("b", "B", dependencies=["a"]))
    assert any("Cycle detected" in error for error in cycle.validate())


def test_invalid_transitions_raise() -> None:
    graph = TaskGraph()
    graph.add_task(Task("a", "A"))

    with pytest.raises(ValueError):
        graph.add_task(Task("a", "Duplicate"))
    with pytest.raises(ValueError):
        graph.mark_completed("a")
    with pytest.raises(KeyError):
        graph.mark_running("missing")
