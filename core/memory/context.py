"""Context Assembler — 5-tier memory merge for pipeline context.

Assembles context from Identity (Tier 0, SOUL.md) → User Profile
(Tier 0.5) → Organization (Tier 1) → Project (Tier 2) → Session
(Tier 3), where lower tiers override higher tiers.

Architecture-v6 §3 Layer 2: Context Assembly.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from core.memory.organization import MonoLakeOrganizationMemory
from core.memory.port import SessionStorePort
from core.memory.project import ProjectMemory
from core.memory.user_profile import FileBasedUserProfile
from core.time_format import format_age

log = logging.getLogger(__name__)

# Context freshness threshold (seconds) — data older than this is stale
DEFAULT_FRESHNESS_THRESHOLD_S = 3600.0  # 1 hour

# Maximum run history entries to inject
DEFAULT_RUN_HISTORY_MAX_ENTRIES = 3


class ContextAssembler:
    """Assemble pipeline context from 5-tier memory hierarchy.

    Merge order: Identity (Tier 0, SOUL.md) → User Profile (Tier 0.5)
    → Organization (Tier 1) → Project (Tier 2) → Session (Tier 3).
    Lower tiers override higher tiers for the same keys.

    Usage:
        assembler = ContextAssembler(
            organization_memory=org_mem,
            project_memory=proj_mem,
            session_store=session_store,
        )
        ctx = assembler.assemble("session-1", "subject")
    """

    def __init__(
        self,
        *,
        organization_memory: MonoLakeOrganizationMemory | None = None,
        project_memory: ProjectMemory | None = None,
        session_store: SessionStorePort | None = None,
        user_profile: FileBasedUserProfile | None = None,
        freshness_threshold_s: float = DEFAULT_FRESHNESS_THRESHOLD_S,
        run_log_dir: Path | str | None = None,
        project_journal: Any | None = None,
        vault: Any | None = None,
        project_root: Path | str | None = None,
        session_manager: Any | None = None,
    ) -> None:
        self._org_memory = organization_memory
        self._project_memory = project_memory
        self._session_store = session_store
        self._user_profile = user_profile
        self._freshness_threshold = freshness_threshold_s
        self._last_assembly_time: float = 0.0
        self._run_log_dir: Path | None = Path(run_log_dir) if run_log_dir else None
        self._project_journal = project_journal  # C2: ProjectJournal
        self._vault = vault  # V0: Vault (artifact storage)
        self._project_root: Path | None = Path(project_root) if project_root else None
        self._session_manager = session_manager

    def assemble(
        self,
        session_id: str,
        subject_id: str,
    ) -> dict[str, Any]:
        """Assemble context from all 5 tiers.

        Args:
            session_id: Current session identifier.
            subject_id: Subject identifier to load context for.

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
                    # Career identity (if available)
                    if hasattr(self._user_profile, "get_career_summary"):
                        career_summary = self._user_profile.get_career_summary()
                        if career_summary:
                            context["_career_summary"] = career_summary
                    # User preferences for personalization
                    if hasattr(self._user_profile, "get_preferences"):
                        prefs = self._user_profile.get_preferences()
                        if prefs:
                            context["_user_preferences"] = prefs
                    context["_user_profile_loaded"] = True
                else:
                    context["_user_profile_loaded"] = False
            except Exception as e:
                log.warning("Failed to load user profile: %s", e)
                context["_user_profile_loaded"] = False

        # Tier 1 (base): Organization Memory
        if self._org_memory:
            try:
                org_ctx = self._org_memory.get_subject_context(subject_id)
                if org_ctx:
                    context.update(org_ctx)
                    context["_org_loaded"] = True
            except Exception as e:
                log.warning("Failed to load organization context: %s", e)
                context["_org_loaded"] = False

        # Tier 2 (override): Project Memory
        if self._project_memory:
            try:
                proj_ctx = self._project_memory.get_context_for_subject(subject_id)
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

        # Project environment: detected project type + harnesses
        self._inject_project_env(context)

        # Run History: inject recent execution summaries (Karpathy P6 L3)
        self._inject_run_history(subject_id, context)

        # C2 Journal: inject project-level context (history + learned patterns)
        self._inject_journal_context(context)

        # V0 Vault: inject artifact inventory summary
        self._inject_vault_context(context)

        # Long-context SQLite artifacts: compaction summaries + dreams.
        self._inject_long_context_artifacts(session_id, context)

        assembled_at = time.time()
        context["_assembled_at"] = assembled_at
        context["_session_id"] = session_id
        context["_subject_id"] = subject_id

        # Generate _llm_summary for prompt consumers that need a compact block.
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

    def _inject_run_history(
        self,
        subject_id: str,
        context: dict[str, Any],
        max_entries: int = DEFAULT_RUN_HISTORY_MAX_ENTRIES,
    ) -> None:
        """P6 Context Budget L3: inject recent run results as 1-line summary.

        Format: "Recent: subject score=81.3 (2h ago) | research done (1d ago)"
        """
        if not self._run_log_dir:
            return

        try:
            from core.observability.run_log import RunLog

            # Scan all JSONL files in run_log_dir for pipeline_end events
            if not self._run_log_dir.exists():
                return

            all_entries = []
            for jsonl_file in self._run_log_dir.glob("*.jsonl"):
                session_key = jsonl_file.stem.replace("_", ":")
                run_log = RunLog(session_key, log_dir=self._run_log_dir)
                entries = run_log.read(limit=max_entries, event_filter="pipeline_end")
                all_entries.extend(entries)

            if not all_entries:
                return

            # Sort by timestamp descending, take most recent
            all_entries.sort(key=lambda e: e.timestamp, reverse=True)
            recent = all_entries[:max_entries]

            now = time.time()
            summaries = []
            for entry in recent:
                score = entry.metadata.get("score", "?")
                age = format_age(now - entry.timestamp)
                name = entry.metadata.get("subject_id", subject_id)
                summaries.append(f"{name} score={score} ({age})")

            context["_run_history"] = " | ".join(summaries)
        except Exception:
            log.debug("Failed to inject run history", exc_info=True)

    def _inject_journal_context(self, context: dict[str, Any]) -> None:
        """C2 Journal: inject project-level history and learned patterns."""
        if not self._project_journal:
            return
        try:
            summary = self._project_journal.get_context_summary(max_runs=3)
            if summary:
                context["_journal_summary"] = summary

            patterns = self._project_journal.get_learned_patterns()
            if patterns:
                # Take last 5 patterns for context budget
                recent = patterns[-5:]
                context["_journal_learned"] = " | ".join(p.lstrip("- ") for p in recent)
        except Exception:
            log.debug("Failed to inject journal context", exc_info=True)

    def _inject_vault_context(self, context: dict[str, Any]) -> None:
        """V0 Vault: inject artifact inventory for the LLM."""
        if not self._vault:
            return
        try:
            summary = self._vault.get_context_summary()
            if summary:
                context["_vault_summary"] = summary
        except Exception:
            log.debug("Failed to inject vault context", exc_info=True)

    def _inject_long_context_artifacts(self, session_id: str, context: dict[str, Any]) -> None:
        """Inject bounded synthesized context from SQLite artifacts."""
        manager = self._session_manager
        if manager is None:
            return
        try:
            artifacts = manager.list_context_artifacts(
                session_id=session_id,
                kinds=("compaction_summary", "dream"),
                limit=3,
            )
            if not artifacts:
                return
            lines = []
            for artifact in artifacts:
                source = ""
                if artifact.source_start_seq is not None or artifact.source_end_seq is not None:
                    source = f" seq={artifact.source_start_seq}-{artifact.source_end_seq}"
                content = artifact.content.strip().replace("\n", " ")
                lines.append(f"{artifact.kind}{source}: {content[:500]}")
            context["_long_context_summary"] = " | ".join(lines)
        except Exception:
            log.debug("Failed to inject long-context artifacts", exc_info=True)

    def _inject_project_env(self, context: dict[str, Any]) -> None:
        """Inject detected project type and harness information."""
        if not self._project_root:
            return
        try:
            from core.config.project_detect import (
                detect_project_type,
                get_harness_summary,
            )

            info = detect_project_type(self._project_root)
            context["_project_type"] = info.project_type
            context["_project_pkg_mgr"] = info.pkg_mgr
            if info.harnesses:
                context["_harnesses"] = info.harnesses
                context["_harness_summary"] = get_harness_summary(info.harnesses)
        except Exception:
            log.debug("Failed to inject project env", exc_info=True)

    @staticmethod
    def _build_llm_summary(
        context: dict[str, Any],
        *,
        max_chars: int = 280,
    ) -> str:
        """Build a pre-formatted LLM-readable summary from assembled context.

        Contract: prompt consumers read this value directly without parsing.

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

        long_context = context.get("_long_context_summary", "")
        if long_context:
            parts.append(f"Long context: {str(long_context)[:budget_session]}")

        return " | ".join(parts) if parts else ""
