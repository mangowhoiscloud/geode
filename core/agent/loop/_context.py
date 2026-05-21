"""Context-window/message helpers + system-prompt assembly.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7). Each
function takes the ``AgenticLoop`` as the first parameter (``loop``)
and reads/writes its state. The class methods on ``AgenticLoop`` are
thin one-line delegators.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.agent.system_prompt import build_system_prompt as _build_system_prompt
from core.llm.prompts import AGENTIC_SUFFIX
from core.skills.skill_catalog_policy import (
    _load_skill_catalog_override,
    apply_skill_catalog_policy,
)

if TYPE_CHECKING:
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


def sync_messages_to_context(loop: AgenticLoop, messages: list[dict[str, Any]]) -> None:
    """Replace context messages with the full messages list.

    During the agentic loop, intermediate tool-use messages are appended
    only to the local ``messages`` list.  This method syncs them back to
    ``self.context`` so the next user turn sees the full history.
    """
    loop.context.messages = list(messages)


def notify_context_event(
    loop: AgenticLoop, event_type: str, *, original_count: int, new_count: int
) -> None:
    """Notify user of context compression. Delegates to ContextWindowManager."""
    loop._ctx_mgr._notify_context_event(
        event_type, original_count=original_count, new_count=new_count
    )


def maybe_prune_messages(loop: AgenticLoop, messages: list[dict[str, Any]]) -> None:
    """Prune old messages. Delegates to ContextWindowManager."""
    loop._ctx_mgr.maybe_prune_messages(messages)


async def check_context_overflow(
    loop: AgenticLoop, system: str, messages: list[dict[str, Any]]
) -> None:
    """Check context window usage. Delegates to ContextWindowManager."""
    await loop._ctx_mgr.check_context_overflow(system, messages, loop.model, loop._provider)


async def aggressive_context_recovery(
    loop: AgenticLoop, system: str, messages: list[dict[str, Any]]
) -> int:
    """Last-resort context recovery. Delegates to ContextWindowManager."""
    return await loop._ctx_mgr.aggressive_context_recovery(
        system, messages, loop.model, loop._provider
    )


def repair_messages(messages: list[dict[str, Any]]) -> None:
    """Remove orphaned tool_result messages. Delegates to ContextWindowManager."""
    from core.agent.context_manager import ContextWindowManager

    ContextWindowManager.repair_messages(messages)


def build_system_prompt(loop: AgenticLoop) -> str:
    """Build the system prompt with skill context and agentic suffix.

    S2-wire (2026-05-18): when ``loop._system_prompt_override`` is set
    (AgentDefinition-driven spawn), the override replaces the default
    GEODE system body. Skill context + agentic suffix + system_suffix
    are still appended so tool-calling and observability invariants
    hold for all spawns regardless of role.
    """
    override = getattr(loop, "_system_prompt_override", None)
    skill_ctx = ""
    if loop._skill_registry is not None:
        # ADR-013 T2 (2026-05-21) — skill catalog mutation surface. policy
        # SoT 가 부재면 apply_*_policy 는 registry.get_context_block() 에
        # 위임 (no behavior change). 정책이 있으면 per-skill description /
        # user_invocable override 적용.
        skill_ctx = apply_skill_catalog_policy(loop._skill_registry, _load_skill_catalog_override())
    # Skills enter the active prompt path here: the loop-level registry renders
    # one context block, then ``{skill_context}`` in the system wrapper is
    # substituted below. The legacy PromptAssembler Phase 2 injection path was
    # removed; do not add a second skill-injection route.
    # S2-fix (2026-05-18) — both branches honor the ``{skill_context}``
    # placeholder so AgentDefinition authors can opt into explicit skill
    # injection (matching ``_DEFAULT_AGENTS`` semantics). If the override
    # has no placeholder, the skill block is appended; if it does, the
    # placeholder is substituted in place. Empty-state marker preserved
    # for both paths so prompts never ship a literal ``{skill_context}``
    # token to the LLM.
    skill_replacement = skill_ctx or '<available_skills status="empty" />'
    if override:
        if "{skill_context}" in override:
            base = override.replace("{skill_context}", skill_replacement)
        else:
            base = override
            if skill_ctx:
                base = base + "\n\n" + skill_ctx
    else:
        base = _build_system_prompt(model=loop.model)
        base = base.replace("{skill_context}", skill_replacement)
    prompt: str = base + "\n" + AGENTIC_SUFFIX
    if loop._system_suffix:
        prompt += "\n\n" + loop._system_suffix
    return prompt
