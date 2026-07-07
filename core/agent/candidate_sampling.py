"""Best-of-N candidate sampling + judge selection for ``delegate_task``.

GAP 2+4 of the test-time compute allocation audit (2026-07-06). The
runtime already had task-decomposition width (``SubAgentManager`` fans
out DIFFERENT subtasks in parallel) but no same-task N-candidate
sampling: there was no way to buy accuracy with width on a single task,
and ``settings.judge_model`` had no runtime consumer outside the
per-turn verify mode. This module owns the two missing pieces:

- **Diversity lenses** — each candidate of the SAME task gets a distinct
  reasoning-lens suffix. Ensemble gain scales with error decorrelation;
  N clones of one model + one prompt fail together, so lens forcing is
  bundled with sampling rather than left optional.
- **Judge selection** — one structured-output LLM call (the
  ``select_candidate`` tool) picks the winner among successful
  candidates. Judge failure is an OBSERVABLE fallback, never silent:
  the verdict falls back to the first successful candidate and carries
  ``judge_error`` so the caller (and the model reading the tool result)
  sees that selection degraded.

Dispatch mirrors ``core/agent/loop/_reflection.py`` (PR-B structured
tool_use pattern): ``resolve_for`` + ``AdapterCallRequest`` +
``call_with_failover``, ``tool_choice="auto"`` (forced tool choice is
incompatible with extended/adaptive thinking across models).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.config import _resolve_provider
from core.llm.adapters import resolve_for
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec
from core.llm.adapters.registry import normalize_registry_provider
from core.llm.router import call_with_failover

log = logging.getLogger(__name__)

__all__ = [
    "DIVERSITY_LENSES",
    "MAX_BEST_OF",
    "CandidateVerdict",
    "candidate_text",
    "judge_candidates",
    "lensed_description",
]

# Hard cap on N — best-of-N costs N sub-agent runs + 1 judge call; the
# marginal candidate past 4 rarely survives a majority-style judge while
# the cost stays linear.
MAX_BEST_OF = 4

# One lens per candidate index (i % len). Deliberately terse imperative
# framings — the lens must bend the approach, not restate the task.
DIVERSITY_LENSES: tuple[str, ...] = (
    "Approach: execute directly with the most conventional method.",
    "Approach: enumerate the likely failure modes first, then solve while guarding against them.",
    "Approach: find the smallest viable solution — prefer the simplest path that fully answers.",
    "Approach: ground every claim in verifiable evidence; cite what you checked.",
)

_JUDGE_TOOL_NAME = "select_candidate"

_JUDGE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "winner_index": {
            "type": "integer",
            "minimum": 0,
            "description": "0-based index of the best candidate.",
        },
        "reason": {
            "type": "string",
            "description": "One-sentence justification (<= 200 chars).",
        },
    },
    "required": ["winner_index", "reason"],
}

_JUDGE_SYSTEM_PROMPT = (
    "Role: candidate-selection judge for an autonomous execution agent. "
    "N sub-agents solved the SAME task with different approaches. "
    f"Compare their results and invoke the ``{_JUDGE_TOOL_NAME}`` tool "
    "with the index of the best one. Judge on: correctness, completeness "
    "against the task, and evidence quality. Do NOT reward verbosity. "
    "The tool call is the only required output."
)

# Per-candidate excerpt cap in the judge prompt — the judge compares
# outcomes, it does not re-read transcripts (clean-context discipline).
_CANDIDATE_EXCERPT_CHARS = 2000


def lensed_description(description: str, index: int) -> str:
    """Return *description* with the index-th diversity lens appended."""
    lens = DIVERSITY_LENSES[index % len(DIVERSITY_LENSES)]
    return f"{description}\n\n{lens}"


@dataclass(frozen=True, slots=True)
class CandidateVerdict:
    """Outcome of one judge pass over N candidate results.

    ``judge_error`` empty = the judge actually selected. Non-empty =
    observable fallback (winner defaults to candidate 0 of the
    successful set); callers surface it in the tool result so degraded
    selection is never mistaken for a judged one.
    """

    winner_index: int
    reason: str
    judge_error: str = ""


def _build_judge_prompt(task_description: str, candidates: list[str]) -> str:
    lines = [f"Task given to every candidate:\n{task_description}\n"]
    for i, text in enumerate(candidates):
        head = text.strip().replace("\r", "")
        if len(head) > _CANDIDATE_EXCERPT_CHARS:
            head = head[:_CANDIDATE_EXCERPT_CHARS] + "…(truncated)"
        lines.append(f"--- Candidate {i} ---\n{head or '(empty result)'}\n")
    lines.append(f"Invoke the {_JUDGE_TOOL_NAME} tool now.")
    return "\n".join(lines)


def _extract_verdict_input(result: Any) -> dict[str, Any] | None:
    """Find the ``select_candidate`` tool_use payload (Path-B shape)."""
    tool_uses = getattr(result, "tool_uses", None)
    if isinstance(tool_uses, tuple | list):
        for entry in tool_uses:
            if isinstance(entry, dict) and entry.get("name") == _JUDGE_TOOL_NAME:
                payload = entry.get("input")
                if isinstance(payload, dict):
                    return payload
    return None


def candidate_text(output: Any) -> str:
    """Extract judge-readable text from a ``SubResult.output`` payload.

    Prefers the common text-carrying keys; falls back to compact JSON so
    the judge reads content, not a Python dict repr (Codex MCP LOW,
    2026-07-06).
    """
    if isinstance(output, dict):
        for key in ("text", "summary", "raw", "result"):
            val = output.get(key)
            if isinstance(val, str) and val.strip():
                return val
        try:
            import json

            return json.dumps(output, ensure_ascii=False, default=str)
        except Exception:
            return str(output)
    return str(output or "")


async def judge_candidates(
    task_description: str,
    candidates: list[str],
    *,
    model: str,
    provider: str | None = None,
    source: str | None = None,
    max_tokens: int = 512,
) -> CandidateVerdict:
    """Pick the best of *candidates* with one judge LLM call.

    ``provider`` / ``source`` should carry the delegating loop's live
    adapter route (``ToolContext``) so the judge does not re-run
    resolution and land on a different credential source than the
    session's main calls (Codex MCP MED, 2026-07-06); ``None`` falls
    back to settings-driven inference like the reflection node.

    Never raises. Every failure path (adapter error, tool declined,
    non-int / out-of-range index) returns the candidate-0 fallback with
    ``judge_error`` set — the graceful contract applies at every
    schema-typed cast, not just the outer try.
    """
    if len(candidates) == 1:
        return CandidateVerdict(0, "only one successful candidate; judge call skipped")
    try:
        provider = provider or _resolve_provider(model)
        from core.llm.adapters._source_inference import infer_source

        resolved_source = source or infer_source(provider)
        adapter = resolve_for(normalize_registry_provider(provider), resolved_source)
        user_prompt = _build_judge_prompt(task_description, candidates)
        log.info(
            "candidate judge dispatch: model=%s provider=%s n=%d",
            model,
            provider,
            len(candidates),
        )

        async def _do_call(m: str) -> object:
            from core.config import settings as _settings

            req = AdapterCallRequest(
                model=m,
                messages=(Message(role="user", content=user_prompt),),
                system_prompt=_JUDGE_SYSTEM_PROMPT,
                tools=(
                    ToolSpec(
                        name=_JUDGE_TOOL_NAME,
                        description="Select the best candidate by 0-based index.",
                        input_schema=_JUDGE_TOOL_SCHEMA,
                    ),
                ),
                tool_choice="auto",
                max_tokens=max_tokens,
                temperature=_settings.temperature_reflection,
            )
            return await adapter.acomplete(req)

        response, _used_model = await call_with_failover([model], _do_call)
    except Exception as exc:
        log.warning("candidate judge call failed: %s", exc, exc_info=True)
        return CandidateVerdict(
            0, "fallback: first successful candidate", f"judge call failed: {exc}"
        )

    parsed = _extract_verdict_input(response)
    if parsed is None:
        return CandidateVerdict(
            0, "fallback: first successful candidate", "judge declined the select_candidate tool"
        )

    raw_index = parsed.get("winner_index")
    if not isinstance(raw_index, int) or isinstance(raw_index, bool):
        return CandidateVerdict(
            0,
            "fallback: first successful candidate",
            f"non-integer winner_index: {raw_index!r}",
        )
    if not 0 <= raw_index < len(candidates):
        return CandidateVerdict(
            0,
            "fallback: first successful candidate",
            f"winner_index {raw_index} out of range 0..{len(candidates) - 1}",
        )

    raw_reason = parsed.get("reason")
    reason = raw_reason.strip()[:200] if isinstance(raw_reason, str) else ""
    return CandidateVerdict(raw_index, reason or "(judge gave no reason)")
