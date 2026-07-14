"""Result dataclass + context-exhausted exception/helpers for AgenticLoop.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7).
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm.token_tracker import LLMUsage

log = logging.getLogger(__name__)


class TerminationReason(StrEnum):
    """Closed alphabet of AgenticLoop terminal states.

    Every terminal :class:`AgenticResult` is born through
    ``AgenticLoop._terminal_result`` with one of these members — the loop's
    exit state space is this enum, nothing else. ``StrEnum`` keeps every
    existing string comparison and JSON serialization working unchanged.

    Consumers that persist or transport results (worker sub-agent protocol,
    checkpoints, transcripts) see plain strings; parse back leniently with
    ``TerminationReason(value)`` and catch ``ValueError`` for forward
    compatibility.
    """

    # Ordinary completion
    NATURAL = "natural"  # model produced a final text answer
    FORCED_TEXT = "forced_text"  # last allowed round forced a text answer

    # Round/time budget guards (while-condition exits)
    MAX_ROUNDS = "max_rounds"
    TIME_BUDGET_EXPIRED = "time_budget_expired"
    SESSION_TIME_BUDGET_HANDOFF = "session_time_budget_handoff"
    SESSION_TIME_BUDGET_EXPIRED = "session_time_budget_expired"

    # Resource/limit terminals
    CONTEXT_EXHAUSTED = "context_exhausted"
    COST_BUDGET_EXCEEDED = "cost_budget_exceeded"
    BILLING_ERROR = "billing_error"

    # Model-behaviour guards
    MODEL_ACTION_REQUIRED = "model_action_required"  # LLM error retry cap hit
    MODEL_REFUSAL = "model_refusal"  # safety classifier declined (HTTP 200)
    USER_CLARIFICATION_NEEDED = "user_clarification_needed"  # overthinking
    CONVERGENCE_DETECTED = "convergence_detected"  # repeating failure pattern
    REPEATED_SUCCESS_NO_PROGRESS = "repeated_success_no_progress"

    # Caller-driven exits
    INPUT_BLOCKED = "input_blocked"  # USER_INPUT_RECEIVED interceptor
    USER_CANCELLED = "user_cancelled"
    ACTIONABLE_PARTIAL = "actionable_partial"  # opted-in partial preserve
    TOOL_USE_YIELD = "tool_use_yield"  # external orchestrator owns next turn

    # Legacy — documented consumers exist (worker retry catalogue, UI event
    # lists) but no current producer site constructs it.
    LLM_ERROR = "llm_error"

    UNKNOWN = "unknown"


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
    every time, defeating the localisation intent. The helper now routes
    through the current configured model's provider/source only; it never
    scans a cross-provider order.

    Returns the static ``_EXHAUSTED_FALLBACK`` on every failure (billing,
    transient, no-credential) — graceful by design, the loop surfaces
    SOME message to the user even on a fully-degraded credential surface.
    """
    from core.config import _resolve_provider, settings
    from core.llm.adapters._source_inference import infer_source
    from core.llm.adapters.dispatch import (
        AdapterDispatchError,
        AdapterUnavailableError,
        complete_text_via_adapters,
    )
    from core.llm.adapters.registry import normalize_registry_provider
    from core.llm.errors import BillingError

    model = settings.model
    provider = normalize_registry_provider(_resolve_provider(model))
    source = infer_source(provider)
    # The static ``_EXHAUSTED_FALLBACK`` covers every failure mode; the
    # dispatch layer records exactly which adapter was tried.
    try:
        result = await complete_text_via_adapters(
            user_input[:200],
            system=_EXHAUSTED_SYSTEM,
            model=model,
            max_tokens=150,
            prefer_provider=provider,
            prefer_source=source,
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
    # Closed value space — see :class:`TerminationReason`. StrEnum members
    # ARE strings, so serialized results and string comparisons are
    # unchanged; deserializers may still carry plain str.
    termination_reason: TerminationReason | str = TerminationReason.UNKNOWN
    summary: str = ""  # Tier 1 compact action summary (auto-generated)
    reasoning_metrics: dict[str, object] | None = None
    usage: "LLMUsage | None" = None  # noqa: UP037 — forward-ref for cycle avoidance

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}
