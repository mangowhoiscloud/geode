"""Client-side conversation compaction — Hermes Phase 3 4-phase pipeline.

For providers without server-side compaction (OpenAI, GLM, etc.) this
module compresses the head of the message list into an LLM-generated
summary while preserving the tail verbatim for continuity. Anthropic
has server-side compaction (``compact_20260112``) and short-circuits
at the top.

**4 phases** (Hermes Phase 3, 2026-05-26, absorbing Claude Code's
tool_use/tool_result boundary + orphan handling — the broader
thinking-block / image-block / citation surface is out of scope
for this PR):

1. **boundary** — find the cut index that won't split a
   ``tool_use`` / ``tool_result`` pair. Starts at
   ``len(messages) - keep_recent`` and walks backwards while the
   tail's first message would orphan a tool_result from the head.
2. **orphan_tool_result** — defensive cleanup for the edge case
   where the boundary algorithm hit index 0 (entire history fits
   in tail but the head has tool_uses with no matching results, or
   vice versa). Drops orphan tool_result blocks whose tool_use_id
   no longer appears anywhere in the post-boundary message list.
3. **summarize** — LLM call against the head messages, producing a
   plain-text summary that follows the Claude-Code-style "preserve
   task / decisions / state / refs / next steps" prompt.
4. **carry_forward** — splice the summary + a compaction marker +
   the cleaned tail so the agent continues with a hybrid view: a
   compact narrative of the past + verbatim recent turns.

Pre-Hermes-3 GEODE shipped phases 3+4 only (`compact_conversation`
ran a single LLM summary + carry-forward). Without phase 1 the cut
could split a `tool_use` / `tool_result` pair, raising "tool_result
block does not match a preceding tool_use" at the provider's
validator. Without phase 2 a malformed history (e.g., resumed from
a checkpoint that lost its tool_use anchor) could carry an orphan
tool_result through to the next LLM call.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Default summarization prompt (aligned with Claude Code / Codex CLI patterns)
_COMPACTION_PROMPT = (
    "You are summarizing a conversation for continuity. Write a concise summary "
    "preserving: (1) the user's original task/goal, (2) key decisions made, "
    "(3) current state and progress, (4) important code/data references, "
    "(5) next steps. Be factual and specific. Do not add commentary."
)

# Marker injected after compaction so the LLM knows history was compressed
COMPACTION_MARKER = (
    "[This conversation was automatically compacted. "
    "Previous context has been summarized above. "
    "Some details from earlier messages may no longer be available.]"
)


async def compact_conversation(
    messages: list[dict[str, Any]],
    provider: str,
    model: str,
    *,
    keep_recent: int = 10,
) -> tuple[list[dict[str, Any]], bool]:
    """Compact conversation via 4-phase pipeline.

    Returns ``(new_messages, did_compact)``. Anthropic uses server-side
    compaction so this is a no-op for that provider; non-Anthropic
    providers run the full pipeline.
    """
    if provider == "anthropic":
        log.debug("Skipping client compaction — Anthropic uses server-side compaction")
        return messages, False

    if len(messages) <= keep_recent + 2:
        log.debug("Not enough messages to compact (%d <= %d)", len(messages), keep_recent + 2)
        return messages, False

    # Phase 1 — boundary
    boundary = find_safe_boundary(messages, keep_recent=keep_recent)
    if boundary <= 0:
        log.debug("compaction boundary at 0 — nothing to summarize")
        return messages, False

    to_summarize = messages[:boundary]
    to_keep = messages[boundary:]

    # Phase 2 — orphan tool_result cleanup
    to_keep = strip_orphan_tool_results(to_keep)

    # Phase 3 — summarize the head
    summary_input = _build_summary_input(to_summarize)
    if not summary_input.strip():
        return messages, False
    summary = await _call_summarize(summary_input, provider, model)
    if not summary:
        log.warning("Compaction summary generation failed — keeping original messages")
        return messages, False

    # Phase 4 — carry forward
    new_messages = _carry_forward(summary, to_keep)
    log.info(
        "Compacted conversation: %d → %d messages "
        "(boundary=%d, summarized=%d, kept_recent=%d, post_orphan_cleanup=%d)",
        len(messages),
        len(new_messages),
        boundary,
        len(to_summarize),
        len(messages) - boundary,
        len(to_keep),
    )
    return new_messages, True


# ── Phase 1: boundary ───────────────────────────────────────────────


def find_safe_boundary(messages: list[dict[str, Any]], *, keep_recent: int) -> int:
    """Return a cut index that won't split a ``tool_use`` / ``tool_result`` pair.

    Starts at ``max(0, len(messages) - keep_recent)`` and walks
    backwards while the boundary message is a ``tool_result`` whose
    parent ``tool_use`` lives in the *previous* message. Each
    backward step pulls the corresponding ``tool_use`` into the tail
    so the pair stays together.

    Stops moving when the boundary hits 0 — the caller is expected to
    handle the entire-history-is-tool-pairs edge case via phase 2.
    """
    if len(messages) <= keep_recent:
        return 0
    boundary = len(messages) - keep_recent
    while boundary > 0:
        cur = messages[boundary]
        prev = messages[boundary - 1]
        cur_result_ids = _extract_tool_result_ids(cur)
        if not cur_result_ids:
            break
        prev_use_ids = _extract_tool_use_ids(prev)
        if cur_result_ids & prev_use_ids:
            boundary -= 1
            continue
        break
    return boundary


# ── Phase 2: orphan tool_result cleanup ─────────────────────────────


_ORPHAN_TOMBSTONE_TEXT = "[tool_result removed during compaction]"


def strip_orphan_tool_results(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop ``tool_result`` blocks whose ``tool_use_id`` isn't anywhere in ``messages``.

    Defensive cleanup for the case where the boundary algorithm
    couldn't move the cut back far enough (e.g., the very first
    message in the kept tail is itself an orphan). Returns a new
    list — the input is not mutated.

    **Matching contract**: a tool_result block survives iff
    *any* assistant message in ``messages`` carries a ``tool_use``
    with the same id. This is positional (ID appears somewhere)
    rather than causal (ID appears in a strictly preceding assistant
    message). The looser matcher is intentional for the post-
    boundary cleanup since the boundary algorithm already
    guarantees pair ordering for the recent tail; duplicate tool_use
    ids that appear non-adjacently are unusual but legal.

    **Role alternation preservation** (Codex MCP catch on
    PR-Hermes-3): if a user message loses ALL its content blocks
    to orphan stripping, the message is kept with a single
    placeholder text block (rather than dropped entirely) so
    consecutive-assistant role-alternation violations cannot occur
    in the carry-forward tail.
    """
    all_use_ids: set[str] = set()
    for msg in messages:
        all_use_ids |= _extract_tool_use_ids(msg)

    cleaned: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") != "user" or not isinstance(content, list):
            cleaned.append(msg)
            continue
        new_blocks: list[Any] = []
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and block.get("tool_use_id") not in all_use_ids
            ):
                continue
            new_blocks.append(block)
        if new_blocks:
            cleaned.append({**msg, "content": new_blocks})
        else:
            # Empty content list would either be rejected by providers
            # or, if simply dropped, would create role-alternation
            # violations (two consecutive assistant messages). Insert a
            # tombstone text block so the user-role slot survives.
            cleaned.append(
                {
                    **msg,
                    "content": [{"type": "text", "text": _ORPHAN_TOMBSTONE_TEXT}],
                }
            )
    return cleaned


def _extract_tool_use_ids(msg: dict[str, Any]) -> set[str]:
    if msg.get("role") != "assistant":
        return set()
    content = msg.get("content")
    if not isinstance(content, list):
        return set()
    ids: set[str] = set()
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tu_id = block.get("id")
            if isinstance(tu_id, str) and tu_id:
                ids.add(tu_id)
    return ids


def _extract_tool_result_ids(msg: dict[str, Any]) -> set[str]:
    if msg.get("role") != "user":
        return set()
    content = msg.get("content")
    if not isinstance(content, list):
        return set()
    ids: set[str] = set()
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            tr_id = block.get("tool_use_id")
            if isinstance(tr_id, str) and tr_id:
                ids.add(tr_id)
    return ids


# ── Phase 3: summarize ──────────────────────────────────────────────


def _build_summary_input(messages: list[dict[str, Any]]) -> str:
    """Convert messages to a flat text representation for summarization."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content[:2000]  # Cap per-message length for summary input
        elif isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict):
                    t = block.get("text", "") or block.get("content", "")
                    if isinstance(t, str):
                        texts.append(t[:500])
                elif isinstance(block, str):
                    texts.append(block[:500])
            text = " ".join(texts)[:2000]
        else:
            text = str(content)[:2000]
        if text.strip():
            parts.append(f"{role}: {text}")
    return "\n".join(parts)


async def _call_summarize(conversation_text: str, provider: str, model: str) -> str | None:
    """Call the LLM to generate a conversation summary.

    PR-ADAPTER-PATTERN-UNIFICATION (2026-05-28) — formerly fanned out to
    ``_summarize_openai`` / ``_summarize_glm`` via direct PAYG client
    builders (``_get_openai_client`` / ``_get_glm_client``). Now delegates
    to :func:`core.llm.adapters.dispatch.complete_text_via_adapters` which
    enumerates registered text-completion-capable adapters by operator
    source preference, honouring the same ``infer_source`` flow as the
    agent loop main path. The legacy ``provider`` argument now seeds the
    candidate ordering: it floats the requested provider to the front
    while keeping the fallback chain (operator might have only one
    provider's credentials).
    """
    from core.llm.adapters.dispatch import (
        AdapterDispatchError,
        AdapterUnavailableError,
        complete_text_via_adapters,
    )
    from core.llm.errors import BillingError

    # Map legacy provider key to the registry-canonical provider name.
    canonical = {"zhipuai": "glm"}.get(provider, provider)
    # PR-NO-FALLBACK (2026-05-28) — ``provider_order`` is now a *preference
    # seed* for the dispatch's default-resolved path, not a fallback chain.
    # Dispatch picks the first provider whose ``infer_source`` resolves to a
    # registered adapter, then tries exactly that one. If the requested
    # provider is the operator's actual configured one, it lands there;
    # otherwise dispatch may pick a different operator-configured provider
    # but never silently retries elsewhere on failure.
    default_order = ("anthropic", "openai", "glm")
    if canonical in default_order:
        provider_order = (canonical, *(p for p in default_order if p != canonical))
    else:
        provider_order = default_order

    try:
        result = await complete_text_via_adapters(
            conversation_text,
            system=_COMPACTION_PROMPT,
            model=model,
            max_tokens=2048,
            provider_order=provider_order,
        )
    except BillingError:
        log.warning(
            "Compaction summarization: adapter credit exhausted "
            "(provider=%s model=%s) — see dispatch.ADAPTER_DISPATCH_ATTEMPT log for adapter name",
            provider,
            model,
        )
        return None
    except AdapterUnavailableError:
        log.warning(
            "Compaction summarization: no text-completion-capable adapter "
            "registered (provider=%s model=%s)",
            provider,
            model,
        )
        return None
    except AdapterDispatchError:
        log.warning(
            "Compaction summarization: single attempt transient failure "
            "(provider=%s model=%s)",
            provider,
            model,
        )
        return None
    except Exception:
        log.exception("Compaction summarization failed for provider=%s", provider)
        return None
    return result.text or None


# ── Phase 4: carry-forward ──────────────────────────────────────────


def _carry_forward(summary: str, to_keep: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the new message list: summary + marker + recent verbatim tail.

    The summary lives in a 4-message preamble (user + assistant pair
    twice: once to deliver the summary, once to gate the marker) so
    the LLM has a consistent role-alternation pattern at the head of
    the conversation. Empirically this is more stable than a single
    system-style preamble at session resume.
    """
    return [
        {"role": "user", "content": f"[Conversation Summary]\n{summary}"},
        {"role": "assistant", "content": "Understood. I have the summary context."},
        {"role": "user", "content": COMPACTION_MARKER},
        {"role": "assistant", "content": "Acknowledged. Continuing from where we left off."},
        *to_keep,
    ]


__all__ = [
    "COMPACTION_MARKER",
    "compact_conversation",
    "find_safe_boundary",
    "strip_orphan_tool_results",
]
