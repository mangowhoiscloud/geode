"""Prompt assembler -- compose base templates with skills, memory, and bootstrap.

Central assembly point that resolves the 5 disconnections identified in ADR-007:
1. Bootstrap overrides -> auto-consumed
2. Memory context -> injected into system prompt
3. Hook metadata -> PROMPT_ASSEMBLED event emitted
4. Hardcoded prompts -> extended via .md skill files
5. Prompt observability -> SHA-256 hash + fragment metadata
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.llm.prompts import _hash_prompt
from core.llm.skill_registry import SkillDefinition, SkillRegistry
from core.orchestration.hook_port import HookSystemPort
from core.orchestration.hooks import HookEvent

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class for assembled result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssembledPrompt:
    """Immutable result of prompt assembly."""

    system: str
    user: str
    assembled_hash: str  # SHA-256[:12] of (system + user)
    base_template_hash: str  # hash of original base template
    fragment_count: int  # number of injected fragments
    total_chars: int  # len(system) + len(user)
    fragments_used: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PromptAssembler
# ---------------------------------------------------------------------------


class PromptAssembler:
    """Prompt assembler -- base template + skills + memory + bootstrap.

    Nodes call ``assemble()`` instead of raw ``.format()`` so that skill
    fragments, memory context, and bootstrap overrides are automatically
    incorporated.

    Security:
        ``allow_full_override=False`` (default) limits ``_prompt_overrides``
        to **append-only** mode. Full replacement requires explicit opt-in
        and should only be used in test/dev environments.
    """

    def __init__(
        self,
        *,
        skill_registry: SkillRegistry | None = None,
        hooks: HookSystemPort | None = None,
        allow_full_override: bool = False,
        # Token budget configuration
        max_skill_chars: int = 500,
        max_skills_per_node: int = 3,
        max_memory_chars: int = 300,
        max_extra_instructions: int = 5,
        max_extra_instruction_chars: int = 100,
        prompt_warning_chars: int = 4000,
    ) -> None:
        self._skills = skill_registry or SkillRegistry()
        self._hooks = hooks
        self._allow_full_override = allow_full_override
        self._max_skill_chars = max_skill_chars
        self._max_skills_per_node = max_skills_per_node
        self._max_memory_chars = max_memory_chars
        self._max_extra_instructions = max_extra_instructions
        self._max_extra_instruction_chars = max_extra_instruction_chars
        self._prompt_warning_chars = prompt_warning_chars

    # -- Public API ---------------------------------------------------------

    def assemble(
        self,
        *,
        base_system: str,
        base_user: str,
        state: dict[str, Any],
        node: str,
        role_type: str,
    ) -> AssembledPrompt:
        """Compose base template + skill + memory + bootstrap into final prompt.

        Args:
            base_system: Rendered system prompt from ``prompts.py``.
            base_user: Rendered user prompt from ``prompts.py``.
            state: ``GeodeState`` dict (contains bootstrap/memory keys).
            node: Node name (``"analyst"``, ``"evaluator"``, etc.).
            role_type: Role type (``"game_mechanics"``, ``"quality_judge"``, etc.).

        Returns:
            ``AssembledPrompt`` with fully composed prompts and metadata.
        """
        base_hash = _hash_prompt(base_system + base_user)
        fragments_used: list[str] = []
        skill_hashes: dict[str, str] = {}  # Karpathy P4: track skill content for drift
        truncation_events: list[str] = []  # Karpathy P6: record what was truncated

        # --- Phase 1: Prompt Override ---
        overrides = state.get("_prompt_overrides", {})
        system_key = f"{node}_system"
        if system_key in overrides:
            if self._allow_full_override:
                system = overrides[system_key]
                fragments_used.append(f"override:{system_key}")
            else:
                system = base_system + "\n\n" + overrides[system_key]
                fragments_used.append(f"override-append:{system_key}")
        else:
            system = base_system

        # --- Phase 2: Skill Fragment Injection ---
        skills = self._skills.get_skills(node=node, role_type=role_type)
        if skills:
            skills = sorted(skills, key=lambda s: s.priority)[: self._max_skills_per_node]
            skill_block = self._format_skill_block(skills)
            system = system + "\n\n" + skill_block
            for s in skills:
                fragments_used.append(f"{s.name}:{s.version}")
                skill_hashes[s.name] = _hash_prompt(s.prompt_body)

        # --- Phase 3: Memory Context Injection ---
        memory_ctx = state.get("memory_context")
        if memory_ctx and isinstance(memory_ctx, dict):
            memory_block = self._format_memory_block(memory_ctx)
            if memory_block:
                if len(memory_block) > self._max_memory_chars:
                    truncation_events.append(
                        f"memory:{len(memory_block)}->{self._max_memory_chars}"
                    )
                    memory_block = memory_block[: self._max_memory_chars] + "..."
                    log.warning("Memory context truncated to %d chars", self._max_memory_chars)
                system = system + "\n\n" + memory_block
                fragments_used.append("memory-context")

        # --- Phase 4: Extra Instructions (Bootstrap) ---
        extra: list[str] = state.get("_extra_instructions", [])
        if extra:
            extra = extra[: self._max_extra_instructions]
            extra = [inst[: self._max_extra_instruction_chars] for inst in extra]
            instructions_block = "## Additional Instructions\n" + "\n".join(
                f"- {inst}" for inst in extra
            )
            system = system + "\n\n" + instructions_block
            fragments_used.append(f"bootstrap-extra:{len(extra)}")

        user = base_user

        # --- Phase 5: Token Budget Observability ---
        # Frontier consensus: no hard cap on system prompt.
        # 1M context models handle large prompts natively.
        # We only warn for observability; never truncate.
        total_system_chars = len(system)
        if total_system_chars > self._prompt_warning_chars:
            log.warning(
                "System prompt %d chars exceeds warning threshold %d",
                total_system_chars,
                self._prompt_warning_chars,
            )

        # --- Phase 6: Hash + Observability ---
        assembled_hash = _hash_prompt(system + user)
        total_chars = len(system) + len(user)

        result = AssembledPrompt(
            system=system,
            user=user,
            assembled_hash=assembled_hash,
            base_template_hash=base_hash,
            fragment_count=len(fragments_used),
            total_chars=total_chars,
            fragments_used=list(fragments_used),
        )

        # Emit hook event (metadata only, NOT raw prompt content)
        if self._hooks is not None:
            hook_data: dict[str, Any] = {
                "node": node,
                "role_type": role_type,
                "assembled_hash": assembled_hash,
                "base_template_hash": base_hash,
                "fragment_count": len(fragments_used),
                "total_chars": total_chars,
                "fragments_used": list(fragments_used),
            }
            # Karpathy P4 ratchet: include skill content hashes for drift detection
            if skill_hashes:
                hook_data["skill_hashes"] = skill_hashes
            if truncation_events:
                hook_data["truncation_events"] = truncation_events
            self._hooks.trigger(HookEvent.PROMPT_ASSEMBLED, hook_data)

        return result

    # -- Formatting helpers -------------------------------------------------

    def _format_skill_block(self, skills: list[SkillDefinition]) -> str:
        """Format skill fragments into a single block.

        Per-fragment char limit applied: bodies exceeding ``max_skill_chars``
        are truncated with ``...`` appended.
        """
        parts: list[str] = []
        for skill in sorted(skills, key=lambda s: s.priority):
            body = skill.prompt_body
            if len(body) > self._max_skill_chars:
                body = body[: self._max_skill_chars] + "..."
                log.warning("Skill '%s' truncated to %d chars", skill.name, self._max_skill_chars)
            parts.append(f"## Skill: {skill.name}\n{body}")
        return "\n\n".join(parts)

    @staticmethod
    def _format_memory_block(memory_ctx: dict[str, Any]) -> str:
        """Format memory context as an LLM-readable block.

        Primary path uses ``_llm_summary`` produced by ``ContextAssembler``.
        Fallback path constructs a summary from legacy keys.
        """
        # Primary path: pre-formatted summary from ContextAssembler
        llm_summary = memory_ctx.get("_llm_summary")
        if llm_summary and isinstance(llm_summary, str):
            return f"## Context from Memory\n{llm_summary}"

        # Fallback path: build from individual keys (backward compatibility)
        parts: list[str] = ["## Context from Memory"]

        if memory_ctx.get("_org_loaded"):
            org_strategy = memory_ctx.get("organization_strategy", "")
            if org_strategy:
                parts.append(f"- Organization strategy: {org_strategy}")

        if memory_ctx.get("_project_loaded"):
            project_goal = memory_ctx.get("project_goal", "")
            if project_goal:
                parts.append(f"- Project goal: {project_goal}")

        if memory_ctx.get("_session_loaded"):
            prev_results: list[str] = memory_ctx.get("previous_results", [])
            if prev_results:
                for pr in prev_results[-3:]:
                    parts.append(f"- Previous: {pr}")

        return "\n".join(parts) if len(parts) > 1 else ""
