"""A.5 (2026-05-25) — meta-judge retrospective drift detection (PR-13).

Plan: ``docs/plans/2026-05-25-p3-anchor-calibration-crm-spct.md`` §C5.

Frontier: **Meta-Rewarding** (Meta 2024-07 arXiv 2407.19594) — meta-judge LLM
이 base judge 의 출력을 retrospective 평가해서 judge drift / saturation 감지.

GEODE 채택: ``mutations.jsonl`` 의 최근 N attribution row 를 prompt 로 직렬화
→ meta-judge LLM 에 "Across these N attributions, did the base judge's
calibration shift?" → ``drift_score`` [0,1] + ``drift_summary`` text 반환.

본 module 은 inference-time observability — mutator weight 학습 없음. cron /
manual invocation 으로 정기 호출, drift_score > threshold 시 operator alert.

Caller pattern (CLI / cron)::

    from core.self_improving.loop.meta_judge import invoke_meta_judge
    result = invoke_meta_judge(n=10)
    if result is None:
        # attribution row 부재 (fresh repo / pre-PR-5)
        return
    if result.drift_score > 0.6:
        log.warning("meta-judge: drift_score=%.2f — %s", result.drift_score, result.drift_summary)
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.self_improving.loop.attribution import AttributionRecord
from core.self_improving.loop.mutations_reader import read_recent_attributions

log = logging.getLogger(__name__)


# JSON Schema-shaped LLM response. Plain-text fallback parser also accepts
# loose "drift_score: 0.42" key-value lines (low-capability model graceful).
META_JUDGE_RESPONSE_SCHEMA: str = """{
  "drift_score": <float in [0.0, 1.0]>,
  "drift_summary": "<one sentence summary of judge drift or calibration shift>"
}"""


_DEFAULT_SYSTEM_PROMPT: str = (
    "You are a meta-judge — your job is to assess whether the base judge's "
    "calibration drifted across a recent batch of attribution rows from a "
    "self-improving loop. Score the drift on [0.0, 1.0] where 0.0 means "
    "perfect calibration consistency (every attribution_score is well-justified "
    "by its observed_dim values) and 1.0 means catastrophic drift (scores no "
    "longer track underlying dim signals).\n\n"
    "Output ONLY a single JSON object matching the schema given by the user. "
    "No prose, no explanation outside the JSON."
)


class MetaJudgeResult(BaseModel):
    """Structured outcome of a single meta-judge invocation.

    ``drift_score`` clipped to [0, 1] by parser. ``evaluated_count`` records
    how many attribution rows the LLM actually saw — caller can use this to
    judge whether the score is statistically meaningful (e.g. < 3 → ignore).
    ``llm_raw`` retained for debugging when the parser had to fall back.
    """

    model_config = ConfigDict(extra="forbid")

    ts: float
    drift_score: float = Field(ge=0.0, le=1.0)
    drift_summary: str
    evaluated_count: int = Field(ge=0)
    llm_raw: str = ""


def build_meta_judge_prompt(records: list[AttributionRecord]) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for the meta-judge LLM call.

    Pure function — exposed for direct unit testing without an LLM call.
    Empty records → ValueError (caller should skip invocation entirely
    rather than build an empty prompt).
    """
    if not records:
        raise ValueError("meta-judge: cannot build prompt for empty records")
    serialised_rows: list[str] = []
    for r in records:
        serialised_rows.append(
            json.dumps(
                {
                    "mutation_id": r.mutation_id,
                    "observed_dim": r.observed_dim,
                    "ci95": r.ci95,
                    "significant": r.significant,
                    "attribution_score": round(r.attribution_score, 4),
                    "fitness_delta": (
                        round(r.fitness_delta, 4) if r.fitness_delta is not None else None
                    ),
                },
                ensure_ascii=False,
            )
        )
    body = "\n".join(serialised_rows)
    user_prompt = (
        f"The following {len(records)} attribution rows are from the most recent "
        f"audits of the self-improving loop. Each row records what the base "
        f"judge measured (``observed_dim``), the per-dim confidence interval "
        f"(``ci95``), whether the dim moved significantly (``significant``), "
        f"and a scalar ``attribution_score``.\n\n"
        f"Attribution rows (JSONL, one per line):\n{body}\n\n"
        f"Assess whether the base judge's calibration drifted across this "
        f"batch. Respond using the schema:\n{META_JUDGE_RESPONSE_SCHEMA}\n"
    )
    return _DEFAULT_SYSTEM_PROMPT, user_prompt


_DRIFT_SCORE_RE = re.compile(r'"?drift_score"?\s*[:=]\s*([0-9]*\.?[0-9]+)', re.IGNORECASE)
_DRIFT_SUMMARY_RE = re.compile(r'"?drift_summary"?\s*[:=]\s*"([^"]+)"', re.IGNORECASE)


def _clamp_score(raw: float) -> float:
    return max(0.0, min(1.0, raw))


def parse_meta_judge_response(text: str) -> tuple[float, str]:
    """Extract ``(drift_score, drift_summary)`` from LLM raw text.

    Strategy:

    1. Strip code-fence wrappers (``` or ```json), look for a JSON object,
       try ``json.loads`` first — strict-schema path.
    2. Fall back to regex extraction (``drift_score: 0.4`` key-value style)
       so a low-capability model that ignores the JSON instruction still
       yields a usable signal.
    3. On total failure → ``(0.0, "")`` so caller can detect "no signal"
       via empty summary.

    Score clamped to ``[0.0, 1.0]`` (defensive against out-of-range output).
    Summary truncated to 500 chars (defense against prompt-leak abuse).
    """
    cleaned = text.strip()
    # Strip markdown code fence if present.
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            score_raw = obj.get("drift_score", 0.0)
            summary_raw = obj.get("drift_summary", "")
            if isinstance(score_raw, int | float):
                return _clamp_score(float(score_raw)), str(summary_raw)[:500]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    score_match = _DRIFT_SCORE_RE.search(cleaned)
    summary_match = _DRIFT_SUMMARY_RE.search(cleaned)
    if score_match:
        try:
            score = _clamp_score(float(score_match.group(1)))
            summary = summary_match.group(1)[:500] if summary_match else ""
            return score, summary
        except (ValueError, IndexError):
            pass

    return 0.0, ""


LlmCallable = Callable[[str, str], str]


def _default_llm_call(system_prompt: str, user_prompt: str) -> str:
    """Lazy delegate to the mutator's default LLM call.

    Keeps the meta-judge module importable in test contexts without the
    anthropic SDK preloaded. Production caller may inject any callable
    with the same shape.
    """
    from core.self_improving.loop.runner import _default_llm_call as _runner_call

    return _runner_call(system_prompt, user_prompt)


def invoke_meta_judge(
    n: int = 10,
    *,
    llm_call: LlmCallable | None = None,
    path: Path | None = None,
) -> MetaJudgeResult | None:
    """Read N recent attribution rows + invoke meta-judge LLM → result.

    Returns ``None`` when no attribution rows are available (fresh repo or
    pre-PR-5 baseline) — caller should treat this as "no signal" and skip
    alerting. Otherwise returns ``MetaJudgeResult`` with clamped score +
    truncated summary + raw LLM text for audit.

    ``llm_call`` defaults to the runner's mutator dispatch; tests inject a
    stub callable to keep this module independent of the LLM SDK.
    """
    if n <= 0:
        raise ValueError(f"n must be >= 1, got {n}")
    records = read_recent_attributions(n, path)
    if not records:
        log.info("meta-judge: no attribution rows; skipping invocation")
        return None
    system_prompt, user_prompt = build_meta_judge_prompt(records)
    call = llm_call if llm_call is not None else _default_llm_call
    raw = call(system_prompt, user_prompt)
    drift_score, drift_summary = parse_meta_judge_response(raw)
    return MetaJudgeResult(
        ts=time.time(),
        drift_score=drift_score,
        drift_summary=drift_summary,
        evaluated_count=len(records),
        llm_raw=raw[:2000],  # cap so the result row stays compact in logs
    )


__all__ = [
    "META_JUDGE_RESPONSE_SCHEMA",
    "LlmCallable",
    "MetaJudgeResult",
    "build_meta_judge_prompt",
    "invoke_meta_judge",
    "parse_meta_judge_response",
]
