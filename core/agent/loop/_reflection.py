"""Reflection node — LLM-driven belief update after the tool batch.

PR-3 C-2 of the cognitive-loop-uplift sprint
(``docs/plans/2026-05-21-cognitive-loop-uplift.md``).

PR-B (2026-05-21) — migrated the reflection call from free-form
JSON-in-text to Anthropic ``tool_use`` structured output. Pre-PR-B
the system prompt asked the LLM to "Return ONLY this JSON, no
prose" but models frequently disobeyed (wrapped in ``"Here is the
JSON: {...}"``, ``` ```json``` fences, trailing prose, etc.), and
a 5-stage forgiving parser handled the drift. Codex MCP caught
parser gaps 3 times during PR-3. The fix is to use the structured-
output contract every other GEODE provider-aware caller already
uses: declare a tool with a JSON ``input_schema`` + ``strict:
True`` opt-in, prefer its invocation via ``tool_choice="auto"``,
and read the parsed ``input`` dict directly off the
``ToolUseBlock``. We use ``"auto"`` rather than forced
``"any"`` / ``{"type": "tool"}`` because both forced shapes are
incompatible with Anthropic extended/adaptive thinking — only
``"auto"`` works across every model + thinking regime (Codex MCP
PR-B review #2). With one tool declared and a strong system
prompt the LLM still calls the tool on the happy path; rare
declines fall through to a WARN + keep-previous-state path.

Pre-PR-3 the agentic loop went tool result → next action with no
explicit belief-update step. ``CognitiveState.hypotheses`` and
``CognitiveState.confidence`` were declared in PR-2 but never
populated. Without a reflection step, downstream features (PR-4
episodic memory, PR-5 causal attribution) have no current-belief
signal to record against an outcome.

The reflection node runs ONE LLM call after every tool-use round.
It sees only the cognitive-state snapshot + a compact tool-result
summary (NOT the full conversation — clean-context discipline) and
invokes the ``record_reflection`` tool which carries:

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

import logging
from typing import Any

from core.agent.cognitive_state import CognitiveState
from core.config import _resolve_provider
from core.llm.adapters import resolve_agentic_adapter
from core.llm.router import call_with_failover

log = logging.getLogger(__name__)


REFLECTION_TOOL_NAME = "record_reflection"


_REFLECTION_TOOL: dict[str, Any] = {
    "name": REFLECTION_TOOL_NAME,
    "description": (
        "Record the agent's updated beliefs after the round that just finished. "
        "Prefer pruning stale hypotheses over piling new ones — the loop tracks "
        "evolution not history. If the round produced no useful signal, keep "
        "the previous hypotheses and lower confidence."
    ),
    # PR-B fix-up #1 — ``strict: True`` opts into Anthropic's strict
    # tool-input validation so a malformed payload is rejected server-
    # side instead of needing client-side coercion. Codex MCP review
    # called out that the previous "Anthropic enforces schema" claim
    # was overstated without this flag. See
    # https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "hypotheses": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Short claims about the task state (each <= 120 chars).",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Overall confidence the goal will be achieved.",
            },
            "next_action_hint": {
                "type": "string",
                "description": "Single-line hint for what to try next (<= 120 chars).",
            },
        },
        "required": ["hypotheses", "confidence"],
    },
}


_SYSTEM_PROMPT = (
    "You are the reflection node of an autonomous execution agent. "
    "Given the agent's current cognitive state and a compact summary "
    "of the round that just finished, invoke the "
    f"``{REFLECTION_TOOL_NAME}`` tool to update the agent's beliefs. "
    "Do NOT emit free-form prose; the tool call is the only required "
    "output."
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
        f"Invoke the {REFLECTION_TOOL_NAME} tool now."
    )


def _extract_reflection_input(response: Any) -> dict[str, Any] | None:
    """Find the ``record_reflection`` tool_use block in the response.

    Returns the tool's ``input`` dict (already parsed by the adapter
    normalizer — see :class:`core.llm.agentic_response.ToolUseBlock`).
    Returns ``None`` when the model declined to invoke the tool;
    callers swallow this case with a WARN.
    """
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == (
            REFLECTION_TOOL_NAME
        ):
            payload = getattr(block, "input", None)
            if isinstance(payload, dict):
                return payload
    return None


def _apply_reflection(state: CognitiveState, parsed: dict[str, Any]) -> None:
    """Update ``state`` in-place with reflection output.

    Schema-typed casts — even though the Anthropic schema validator
    enforces field types server-side, the dispatcher fork (GLM /
    OpenAI / Codex) may not. Drop fields with the wrong type
    silently rather than poisoning the entire state. PR-3 prefers
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
    # ``bool`` is an ``int`` subclass — exclude explicitly so
    # ``True``/``False`` doesn't collapse to ``1.0``/``0.0`` and
    # mute a real confidence signal (Codex MCP review of PR-5
    # caught the same anti-pattern in the mutator schema).
    if isinstance(confidence_raw, int | float) and not isinstance(confidence_raw, bool):
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

    PR-B (2026-05-21) — uses ``tool_use`` structured output (the
    ``record_reflection`` tool with ``strict: True`` schema +
    ``tool_choice="auto"``). The Anthropic API validates the schema
    server-side when ``strict`` is set, so we read ``input``
    directly off the returned ``ToolUseBlock``.

    Errors (LLM failure, model declined the tool, schema mismatch
    on a non-Anthropic provider) are logged at WARN and swallowed —
    the loop must remain robust to a flaky reflection model. The
    next round just re-runs reflection with the same previous state.

    Dispatch goes through ``core.llm.router.call_with_failover`` so
    the call shares the credential rotator with the rest of GEODE
    (paperclip-style abstraction established by PR-1 G-A).
    """
    # The try block wraps the ENTIRE LLM path including provider /
    # adapter resolution (Codex MCP fix-up — setup failures used to
    # escape and break the agentic loop, violating the "errors
    # swallowed at WARN" guarantee).
    try:
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

        # ADR-012 S0b — 5축의 ``reflection`` SoT 가 인퍼런스 경로에서
        # 실제로 적용되는 단일 지점. 정책이 부재하면 ``apply_reflection_policy``
        # 는 입력 그대로 반환 (현재 행동 보존).
        from core.agent.reflection_policy import (
            _load_reflection_policy_override,
            apply_reflection_policy,
        )

        active_tool, active_system = apply_reflection_policy(
            _REFLECTION_TOOL, _SYSTEM_PROMPT, _load_reflection_policy_override()
        )

        async def _do_call(m: str) -> object:
            # PR-B fix-up #2 — ``tool_choice="auto"``. Anthropic docs
            # mark *both* ``"any"`` and named-tool forcing as
            # incompatible with extended/adaptive thinking, so
            # operators who pick Opus 4.7 / Sonnet 4.6 via
            # ``/model reflection`` would otherwise hit a 400. Only
            # ``"auto"`` works across every model + thinking regime.
            # With one tool declared + a strong "invoke the tool"
            # system prompt the LLM still calls the tool on the
            # happy path; the rare decline is handled gracefully by
            # ``_extract_reflection_input → None → keep previous
            # state``. Cross-provider: ``"auto"`` normalises to
            # ``"auto"`` on OpenAI/Codex via the shared normaliser.
            from core.config import settings as _settings

            return await adapter.agentic_call(
                model=m,
                system=active_system,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[active_tool],
                tool_choice="auto",
                max_tokens=max_tokens,
                temperature=_settings.temperature_reflection,
            )

        response, _used_model = await call_with_failover([model], _do_call)
    except Exception:
        log.warning(
            "reflection setup/LLM call raised; keeping previous state",
            exc_info=True,
        )
        return

    if response is None:
        log.warning("reflection LLM call returned None (model=%s); keeping previous state", model)
        return

    parsed = _extract_reflection_input(response)
    if parsed is None:
        log.warning(
            "reflection response did not include a %s tool_use block; keeping previous state",
            REFLECTION_TOOL_NAME,
        )
        return

    _apply_reflection(state, parsed)


__all__ = ["REFLECTION_TOOL_NAME", "reflect_async"]
