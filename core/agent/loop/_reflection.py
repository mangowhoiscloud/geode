"""Reflection node — LLM-driven belief update after the tool batch.

PR-3 C-2 of the cognitive-loop-uplift sprint
(``docs/plans/2026-05-21-cognitive-loop-uplift.md``).

Pre-PR-3 the agentic loop went tool result → next action with no
explicit belief-update step. ``CognitiveState.hypotheses`` and
``CognitiveState.confidence`` were declared in PR-2 but never
populated. Without a reflection step, downstream features (PR-4
episodic memory, PR-5 causal attribution) have no current-belief
signal to record against an outcome.

The reflection node runs ONE LLM call after every tool-use round.
It sees only the cognitive-state snapshot + a compact tool-result
summary (NOT the full conversation — clean-context discipline) and
returns a small JSON object with:

  hypotheses[<=5]   — short claims about the task state
  confidence ∈ [0,1] — overall confidence the goal will be achieved
  next_action_hint  — short hint pushed into ``state.subgoals``

Settings knobs (see ``core.config._settings``):
  cognitive_reflection_enabled       (bool, default True)
  cognitive_reflection_model         (str, default haiku-4.5)
  cognitive_reflection_max_tokens    (int, default 512)

Dispatch goes through ``core.llm.router.call_with_failover`` so the
reflection call shares the same credential rotator + retry path as
every other provider-aware caller (paperclip-style abstraction
established by PR-1).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.agent.cognitive_state import CognitiveState
from core.config import _resolve_provider
from core.llm.adapters import resolve_agentic_adapter
from core.llm.router import call_with_failover

log = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "You are the reflection node of an autonomous execution agent. "
    "Given the agent's current cognitive state and a compact summary "
    "of the round that just finished, produce a JSON object that "
    "updates the agent's beliefs.\n\n"
    "Output schema (return ONLY this JSON, no prose):\n"
    "{\n"
    '  "hypotheses": ["short claim 1", ...],  // <= 5 entries, each <= 120 chars\n'
    '  "confidence": 0.0,                      // float in [0,1]\n'
    '  "next_action_hint": "..."               // <= 120 chars, what to try next\n'
    "}\n\n"
    "Prefer pruning stale hypotheses over piling new ones; the loop "
    "tracks evolution not history. If the round produced no useful "
    "signal, keep the previous hypotheses and lower confidence."
)


def _summarise_tool_results(tool_results: list[dict[str, Any]], *, cap: int = 8) -> str:
    """Build a compact prompt-safe summary of the tool batch results.

    Each entry becomes ``- <tool_use_id>: <head>`` where ``head`` is
    the first 200 chars of any text content. The block is capped at
    ``cap`` entries to keep the prompt small — reflection sees a
    snapshot, not a transcript.
    """
    if not tool_results:
        return "(no tool results — text-only round)"
    lines: list[str] = []
    for block in tool_results[:cap]:
        tid = str(block.get("tool_use_id", "?"))
        content = block.get("content")
        head = ""
        if isinstance(content, str):
            head = content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    head = part["text"]
                    break
        head = head.strip().replace("\n", " ")
        if len(head) > 200:
            head = head[:200] + "…"
        lines.append(f"- {tid}: {head or '(empty)'}")
    if len(tool_results) > cap:
        lines.append(f"- … ({len(tool_results) - cap} more results truncated)")
    return "\n".join(lines)


def _build_user_prompt(state: CognitiveState, tool_summary: str) -> str:
    """Compose the user-side prompt that the reflection LLM sees."""
    return (
        f"Goal: {state.goal!r}\n"
        f"Subgoals: {state.subgoals!r}\n"
        f"Round count: {state.round_count}\n"
        f"Last action: {state.last_action!r}\n"
        f"Last observation: {state.last_observation!r}\n"
        f"Previous hypotheses: {state.hypotheses!r}\n"
        f"Previous confidence: {state.confidence!r}\n\n"
        f"Tool batch results:\n{tool_summary}\n\n"
        "Return ONLY the JSON object specified in the system prompt."
    )


def _parse_reflection(text: str) -> dict[str, Any]:
    """Parse the reflection LLM output into a structured dict.

    The LLM is instructed to return only JSON. In practice models
    sometimes wrap it in a ```json``` fence or prose; strip those
    cases. Anything that cannot be parsed raises ``ValueError`` so
    the caller can fall back to keeping the previous state.
    """
    stripped = text.strip()
    # Tolerate ```json fences
    if stripped.startswith("```"):
        # drop the opening fence (with or without language tag)
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        # drop trailing fence
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[: -len("```")]
        stripped = stripped.strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError(f"reflection output is not a JSON object: {type(parsed).__name__}")
    return parsed


def _apply_reflection(state: CognitiveState, parsed: dict[str, Any]) -> None:
    """Update ``state`` in-place with reflection output.

    Schema-typed casts — invalid types per field silently drop that
    field rather than poisoning the entire state. PR-3 prefers
    *partial* belief update over complete rejection so a flaky
    reflection model still moves the needle.
    """
    hypotheses_raw = parsed.get("hypotheses")
    if isinstance(hypotheses_raw, list):
        cleaned: list[str] = []
        for item in hypotheses_raw[:5]:
            if isinstance(item, str):
                head = item.strip()
                if head:
                    cleaned.append(head[:120])
        state.hypotheses = cleaned

    confidence_raw = parsed.get("confidence")
    if isinstance(confidence_raw, int | float):
        state.confidence = max(0.0, min(1.0, float(confidence_raw)))

    hint_raw = parsed.get("next_action_hint")
    if isinstance(hint_raw, str):
        hint = hint_raw.strip()
        if hint:
            head = hint[:120]
            # subgoals is a rolling stack of hints — keep the last 5
            state.subgoals.append(head)
            if len(state.subgoals) > 5:
                del state.subgoals[0 : len(state.subgoals) - 5]


async def reflect_async(
    state: CognitiveState,
    tool_results: list[dict[str, Any]],
    *,
    model: str,
    max_tokens: int,
) -> None:
    """Run the reflection LLM call and update ``state`` in place.

    Errors (LLM failure, JSON parse failure, schema mismatch) are
    logged at WARN and swallowed — the loop must remain robust to a
    flaky reflection model. The next round just re-runs reflection
    with the same previous state.

    Dispatch goes through ``core.llm.router.call_with_failover`` so
    the call shares the credential rotator with the rest of GEODE
    (paperclip-style abstraction established by PR-1 G-A).
    """
    provider = _resolve_provider(model)
    adapter = resolve_agentic_adapter(provider)
    tool_summary = _summarise_tool_results(tool_results)
    user_prompt = _build_user_prompt(state, tool_summary)

    log.info(
        "reflection dispatch: model=%s provider=%s round=%d max_tokens=%d",
        model,
        provider,
        state.round_count,
        max_tokens,
    )

    async def _do_call(m: str) -> object:
        return await adapter.agentic_call(
            model=m,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[],
            tool_choice={"type": "auto"},
            max_tokens=max_tokens,
            temperature=0.2,
        )

    try:
        response, _used_model = await call_with_failover([model], _do_call)
    except Exception:
        log.warning("reflection LLM call raised; keeping previous state", exc_info=True)
        return

    if response is None:
        log.warning("reflection LLM call returned None (model=%s); keeping previous state", model)
        return

    text_chunks: list[str] = []
    for block in getattr(response, "content", []):
        block_text = getattr(block, "text", "")
        if block_text:
            text_chunks.append(block_text)
    raw = "".join(text_chunks)
    if not raw:
        log.warning("reflection LLM returned empty text; keeping previous state")
        return

    try:
        parsed = _parse_reflection(raw)
    except (ValueError, json.JSONDecodeError):
        log.warning("reflection output not valid JSON; keeping previous state. raw=%r", raw[:200])
        return

    _apply_reflection(state, parsed)


__all__ = ["reflect_async"]
