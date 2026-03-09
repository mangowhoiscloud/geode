"""Trigger Manager — F1-F4 trigger types for pipeline automation.

Supports manual, scheduled (cron), event-driven (HookSystem), and
webhook triggers. Unified dispatch method normalizes all trigger types
into a single pipeline execution flow. Background scheduler runs as
a daemon thread.

Architecture-v6 §4.5 / §12.2: Automation Layer — Trigger Manager & Dispatch.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from geode.automation.snapshot import SnapshotManager
    from geode.infrastructure.ports.hook_port import HookSystemPort

log = logging.getLogger(__name__)


class TriggerType(Enum):
    """Supported trigger types (F1–F4)."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"
    EVENT = "event"
    WEBHOOK = "webhook"


@dataclass
class TriggerConfig:
    """Configuration for a trigger."""

    trigger_id: str
    trigger_type: TriggerType
    name: str = ""
    cron_expr: str = ""  # For SCHEDULED type (minute hour day month weekday)
    event_name: str = ""  # For EVENT type (HookEvent value)
    webhook_path: str = ""  # For WEBHOOK type
    callback: Callable[..., Any] | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TriggerResult:
    """Result from a trigger execution."""

    trigger_id: str
    trigger_type: TriggerType
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    executed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "trigger_type": self.trigger_type.value,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "executed_at": self.executed_at,
        }


# ---------------------------------------------------------------------------
# Minimal cron parser
# ---------------------------------------------------------------------------


class CronParser:
    """Minimal cron expression matcher.

    Format: "minute hour day month weekday"
    Supports: * (any), specific numbers, comma-separated lists.
    """

    @staticmethod
    def matches(cron_expr: str, dt_tuple: tuple[int, int, int, int, int]) -> bool:
        """Check if a datetime tuple matches a cron expression.

        Args:
            cron_expr: Cron string "min hour day month weekday".
            dt_tuple: (minute, hour, day, month, weekday) where weekday 0=Mon.

        Returns:
            True if the cron expression matches the given time.
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: '{cron_expr}' (need 5 fields)")

        for field_val, cron_field in zip(dt_tuple, parts, strict=True):
            if cron_field == "*":
                continue
            allowed: set[int] = set()
            for token in cron_field.split(","):
                token = token.strip()
                if "-" in token:
                    lo, hi = token.split("-", 1)
                    allowed.update(range(int(lo), int(hi) + 1))
                else:
                    allowed.add(int(token))
            if field_val not in allowed:
                return False
        return True

    @staticmethod
    def current_tuple() -> tuple[int, int, int, int, int]:
        """Get current time as a cron-compatible tuple."""
        t = time.localtime()
        return (t.tm_min, t.tm_hour, t.tm_mday, t.tm_mon, t.tm_wday)


# ---------------------------------------------------------------------------
# Trigger Manager
# ---------------------------------------------------------------------------


class _TriggerStats:
    __slots__ = ("errors", "fired", "scheduled_checks")

    def __init__(self) -> None:
        self.fired: int = 0
        self.errors: int = 0
        self.scheduled_checks: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "fired": self.fired,
            "errors": self.errors,
            "scheduled_checks": self.scheduled_checks,
        }


class TriggerManager:
    """Manage F1–F4 triggers for pipeline automation.

    Usage:
        mgr = TriggerManager()
        mgr.register(TriggerConfig(
            trigger_id="t1",
            trigger_type=TriggerType.MANUAL,
            callback=lambda data: print("Fired!", data),
        ))
        result = mgr.fire_manual("t1", {"ip_name": "Berserk"})
    """

    MAX_RESULTS = 1000  # Prune oldest results when exceeded

    def __init__(
        self,
        scheduler_interval_s: float = 60.0,
        hooks: HookSystemPort | None = None,
        snapshot_manager: SnapshotManager | None = None,
    ) -> None:
        self._triggers: dict[str, TriggerConfig] = {}
        self._results: list[TriggerResult] = []
        self._scheduler_interval = scheduler_interval_s
        self._scheduler_thread: threading.Thread | None = None
        self._scheduler_stop = threading.Event()
        self._lock = threading.Lock()
        self._stats = _TriggerStats()
        self._hooks = hooks
        self._snapshot_manager = snapshot_manager

    @property
    def stats(self) -> _TriggerStats:
        return self._stats

    def register(self, config: TriggerConfig) -> None:
        """Register a new trigger."""
        with self._lock:
            self._triggers[config.trigger_id] = config
        log.info("Registered trigger %s (%s)", config.trigger_id, config.trigger_type.value)

    def unregister(self, trigger_id: str) -> bool:
        """Remove a trigger. Returns True if found."""
        with self._lock:
            return self._triggers.pop(trigger_id, None) is not None

    def get_trigger(self, trigger_id: str) -> TriggerConfig | None:
        return self._triggers.get(trigger_id)

    def list_triggers(self, trigger_type: TriggerType | None = None) -> list[TriggerConfig]:
        """List triggers, optionally filtered by type."""
        triggers = list(self._triggers.values())
        if trigger_type:
            triggers = [t for t in triggers if t.trigger_type == trigger_type]
        return triggers

    def fire_manual(self, trigger_id: str, data: dict[str, Any] | None = None) -> TriggerResult:
        """Manually fire a trigger (F1)."""
        config = self._triggers.get(trigger_id)
        if config is None:
            raise KeyError(f"Trigger '{trigger_id}' not found")

        return self._execute_trigger(config, data or {})

    def check_scheduled(
        self,
        dt_tuple: tuple[int, int, int, int, int] | None = None,
    ) -> list[TriggerResult]:
        """Check and fire all scheduled triggers matching current time (F2)."""
        self._stats.scheduled_checks += 1
        current = dt_tuple or CronParser.current_tuple()
        results: list[TriggerResult] = []

        with self._lock:
            scheduled = [
                t
                for t in self._triggers.values()
                if t.trigger_type == TriggerType.SCHEDULED and t.enabled and t.cron_expr
            ]

        for config in scheduled:
            try:
                if CronParser.matches(config.cron_expr, current):
                    result = self._execute_trigger(config, {"cron_time": current})
                    results.append(result)
            except ValueError as e:
                log.warning("Invalid cron for trigger %s: %s", config.trigger_id, e)

        return results

    def make_event_handler(self, trigger_id: str) -> Callable[..., None]:
        """Create a HookSystem-compatible handler for an event trigger (F3).

        Returns a handler that can be registered with HookSystem.
        """

        def _handler(event: Any, data: dict[str, Any]) -> None:
            config = self._triggers.get(trigger_id)
            if config and config.enabled:
                self._execute_trigger(config, {**data, "event": str(event)})

        return _handler

    def handle_webhook(self, trigger_id: str, payload: dict[str, Any]) -> TriggerResult:
        """Handle an incoming webhook payload (F4)."""
        config = self._triggers.get(trigger_id)
        if config is None:
            raise KeyError(f"Webhook trigger '{trigger_id}' not found")
        if config.trigger_type != TriggerType.WEBHOOK:
            raise ValueError(f"Trigger '{trigger_id}' is not a WEBHOOK trigger")

        return self._execute_trigger(config, payload)

    def dispatch(
        self,
        trigger_type: TriggerType,
        payload: dict[str, Any],
        automation_id: str | None = None,
    ) -> TriggerResult:
        """Unified dispatch — all trigger types converge to single pipeline execution.

        Normalizes F1-F4 triggers into a single flow:
        1. Snapshot capture (if SnapshotManager available)
        2. Trigger-type-specific preprocessing
        3. Trigger execution via callback
        4. Result event publishing

        Architecture-v6 §12.2: Dispatch Layer.

        Args:
            trigger_type: One of MANUAL, SCHEDULED, EVENT, WEBHOOK.
            payload: Trigger-specific data dict.
            automation_id: Optional trigger ID for traceability.
                If provided, looks up the registered trigger.
                If None, creates an ephemeral trigger config.
        """
        session_id = payload.get(
            "session_id",
            f"auto_{int(time.time())}",
        )

        # 1. Snapshot capture
        snapshot_id = ""
        if self._snapshot_manager:
            snap = self._snapshot_manager.capture(
                session_id,
                context={
                    "trigger_type": trigger_type.value,
                    "automation_id": automation_id or "",
                    "payload_keys": list(payload.keys()),
                },
            )
            snapshot_id = snap.snapshot_id

        # 2. Resolve trigger config
        config: TriggerConfig | None = None
        if automation_id:
            config = self._triggers.get(automation_id)

        if config is None:
            # Ephemeral config for ad-hoc dispatch
            config = TriggerConfig(
                trigger_id=automation_id or f"dispatch-{session_id}",
                trigger_type=trigger_type,
                name=f"dispatch:{trigger_type.value}",
            )

        # 3. Trigger-type-specific preprocessing
        dispatch_payload = {**payload}
        dispatch_payload["_dispatch"] = {
            "session_id": session_id,
            "snapshot_id": snapshot_id,
            "trigger_type": trigger_type.value,
            "automation_id": automation_id or "",
        }

        if trigger_type == TriggerType.SCHEDULED and payload.get("batch"):
            dispatch_payload["_batch_mode"] = True

        if trigger_type == TriggerType.WEBHOOK:
            dispatch_payload["_source"] = payload.get("source", "external")

        if trigger_type == TriggerType.EVENT:
            dispatch_payload["_follow_up"] = (
                payload.get(
                    "event",
                    "",
                )
                == "pipeline_complete"
            )

        # 4. Execute
        result = self._execute_trigger(config, dispatch_payload)

        # 5. Publish post-dispatch event
        if self._hooks:
            from geode.orchestration.hooks import HookEvent

            self._hooks.trigger(
                HookEvent.POST_ANALYSIS,
                {
                    "trigger_type": trigger_type.value,
                    "automation_id": automation_id or "",
                    "session_id": session_id,
                    "snapshot_id": snapshot_id,
                    "success": result.success,
                },
            )

        return result

    def _execute_trigger(self, config: TriggerConfig, data: dict[str, Any]) -> TriggerResult:
        """Execute a trigger's callback with error isolation."""
        try:
            if config.callback:
                config.callback(data)
            result = TriggerResult(
                trigger_id=config.trigger_id,
                trigger_type=config.trigger_type,
                success=True,
                data=data,
            )
            self._stats.fired += 1

            if self._hooks:
                from geode.orchestration.hooks import HookEvent

                self._hooks.trigger(
                    HookEvent.TRIGGER_FIRED,
                    {
                        "trigger_id": config.trigger_id,
                        "type": config.trigger_type.value,
                    },
                )
        except Exception as exc:
            result = TriggerResult(
                trigger_id=config.trigger_id,
                trigger_type=config.trigger_type,
                success=False,
                error=str(exc),
            )
            self._stats.errors += 1
            log.warning("Trigger %s failed: %s", config.trigger_id, exc)

        with self._lock:
            self._results.append(result)
            # Prune oldest results to prevent unbounded growth
            if len(self._results) > self.MAX_RESULTS:
                self._results = self._results[-self.MAX_RESULTS :]
        return result

    # ---------------------------------------------------------------------------
    # Background scheduler (daemon thread)
    # ---------------------------------------------------------------------------

    def start_scheduler(self) -> None:
        """Start background scheduler thread for cron triggers."""
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return

        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="trigger-scheduler",
        )
        self._scheduler_thread.start()
        log.info("Trigger scheduler started (interval=%.0fs)", self._scheduler_interval)

    def stop_scheduler(self) -> None:
        """Stop background scheduler thread."""
        self._scheduler_stop.set()
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5.0)
            self._scheduler_thread = None
        log.info("Trigger scheduler stopped")

    @property
    def is_scheduler_running(self) -> bool:
        return self._scheduler_thread is not None and self._scheduler_thread.is_alive()

    def _scheduler_loop(self) -> None:
        """Background loop that checks scheduled triggers."""
        while not self._scheduler_stop.is_set():
            try:
                self.check_scheduled()
            except Exception as exc:
                log.warning("Scheduler error: %s", exc)
            self._scheduler_stop.wait(self._scheduler_interval)

    def register_pipeline_trigger(
        self,
        trigger_id: str,
        ip_name: str,
        *,
        trigger_type: TriggerType = TriggerType.MANUAL,
        cron_expr: str = "",
        callback: Callable[..., Any] | None = None,
    ) -> TriggerConfig:
        """Register a trigger that initiates a pipeline analysis.

        Convenience method bridging TriggerManager → pipeline planner.
        The callback receives {"ip_name": ..., "trigger_id": ...} when fired.
        """
        config = TriggerConfig(
            trigger_id=trigger_id,
            trigger_type=trigger_type,
            name=f"pipeline:{ip_name}",
            cron_expr=cron_expr,
            callback=callback,
            metadata={"ip_name": ip_name, "source": "pipeline_trigger"},
        )
        self.register(config)
        log.info("Pipeline trigger registered: %s for IP '%s'", trigger_id, ip_name)
        return config

    def get_results(self, trigger_id: str | None = None, limit: int = 100) -> list[TriggerResult]:
        """Get execution results, optionally filtered by trigger_id."""
        with self._lock:
            results = list(self._results)
        if trigger_id:
            results = [r for r in results if r.trigger_id == trigger_id]
        return results[-limit:]
