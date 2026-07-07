"""In-loop verify for AgenticLoop turns.

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
- ``reflection_hint``: a ready-to-inject ``<reflection>...</reflection>``
  block (verbal-RL pattern, Reflexion paper NeurIPS 2023). Callers
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

from core.agent.loop._reflection import (
    synthesize_failure_reflection_hint,
    synthesize_reflexion_hint,
)

if TYPE_CHECKING:
    from core.agent.loop.models import AgenticResult

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MIN_TEXT_CHARS",
    "VerifyMode",
    "VerifyResult",
    "get_verify_mode",
    "synthesize_failure_reflection_hint",
    "synthesize_reflection_hint",
    "synthesize_reflexion_hint",
    "verify_turn",
]

synthesize_reflection_hint = synthesize_failure_reflection_hint


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

# Rubric misses that PR-CL-A1 (Dynamic Replan) should retry from. Hard
# failures like ``model_action_required`` request operator intervention
# (cost cap / billing) so retry would just burn more tokens. The other
# three codes are recoverable via a different prompt or tool path.
_RETRYABLE_MISSES: frozenset[str] = frozenset(
    {
        "empty_turn",
        "short_output",
        "tool_error",
        "step_expected_mismatch",
        "manual_checklist_without_action",
    }
)


@dataclass(frozen=True, slots=True, init=False)
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
    - ``reflection_hint``: ready-to-inject system-suffix block for the next
      round. Empty when passed.
    - ``ts``: monotonic timestamp when the verify ran (for ordering).
    """

    passed: bool
    mode: VerifyMode
    score: float = 1.0
    rubric_misses: tuple[str, ...] = ()
    reflection_hint: str = ""
    ts: float = 0.0
    # ``effective_mode`` differs from ``mode`` when the requested mode
    # falls back to a different implementation. Today the only fallback
    # path is ``llm_judge`` → ``rule_based`` (Codex MCP LOW #4 honesty
    # fix, 2026-05-23). Equal to ``mode`` when no fallback occurred.
    effective_mode: VerifyMode = VerifyMode.RULE_BASED
    # ``should_retry`` is the machine-readable replan signal for PR-CL-A1
    # (Dynamic Replan) — agentic-loop-evolution.md A3 spec calls for a
    # "pass / fail / retry" signal, distinct from the human-readable
    # ``reflection_hint`` (Codex MCP MEDIUM #4, 2026-05-23). Set True when
    # a verify failure is recoverable (any rubric_miss is in the
    # ``_RETRYABLE_MISSES`` allowlist); set False on a hard fail (e.g.
    # ``model_action_required`` indicates operator intervention needed).
    should_retry: bool = False

    def __init__(
        self,
        passed: bool,
        mode: VerifyMode,
        score: float = 1.0,
        rubric_misses: tuple[str, ...] = (),
        reflection_hint: str = "",
        ts: float = 0.0,
        effective_mode: VerifyMode = VerifyMode.RULE_BASED,
        should_retry: bool = False,
        reflexion_hint: str | None = None,
    ) -> None:
        hint = reflection_hint if reflexion_hint is None else reflexion_hint
        object.__setattr__(self, "passed", passed)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "rubric_misses", rubric_misses)
        object.__setattr__(self, "reflection_hint", hint)
        object.__setattr__(self, "ts", ts)
        object.__setattr__(self, "effective_mode", effective_mode)
        object.__setattr__(self, "should_retry", should_retry)

    @property
    def reflexion_hint(self) -> str:
        """Legacy alias for callers that still use the paper spelling."""
        return self.reflection_hint

    def to_payload(self) -> dict[str, Any]:
        """Render as a hook-payload-friendly dict."""
        return {
            "passed": self.passed,
            "mode": self.mode.value,
            "effective_mode": self.effective_mode.value,
            "score": round(self.score, 4),
            "rubric_misses": list(self.rubric_misses),
            "reflection_hint": self.reflection_hint,
            "reflexion_hint": self.reflection_hint,
            "should_retry": self.should_retry,
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


def _truthy_env(name: str) -> bool:
    """Return True when an opt-in env knob is explicitly enabled."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _action_before_talk_enabled() -> bool:
    """Opt-in verifier pressure for benchmark tasks with available tools.

    Normal GEODE chat can legitimately ask users to inspect local state. Tau2
    telecom runs are different: the benchmark exposes tools for those checks,
    so manual phone-setting checklists before tool action are usually wasted
    turns. Keep this behind an env knob so the rule only applies when a
    benchmark harness requests it.
    """
    return _truthy_env("GEODE_VERIFY_ACTION_BEFORE_TALK")


def _looks_like_manual_checklist(text: str) -> bool:
    """Detect phone-setting checklist talk that should have been tool action."""
    lower = text.lower()
    if not lower:
        return False
    manual_markers = (
        "check your phone",
        "phone settings",
        "open your phone",
        "quick settings",
        "control center",
        "go to your cellular",
        "go to your mobile",
        "please check",
        "tell me whether",
        "try sending",
        "try to send",
        "restart the phone",
        "reboot the phone",
    )
    blocker_markers = (
        "airplane",
        "mobile data",
        "cellular",
        "sim",
        "network mode",
        "apn",
        "mms",
        "picture message",
    )
    return any(marker in lower for marker in manual_markers) and any(
        marker in lower for marker in blocker_markers
    )


def _check_step_expected_match(text: str) -> bool:
    """PR-CL-A1 (2026-05-23) — verify the just-finished turn's text against
    the active :class:`PlanStep.expected_outcome`.

    Returns True when the step matches (or there's no active plan / no
    expected_outcome on the current step — both treated as "no constraint
    to check"). False when expected_outcome is set and the turn's text
    fails the keyword overlap heuristic (case-insensitive substring
    match on any non-trivial token >=3 chars in expected_outcome).

    Failures NEVER raise — falls back to True so observability mustn't
    break the run it observes.
    """
    try:
        from core.observability.session_metrics import current_session_metrics

        plan = current_session_metrics().active_plan
        if plan is None:
            return True
        cur = plan.current_step()
        if cur is None:
            return True
        expected = (cur.expected_outcome or "").strip()
        if not expected:
            return True
        haystack = text.lower()
        # Split expected into tokens >=3 chars; any token must appear.
        # Conservative — short expected strings (single short word) match
        # liberally so the rubric_miss only fires on clear mismatches.
        tokens = [t for t in expected.lower().split() if len(t) >= 3]
        if not tokens:
            return True
        return any(tok in haystack for tok in tokens)
    except Exception:
        return True


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
    - ``step_expected_mismatch`` (PR-CL-A1): the turn's text doesn't
      contain any non-trivial token from the active
      :class:`PlanStep.expected_outcome`. Fires only when a Plan is
      active AND the current step has a non-empty expected_outcome.
      Treated as retryable so PR-CL-A1 replan can revise the plan.
    - ``manual_checklist_without_action``: opt-in benchmark rule
      (``GEODE_VERIFY_ACTION_BEFORE_TALK=1``) for cases where the turn
      asks the user to manually inspect phone/network state without making
      an available tool call first.

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

    # PR-CL-A1 — Plan expected_outcome integration. Only fires when a
    # turn produced *some* text (skip empty_turn cases — they already
    # flagged) and the active step has a concrete expected_outcome.
    if text_len > 0 and not _check_step_expected_match(text):
        misses.append("step_expected_mismatch")

    if (
        text_len > 0
        and not tool_calls
        and _action_before_talk_enabled()
        and _looks_like_manual_checklist(text)
    ):
        misses.append("manual_checklist_without_action")

    passed = not misses
    hint = "" if passed else synthesize_failure_reflection_hint(tuple(misses))
    # Retry signal: hard-fail (e.g. ``model_action_required``) ALWAYS
    # wins — even if a retryable miss (e.g. ``step_expected_mismatch``)
    # co-occurs, the operator-action signal should not be ignored
    # (Codex MCP HIGH #1, PR-CL-A1, 2026-05-23). The prior `any(...)`
    # path let a recoverable miss flip should_retry True alongside a
    # hard-fail, looping the agent on a billing/cost-cap event.
    hard_fail = any(m == "model_action_required" for m in misses)
    retry = (not passed) and (not hard_fail) and any(m in _RETRYABLE_MISSES for m in misses)
    return VerifyResult(
        passed=passed,
        mode=VerifyMode.RULE_BASED,
        effective_mode=VerifyMode.RULE_BASED,
        score=1.0 if passed else 0.0,
        rubric_misses=tuple(misses),
        reflection_hint=hint,
        should_retry=retry,
        ts=time.monotonic(),
    )


_LLM_JUDGE_SYSTEM_PROMPT = """\
Task: strict, concise verification for one agent turn. Read the turn
output below and emit a single-line JSON object — nothing else — with
these keys:

    {"passed": <true|false>, "score": <0.0-1.0>, "reason": "<short>"}

Pass when the turn made measurable progress toward the user's request
(tool used + text reflecting result, OR clean handoff). Fail when the
turn was empty, returned only an error, or contradicted the prior plan.
Score 1.0 = clearly correct, 0.5 = ambiguous, 0.0 = clearly wrong.
"""


def _judge_prompt(result: AgenticResult) -> str:
    """Render the just-finished turn as input for the judge."""
    tool_names = [tc.get("name", "?") for tc in (result.tool_calls or []) if isinstance(tc, dict)]
    return (
        "Turn output to evaluate:\n"
        f"- termination_reason: {result.termination_reason!r}\n"
        f"- rounds: {result.rounds}\n"
        f"- tool_calls: {tool_names}\n"
        f"- text (truncated 2000 chars):\n{(result.text or '')[:2000]}\n"
    )


def _parse_judge_payload(raw: str) -> tuple[bool, float, str]:
    """Extract ``(passed, score, reason)`` from the judge's single-line JSON.

    Falls back to neutral pass with score=0.5 when parsing fails — judge
    crashes must not break the agent run.
    """
    import json

    text = (raw or "").strip()
    # Some models wrap JSON in code fences; strip the obvious decorations.
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        log.debug("LLM judge returned non-JSON; treating as pass", extra={"raw": text[:200]})
        return True, 0.5, "judge_unparseable"
    passed = bool(obj.get("passed", True))
    raw_score = obj.get("score", 0.5)
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        score = 0.5
    score = max(0.0, min(1.0, score))
    reason = str(obj.get("reason", ""))[:200]
    return passed, score, reason


_JUDGE_CALL_TIMEOUT_S: float = 120.0


def _build_judge_result_from_response(response: Any, result: AgenticResult) -> VerifyResult:
    """Shared judge response → VerifyResult translation.

    Pulled out of the call paths so sync and async wrappers parse identically.
    Falls back to ``_llm_judge_fallback`` when the response carries no usable
    text — caller already handled the network-level None.
    """
    raw_text = (getattr(response, "text", "") or "").strip()
    if not raw_text:
        return _llm_judge_fallback(result)
    passed, score, reason = _parse_judge_payload(raw_text)
    misses: tuple[str, ...] = ()
    hint = ""
    if not passed:
        misses = ("judge_fail",) if not reason else ("judge_fail", reason[:40])
        hint = synthesize_failure_reflection_hint(("judge_fail",)) + (
            f"\nJudge reason: {reason}" if reason else ""
        )
    return VerifyResult(
        passed=passed,
        mode=VerifyMode.LLM_JUDGE,
        effective_mode=VerifyMode.LLM_JUDGE,
        score=score,
        rubric_misses=misses,
        reflection_hint=hint,
        should_retry=(not passed),
        ts=time.monotonic(),
    )


async def _verify_llm_judge_async(
    result: AgenticResult, *, loop: Any | None = None
) -> VerifyResult:
    """Async LLM-judge path — awaits ``loop._call_llm`` cleanly under the
    same event loop the agentic finalizer runs on (Codex MCP HIGH #2 +
    MEDIUM #3, 2026-05-23). Bounded by :data:`_JUDGE_CALL_TIMEOUT_S` via
    :func:`asyncio.wait_for` so a stuck adapter cannot hang finalisation.

    Judge token usage is recorded via the loop's ``_track_usage_async``
    helper after a non-``None`` response so judge cost surfaces in the
    session's TokenTracker (Codex MCP MEDIUM #4 fix, 2026-05-23). Cost
    is currently aggregated into the same TokenTracker that handles the
    action loop — per-phase tagging (``phase="judge"``) is a follow-up
    that needs adapter-level API extension.
    """
    if loop is None:
        return _llm_judge_fallback(result)
    try:
        import asyncio

        from core.config import settings

        judge_model = (getattr(settings, "judge_model", "") or "").strip() or loop.model
        prompt = _judge_prompt(result)
        response = await asyncio.wait_for(
            loop._call_llm(
                _LLM_JUDGE_SYSTEM_PROMPT,
                [{"role": "user", "content": prompt}],
                model=judge_model,
            ),
            timeout=_JUDGE_CALL_TIMEOUT_S,
        )
        if response is None:
            log.debug("LLM judge (async): no response; falling back to rule_based")
            return _llm_judge_fallback(result)
        # Codex MCP MEDIUM #4 — record judge usage explicitly. Mirrors the
        # action-loop path at ``agent_loop.py:_track_usage_async``. Failure
        # is swallowed so judge usage accounting never breaks the run.
        track = getattr(loop, "_track_usage_async", None)
        if track is not None:
            try:
                await track(response)
            except Exception:
                log.debug("Judge usage tracking failed", exc_info=True)
        return _build_judge_result_from_response(response, result)
    except Exception:
        log.warning(
            "LLM judge (async) call failed; falling back to rule_based",
            exc_info=True,
        )
        return _llm_judge_fallback(result)


def _verify_llm_judge(result: AgenticResult, *, loop: Any | None = None) -> VerifyResult:
    """Sync LLM-self-judge mode — opt-in, one extra LLM call per turn.

    PR-CL-A6 (2026-05-23) — sync wrapper for callers that aren't inside an
    asyncio event loop (CLI smoke tests, pure-sync verify dispatch). The
    production path (``_run_turn_verify_async`` from
    ``finalize_and_return_async``) awaits :func:`_verify_llm_judge_async`
    directly.

    PR-GATEWAY-BRIDGE-FRONTIER (2026-06-12) — the previous "sync caller
    inside a running loop" branch bridged via ThreadPoolExecutor +
    ``asyncio.run`` (a throwaway loop per call — the loop-pollution
    residue class; its comment even claimed the new loop *protected*
    clients, which was exactly backwards pre-loop-affinity). Frontier
    convergence (hermes ``model_tools._run_async``: never a disposable
    loop at runtime) and GEODE's own production reality (every running-
    loop caller has the async path available) make that branch dead
    weight: a sync call from inside a running loop is a misuse and now
    downgrades honestly to the rule-based fallback with a WARNING,
    instead of hiding the misuse behind a thread bridge. The no-loop
    case keeps ``asyncio.run`` — that IS the process-edge contract.

    Failures NEVER raise — observability mustn't break the run it observes.
    """
    if loop is None:
        log.debug("LLM judge: no loop reference; falling back to rule_based")
        return _llm_judge_fallback(result)
    try:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_verify_llm_judge_async(result, loop=loop))
        log.warning(
            "LLM judge: sync verify_turn called from inside a running event "
            "loop — use verify_turn_async; downgrading to rule_based "
            "(PR-GATEWAY-BRIDGE-FRONTIER)"
        )
        return _llm_judge_fallback(result)
    except Exception:
        log.warning("LLM judge call failed; falling back to rule_based", exc_info=True)
        return _llm_judge_fallback(result)


def _llm_judge_fallback(result: AgenticResult) -> VerifyResult:
    """Used when the LLM judge can't run (no loop ref / response None /
    exception). Runs the rule-based path but tags the result mode as
    LLM_JUDGE (operator intent) with ``effective_mode=RULE_BASED`` so
    telemetry surfaces the downgrade."""
    rb = _verify_rule_based(result)
    return VerifyResult(
        passed=rb.passed,
        mode=VerifyMode.LLM_JUDGE,
        effective_mode=VerifyMode.RULE_BASED,
        score=rb.score,
        rubric_misses=rb.rubric_misses,
        reflection_hint=rb.reflection_hint,
        should_retry=rb.should_retry,
        ts=rb.ts,
    )


async def verify_turn_async(result: AgenticResult, *, loop: Any | None = None) -> VerifyResult:
    """Async dispatcher — preferred for callers running inside an event
    loop (e.g. ``finalize_and_return_async``). Avoids the cross-loop
    thread-pool hop that the sync wrapper has to use for in-loop
    invocation (Codex MCP HIGH #2 fix, 2026-05-23).
    """
    mode = get_verify_mode()
    if mode is VerifyMode.OFF:
        return VerifyResult(passed=True, mode=mode, effective_mode=mode, ts=time.monotonic())
    try:
        if mode is VerifyMode.LLM_JUDGE:
            return await _verify_llm_judge_async(result, loop=loop)
        return _verify_rule_based(result)
    except Exception:
        log.warning("verify_turn_async crashed; treating as pass", exc_info=True)
        return VerifyResult(passed=True, mode=mode, effective_mode=mode, ts=time.monotonic())


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
