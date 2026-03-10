"""Tests for TaskSystem — dependency-aware task graph execution."""

from __future__ import annotations

import pytest
from core.orchestration.task_system import (
    Task,
    TaskGraph,
    TaskStatus,
    create_ip_analysis_graph,
)


class TestTask:
    def test_default_status_is_pending(self):
        task = Task(task_id="t1", name="Test")
        assert task.status == TaskStatus.PENDING
        assert task.dependencies == []
        assert task.result is None

    def test_elapsed_none_when_not_started(self):
        task = Task(task_id="t1", name="Test")
        assert task.elapsed_s is None

    def test_is_terminal(self):
        task = Task(task_id="t1", name="Test")
        assert task.is_terminal is False

        task.status = TaskStatus.COMPLETED
        assert task.is_terminal is True

        task.status = TaskStatus.FAILED
        assert task.is_terminal is True

        task.status = TaskStatus.SKIPPED
        assert task.is_terminal is True


class TestTaskGraph:
    def test_add_and_get_task(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="t1", name="Test"))
        assert graph.task_count == 1
        assert graph.get_task("t1") is not None
        assert graph.get_task("nonexistent") is None

    def test_add_duplicate_raises(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="t1", name="Test"))
        with pytest.raises(ValueError, match="t1"):
            graph.add_task(Task(task_id="t1", name="Duplicate"))

    def test_get_ready_tasks_no_deps(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A"))
        graph.add_task(Task(task_id="b", name="B"))
        ready = graph.get_ready_tasks()
        assert len(ready) == 2

    def test_get_ready_tasks_with_deps(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A"))
        graph.add_task(Task(task_id="b", name="B", dependencies=["a"]))

        ready = graph.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == "a"

    def test_mark_running_and_completed(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="t1", name="Test"))
        graph.get_ready_tasks()  # Move to READY

        graph.mark_running("t1")
        assert graph.get_task("t1").status == TaskStatus.RUNNING
        assert graph.stats.started == 1

        graph.mark_completed("t1", result={"output": 42})
        task = graph.get_task("t1")
        assert task.status == TaskStatus.COMPLETED
        assert task.result == {"output": 42}
        assert task.elapsed_s is not None
        assert graph.stats.completed == 1

    def test_mark_failed(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="t1", name="Test"))
        graph.get_ready_tasks()
        graph.mark_running("t1")
        graph.mark_failed("t1", error="boom")

        task = graph.get_task("t1")
        assert task.status == TaskStatus.FAILED
        assert task.error == "boom"
        assert graph.stats.failed == 1

    def test_dependency_chain_execution(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A"))
        graph.add_task(Task(task_id="b", name="B", dependencies=["a"]))
        graph.add_task(Task(task_id="c", name="C", dependencies=["b"]))

        # Only 'a' is ready
        ready = graph.get_ready_tasks()
        assert [t.task_id for t in ready] == ["a"]

        graph.mark_running("a")
        graph.mark_completed("a")

        # Now 'b' is ready
        ready = graph.get_ready_tasks()
        assert [t.task_id for t in ready] == ["b"]

        graph.mark_running("b")
        graph.mark_completed("b")

        # Now 'c' is ready
        ready = graph.get_ready_tasks()
        assert [t.task_id for t in ready] == ["c"]

    def test_parallel_tasks_ready_together(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="root", name="Root"))
        graph.add_task(Task(task_id="a", name="A", dependencies=["root"]))
        graph.add_task(Task(task_id="b", name="B", dependencies=["root"]))
        graph.add_task(Task(task_id="c", name="C", dependencies=["root"]))

        ready = graph.get_ready_tasks()
        assert [t.task_id for t in ready] == ["root"]

        graph.mark_running("root")
        graph.mark_completed("root")

        ready = graph.get_ready_tasks()
        assert sorted(t.task_id for t in ready) == ["a", "b", "c"]

    def test_propagate_failure(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A"))
        graph.add_task(Task(task_id="b", name="B", dependencies=["a"]))
        graph.add_task(Task(task_id="c", name="C", dependencies=["b"]))

        graph.get_ready_tasks()
        graph.mark_running("a")
        graph.mark_failed("a", error="crash")

        skipped = graph.propagate_failure("a")
        assert "b" in skipped
        assert "c" in skipped
        assert graph.get_task("b").status == TaskStatus.SKIPPED
        assert graph.get_task("c").status == TaskStatus.SKIPPED

    def test_is_complete(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A"))
        graph.add_task(Task(task_id="b", name="B", dependencies=["a"]))

        assert graph.is_complete() is False

        graph.get_ready_tasks()
        graph.mark_running("a")
        graph.mark_completed("a")
        graph.get_ready_tasks()
        graph.mark_running("b")
        graph.mark_completed("b")

        assert graph.is_complete() is True

    def test_execution_summary(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A"))
        graph.get_ready_tasks()
        graph.mark_running("a")
        graph.mark_completed("a")

        summary = graph.execution_summary()
        assert summary["total_tasks"] == 1
        assert summary["is_complete"] is True
        assert summary["by_status"]["completed"] == 1
        assert "a" in summary["tasks"]

    def test_topological_order(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A"))
        graph.add_task(Task(task_id="b", name="B", dependencies=["a"]))
        graph.add_task(Task(task_id="c", name="C", dependencies=["a"]))
        graph.add_task(Task(task_id="d", name="D", dependencies=["b", "c"]))

        batches = graph.topological_order()
        assert len(batches) == 3
        assert batches[0] == ["a"]
        assert sorted(batches[1]) == ["b", "c"]
        assert batches[2] == ["d"]

    def test_validate_missing_dependency(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A", dependencies=["missing"]))
        errors = graph.validate()
        assert len(errors) >= 1
        assert "missing" in errors[0]

    def test_validate_clean_graph(self):
        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A"))
        graph.add_task(Task(task_id="b", name="B", dependencies=["a"]))
        errors = graph.validate()
        assert errors == []

    def test_mark_nonexistent_raises(self):
        graph = TaskGraph()
        with pytest.raises(KeyError):
            graph.mark_running("nope")

    def test_stats_to_dict(self):
        graph = TaskGraph()
        d = graph.stats.to_dict()
        assert set(d.keys()) == {"started", "completed", "failed", "skipped"}


class TestCreateIPAnalysisGraph:
    def test_creates_13_tasks(self):
        graph = create_ip_analysis_graph("Berserk")
        assert graph.task_count == 13

    def test_valid_graph(self):
        graph = create_ip_analysis_graph("Berserk")
        errors = graph.validate()
        assert errors == []

    def test_initial_ready_task(self):
        graph = create_ip_analysis_graph("Berserk")
        ready = graph.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == "berserk_router"

    def test_analysts_parallel_after_signals(self):
        graph = create_ip_analysis_graph("Berserk")

        # Complete router
        graph.get_ready_tasks()
        graph.mark_running("berserk_router")
        graph.mark_completed("berserk_router")

        # Complete signals
        ready = graph.get_ready_tasks()
        assert len(ready) == 1
        graph.mark_running("berserk_signals")
        graph.mark_completed("berserk_signals")

        # 4 analysts should be ready in parallel
        ready = graph.get_ready_tasks()
        assert len(ready) == 4
        names = sorted(t.task_id for t in ready)
        assert "berserk_analyst_community" in names
        assert "berserk_analyst_creative" in names
        assert "berserk_analyst_market" in names
        assert "berserk_analyst_technical" in names

    def test_prefix_from_ip_name(self):
        graph = create_ip_analysis_graph("One Piece")
        task = graph.get_task("one_piece_router")
        assert task is not None
        assert task.name == "Route + load IP data"
