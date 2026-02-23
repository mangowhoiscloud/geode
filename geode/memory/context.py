"""Context Assembler — 3-tier memory merge for pipeline context.

Assembles context from Organization → Project → Session memory,
where lower tiers override higher tiers.

Architecture-v6 §3 Layer 2: Context Assembly.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from geode.infrastructure.ports.memory_port import (
    OrganizationMemoryPort,
    ProjectMemoryPort,
    SessionStorePort,
)

log = logging.getLogger(__name__)

# Context freshness threshold (seconds) — data older than this is stale
DEFAULT_FRESHNESS_THRESHOLD_S = 3600.0  # 1 hour


class ContextAssembler:
    """Assemble pipeline context from 3-tier memory hierarchy.

    Merge order: Organization (base) → Project (override) → Session (override).
    Lower tiers override higher tiers for the same keys.

    Usage:
        assembler = ContextAssembler(
            organization_memory=org_mem,
            project_memory=proj_mem,
            session_store=session_store,
        )
        ctx = assembler.assemble("session-1", "Berserk")
    """

    def __init__(
        self,
        *,
        organization_memory: OrganizationMemoryPort | None = None,
        project_memory: ProjectMemoryPort | None = None,
        session_store: SessionStorePort | None = None,
        freshness_threshold_s: float = DEFAULT_FRESHNESS_THRESHOLD_S,
    ) -> None:
        self._org_memory = organization_memory
        self._project_memory = project_memory
        self._session_store = session_store
        self._freshness_threshold = freshness_threshold_s
        self._last_assembly_time: float = 0.0

    def assemble(
        self,
        session_id: str,
        ip_name: str,
    ) -> dict[str, Any]:
        """Assemble context from all 3 tiers.

        Args:
            session_id: Current session identifier.
            ip_name: IP name to load context for.

        Returns:
            Merged context dict with keys from all tiers.
        """
        context: dict[str, Any] = {}

        # Tier 1 (base): Organization Memory
        if self._org_memory:
            try:
                org_ctx = self._org_memory.get_ip_context(ip_name)
                if org_ctx:
                    context.update(org_ctx)
                    context["_org_loaded"] = True
            except Exception as e:
                log.warning("Failed to load organization context: %s", e)
                context["_org_loaded"] = False

        # Tier 2 (override): Project Memory
        if self._project_memory:
            try:
                proj_ctx = self._project_memory.get_context_for_ip(ip_name)
                if proj_ctx:
                    # Merge project context (overrides org)
                    for key, value in proj_ctx.items():
                        if value:  # Only override with non-empty values
                            context[key] = value
                    context["_project_loaded"] = True
            except Exception as e:
                log.warning("Failed to load project context: %s", e)
                context["_project_loaded"] = False

        # Tier 3 (override): Session Data
        if self._session_store:
            try:
                session_data = self._session_store.get(session_id)
                if session_data:
                    # Session data overrides everything
                    context.update(session_data)
                    context["_session_loaded"] = True
            except Exception as e:
                log.warning("Failed to load session context: %s", e)
                context["_session_loaded"] = False

        assembled_at = time.time()
        context["_assembled_at"] = assembled_at
        context["_session_id"] = session_id
        context["_ip_name"] = ip_name

        return context

    def mark_assembled(self, assembled_at: float | None = None) -> None:
        """Record the last assembly timestamp (command, separate from query)."""
        self._last_assembly_time = assembled_at or time.time()

    def is_data_fresh(self, max_age_s: float | None = None) -> bool:
        """Check if the last assembled context is still fresh.

        Args:
            max_age_s: Override freshness threshold (seconds).

        Returns:
            True if data was assembled within the threshold.
        """
        if self._last_assembly_time == 0.0:
            return False
        threshold = max_age_s or self._freshness_threshold
        return (time.time() - self._last_assembly_time) < threshold
