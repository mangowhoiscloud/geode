"""Sub-agent runtime hooks and public timeline announcements."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from core.agent.cognitive_state_ctx import get_session_id, get_turn_id
from core.agent.subagent_protocol import SubagentRunRecord, SubResult, SubTask
from core.hooks import HookCorrelation, HookName, HookRegistry, RuntimeEvent, RuntimeEventBus
from core.memory.session_key import build_subagent_session_key

if TYPE_CHECKING:
    from core.observability.run_event import RunEventSinkProvider

log = logging.getLogger(__name__)


@dataclass(slots=True)
class SubagentAnnouncements:
    """Publish one consistent start/stop projection for child execution."""

    runtime_events: RuntimeEventBus | None
    public_hooks: HookRegistry | None
    activity_sink_provider: RunEventSinkProvider | None
    parent_session_key: str

    def new_run_record(self, task: SubTask) -> SubagentRunRecord:
        return SubagentRunRecord(
            run_id=uuid4().hex[:12],
            task_id=task.task_id,
            child_session_key=build_subagent_session_key(
                task.args.get("subject_id", task.args.get("subject", "unknown")),
                task.task_id,
            ),
            parent_session_key=self.parent_session_key or get_session_id(),
        )

    async def emit_runtime(
        self,
        event: RuntimeEvent,
        task: SubTask,
        *,
        result: SubResult | None = None,
        error: str | None = None,
    ) -> None:
        if self.runtime_events is None:
            return
        data: dict[str, object] = {
            "source": "sub_agent",
            "task_id": task.task_id,
            "task_type": task.task_type,
            "description": task.description,
        }
        try:
            sink = self.activity_sink_provider() if self.activity_sink_provider else None
        except Exception:
            sink = None
        data["component"] = sink.component if sink is not None else "agentic_loop"
        if result is not None:
            data.update(
                duration_ms=result.duration_ms,
                success=result.success,
                status="completed" if result.success else "failed",
            )
            if event == RuntimeEvent.SUBAGENT_COMPLETED:
                summary = result.output.get("summary", "") if result.output else ""
                data["summary"] = summary or (str(result.output)[:200] if result.output else "")
        if error is not None:
            data["error"] = error
        try:
            await self.runtime_events.trigger_async(event, data)
        except Exception:
            log.warning(
                "Hook trigger failed for %s on task %s",
                event.value,
                task.task_id,
                exc_info=True,
            )

    async def emit_start(
        self, task: SubTask, record: SubagentRunRecord, *, generation: int
    ) -> None:
        from core.observability.session_timeline import current_session_timeline

        timeline = current_session_timeline()
        if timeline is not None:
            timeline.record_subagent_start(
                task.task_id,
                task.task_type,
                child_session_key=record.child_session_key,
                run_id=record.run_id,
            )
        if self.public_hooks is None:
            return
        await self.public_hooks.invoke(
            HookName.SUBAGENT_START,
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "description": task.description,
                "child_session_key": record.child_session_key,
                "parent_session_key": record.parent_session_key,
                "generation": generation,
            },
            correlation=HookCorrelation(
                session_id=get_session_id(),
                turn_id=get_turn_id(),
                run_id=record.run_id,
            ),
        )

    async def emit_stop(
        self,
        task: SubTask,
        result: SubResult,
        record: SubagentRunRecord,
        *,
        generation: int,
        interrupted: bool,
    ) -> None:
        status = "interrupted" if interrupted else ("completed" if result.success else "failed")
        from core.observability.session_timeline import current_session_timeline

        timeline = current_session_timeline()
        if timeline is not None:
            summary = (
                str(result.output.get("summary", ""))
                if isinstance(result.output, dict)
                else str(result.output or "")
            )
            timeline.record_subagent_complete(
                task.task_id,
                status,
                summary[:500],
                child_session_key=record.child_session_key,
                run_id=record.run_id,
            )
        if self.public_hooks is None:
            return
        await self.public_hooks.invoke(
            HookName.SUBAGENT_STOP,
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "success": result.success and not interrupted,
                "status": status,
                "duration_ms": result.duration_ms,
                "error": "Interrupted by parent" if interrupted else (result.error or ""),
                "child_session_key": record.child_session_key,
                "generation": generation,
            },
            correlation=HookCorrelation(
                session_id=get_session_id(),
                turn_id=get_turn_id(),
                run_id=record.run_id,
            ),
        )


__all__ = ["SubagentAnnouncements"]
