"""Disk-persistent store for ``AnalysisPlan`` instances.

v0.53.3 — replaces the v0.53.2-and-earlier in-memory ``_PLAN_CACHE``
closure dict so plans survive daemon restarts and are visible across
all ``_build_tool_handlers`` factory invocations (the B1 closure bug
the user hit on 2026-04-27).

Storage shape (``.geode/plans.json``):

    {
      "plan_<hex>": {
        "plan_id": "plan_<hex>",
        "ip_name": "...",
        "steps": [{"step_id":..., "description":..., ...}, ...],
        "status": "draft" | "presented" | "approved" | ...,
        "created_at": <epoch float>,
        "total_estimated_time_s": <float>,
        "total_estimated_cost": <float>,
        "metadata": {...}
      },
      ...
    }

Atomic write via tmp+rename (mirrors core/scheduler/scheduler.py:save).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any

from core.orchestration.plan_mode import AnalysisPlan, PlanStatus, PlanStep
from core.paths import PROJECT_PLANS_FILE

log = logging.getLogger(__name__)


class PlanStore:
    """In-memory + on-disk plan store. Thread-safe; lazy-loaded."""

    def __init__(self, path: Path | str = PROJECT_PLANS_FILE) -> None:
        self._path = Path(path)
        self._plans: dict[str, AnalysisPlan] = {}
        self._loaded = False
        self._lock = Lock()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            # Double-checked locking — another thread may have loaded
            # while we were waiting on self._lock.
            if self._loaded:
                return  # type: ignore[unreachable]
            if self._path.exists():
                try:
                    with open(self._path, encoding="utf-8") as f:
                        data: dict[str, Any] = json.load(f) or {}
                except (json.JSONDecodeError, OSError) as exc:
                    log.warning("PlanStore: failed to read %s: %s", self._path, exc)
                    data = {}
                for pid, raw in data.items():
                    try:
                        self._plans[pid] = _plan_from_dict(raw)
                    except Exception:
                        log.warning(
                            "PlanStore: skipping malformed plan %s in %s",
                            pid,
                            self._path,
                            exc_info=True,
                        )
            self._loaded = True

    def _save(self) -> None:
        """Atomic write — tmp + rename (must be called under self._lock)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {pid: _plan_to_dict(p) for pid, p in self._plans.items()}
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        tmp = self._path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(str(tmp), str(self._path))
        except OSError as exc:
            log.warning("PlanStore: failed to write %s: %s", self._path, exc)
            with contextlib.suppress(OSError):
                tmp.unlink()

    # --- public API ---------------------------------------------------------

    def put(self, plan: AnalysisPlan) -> None:
        """Insert or update a plan; persists immediately."""
        self._ensure_loaded()
        with self._lock:
            self._plans[plan.plan_id] = plan
            self._save()

    def get(self, plan_id: str) -> AnalysisPlan | None:
        """Retrieve a plan by ID, or None."""
        self._ensure_loaded()
        return self._plans.get(plan_id)

    def list_all(self) -> list[AnalysisPlan]:
        """Return all plans (any status). Caller filters as needed."""
        self._ensure_loaded()
        return list(self._plans.values())

    def keys(self) -> list[str]:
        self._ensure_loaded()
        return list(self._plans.keys())

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._plans)

    def __contains__(self, plan_id: object) -> bool:
        self._ensure_loaded()
        return plan_id in self._plans

    def clear(self) -> None:
        """Test helper — wipe in-memory + on-disk state."""
        with self._lock:
            self._plans.clear()
            with contextlib.suppress(OSError):
                if self._path.exists():
                    self._path.unlink()
            self._loaded = True


# ---------------------------------------------------------------------------
# JSON (de)serialisation helpers — module-private
# ---------------------------------------------------------------------------


def _plan_to_dict(plan: AnalysisPlan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "ip_name": plan.ip_name,
        "steps": [_step_to_dict(s) for s in plan.steps],
        "status": plan.status.value,
        "created_at": plan.created_at,
        "total_estimated_time_s": plan.total_estimated_time_s,
        "total_estimated_cost": plan.total_estimated_cost,
        "metadata": dict(plan.metadata),
    }


def _step_to_dict(step: PlanStep) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "description": step.description,
        "node_name": step.node_name,
        "estimated_time_s": step.estimated_time_s,
        "dependencies": list(step.dependencies),
        "metadata": dict(step.metadata),
    }


def _plan_from_dict(raw: dict[str, Any]) -> AnalysisPlan:
    steps = [_step_from_dict(s) for s in (raw.get("steps") or [])]
    return AnalysisPlan(
        plan_id=str(raw["plan_id"]),
        ip_name=str(raw.get("ip_name", "")),
        steps=steps,
        status=PlanStatus(raw.get("status", "draft")),
        created_at=float(raw.get("created_at", 0.0)),
        total_estimated_time_s=float(raw.get("total_estimated_time_s", 0.0)),
        total_estimated_cost=float(raw.get("total_estimated_cost", 0.0)),
        metadata=dict(raw.get("metadata") or {}),
    )


def _step_from_dict(raw: dict[str, Any]) -> PlanStep:
    return PlanStep(
        step_id=str(raw["step_id"]),
        description=str(raw.get("description", "")),
        node_name=str(raw.get("node_name", "agentic")),
        estimated_time_s=float(raw.get("estimated_time_s", 0.0)),
        dependencies=list(raw.get("dependencies") or []),
        metadata=dict(raw.get("metadata") or {}),
    )
