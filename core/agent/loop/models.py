"""Result dataclass + context-exhausted exception/helpers for AgenticLoop.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7).
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm.token_tracker import LLMUsage

log = logging.getLogger(__name__)


class _ContextExhaustedError(Exception):
    """Raised when context remains critical after pruning — unrecoverable."""


_EXHAUSTED_FALLBACK = (
    "Context window exhausted. "
    "This conversation has been automatically reset — "
    "please start a new thread or send a new message to continue."
)

_EXHAUSTED_SYSTEM = (
    "The conversation context has been exhausted and automatically reset. "
    "Reply ONLY with a short notice (1-2 sentences) in the SAME language as the user's message. "
    "Tell them the conversation was reset and they should start a new thread or send a new message."
)


async def _context_exhausted_message(user_input: str) -> str:
    """Generate context-exhausted message in the user's language via lightweight LLM call.

    PR-EXTRACT-LEARNING-MODELS-ADAPTER (2026-05-28) — dispatches through
    :func:`core.llm.adapters.dispatch.complete_text_via_adapters` so a
    ChatGPT-subscription-only operator (no Anthropic key) finally gets
    a language-matched notice. The previous direct ``anthropic.Anthropic``
    instantiation returned the static English fallback for that operator
    every time, defeating the localisation intent. Provider preference
    ``("anthropic", "openai", "glm")`` preserves the historic Haiku-
    first ordering while opening the gpt-5.x + GLM paths.

    Returns the static ``_EXHAUSTED_FALLBACK`` on every failure (billing,
    transient, no-credential) — graceful by design, the loop surfaces
    SOME message to the user even on a fully-degraded credential surface.
    """
    from core.config import ANTHROPIC_BUDGET
    from core.llm.adapters.dispatch import (
        AdapterDispatchError,
        AdapterUnavailableError,
        complete_text_via_adapters,
    )
    from core.llm.errors import BillingError

    # PR-NO-FALLBACK (2026-05-28) — strict single-adapter dispatch picks
    # the first provider in this order whose ``infer_source`` resolves to
    # a registered adapter, then tries that single adapter. The static
    # ``_EXHAUSTED_FALLBACK`` covers every failure mode; the dispatch
    # layer's INFO log records exactly which adapter was tried and why
    # it failed so operators see honest per-attempt observability.
    try:
        result = await complete_text_via_adapters(
            user_input[:200],
            system=_EXHAUSTED_SYSTEM,
            max_tokens=150,
            provider_order=("anthropic", "openai", "glm"),
            model_by_provider={"anthropic": ANTHROPIC_BUDGET},
        )
    except BillingError:
        log.debug("Exhausted message: adapter credit exhausted — static fallback")
        return _EXHAUSTED_FALLBACK
    except AdapterUnavailableError:
        log.debug("Exhausted message: no capable adapter registered — static fallback")
        return _EXHAUSTED_FALLBACK
    except AdapterDispatchError:
        log.debug("Exhausted message: single attempt transient failure — static fallback")
        return _EXHAUSTED_FALLBACK
    except Exception:
        log.debug("Exhausted message LLM call failed, using fallback", exc_info=True)
        return _EXHAUSTED_FALLBACK
    return (result.text or "").strip() or _EXHAUSTED_FALLBACK


@dataclass
class AgenticResult:
    """Result of an agentic loop execution.

    ``usage`` (Defect A F-A1 / 2026-05-11) carries the aggregated
    ``LLMUsage`` for *this* arun invocation only — captured via a
    ``TokenTracker.snapshot()`` taken at the start of ``arun`` and a
    ``delta_since(snap)`` at finalize time. It is ``None`` when the
    loop terminated before any LLM call (e.g. context-exhausted
    fallback). Used by the petri ``GeodeModelAPI`` adapter to surface
    target-side tokens into ``inspect_ai`` ``role_usage`` — without
    it, custom ModelAPI implementations are invisible to the inspect
    log's ``role_usage`` aggregation (see ``inspect_ai.log._log``).
    """

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    error: str | None = None
    # "natural" | "forced_text" | "max_rounds" | "time_budget_expired"
    # | "llm_error" | "context_exhausted" | "cost_budget_exceeded"
    # | "model_action_required" — LLM error retried up to cap; user must
    #   switch model/provider via /model and re-run. Diagnostic in ``text``.
    # | "model_refusal" — Fable 5 safety classifier declined (stop_reason
    #   "refusal", HTTP 200); text carries the category when reported.
    # | "user_clarification_needed" — overthinking detected (consecutive
    #   high-token text-only rounds with no tool use). Loop stops and asks
    #   the user to narrow the request.
    termination_reason: str = "unknown"
    summary: str = ""  # Tier 1 compact action summary (auto-generated)
    reasoning_metrics: dict[str, object] | None = None
    usage: "LLMUsage | None" = None  # noqa: UP037 — forward-ref for cycle avoidance

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}
