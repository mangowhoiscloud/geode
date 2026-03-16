"""Context Assembler — 3-tier memory merge for pipeline context.

Assembles context from Organization → Project → Session memory,
where lower tiers override higher tiers.

Architecture-v6 §3 Layer 2: Context Assembly.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.infrastructure.ports.memory_port import (
    OrganizationMemoryPort,
    ProjectMemoryPort,
    SessionStorePort,
    UserProfilePort,
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
        user_profile: UserProfilePort | None = None,
        freshness_threshold_s: float = DEFAULT_FRESHNESS_THRESHOLD_S,
    ) -> None:
        self._org_memory = organization_memory
        self._project_memory = project_memory
        self._session_store = session_store
        self._user_profile = user_profile
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

        # Tier 0 (identity): SOUL.md — organization mission & principles
        if self._org_memory:
            try:
                soul = self._org_memory.get_soul()
                if soul:
                    context["_soul"] = soul
                    context["_soul_loaded"] = True
            except Exception:
                context["_soul_loaded"] = False

        # Tier 0.5 (user profile): persistent user preferences & identity
        if self._user_profile:
            try:
                if self._user_profile.exists():
                    profile_summary = self._user_profile.get_context_summary()
                    if profile_summary:
                        context["_user_profile_summary"] = profile_summary
                    context["_user_profile_loaded"] = True
                else:
                    context["_user_profile_loaded"] = False
            except Exception as e:
                log.warning("Failed to load user profile: %s", e)
                context["_user_profile_loaded"] = False

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

        # ADR-007: Generate _llm_summary for PromptAssembler consumption
        context["_llm_summary"] = self._build_llm_summary(context)

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

    @staticmethod
    def _build_llm_summary(
        context: dict[str, Any],
        *,
        max_chars: int = 280,
    ) -> str:
        """Build a pre-formatted LLM-readable summary from assembled context.

        Contract (ADR-007): PromptAssembler reads this value directly without parsing.

        Karpathy P6 L2 extraction: prioritize high-value information instead of
        hard truncation.  Each tier gets a budget proportional to its value:
          SOUL (10%) → Organization (25%) → Project (25%) → Session (40%)
        """
        # Budget allocation per tier (proportional, not hard-cut)
        budget_soul = int(max_chars * 0.10)
        budget_org = int(max_chars * 0.25)
        budget_proj = int(max_chars * 0.25)
        budget_session = max_chars - budget_soul - budget_org - budget_proj

        parts: list[str] = []

        # SOUL.md — extract mission line (first non-header, non-empty line)
        if context.get("_soul_loaded"):
            soul_text = context.get("_soul", "")
            if soul_text:
                for line in soul_text.split("\n"):
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and not stripped.startswith(">"):
                        parts.append(f"Mission: {stripped[:budget_soul]}")
                        break

        # User profile summary (Tier 0.5)
        if context.get("_user_profile_loaded"):
            profile_summary = context.get("_user_profile_summary", "")
            if profile_summary:
                parts.append(profile_summary[:budget_soul])

        if context.get("_org_loaded"):
            org_strategy = context.get("organization_strategy", "")
            if org_strategy:
                parts.append(f"Org: {org_strategy[:budget_org]}")

        if context.get("_project_loaded"):
            project_goal = context.get("project_goal", "")
            if project_goal:
                parts.append(f"Project: {project_goal[:budget_proj]}")

        if context.get("_session_loaded"):
            prev_results = context.get("previous_results", [])
            if prev_results:
                # L2 extraction: most recent results first, fit within budget
                remaining = budget_session
                for pr in reversed(prev_results[-3:]):
                    entry = str(pr)
                    if len(entry) > remaining:
                        if remaining > 20:
                            parts.append(f"Prev: {entry[:remaining]}…")
                        break
                    parts.append(f"Prev: {entry}")
                    remaining -= len(entry) + 8  # "Prev: " + " | "

        return " | ".join(parts) if parts else ""
