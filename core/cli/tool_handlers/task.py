"""User-facing task management handlers (task_create/update/get/list/stop)."""

from __future__ import annotations

from typing import Any

from core.cli.tool_handlers.clarification import _clarify


def _build_task_handlers() -> dict[str, Any]:
    """Build user-facing task management handlers (task_create/update/get/list/stop)."""
    import uuid

    from core.cli.session_state import _get_user_task_graph
    from core.orchestration.task_system import Task, TaskStatus

    def _status_to_internal(status: str) -> TaskStatus:
        return {
            "pending": TaskStatus.PENDING,
            "in_progress": TaskStatus.RUNNING,
            "completed": TaskStatus.COMPLETED,
            "failed": TaskStatus.FAILED,
        }.get(status, TaskStatus.PENDING)

    def _status_to_external(status: TaskStatus) -> str:
        return {
            TaskStatus.PENDING: "pending",
            TaskStatus.READY: "pending",
            TaskStatus.RUNNING: "in_progress",
            TaskStatus.COMPLETED: "completed",
            TaskStatus.FAILED: "failed",
            TaskStatus.SKIPPED: "failed",
        }.get(status, "pending")

    def _task_to_dict(task: Task, detail: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "task_id": task.task_id,
            "subject": task.name,
            "task_status": _status_to_external(task.status),
            "owner": task.metadata.get("owner", ""),
        }
        if detail:
            out["description"] = task.metadata.get("description", "")
            out["elapsed_s"] = task.elapsed_s
            out["metadata"] = {
                k: v for k, v in task.metadata.items() if k not in ("owner", "description")
            }
            if task.error:
                out["error"] = task.error
        return out

    def handle_task_create(**kwargs: Any) -> dict[str, Any]:
        subject = kwargs.get("subject", "")
        if not subject:
            return _clarify("task_create", ["subject"], "작업 제목을 알려주세요.")
        graph = _get_user_task_graph()
        task_id = f"t_{uuid.uuid4().hex[:8]}"
        metadata: dict[str, Any] = dict(kwargs.get("metadata") or {})
        if desc := kwargs.get("description"):
            metadata["description"] = desc
        task = Task(task_id=task_id, name=subject, metadata=metadata)
        graph.add_task(task)
        return {"status": "ok", "action": "created", "task_id": task_id, "subject": subject}

    def handle_task_update(**kwargs: Any) -> dict[str, Any]:
        task_id = kwargs.get("task_id", "")
        if not task_id:
            return _clarify("task_update", ["task_id"], "변경할 task_id를 알려주세요.")
        graph = _get_user_task_graph()
        task = graph.get_task(task_id)
        if task is None:
            return {"error": f"Task '{task_id}' not found"}
        if new_subject := kwargs.get("subject"):
            task.name = new_subject
        if owner := kwargs.get("owner"):
            task.metadata["owner"] = owner
        if desc := kwargs.get("description"):
            task.metadata["description"] = desc
        if extra_meta := kwargs.get("metadata"):
            for k, v in extra_meta.items():
                if v is None:
                    task.metadata.pop(k, None)
                else:
                    task.metadata[k] = v
        if new_status := kwargs.get("status"):
            try:
                if new_status == "in_progress":
                    graph.mark_running(task_id)
                elif new_status == "completed":
                    graph.mark_completed(task_id)
                elif new_status == "failed":
                    graph.mark_failed(task_id, error="manually failed")
            except ValueError as exc:
                return {"error": str(exc)}
        return {"status": "ok", "action": "updated", **_task_to_dict(task)}

    def handle_task_get(**kwargs: Any) -> dict[str, Any]:
        task_id = kwargs.get("task_id", "")
        if not task_id:
            return _clarify("task_get", ["task_id"], "조회할 task_id를 알려주세요.")
        graph = _get_user_task_graph()
        task = graph.get_task(task_id)
        if task is None:
            return {"error": f"Task '{task_id}' not found"}
        return {"status": "ok", **_task_to_dict(task, detail=True)}

    def handle_task_list(**kwargs: Any) -> dict[str, Any]:
        graph = _get_user_task_graph()
        status_filter = kwargs.get("status_filter", "all")
        tasks = list(graph._tasks.values())
        if status_filter != "all":
            target = _status_to_internal(status_filter)
            # pending filter includes READY
            if status_filter == "pending":
                tasks = [t for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.READY)]
            else:
                tasks = [t for t in tasks if t.status == target]
        # Sort: in_progress first, then pending, then completed/failed
        order = {"in_progress": 0, "pending": 1, "completed": 2, "failed": 3}
        tasks.sort(key=lambda t: order.get(_status_to_external(t.status), 9))
        return {
            "status": "ok",
            "count": len(tasks),
            "tasks": [_task_to_dict(t) for t in tasks],
        }

    def handle_task_stop(**kwargs: Any) -> dict[str, Any]:
        task_id = kwargs.get("task_id", "")
        if not task_id:
            return _clarify("task_stop", ["task_id"], "취소할 task_id를 알려주세요.")
        graph = _get_user_task_graph()
        task = graph.get_task(task_id)
        if task is None:
            return {"error": f"Task '{task_id}' not found"}
        reason = kwargs.get("reason", "stopped")
        try:
            graph.mark_failed(task_id, error=reason)
            graph.propagate_failure(task_id)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"status": "ok", "action": "stopped", "task_id": task_id, "reason": reason}

    return {
        "task_create": handle_task_create,
        "task_update": handle_task_update,
        "task_get": handle_task_get,
        "task_list": handle_task_list,
        "task_stop": handle_task_stop,
    }
