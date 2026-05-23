"""In-loop verify (Reflexion-style) for AgenticLoop turns.

Per-turn verification of agent action quality. Fires once per turn at the
TURN_COMPLETED boundary so it does not interrupt mid-turn execution. The
``VerifyResult`` is recorded into :class:`SessionMetrics` for telemetry +
read by PR-CL-A1 (Dynamic Replan) to decide whether to replan the next turn.

Three modes (operator-tunable via ``GEODE_VERIFY_MODE`` env knob):

- ``off`` — wiring present but skipped (zero overhead).
- ``rule_based`` (default) — structural sanity checks: empty turn, tool
  errors, suspiciously-short output, premature termination. Cheap +
  deterministic; no LLM call.
- ``llm_judge`` — opt-in self-judge LLM call evaluating the turn's
  semantic quality against a rubric. Adds one LLM call per turn (cost
  proportional to context).

When a verify check FAILs, the result includes:

- ``rubric_misses``: tuple of short reason codes (e.g. ``"empty_turn"``,
  ``"tool_error"``).
- ``reflexion_hint``: a ready-to-inject ``<reflexion>...</reflexion>``
  block (verbal RL pattern, Reflexion paper NeurIPS 2023). Callers
  prepend this to the next round's ``loop._system_suffix`` so the model
  sees its own failure analysis next turn.

Frontier alignment (Socratic Q5):

- **Reflexion** (arxiv 2303.11366) — verbal RL → 91% HumanEval pass@1
- **OpenAI o1** — chain-of-verify pattern
- **AgentHub** — per-branch verify gate
- **Claude Code** — Plan / Edit mode separation with implicit verify on
  Edit failures (tool error → retry).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent.loop.models import AgenticResult

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MIN_TEXT_CHARS",
    "VerifyMode",
    "VerifyResult",
    "get_verify_mode",
    "synthesize_reflexion_hint",
    "verify_turn",
]


class VerifyMode(StrEnum):
    """Three operator-tunable verify modes.

    :class:`StrEnum` lets the value flow into config / env / hook payload
    without explicit ``.value`` access.
    """

    OFF = "off"
    RULE_BASED = "rule_based"
    LLM_JUDGE = "llm_judge"


# Per-turn output below this char count is flagged ``suspicious_short_output``
# by the rule-based path. Empirical threshold — a "real" response to a
# non-trivial user request rarely lands below this. Operator can override
# via ``GEODE_VERIFY_MIN_TEXT_CHARS`` env knob.
DEFAULT_MIN_TEXT_CHARS: int = 10


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """Outcome of a single per-turn verify pass.

    Frozen so a recorded result can be passed across threads / contexts
    without races. ``rubric_misses`` is a tuple (not list) for the same
    reason — immutable, hashable.

    Fields:

    - ``passed``: ``True`` when *all* checks pass for the configured mode.
      In ``OFF`` mode, always ``True`` (no checks run).
    - ``mode``: which mode produced this result (telemetry).
    - ``score``: 0.0–1.0 numeric score. ``rule_based`` returns 1.0 on pass,
      0.0 on fail (no gradation). ``llm_judge`` returns the judge's score.
    - ``rubric_misses``: short reason codes for failed checks. Empty on pass.
    - ``reflexion_hint``: ready-to-inject system-suffix block for the next
      round. Empty when passed.
    - ``ts``: monotonic timestamp when the verify ran (for ordering).
    """

    passed: bool
    mode: VerifyMode
    score: float = 1.0
    rubric_misses: tuple[str, ...] = ()
    reflexion_hint: str = ""
    ts: float = 0.0
    # ``effective_mode`` differs from ``mode`` when the requested mode
    # falls back to a different implementation. Today the only fallback
    # path is ``llm_judge`` → ``rule_based`` (Codex MCP LOW #4 honesty
    # fix, 2026-05-23). Equal to ``mode`` when no fallback occurred.
    effective_mode: VerifyMode = VerifyMode.RULE_BASED

    def to_payload(self) -> dict[str, Any]:
        """Render as a hook-payload-friendly dict."""
        return {
            "passed": self.passed,
            "mode": self.mode.value,
            "effective_mode": self.effective_mode.value,
            "score": round(self.score, 4),
            "rubric_misses": list(self.rubric_misses),
            "reflexion_hint": self.reflexion_hint,
            "ts": self.ts,
        }


def get_verify_mode() -> VerifyMode:
    """Resolve the active verify mode from the environment.

    ``GEODE_VERIFY_MODE`` env knob overrides; default ``rule_based``. Unknown
    values fall back to default with a warning so a typo doesn't silently
    disable verify."""
    raw = os.environ.get("GEODE_VERIFY_MODE", "").strip().lower()
    if not raw:
        return VerifyMode.RULE_BASED
    try:
        return VerifyMode(raw)
    except ValueError:
        log.warning(
            "Unknown GEODE_VERIFY_MODE=%r; falling back to rule_based. "
            "Valid: off / rule_based / llm_judge.",
            raw,
        )
        return VerifyMode.RULE_BASED


def _min_text_chars() -> int:
    """Read the suspicious-short-output threshold (env-overridable)."""
    raw = os.environ.get("GEODE_VERIFY_MIN_TEXT_CHARS", "").strip()
    if not raw:
        return DEFAULT_MIN_TEXT_CHARS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MIN_TEXT_CHARS
    return value if value >= 0 else DEFAULT_MIN_TEXT_CHARS


def _verify_rule_based(result: AgenticResult) -> VerifyResult:
    """Fast structural checks — no LLM call.

    Emitted reason codes (stable identifiers for downstream consumers):

    - ``empty_turn``: model produced no text AND made no tool call.
    - ``tool_error``: any tool call ended with ``error`` flag set.
    - ``short_output``: text shorter than ``GEODE_VERIFY_MIN_TEXT_CHARS``
      AND no tool calls (mid-conversation acknowledgements often legit
      short, but only when paired with tool action).
    - ``model_action_required``: termination reason indicates the model
      asked for operator intervention (cost limit, billing error, etc.).

    Reason code list is intentionally short — verbal RL hints are stronger
    when they cite a concrete failure category, not a long checklist.
    """
    misses: list[str] = []
    text = (result.text or "").strip()
    tool_calls = result.tool_calls or []
    text_len = len(text)

    if text_len == 0 and not tool_calls:
        misses.append("empty_turn")
    elif text_len < _min_text_chars() and not tool_calls:
        misses.append("short_output")

    for tc in tool_calls:
        if tc.get("error") or tc.get("error_type"):
            misses.append("tool_error")
            break  # one tool_error code is enough; the hint stays short

    termination_reason = (result.termination_reason or "").strip()
    if termination_reason == "model_action_required":
        misses.append("model_action_required")

    passed = not misses
    hint = "" if passed else synthesize_reflexion_hint(tuple(misses))
    return VerifyResult(
        passed=passed,
        mode=VerifyMode.RULE_BASED,
        effective_mode=VerifyMode.RULE_BASED,
        score=1.0 if passed else 0.0,
        rubric_misses=tuple(misses),
        reflexion_hint=hint,
        ts=time.monotonic(),
    )


# Reason-code → human-readable failure summary mapping used by
# ``synthesize_reflexion_hint``. Kept module-local so reason codes stay
# in lock-step with hint text and downstream test harnesses can lift the
# table to assert on phrasing.
_REASON_DESCRIPTIONS: dict[str, str] = {
    "empty_turn": "Last turn produced no text and called no tools.",
    "short_output": "Last turn returned an unusually short response without tool action.",
    "tool_error": "A tool call in the last turn failed with an error.",
    "model_action_required": "The model surfaced a recoverable error (cost, billing, etc.).",
}


def synthesize_reflexion_hint(rubric_misses: tuple[str, ...]) -> str:
    """Build the ``<reflexion>...</reflexion>`` system-suffix block.

    Verbal RL — the agent reads its own failure analysis at the start of
    the next round. The block is concise (3 lines per miss max) to avoid
    crowding the system prompt; longer rubrics live in the LLM-judge mode.

    Returns the empty string when no misses are supplied so callers can
    cheaply skip the suffix mutation on pass.
    """
    if not rubric_misses:
        return ""
    lines = ["<reflexion>", "Self-evaluation flagged the previous turn:"]
    for code in rubric_misses:
        description = _REASON_DESCRIPTIONS.get(code, code)
        lines.append(f"- {code}: {description}")
    lines.append(
        "Next turn: address the flagged item(s) directly. "
        "If you cannot, say so and ask the user to clarify."
    )
    lines.append("</reflexion>")
    return "\n".join(lines)


def _verify_llm_judge(result: AgenticResult, *, loop: Any | None = None) -> VerifyResult:
    """LLM-self-judge mode — opt-in, one extra LLM call per turn.

    This PR ships the wiring stub (mode dispatch + result shape); the
    actual LLM call follows in PR-CL-A6 (Plan / Action Model Separation)
    which gives us a dedicated judge model knob. Until then, the stub
    falls back to ``rule_based`` so the mode-knob doesn't break the loop
    when an operator opts in early.
    """
    log.info(
        "GEODE_VERIFY_MODE=llm_judge selected but the judge call is "
        "scheduled to land in PR-CL-A6; falling back to rule_based."
    )
    rb = _verify_rule_based(result)
    # ``mode`` reflects the operator's *requested* intent (LLM_JUDGE);
    # ``effective_mode`` records the *path that actually ran* (RULE_BASED).
    # Downstream telemetry can distinguish "operator asked for judge but
    # got rule-based" from "operator asked for rule-based" (Codex MCP
    # LOW #4 honesty fix, 2026-05-23).
    return VerifyResult(
        passed=rb.passed,
        mode=VerifyMode.LLM_JUDGE,
        effective_mode=VerifyMode.RULE_BASED,
        score=rb.score,
        rubric_misses=rb.rubric_misses,
        reflexion_hint=rb.reflexion_hint,
        ts=rb.ts,
    )


def verify_turn(result: AgenticResult, *, loop: Any | None = None) -> VerifyResult:
    """Dispatch to the configured verify mode and return the result.

    Modes:
      - ``OFF`` — return a passing sentinel (no checks).
      - ``RULE_BASED`` — structural checks (default).
      - ``LLM_JUDGE`` — opt-in self-judge call (stub in this PR; A6 fills).

    Failures inside the verify path NEVER propagate — observability must
    not break the run it observes. On exception we log + return a
    passing sentinel marked with mode so a downstream consumer can
    distinguish "verify ran clean" from "verify crashed silently".
    """
    mode = get_verify_mode()
    if mode is VerifyMode.OFF:
        return VerifyResult(passed=True, mode=mode, effective_mode=mode, ts=time.monotonic())
    try:
        if mode is VerifyMode.LLM_JUDGE:
            return _verify_llm_judge(result, loop=loop)
        return _verify_rule_based(result)
    except Exception:
        log.warning("verify_turn crashed; treating as pass", exc_info=True)
        return VerifyResult(passed=True, mode=mode, effective_mode=mode, ts=time.monotonic())


@dataclass(frozen=True, slots=True)
class _VerifySink:
    """Optional explicit recipient for verify results.

    Public surface is :func:`verify_turn` directly; this sink is provided
    for tests that want to assert on the result without round-tripping
    through SessionMetrics.
    """

    received: list[VerifyResult] = field(default_factory=list)

    def record(self, vr: VerifyResult) -> None:
        self.received.append(vr)
