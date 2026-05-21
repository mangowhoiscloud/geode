"""In-context slot wiring orchestrator — ADR-012 M4.4.

Connects the S5 in-context slot schema (`core/self_improving_loop/in_context_slots.py`)
to the actual LLM inference path. For every active LLM call, this
orchestrator consults the 4-slot SoT and applies the configured
transforms to the outgoing ``messages`` + ``system`` text before they
reach the provider.

**4 slots → wiring status**:

* ``exemplars`` — **wired**. Reads the M3 few-shot exemplar pool
  (`core/llm/few_shot_pool.py`) via ``_load_few_shot_pool_override`` →
  applies via ``apply_few_shot_pool`` (top-K by fitness_delta desc).
  Prepends ``(user, assistant)`` pairs at the head of ``messages``.
* ``memory_recall`` — **wired (M4.4.1)**. Reads frontmatter-style
  memory files from ``~/.geode/memory/recall/`` (or
  ``GEODE_MEMORY_RECALL_DIR`` env override), ranks by keyword overlap
  × recency, prepends a ``<memory-recall>`` block to the system prompt.
* ``rubric_excerpts`` — **wired (M4.4.2)**. Reads ``baseline.json``,
  computes the worst-regressed dims (where ``baseline_means -
  dim_means > 0``), formats a ``<rubric-warning>`` block with the
  built-in 17-dim ``DIM_RUBRIC`` directive for each, and prepends to
  the system prompt.
* ``tool_hints`` — **stub**. Reader (RunLog + episodic memory
  success_rate ranked) is a follow-up PR (M4.4.3).

**No-op fast path**: when ``_load_in_context_slots_override`` returns
``None`` (no SoT configured, the GEODE default), the orchestrator
returns the input ``messages`` + ``system`` unchanged — zero allocation,
zero log noise. This is the path the agentic loop hits on every call
for operators who have not opted into in-context wiring.

**Per-slot graceful**: each slot's reader / apply path runs inside its
own ``try / except``. A failure in one slot never blocks the others
or the underlying LLM call.

**Frontier parity**: Claude Code's system prompt and Codex CLI's
``<system-reminder>`` framework both ship hardcoded equivalents of
the 4 slots. GEODE surfaces them as explicit mutator targets so the
self-improving loop can optimize each independently.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["apply_in_context_slots"]


def apply_in_context_slots(
    messages: list[dict[str, Any]],
    *,
    system: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Apply the 4-slot in-context wiring to ``messages`` + ``system``.

    Args:
        messages: The agentic-loop's pending ``messages`` list (will be
            passed to the provider's ``messages.create`` / ``responses``
            endpoint). Caller passes the list verbatim; orchestrator
            never mutates in place.
        system: The system prompt text. ``""`` when the caller hasn't
            set one. Always returned alongside ``messages`` so a future
            slot reader (``memory_recall`` / ``rubric_excerpts``) that
            wants ``injection_point="system_prompt"`` can transform it.

    Returns:
        ``(new_messages, new_system)`` — both are fresh objects when any
        slot fired, else the input identities for the no-op fast path.
    """
    # No-op fast path — done first so the common "no SoT configured"
    # case adds zero overhead on every LLM call.
    try:
        from core.self_improving_loop.in_context_slots import (
            SLOT_EXEMPLARS,
            SLOT_MEMORY_RECALL,
            SLOT_RUBRIC_EXCERPTS,
            _load_in_context_slots_override,
        )

        slots = _load_in_context_slots_override()
    except Exception:  # pragma: no cover — defensive
        log.debug("in_context_slots load failed; skipping wiring", exc_info=True)
        return messages, system
    if not slots:
        return messages, system

    new_messages = messages
    new_system = system

    # exemplars — M3 substrate active. Top-K few-shot pairs at head of
    # the messages list, ranked by fitness_delta desc.
    exemplars_cfg = slots.get(SLOT_EXEMPLARS)
    if exemplars_cfg is not None:
        try:
            from core.llm.few_shot_pool import (
                _load_few_shot_pool_override,
                apply_few_shot_pool,
            )

            pool = _load_few_shot_pool_override()
            if pool:
                new_messages = apply_few_shot_pool(
                    new_messages, pool, max_entries=exemplars_cfg.max_entries
                )
        except Exception as exc:
            log.debug("exemplars slot apply failed: %s", exc, exc_info=True)

    # memory_recall — M4.4.1 reader active. Frontmatter MD files from
    # ``~/.geode/memory/recall/`` (or env override) ranked by keyword
    # overlap × recency, formatted as a ``<memory-recall>`` block and
    # prepended to the system prompt.
    memory_cfg = slots.get(SLOT_MEMORY_RECALL)
    if memory_cfg is not None:
        try:
            from core.self_improving_loop.memory_recall import (
                format_memory_block,
                load_memory_entries,
                rank_memory_entries,
            )

            entries = load_memory_entries()
            if entries:
                query = _latest_user_query(new_messages)
                ranked = rank_memory_entries(entries, query, top_k=memory_cfg.max_entries)
                block = format_memory_block(ranked)
                if block:
                    new_system = block + "\n\n" + new_system if new_system else block
        except Exception as exc:
            log.debug("memory_recall slot apply failed: %s", exc, exc_info=True)

    # rubric_excerpts — M4.4.2 reader active. Reads autoresearch's
    # ``baseline.json``, finds the worst-regressed dims, formats a
    # ``<rubric-warning>`` block and prepends it to the system prompt.
    rubric_cfg = slots.get(SLOT_RUBRIC_EXCERPTS)
    if rubric_cfg is not None:
        try:
            from core.self_improving_loop.rubric_excerpts import (
                find_worst_regressions,
                format_rubric_block,
                load_baseline,
            )

            baseline = load_baseline()
            if baseline is not None:
                rows = find_worst_regressions(baseline, top_k=rubric_cfg.max_entries)
                block = format_rubric_block(rows)
                if block:
                    new_system = block + "\n\n" + new_system if new_system else block
        except Exception as exc:
            log.debug("rubric_excerpts slot apply failed: %s", exc, exc_info=True)

    # tool_hints — reader deferred to follow-up PR (M4.4.3). Wiring
    # framework is in place; activation mirrors the rubric_excerpts
    # block above.

    return new_messages, new_system


def _latest_user_query(messages: list[dict[str, Any]]) -> str:
    """Return the most recent user-role string content, or ``""`` if absent.

    Used by ``memory_recall`` (and future similarity-ranked slots) to
    score memory entries against the operator's current task. Tolerates
    tool-result / non-string content shapes by skipping them.
    """
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
    return ""
