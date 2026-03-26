"""Unit tests for task management tool handlers.

Tests task_create / task_update / task_get / task_list / task_stop handlers
via _build_task_handlers() without touching the IP analysis pipeline.
"""

from __future__ import annotations

import pytest
from core.cli.tool_handlers import _build_task_handlers


@pytest.fixture()
def handlers():
    """Fresh handler map with isolated TaskGraph per test."""
    # Reset user task graph for isolation
    from core.cli import _reset_user_task_graph

    _reset_user_task_graph()
    return _build_task_handlers()


# ---------------------------------------------------------------------------
# task_create
# ---------------------------------------------------------------------------


class TestTaskCreate:
    def test_creates_task_returns_task_id(self, handlers):
        result = handlers["task_create"](subject="Analyze Berserk")
        assert result["status"] == "ok"
        assert result["action"] == "created"
        assert result["task_id"].startswith("t_")
        assert result["subject"] == "Analyze Berserk"

    def test_missing_subject_returns_clarification(self, handlers):
        result = handlers["task_create"]()
        assert result.get("clarification_needed") is True
        assert "subject" in result["missing"]

    def test_description_stored_in_metadata(self, handlers):
        result = handlers["task_create"](subject="Run analysis", description="detailed desc")
        task_id = result["task_id"]
        detail = handlers["task_get"](task_id=task_id)
        assert detail["description"] == "detailed desc"

    def test_metadata_stored(self, handlers):
        result = handlers["task_create"](subject="Step 1", metadata={"priority": "P0"})
        task_id = result["task_id"]
        detail = handlers["task_get"](task_id=task_id)
        assert detail["metadata"]["priority"] == "P0"


# ---------------------------------------------------------------------------
# task_update
# ---------------------------------------------------------------------------


class TestTaskUpdate:
    def _create(self, handlers, subject="Test task"):
        return handlers["task_create"](subject=subject)["task_id"]

    def test_status_pending_to_in_progress(self, handlers):
        task_id = self._create(handlers)
        result = handlers["task_update"](task_id=task_id, status="in_progress")
        assert result["status"] == "ok"
        detail = handlers["task_get"](task_id=task_id)
        assert detail["task_status"] == "in_progress"

    def test_status_in_progress_to_completed(self, handlers):
        task_id = self._create(handlers)
        handlers["task_update"](task_id=task_id, status="in_progress")
        result = handlers["task_update"](task_id=task_id, status="completed")
        assert result["status"] == "ok"
        detail = handlers["task_get"](task_id=task_id)
        assert detail["task_status"] == "completed"

    def test_update_subject(self, handlers):
        task_id = self._create(handlers, subject="Old title")
        handlers["task_update"](task_id=task_id, subject="New title")
        detail = handlers["task_get"](task_id=task_id)
        assert detail["subject"] == "New title"

    def test_update_owner(self, handlers):
        task_id = self._create(handlers)
        handlers["task_update"](task_id=task_id, owner="subagent-1")
        detail = handlers["task_get"](task_id=task_id)
        assert detail["owner"] == "subagent-1"

    def test_missing_task_id_clarification(self, handlers):
        result = handlers["task_update"]()
        assert result.get("clarification_needed") is True

    def test_nonexistent_task_returns_error(self, handlers):
        result = handlers["task_update"](task_id="t_999999")
        assert "error" in result

    def test_invalid_status_transition_returns_error(self, handlers):
        task_id = self._create(handlers)
        # Cannot go directly pending → completed (must be running first)
        result = handlers["task_update"](task_id=task_id, status="completed")
        assert "error" in result

    def test_metadata_merge(self, handlers):
        task_id = self._create(handlers, subject="Meta test")
        handlers["task_update"](task_id=task_id, metadata={"key1": "v1"})
        handlers["task_update"](task_id=task_id, metadata={"key2": "v2"})
        detail = handlers["task_get"](task_id=task_id)
        assert detail["metadata"]["key1"] == "v1"
        assert detail["metadata"]["key2"] == "v2"

    def test_metadata_delete_with_none(self, handlers):
        task_id = self._create(handlers, subject="Delete meta")
        handlers["task_update"](task_id=task_id, metadata={"to_remove": "val"})
        handlers["task_update"](task_id=task_id, metadata={"to_remove": None})
        detail = handlers["task_get"](task_id=task_id)
        assert "to_remove" not in detail["metadata"]


# ---------------------------------------------------------------------------
# task_get
# ---------------------------------------------------------------------------


class TestTaskGet:
    def test_get_existing_task(self, handlers):
        task_id = handlers["task_create"](subject="Get me")["task_id"]
        result = handlers["task_get"](task_id=task_id)
        assert result["status"] == "ok"
        assert result["task_id"] == task_id
        assert result["subject"] == "Get me"
        assert result.get("status_field", True)
        assert "elapsed_s" in result

    def test_get_nonexistent_returns_error(self, handlers):
        result = handlers["task_get"](task_id="t_does_not_exist")
        assert "error" in result

    def test_missing_task_id_clarification(self, handlers):
        result = handlers["task_get"]()
        assert result.get("clarification_needed") is True


# ---------------------------------------------------------------------------
# task_list
# ---------------------------------------------------------------------------


class TestTaskList:
    def test_empty_list(self, handlers):
        result = handlers["task_list"]()
        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["tasks"] == []

    def test_lists_created_tasks(self, handlers):
        handlers["task_create"](subject="Task A")
        handlers["task_create"](subject="Task B")
        result = handlers["task_list"]()
        assert result["count"] == 2
        subjects = {t["subject"] for t in result["tasks"]}
        assert subjects == {"Task A", "Task B"}

    def test_status_filter_pending(self, handlers):
        t1 = handlers["task_create"](subject="Pending")["task_id"]
        t2 = handlers["task_create"](subject="Running")["task_id"]
        handlers["task_update"](task_id=t2, status="in_progress")
        result = handlers["task_list"](status_filter="pending")
        assert result["count"] == 1
        assert result["tasks"][0]["task_id"] == t1

    def test_status_filter_in_progress(self, handlers):
        t1 = handlers["task_create"](subject="Task")["task_id"]
        handlers["task_update"](task_id=t1, status="in_progress")
        result = handlers["task_list"](status_filter="in_progress")
        assert result["count"] == 1

    def test_in_progress_sorted_first(self, handlers):
        handlers["task_create"](subject="Pending task")
        t2 = handlers["task_create"](subject="Running task")["task_id"]
        handlers["task_update"](task_id=t2, status="in_progress")
        result = handlers["task_list"]()
        assert result["tasks"][0]["task_status"] == "in_progress"


# ---------------------------------------------------------------------------
# task_stop
# ---------------------------------------------------------------------------


class TestTaskStop:
    def test_stop_running_task(self, handlers):
        task_id = handlers["task_create"](subject="Stoppable")["task_id"]
        handlers["task_update"](task_id=task_id, status="in_progress")
        result = handlers["task_stop"](task_id=task_id, reason="user cancelled")
        assert result["status"] == "ok"
        assert result["action"] == "stopped"
        assert result["reason"] == "user cancelled"
        detail = handlers["task_get"](task_id=task_id)
        assert detail["task_status"] == "failed"

    def test_stop_pending_task(self, handlers):
        task_id = handlers["task_create"](subject="Pending stop")["task_id"]
        result = handlers["task_stop"](task_id=task_id)
        assert result["status"] == "ok"
        detail = handlers["task_get"](task_id=task_id)
        assert detail["task_status"] == "failed"

    def test_stop_nonexistent_returns_error(self, handlers):
        result = handlers["task_stop"](task_id="t_ghost")
        assert "error" in result

    def test_missing_task_id_clarification(self, handlers):
        result = handlers["task_stop"]()
        assert result.get("clarification_needed") is True
