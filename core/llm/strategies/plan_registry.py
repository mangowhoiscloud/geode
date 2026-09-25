"""Runtime plan and per-model plan-order storage.

Policy interpretation and source-constrained account selection belong to
``core.llm.routing``. This module owns only stored plans and file ownership.
"""

from __future__ import annotations

import threading

from core.llm.strategies.plans import Plan


class PlanRegistry:
    """In-memory Plan store with per-model ordered plan references.

    Keyed by Plan.id. A separate `_routing` map records the preferred
    Plan ID order for each model name (set by the user via
    `/login route`).
    """

    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}
        # model_pattern -> ordered list of plan_ids
        self._routing: dict[str, list[str]] = {}
        self._file_plans: dict[str, dict[str, Plan]] = {}
        self._file_routing: dict[str, dict[str, list[str]]] = {}
        self._lock = threading.Lock()

    # --- Plan CRUD ---

    def add(self, plan: Plan) -> None:
        with self._lock:
            self._plans[plan.id] = plan

    def get(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)

    def remove(self, plan_id: str) -> bool:
        with self._lock:
            existed = self._plans.pop(plan_id, None) is not None
            for model, ids in list(self._routing.items()):
                self._routing[model] = [i for i in ids if i != plan_id]
                if not self._routing[model]:
                    del self._routing[model]
            return existed

    def list_all(self) -> list[Plan]:
        return list(self._plans.values())

    def list_for_provider(self, provider: str) -> list[Plan]:
        return [p for p in self._plans.values() if p.provider == provider]

    # --- Routing ---

    def set_routing(self, model: str, plan_ids: list[str]) -> None:
        with self._lock:
            self._routing[model] = list(plan_ids)

    def get_routing(self, model: str) -> list[str]:
        return list(self._routing.get(model, ()))

    def all_routing(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._routing.items()}

    def file_plans(self, source: str) -> dict[str, Plan]:
        """Return the last file-owned objects for candidate collision validation."""
        return dict(self._file_plans.get(source, {}))

    def remember_auth_file(
        self, source: str, plans: list[Plan], routing: dict[str, list[str]]
    ) -> None:
        """Track file ownership without taking ownership of unrelated runtime plans."""
        ids = {plan.id for plan in plans}
        for other, entries in self._file_plans.items():
            if other != source:
                for plan_id in ids:
                    entries.pop(plan_id, None)
        for other, entries_routing in self._file_routing.items():
            if other != source:
                for model in routing:
                    entries_routing.pop(model, None)
        self._file_plans[source] = {plan.id: plan for plan in plans}
        self._file_routing[source] = {model: list(ids) for model, ids in routing.items()}

    def reconcile_auth_file(
        self, source: str, plans: list[Plan], routing: dict[str, list[str]]
    ) -> None:
        """Replace this file's validated entries, retaining borrowed plans."""
        with self._lock:
            previous = self._file_plans.get(source, {})
            ids = {plan.id for plan in plans}
            for plan_id, plan in previous.items():
                if plan_id not in ids and self._plans.get(plan_id) is plan:
                    self._plans.pop(plan_id)
            for model, chain in self._file_routing.get(source, {}).items():
                if self._routing.get(model) == chain:
                    self._routing.pop(model)
            owned: list[Plan] = []
            for plan in plans:
                current = self._plans.get(plan.id)
                if current is not None and previous.get(plan.id) is not current:
                    continue
                if current == plan:
                    plan = current
                self._plans[plan.id] = plan
                owned.append(plan)
            owned_routing = {
                model: list(chain) for model, chain in routing.items() if model not in self._routing
            }
            self._routing.update(owned_routing)
            self.remember_auth_file(source, owned, owned_routing)

    def clear(self) -> None:
        with self._lock:
            self._plans.clear()
            self._routing.clear()
            self._file_plans.clear()
            self._file_routing.clear()


# Module-level singleton (mirrors ProfileStore lifecycle)
_plan_registry: PlanRegistry | None = None
_registry_lock = threading.Lock()


def get_plan_registry() -> PlanRegistry:
    """Return the singleton PlanRegistry, building it if necessary."""
    global _plan_registry
    if _plan_registry is None:
        with _registry_lock:
            if _plan_registry is None:
                _plan_registry = PlanRegistry()
    return _plan_registry


def reset_plan_registry() -> None:
    """Test helper — clear the singleton between tests."""
    global _plan_registry
    with _registry_lock:
        _plan_registry = None
